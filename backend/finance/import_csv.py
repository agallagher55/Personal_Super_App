"""Parses the two CSV export formats reviewed in finance/ARCHITECTURE.md
Part A2 (credit card activity, and general bank activity) and range-replace
loads them into the transactions table (see db.replace_transactions_in_range
for why range-replace rather than per-row dedup).

Pending purchases count the same as Completed ones everywhere downstream
(decided 2026-09-06, ARCHITECTURE.md A8) - `status` is stored for
reference but nothing here filters rows on it.
"""

import csv
import io
import os
from datetime import datetime, timezone

import db as finance_db
import summary as finance_summary

CREDIT_CARD_HEADER = {
    'transaction_date', 'transaction_type', 'status', 'merchant',
    'amount', 'currency', 'notes', 'category',
}
BANK_ACTIVITY_HEADER = {
    'effective_date', 'effective_time', 'settlement_date', 'account_id',
    'account_type', 'activity_type', 'activity_sub_type', 'description',
    'direction', 'symbol', 'name', 'currency', 'quantity', 'unit_price',
    'commission', 'net_cash_amount',
}

# Neither the file name nor any column in the credit card export identifies
# which card it is (ARCHITECTURE.md A2/A8), so one card is assumed until
# there's a reason - and a way - to support more.
DEFAULT_CREDIT_CARD_ACCOUNT = 'main-credit-card'
DEFAULT_CREDIT_CARD_LABEL = 'Credit Card'
# Confirmed 2026-09-07 (finance/README.md, "each source differentiated
# by colour"): main-credit-card is the Wealthsimple card - setting this
# lets summary.monthly_trend_by_source() group Spend by Month by source
# without a schema change (accounts.institution already exists, just
# wasn't populated for CSV-imported accounts until now).
DEFAULT_CREDIT_CARD_INSTITUTION = 'Wealthsimple'

MAX_IMPORT_BYTES = 5 * 1024 * 1024  # generous for a personal export


class ImportFormatError(ValueError):
    """The uploaded file's header didn't match either known export shape,
    or otherwise couldn't be turned into transaction rows."""


def detect_kind(fieldnames):
    fields = set(fieldnames or [])
    if CREDIT_CARD_HEADER <= fields:
        return 'credit_card'
    if BANK_ACTIVITY_HEADER <= fields:
        return 'bank_activity'
    return None


def _rows_from_credit_card(reader):
    rows = []
    for row in reader:
        date = row['transaction_date'].strip()
        if not date:
            continue
        # `merchant` is blank on Payment rows (paying the card bill has no
        # merchant) - `notes` as a second fallback, then the transaction
        # type itself, so no row ends up with a blank description.
        description = row['merchant'].strip() or row.get('notes', '').strip() or row['transaction_type'].strip()
        rows.append({
            'date': date,
            'description': description,
            'amount': float(row['amount']),
            'activity_type': row['transaction_type'].strip(),
            'category': row['category'].strip() or None,
            'status': row['status'].strip() or None,
        })
    return rows


def _rows_from_bank_activity(rows_in):
    rows = []
    for row in rows_in:
        date = row['effective_date'].strip()
        if not date:
            continue
        # `activity_type` alone (MoneyMovement/BonusPayment/Interest) is too
        # coarse to be useful downstream - it's the same value on a direct
        # deposit, a bill payment, and an e-transfer alike. `activity_sub_type`
        # (AFT_IN, SPEND, CASHBACK, E_TRFOUT, ...) is what actually
        # distinguishes them, and is what summary.py's income/expense
        # classification (ARCHITECTURE.md Part A, Cash Flow) keys off. Falls
        # back to the coarse type only when sub_type is blank or '-' (as on
        # Interest rows), so that case still gets a meaningful value instead
        # of an empty string.
        sub_type = row['activity_sub_type'].strip()
        activity_type = sub_type if sub_type and sub_type != '-' else row['activity_type'].strip()
        rows.append({
            'date': date,
            'description': row['description'].strip(),
            'amount': float(row['net_cash_amount']),
            'activity_type': activity_type,
            # Income rows (direct deposits, cashback, interest, ...) default
            # to 'Income'; expense-type rows (debit spend, pre-authorized
            # debits, bill payments, P2P sends - summary.CHEQUING_EXPENSE_TYPES)
            # default to 'Uncategorized', the same label the credit card
            # export itself uses for its own uncategorized rows (its Payment
            # rows) - both are folded into Spending (ARCHITECTURE.md A5g), so
            # both need a real value here rather than sitting NULL, ready to
            # be fixed via the same one-time/permanent override mechanism
            # ("Editing categories"). Everything else (e-transfers, TRANSFER,
            # EFT - can't tell real income/expense from a transfer between
            # your own accounts, per summary.py) stays NULL: it's excluded
            # from both Spending and Cash Flow entirely, so a category would
            # never be seen anyway. Uses summary.py's CHEQUING_INCOME_TYPES/
            # CHEQUING_EXPENSE_TYPES as the one source of truth for these
            # classifications, rather than a second hardcoded copy here.
            'category': _default_chequing_category(activity_type),
            'status': None,
        })
    return rows


def _default_chequing_category(activity_type):
    if activity_type in finance_summary.CHEQUING_INCOME_TYPES:
        return 'Income'
    if activity_type in finance_summary.CHEQUING_EXPENSE_TYPES:
        return 'Uncategorized'
    return None


def parse_csv_text(text):
    """Returns (kind, account_id, account_label, account_kind, rows), where
    rows have date/description/amount/activity_type/category/status but no
    id/account_id yet (assigned by import_csv_text once the account is
    resolved)."""
    reader = csv.DictReader(io.StringIO(text))
    kind = detect_kind(reader.fieldnames)
    if kind is None:
        raise ImportFormatError(
            "Unrecognized CSV header - doesn't match the credit card or bank "
            "activity export formats documented in finance/ARCHITECTURE.md Part A2."
        )

    if kind == 'credit_card':
        rows = _rows_from_credit_card(reader)
        if not rows:
            raise ImportFormatError('CSV has a header but no usable data rows.')
        return kind, DEFAULT_CREDIT_CARD_ACCOUNT, DEFAULT_CREDIT_CARD_LABEL, 'credit_card', rows

    raw_rows = list(reader)
    if not raw_rows:
        raise ImportFormatError('CSV has a header but no data rows.')
    account_id = raw_rows[0]['account_id'].strip()
    account_label = raw_rows[0]['account_type'].strip() or 'Bank account'
    if not account_id:
        raise ImportFormatError('Bank activity export is missing account_id on its first row.')
    rows = _rows_from_bank_activity(raw_rows)
    if not rows:
        raise ImportFormatError('CSV has a header but no usable data rows.')
    return kind, account_id, account_label, 'chequing', rows


def _assign_ids(account_id, rows, source_file, imported_at):
    """Ids come from row content, not file position - see
    db.transaction_id for why. `occurrence` counts rows that are
    identical in every hashed field, so two separate same-day charges of
    the same amount at the same merchant still get distinct ids.
    """
    occurrences = {}
    out = []
    for row in rows:

        key = (row['date'], row['description'], row['amount'], row['activity_type'])
        occurrence = occurrences.get(key, 0)
        occurrences[key] = occurrence + 1

        out.append({
            'id': finance_db.transaction_id(account_id, *key, occurrence),
            'account_id': account_id,
            'source_file': source_file,
            'imported_at': imported_at,
            'btc_quantity': row.get('btc_quantity'),  # only import_shakepay.py's ROUNDUP_BUY rows set this
            **row,
        })
    return out


def import_csv_text(conn, source_file, text):
    """Parses `text` (one export file's full contents) and range-replace
    loads it into the transactions table. Returns a summary dict."""
    kind, account_id, account_label, account_kind, rows = parse_csv_text(text)

    imported_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    dated_rows = _assign_ids(account_id, rows, source_file, imported_at)
    dates = [r['date'] for r in dated_rows]

    institution = DEFAULT_CREDIT_CARD_INSTITUTION if kind == 'credit_card' else None
    with conn:
        finance_db.upsert_account(conn, account_id, account_label, institution, account_kind)
        finance_db.replace_transactions_in_range(conn, account_id, min(dates), max(dates), dated_rows)

    return {
        'kind': kind,
        'account_id': account_id,
        'rows_imported': len(dated_rows),
        'date_start': min(dates),
        'date_end': max(dates),
    }


def _save_upload_copy(filename, text):
    """Keeps a timestamped copy of every uploaded file under
    data/finance/imports/ for audit purposes - matches source_file on each
    transaction row back to the exact file it came from."""
    imports_dir = os.path.join(finance_db.DATA_DIR, 'imports')
    os.makedirs(imports_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    safe_name = os.path.basename(filename) or 'upload.csv'
    dest = os.path.join(imports_dir, f'{stamp}-{safe_name}')
    with open(dest, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    return dest


def import_uploaded_file(filename, text):
    """Entry point for backend/server.py's POST /finance/import route:
    saves an audit copy, then imports it."""
    _save_upload_copy(filename, text)
    conn = finance_db.connect()
    try:
        finance_db.init_schema(conn)
        return import_csv_text(conn, filename, text)
    finally:
        conn.close()


def _resolve_csv_paths(args):
    """Each arg is either a CSV file or a directory of them (e.g. a
    standing data/finance/wealthsimple/ folder you save every export
    into) - directories are expanded to their *.csv files (non-recursive,
    case-insensitive extension, sorted for a stable run order), same
    convention as import_shakepay._resolve_pdf_paths."""
    paths = []
    for arg in args:
        if os.path.isdir(arg):
            csvs = sorted(
                os.path.join(arg, name) for name in os.listdir(arg)
                if name.lower().endswith('.csv')
            )
            if not csvs:
                print(f'{arg}: no .csv files found, skipping')
            paths.extend(csvs)
        else:
            paths.append(arg)
    return paths


def main():
    import sys
    if len(sys.argv) < 2:
        print('usage: python3 backend/finance/import_csv.py <path-to-csv | a directory of them> [...]')
        raise SystemExit(1)

    paths = _resolve_csv_paths(sys.argv[1:])
    if not paths:
        print('No CSVs to import.')
        raise SystemExit(1)

    for path in paths:
        with open(path, 'r', encoding='utf-8-sig') as f:
            text = f.read()
        try:
            summary = import_uploaded_file(os.path.basename(path), text)
        except ImportFormatError as error:
            print(f'{path}: {error}')
            continue
        print(f'{path}: {summary}')


if __name__ == '__main__':
    main()
