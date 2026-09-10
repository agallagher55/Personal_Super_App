"""Parses Shakepay's monthly statement PDFs and range-replace loads them
into the same data/finance/finance.db transactions table import_csv.py
writes to (finance/ARCHITECTURE.md Part A) - so Shakepay activity shows
up on /finance's Spending and Cash Flow sections alongside the credit
card and bank CSV imports, without either of those needing any changes.

Shakepay isn't Plaid-linkable and has no CSV export, so this is a
separate ingestion path (a local PDF, not an uploaded file) rather than
a third branch of import_csv.parse_csv_text. It is deliberately never
imported by backend/server.py: `pypdf` (see the module-level ImportError
below) would otherwise become a dependency of the live server process for
a file type only run by hand, from a terminal, a few times a month.

Usage:
    pip install pypdf   # scoped exception, same as plaid-python/
                         # cryptography are for finance/ - see
                         # finance/ARCHITECTURE.md section 1
    python3 backend/finance/import_shakepay.py statement1.pdf [statement2.pdf ...]
    python3 backend/finance/import_shakepay.py data/finance/shakepay/

Any argument that's a directory is expanded to the *.pdf files directly
inside it (not recursive) - keep a standing folder of every month's two
downloads (e.g. data/finance/shakepay/, which is already under the
git-ignored data/finance/) and re-point the command at that folder each
time rather than naming files by hand.

Shakepay sends two separate PDFs each month for the same account (see
finance/README.md for the full description of both): the "Shakepay Inc."
account statement (cash/USD/crypto activity - card purchases only show up
here as an anonymous funding-transfer line) and the "Shakepay Financial
Inc." card statement (card purchases with real merchant names). Each is
auto-detected from its own content and can be passed in any order, any
month; run both together for a full month so nothing is missing.

Three accounts, deliberately separate from the shakepay-cad/shakepay-btc
net-worth accounts networth.py seeded from static/finance/finance-dashboard.json
(ARCHITECTURE.md Part C) - those are dated balance *snapshots* for the net
worth sections; these are itemized *transactions* for Spending/Cash Flow,
the same relationship import_csv.py's main-credit-card account has to its
own (separate) net worth entry:

  shakepay-card (kind=credit_card)  - card purchases, activity_type
      Purchase/Refund - falls into the exact same scope
      credit_card_expense_total()/category_breakdown()/monthly_trend()/
      top_merchants() already give a second credit card (the "Phase 4b"
      case flagged, not yet built, in ARCHITECTURE.md A9), so it shows up
      in Spending and Cash Flow immediately. Lands as category=None
      (shows "Uncategorized" until tagged via the pencil-edit dialog),
      same as an issuer export with a blank category column.
  shakepay-cash (kind=chequing)     - P2P sends/receives, Interac
      transfers, round-up BTC buys (the CAD side).
  shakepay-crypto (kind=bitcoin_wallet) - staking/cashback rewards,
      interest, and BTC received from an external address.

Every cash/crypto activity_type below reuses an existing, already-tested
classification where the meaning genuinely matches (see cash_flow_income_
total()/chequing_expense_total() in summary.py), or is a new value chosen
to NOT appear in summary.CHEQUING_INCOME_TYPES/CHEQUING_EXPENSE_TYPES -
nothing in summary.py changes:

  Send cash via Shakepay   -> P2P        (existing expense type - a
                                          payment to another actual
                                          person, exactly what bank P2P
                                          rows already mean)
  Receive cash via Shakepay -> P2P_IN    (new, excluded by default - no
                                          existing "P2P income" type to
                                          reuse; add it to
                                          summary.CHEQUING_INCOME_TYPES
                                          yourself if you want it counted)
  Interac e-Transfer (in/out) -> E_TRFIN/E_TRFOUT (existing, already-
                                          excluded types - moving money
                                          between your own Shakepay
                                          wallet and your own bank is
                                          exactly the "can't tell if this
                                          is really income/expense or a
                                          self-transfer" case those types
                                          already exist for)
  Round-up BTC buy (CAD side) -> ROUNDUP_BUY (new, excluded - converting
                                          CAD to BTC you still hold is an
                                          investment move, not spend)
  Shakepay reward/cashback  -> CRYPTO_REWARD (new, excluded - paid in
                                          BTC, not spendable CAD, unlike
                                          credit-card cashback)
  Shakepay Interest         -> CRYPTO_INTEREST (new, excluded, same
                                          reasoning)
  Receive Bitcoin (external) -> CRYPTO_DEPOSIT (new, excluded - a
                                          transfer in, not earned income)

`category` for every row comes from import_csv._default_chequing_category,
the exact same helper import_csv.py itself uses - 'Uncategorized' for
CHEQUING_EXPENSE_TYPES members (so P2P sends get it, matching a bank P2P
row exactly), None for everything else (matching how the credit card
export's own blank-category rows, and every excluded transfer-shaped
type, already behave). Reusing it here rather than hardcoding means a
future change to those tuples (e.g. deciding to count P2P_IN as income)
takes effect automatically, with no edit needed in this file.

The funding-transfer lines that appear in *both* PDFs for the same card
swipe (a "Transfer ... to Shakepay Financial Inc. for Card purchase" line
in the account statement, an identical-amount "+$X" line in the card
statement) are always dropped - only the merchant-named Card purchase
line is kept - so spend isn't double counted. Same idea for round-up
buys, which appear once in the cash table (the CAD side, kept) and once
in the crypto table (the BTC side, dropped).
"""

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import dates  # noqa: E402
import db as finance_db  # noqa: E402
import import_csv  # noqa: E402

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

DATE_RE = r'\d{4}-\d{2}-\d{2}'
TIME_RE = r'\d{2}:\d{2}:\d{2}'
MONEY_RE = r'[+-][\d,]+\.\d{2}'

ACCOUNTS = {
    'shakepay-card': ('Shakepay Card', 'Shakepay', 'credit_card'),
    'shakepay-cash': ('Shakepay Cash', 'Shakepay', 'chequing'),
    'shakepay-crypto': ('Shakepay Crypto', 'Shakepay', 'bitcoin_wallet'),
}


class ShakepayImportError(ValueError):
    """The PDF's content didn't match either known Shakepay statement
    shape."""


def _money(text):
    return float(text.replace(',', '').lstrip('+'))


def _require_pypdf():
    if PdfReader is None:
        sys.exit('pypdf is required to run this script: pip install pypdf')


def extract_text(pdf_path):
    _require_pypdf()
    reader = PdfReader(pdf_path)
    pages = [' '.join((page.extract_text() or '').split()) for page in reader.pages]
    return ' '.join(pages)


def statement_period(text):
    match = re.search(rf'({DATE_RE}) to ({DATE_RE})', text)
    return (match.group(1), match.group(2)) if match else (None, None)


def detect_statement_type(text):
    if 'Card transactions' in text and 'Shakepay Financial Inc.' in text:
        return 'card'
    if 'Cash transactions (CAD)' in text:
        return 'account'
    return None


# Some pypdf versions/platforms (observed: ArcGIS Pro's bundled Python
# environment) extract this statement's tables without a space between
# adjacent columns whose visual gap is small - "09:14:06Transfer",
# "Card purchaseRAMBLERS", "+5.006.73" - apparently a difference in the
# horizontal-gap heuristic pypdf's default text extraction uses to decide
# whether two runs need a space between them. Not fixable by pinning a
# pypdf version we don't control (ArcGIS Pro bundles its own), so the
# parser has to tolerate both shapes instead.
#
# Each fix below is narrowly targeted at this statement's own fixed
# template keywords/timestamps, not a general "insert space at every
# lower-to-upper-case transition" heuristic - that would also mangle real
# mixed-case merchant names this statement legitimately contains
# ("McDonalds", "DOLLARAMA") that must NOT get a space inserted inside
# them. The two regexes below are anchored on formats that never appear
# inside a merchant name (a full HH:MM:SS timestamp, a bare YYYY-MM-DD
# date) so they can't false-positive there either.
_GLUED_LITERAL_FIXES = (
    ('TransferTransfer from Shakepay Inc.', 'Transfer Transfer from Shakepay Inc.'),
    ('Round upBought', 'Round up Bought'),
    ('Shakepay InterestInterest', 'Shakepay Interest Interest'),
    ('Receive BitcoinBitcoin', 'Receive Bitcoin Bitcoin'),
    ('Starting balanceBTC', 'Starting balance BTC'),
    ('Closing balanceBTC', 'Closing balance BTC'),
    ('Shakepay@', 'Shakepay @'),
    # Unconditional trailing space after these fixed keywords - always
    # safe since none of them is ever itself a merchant/counterparty
    # name, and a real pre-existing space just becomes a harmless double
    # space that the final whitespace normalization collapses.
    ('Card purchase', 'Card purchase '),
    ('Interac e-Transfer', 'Interac e-Transfer '),
    ('Shakepay reward', 'Shakepay reward '),
    ('CAD balance', 'CAD balance '),
)


def _insert_missing_spaces(text):
    text = re.sub(r'(?<=\d{2}:\d{2}:\d{2})(?=\S)', ' ', text)  # time -> next column
    text = re.sub(r'(?<=\d{4}-\d{2}-\d{2})(?=[A-Za-z])', ' ', text)  # bare date -> next word
    for glued, fixed in _GLUED_LITERAL_FIXES:
        text = text.replace(glued, fixed)
    return ' '.join(text.split())


def _flex_phrase(phrase):
    """A phrase's words joined with \\s* instead of a literal single
    space, so a known boilerplate string still matches whole even where
    _insert_missing_spaces above didn't specifically target its internal
    gluing (e.g. header artifacts like "(CA$)**Original" or
    "TransactionDescription")."""
    return r'\s*'.join(re.escape(word) for word in phrase.split(' '))


_FOOTER_RE = re.compile(r'Monthly account statement.*?Page \d+ of \d+')
# Longest/most specific first - see _strip_boilerplate.
_HEADER_RES = [
    re.compile(_flex_phrase(
        'Date/time (EST) Transaction Description Debit (CA$) Credit (CA$) Balance (CA$)')),
    re.compile(_flex_phrase(
        'Date/time (EST) Transaction Description Debit (US$) Credit (US$) Balance (US$)')),
    re.compile(_flex_phrase(
        'Date/time (EST) Transaction Description Debit Credit Market value (CA$)** Original cost (CA$)***')),
    re.compile(_flex_phrase('Date/time (EST) Transaction Description Debit Credit')),
]


def _strip_boilerplate(text):
    text = _FOOTER_RE.sub(' ', text)
    for pattern in _HEADER_RES:
        text = pattern.sub(' ', text)
    return ' '.join(text.split())


def _slice_section(text, start_marker, end_markers):
    start = text.find(start_marker)
    if start == -1:
        return ''
    start += len(start_marker)
    end = len(text)
    for marker in end_markers:
        idx = text.find(marker, start)
        if idx != -1:
            end = min(end, idx)
    return text[start:end].strip()


def _split_transactions(section_text):
    if not section_text or 'No account activity' in section_text:
        return []
    chunks = re.split(rf'(?={DATE_RE})', section_text)
    return [c.strip() for c in chunks if c.strip()]


def _row(date, description, amount, activity_type, btc_quantity=None):
    return {
        'date': date,
        'description': description,
        'amount': finance_db.round_cad(amount),
        'activity_type': activity_type,
        'category': import_csv._default_chequing_category(activity_type),
        'status': None,
        'btc_quantity': finance_db.round_btc(btc_quantity),
    }


# --- Cash (CAD) subsection -------------------------------------------------

_CASH_PATTERNS = [
    (re.compile(rf'^({DATE_RE}) (Starting|Closing) balance ([\d,]+\.\d{{2}})$'), 'balance_snapshot'),
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) Interac e-Transfer (\S+) ({MONEY_RE})\s*([\d,]+\.\d{{2}})$'), 'interac'),
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) (Receive|Send) cash via Shakepay (@\S+) ({MONEY_RE})\s*([\d,]+\.\d{{2}})$'), 'p2p'),
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) Transfer Transfer from Shakepay Inc\. to Shakepay Financial '
                rf'Inc\. for Card purchase ({MONEY_RE})\s*([\d,]+\.\d{{2}})$'), 'card_funding'),
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) Round up Bought ([\d.]+) BTC @ CA\$([\d,]+\.\d{{2}})\s*'
                rf'({MONEY_RE})\s*([\d,]+\.\d{{2}})$'), 'roundup'),
]


def _parse_cash_section(text):
    rows, unparsed = [], []
    skipped_card_funding = 0
    for chunk in _split_transactions(text):
        matched = False
        for pattern, kind in _CASH_PATTERNS:
            match = pattern.match(chunk)
            if not match:
                continue
            matched = True
            if kind in ('balance_snapshot', 'card_funding'):
                skipped_card_funding += kind == 'card_funding'
                continue
            if kind == 'interac':
                date, time, counterparty, amount, balance = match.groups()
                amount = _money(amount)
                activity_type = 'E_TRFIN' if amount > 0 else 'E_TRFOUT'
                rows.append(_row(date, f'Interac e-Transfer {counterparty}', amount, activity_type))
            elif kind == 'p2p':
                date, time, direction, handle, amount, balance = match.groups()
                activity_type = 'P2P' if direction == 'Send' else 'P2P_IN'
                rows.append(_row(date, f'{direction} cash via Shakepay {handle}', _money(amount), activity_type))
            elif kind == 'roundup':
                date, time, btc_qty, btc_price, amount, balance = match.groups()
                rows.append(_row(date, f'Round up - bought {btc_qty} BTC @ CA${btc_price}',
                                  _money(amount), 'ROUNDUP_BUY', btc_quantity=float(btc_qty)))
            break
        if not matched:
            unparsed.append(chunk)
    return rows, unparsed, {'skipped_card_funding_transfers': skipped_card_funding}


# --- Crypto subsection -------------------------------------------------

_CRYPTO_PATTERNS = [
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) Shakepay reward (ShakingSats|ShakeSquad|Bitcoin cashback)\s*'
                rf'\+([\d.]+)\s*BTC\s*([\d,]+\.\d{{2}})\s*([\d,]+\.\d{{2}})$'), 'reward'),
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) Shakepay Interest Interest payout on CAD balance\s*'
                rf'\+([\d.]+)\s*BTC\s*([\d,]+\.\d{{2}})\s*([\d,]+\.\d{{2}})$'), 'interest'),
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) Receive Bitcoin Bitcoin address (.+?)\s*'
                rf'\+([\d.]+)\s*BTC\s*([\d,]+\.\d{{2}})\s*([\d,]+\.\d{{2}})$'), 'deposit'),
]


def _parse_crypto_section(text):
    rows, unparsed = [], []
    skipped_roundup_mirrors = 0
    for chunk in _split_transactions(text):
        if 'Starting balance BTC' in chunk or 'Closing balance BTC' in chunk:
            continue
        if 'Round up Bought @' in chunk:
            skipped_roundup_mirrors += 1
            continue
        matched = False
        for pattern, kind in _CRYPTO_PATTERNS:
            match = pattern.match(chunk)
            if not match:
                continue
            matched = True
            if kind in ('reward', 'interest'):
                date, time, *rest = match.groups()
                if kind == 'reward':
                    program, btc_qty, value_cad, cost_cad = rest
                    description = f'Shakepay reward - {program}'
                else:
                    btc_qty, value_cad, cost_cad = rest
                    description = 'Shakepay Interest - CAD balance payout'
                rows.append(_row(date, description, _money(value_cad),
                                  'CRYPTO_REWARD' if kind == 'reward' else 'CRYPTO_INTEREST'))
            else:
                date, time, address, btc_qty, value_cad, cost_cad = match.groups()
                rows.append(_row(date, 'Receive Bitcoin', _money(value_cad), 'CRYPTO_DEPOSIT'))
            break
        if not matched:
            unparsed.append(chunk)
    return rows, unparsed, {'skipped_roundup_mirrors': skipped_roundup_mirrors}


def _parse_account_statement(text):
    cleaned = _strip_boilerplate(text)
    cash_section = _slice_section(cleaned, 'Cash transactions (CAD)', ['US Dollar (USD) transactions'])
    crypto_section = _slice_section(cleaned, 'Crypto transactions', ['Audit Notice', 'Disclosures'])
    cash_rows, cash_unparsed, cash_stats = _parse_cash_section(cash_section)
    crypto_rows, crypto_unparsed, crypto_stats = _parse_crypto_section(crypto_section)
    rows_by_account = {'shakepay-cash': cash_rows, 'shakepay-crypto': crypto_rows}
    stats = {**cash_stats, **crypto_stats}
    return rows_by_account, cash_unparsed + crypto_unparsed, stats


# --- Card statement -------------------------------------------------

_CARD_PATTERNS = [
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) Transfer Transfer from Shakepay Inc\. to Shakepay Financial '
                rf'Inc\. for Card purchase \+\$([\d,]+\.\d{{2}})$'), 'card_funding'),
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) Card purchase (.+?) -\$([\d,]+\.\d{{2}})$'), 'purchase'),
]
_GENERIC_SIGNED_LINE = re.compile(rf'^({DATE_RE}) ({TIME_RE}) (.+?) ([+-])\$([\d,]+\.\d{{2}})$')


def _parse_card_subsection(text):
    rows, unparsed = [], []
    skipped_funding = 0
    for chunk in _split_transactions(text):
        matched = False
        for pattern, kind in _CARD_PATTERNS:
            match = pattern.match(chunk)
            if not match:
                continue
            matched = True
            if kind == 'card_funding':
                skipped_funding += 1
                continue
            date, time, merchant, amount = match.groups()
            rows.append(_row(date, merchant.strip(), -_money(amount), 'Purchase'))
            break
        if matched:
            continue
        generic = _GENERIC_SIGNED_LINE.match(chunk)
        if generic:
            date, time, description, sign, amount = generic.groups()
            signed = _money(amount) * (1 if sign == '+' else -1)
            rows.append(_row(date, description.strip(), signed, 'Purchase' if signed < 0 else 'Refund'))
        else:
            unparsed.append(chunk)
    return rows, unparsed, skipped_funding


def _parse_card_statement(text):
    cleaned = _strip_boilerplate(text)
    card_section = _slice_section(cleaned, 'Card transactions', ['Bill payments'])
    bills_section = _slice_section(cleaned, 'Bill payments', ['Pre-authorized debits'])
    preauth_section = _slice_section(cleaned, 'Pre-authorized debits', ['Disclosures'])
    card_rows, card_unparsed, skipped_funding = _parse_card_subsection(card_section)
    bill_rows, bill_unparsed, _ = _parse_card_subsection(bills_section)
    preauth_rows, preauth_unparsed, _ = _parse_card_subsection(preauth_section)
    rows_by_account = {'shakepay-card': card_rows + bill_rows + preauth_rows}
    return rows_by_account, card_unparsed + bill_unparsed + preauth_unparsed, {'skipped_card_funding_transfers': skipped_funding}


def parse_statement_text(text):
    """Returns (statement_type, period, rows_by_account, unparsed, stats).
    Exposed separately from import_shakepay_pdf/extract_text so tests can
    exercise the parsing/mapping logic against small inline text fixtures
    instead of real PDF binaries."""
    text = _insert_missing_spaces(text)
    stype = detect_statement_type(text)
    if stype is None:
        raise ShakepayImportError(
            "Unrecognized statement - doesn't match either the Shakepay Inc. account "
            "statement or the Shakepay Financial Inc. card statement (see finance/README.md)."
        )
    period = statement_period(text)
    if stype == 'account':
        rows_by_account, unparsed, stats = _parse_account_statement(text)
    else:
        rows_by_account, unparsed, stats = _parse_card_statement(text)
    return stype, period, rows_by_account, unparsed, stats


def _save_import_copy(path):
    """Mirrors import_csv._save_upload_copy for audit purposes - keeps a
    timestamped copy of every imported PDF under data/finance/imports/."""
    imports_dir = os.path.join(finance_db.DATA_DIR, 'imports')
    os.makedirs(imports_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    safe_name = os.path.basename(path) or 'statement.pdf'
    dest = os.path.join(imports_dir, f'{stamp}-{safe_name}')
    with open(path, 'rb') as src, open(dest, 'wb') as out:
        out.write(src.read())
    return dest


def import_shakepay_text(conn, source_file, text, imported_at=None):
    """Parses one statement's already-extracted text and range-replace
    loads it into finance.db, one account at a time (each account's own
    date range, same as import_csv.import_csv_text). Split out from
    import_shakepay_pdf so tests can exercise this against plain text
    fixtures instead of real PDF binaries. Returns a summary dict.

    One import_batches row per account (db.create_import_batch's
    `kind='shakepay_{stype}'`), not one per statement: a single Shakepay
    statement covers several sub-accounts (cash, card, crypto) with
    independent date ranges, and a batch's row_count/date_range need to
    agree with one coherent set of inserted rows the way import_csv.py's
    single-account batches already do. Same all-or-nothing behavior for a
    failed import: everything here shares the one `with conn:` below, so
    a failure partway through leaves no batch for the account it failed
    on, and rolls back any batches already created earlier in this same
    call along with their rows.
    """
    stype, period, rows_by_account, unparsed, stats = parse_statement_text(text)
    imported_at = imported_at or dates.now_iso()
    statement_hash = finance_db.file_hash(text)

    accounts_imported = []
    with conn:
        for account_id, rows in rows_by_account.items():
            if not rows:
                continue
            label, institution, kind = ACCOUNTS[account_id]
            finance_db.upsert_account(conn, account_id, label, institution, kind)
            dated_rows = import_csv._assign_ids(account_id, rows, source_file, imported_at)
            row_dates = [r['date'] for r in dated_rows]
            date_start, date_end = min(row_dates), max(row_dates)
            batch_id = finance_db.create_import_batch(
                conn, kind=f'shakepay_{stype}', imported_at=imported_at, source_file=source_file,
                file_hash=statement_hash, date_range_start=date_start, date_range_end=date_end,
                row_count=len(dated_rows),
            )
            for row in dated_rows:
                row['batch_id'] = batch_id
            finance_db.replace_transactions_in_range(conn, account_id, date_start, date_end, dated_rows)
            accounts_imported.append({
                'account_id': account_id,
                'batch_id': batch_id,
                'rows_imported': len(dated_rows),
                'date_start': date_start,
                'date_end': date_end,
            })

    return {
        'source_file': source_file,
        'statement_type': stype,
        'period_start': period[0],
        'period_end': period[1],
        'accounts': accounts_imported,
        'stats': stats,
        'unparsed': unparsed,
    }


def import_shakepay_pdf(conn, path, save_copy=True):
    """Entry point for the CLI below: reads `path` (a real PDF file),
    optionally keeps an audit copy, then imports it via
    import_shakepay_text."""
    text = extract_text(path)
    if save_copy:
        _save_import_copy(path)
    return import_shakepay_text(conn, os.path.basename(path), text)


def _resolve_pdf_paths(args):
    """Each arg is either a statement PDF or a directory of them (e.g. a
    dedicated data/finance/shakepay/ folder you save every month's
    downloads into) - directories are expanded to their *.pdf files
    (non-recursive, case-insensitive extension, sorted for a stable,
    repeatable run order) rather than needing every file named on the
    command line by hand."""
    paths = []
    for arg in args:
        if os.path.isdir(arg):
            pdfs = sorted(
                os.path.join(arg, name) for name in os.listdir(arg)
                if name.lower().endswith('.pdf')
            )
            if not pdfs:
                print(f'{arg}: no .pdf files found, skipping')
            paths.extend(pdfs)
        else:
            paths.append(arg)
    return paths


def main():
    if len(sys.argv) < 2:
        print('usage: python3 backend/finance/import_shakepay.py <statement.pdf | a directory of them> [...]')
        raise SystemExit(1)

    paths = _resolve_pdf_paths(sys.argv[1:])
    if not paths:
        print('No PDFs to import.')
        raise SystemExit(1)

    conn = finance_db.connect()
    try:
        finance_db.init_schema(conn)
        for path in paths:
            summary = import_shakepay_pdf(conn, path)
            print(f"{path}: {summary['statement_type']} statement, "
                  f"{summary['period_start']} to {summary['period_end']}")
            for account in summary['accounts']:
                print(f"  {account['account_id']}: {account['rows_imported']} row(s) "
                      f"({account['date_start']} to {account['date_end']})")
            for key, value in summary['stats'].items():
                if value:
                    print(f'  {key}: {value} (skipped - see finance/README.md)')
            if summary['unparsed']:
                print(f"  {len(summary['unparsed'])} line(s) could not be parsed:")
                for line in summary['unparsed']:
                    print(f'    {line}')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
