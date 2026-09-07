#!/usr/bin/env python3
"""Parse Shakepay monthly PDF statements into structured transactions.

Shakepay issues two separate PDFs for the same account each month:

  - the "Shakepay Inc." statement: cash (CAD/USD) and crypto activity
  - the "Shakepay Financial Inc." statement: card purchases, with the
    actual merchant name for each purchase

Card spend only carries a merchant name in the second file. The first
file's "Transfer ... to Shakepay Financial Inc. for Card purchase" lines
fund the same purchases and are intentionally skipped here rather than
imported as separate transactions, to avoid double-counting spend when
both files are given - see finance/README.md.

Usage:
    python3 finance/import_shakepay.py statement1.pdf [statement2.pdf ...]
        [--out data/finance/shakepay_transactions.json]
        [--csv data/finance/shakepay_transactions.csv]
        [--dry-run]

Pass any number of PDFs from any number of months; each is auto-detected
as a "card" or "account" statement from its own content, and results are
merged (upserted by a stable id) into --out so re-running is idempotent.

Requires `pypdf` (pip install pypdf). This repo is otherwise stdlib-only
(see service_now/README.md); pypdf is a scoped exception for this one-off
import tool, same as plaid-python/cryptography are for finance/ per
finance/ARCHITECTURE.md section 1.

This is intentionally standalone: it writes its own JSON/CSV, not
data/finance/finance.db, and doesn't show up on the /finance dashboard
that backend/finance/import_csv.py feeds. Wiring Shakepay in as a real
account there is a bigger step - card purchases would map naturally onto
that system's 'Purchase' activity_type, but everything else here (P2P
sends/receives, round-ups, crypto rewards) has no equivalent in
summary.py's CHEQUING_INCOME_TYPES/CHEQUING_EXPENSE_TYPES yet, and new
uncategorized rows wouldn't appear in Spending until manually categorized
- the same gap already flagged for a second credit card in
finance/ARCHITECTURE.md section A9.
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys

try:
    from pypdf import PdfReader
except ImportError:
    sys.exit("pypdf is required to run this script: pip install pypdf")

DATE_RE = r'\d{4}-\d{2}-\d{2}'
TIME_RE = r'\d{2}:\d{2}:\d{2}'
MONEY_RE = r'[+-][\d,]+\.\d{2}'


def _money(text):
    return float(text.replace(',', '').lstrip('+'))


def extract_text(pdf_path):
    reader = PdfReader(pdf_path)
    pages = [' '.join((page.extract_text() or '').split()) for page in reader.pages]
    return ' '.join(pages)


def statement_period(text):
    match = re.search(r'(\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})', text)
    return (match.group(1), match.group(2)) if match else (None, None)


def detect_statement_type(text):
    if 'Card transactions' in text and 'Shakepay Financial Inc.' in text:
        return 'card'
    if 'Cash transactions (CAD)' in text:
        return 'account'
    return None


def _strip_boilerplate(text):
    text = re.sub(r'Monthly account statement.*?Page \d+ of \d+', ' ', text)
    headers = [
        'Date/time (EST) Transaction Description Debit (CA$) Credit (CA$) Balance (CA$)',
        'Date/time (EST) Transaction Description Debit (US$) Credit (US$) Balance (US$)',
        'Date/time (EST) Transaction Description Debit Credit Market value (CA$)** Original cost (CA$)***',
        'Date/time (EST) Transaction Description Debit Credit',
    ]
    for header in headers:
        text = text.replace(header, ' ')
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
    chunks = re.split(r'(?=' + DATE_RE + r')', section_text)
    return [c.strip() for c in chunks if c.strip()]


def _make_id(*parts):
    return hashlib.sha1('|'.join(str(p) for p in parts).encode()).hexdigest()[:16]


# --- Cash (CAD) subsection -------------------------------------------------

_CASH_PATTERNS = [
    (re.compile(rf'^({DATE_RE}) (Starting|Closing) balance ([\d,]+\.\d{{2}})$'), 'balance_snapshot'),
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) Interac e-Transfer (\S+) ({MONEY_RE}) ([\d,]+\.\d{{2}})$'), 'interac'),
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) (Receive|Send) cash via Shakepay (@\S+) ({MONEY_RE}) ([\d,]+\.\d{{2}})$'), 'p2p'),
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) Transfer Transfer from Shakepay Inc\. to Shakepay Financial '
                rf'Inc\. for Card purchase ({MONEY_RE}) ([\d,]+\.\d{{2}})$'), 'card_funding'),
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) Round up Bought ([\d.]+) BTC @ CA\$([\d,]+\.\d{{2}}) '
                rf'({MONEY_RE}) ([\d,]+\.\d{{2}})$'), 'roundup'),
]


def parse_cash_section(text, source_file):
    transactions = []
    skipped_card_funding = 0
    for chunk in _split_transactions(text):
        matched = False
        for pattern, kind in _CASH_PATTERNS:
            match = pattern.match(chunk)
            if not match:
                continue
            matched = True
            if kind == 'balance_snapshot':
                continue
            if kind == 'card_funding':
                skipped_card_funding += 1
                continue
            if kind == 'interac':
                date, time, counterparty, amount, balance = match.groups()
                amount = _money(amount)
                transactions.append({
                    'id': _make_id('cash', date, time, 'interac', amount),
                    'date': date, 'time': time, 'amount': amount, 'currency': 'CAD',
                    'account': 'shakepay_cash',
                    'category': 'interac_transfer_in' if amount > 0 else 'interac_transfer_out',
                    'kind': 'income' if amount > 0 else 'transfer',
                    'name': f'Interac e-Transfer {counterparty}',
                    'merchant_name': None, 'counterparty': counterparty,
                    'source_file': source_file, 'source_statement': 'account',
                })
            elif kind == 'p2p':
                date, time, direction, handle, amount, balance = match.groups()
                amount = _money(amount)
                transactions.append({
                    'id': _make_id('cash', date, time, 'p2p', handle, amount),
                    'date': date, 'time': time, 'amount': amount, 'currency': 'CAD',
                    'account': 'shakepay_cash',
                    'category': 'p2p_receive' if direction == 'Receive' else 'p2p_send',
                    'kind': 'transfer',
                    'name': f'{direction} cash via Shakepay {handle}',
                    'merchant_name': None, 'counterparty': handle,
                    'source_file': source_file, 'source_statement': 'account',
                })
            elif kind == 'roundup':
                date, time, btc_qty, btc_price, amount, balance = match.groups()
                amount = _money(amount)
                transactions.append({
                    'id': _make_id('cash', date, time, 'roundup', amount),
                    'date': date, 'time': time, 'amount': amount, 'currency': 'CAD',
                    'account': 'shakepay_cash',
                    'category': 'roundup_btc_purchase', 'kind': 'transfer',
                    'name': f'Round up - bought {btc_qty} BTC @ CA${btc_price}',
                    'merchant_name': None, 'counterparty': None,
                    'source_file': source_file, 'source_statement': 'account',
                })
            break
        if not matched:
            transactions.append({'id': _make_id('cash-unparsed', chunk), 'unparsed': True,
                                  'raw': chunk, 'source_file': source_file, 'source_statement': 'account'})
    return transactions, skipped_card_funding


# --- Crypto subsection -------------------------------------------------

_CRYPTO_PATTERNS = [
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) Shakepay reward (ShakingSats|ShakeSquad|Bitcoin cashback) '
                rf'\+([\d.]+) BTC ([\d,]+\.\d{{2}}) ([\d,]+\.\d{{2}})$'), 'reward'),
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) Shakepay Interest Interest payout on CAD balance '
                rf'\+([\d.]+) BTC ([\d,]+\.\d{{2}}) ([\d,]+\.\d{{2}})$'), 'interest'),
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) Receive Bitcoin Bitcoin address (.+?) '
                rf'\+([\d.]+) BTC ([\d,]+\.\d{{2}}) ([\d,]+\.\d{{2}})$'), 'deposit'),
]


def parse_crypto_section(text, source_file):
    transactions = []
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
                    name = f'Shakepay reward - {program}'
                else:
                    btc_qty, value_cad, cost_cad = rest
                    name = 'Shakepay Interest - CAD balance payout'
                transactions.append({
                    'id': _make_id('crypto', date, time, kind, btc_qty),
                    'date': date, 'time': time, 'amount': _money(value_cad), 'currency': 'CAD',
                    'account': 'shakepay_crypto',
                    'category': 'crypto_reward' if kind == 'reward' else 'crypto_interest',
                    'kind': 'income', 'name': name, 'merchant_name': None, 'counterparty': None,
                    'btc_quantity': float(btc_qty), 'original_cost_cad': _money(cost_cad),
                    'source_file': source_file, 'source_statement': 'account',
                })
            else:
                date, time, address, btc_qty, value_cad, cost_cad = match.groups()
                transactions.append({
                    'id': _make_id('crypto', date, time, 'deposit', btc_qty, value_cad),
                    'date': date, 'time': time, 'amount': _money(value_cad), 'currency': 'CAD',
                    'account': 'shakepay_crypto', 'category': 'crypto_deposit', 'kind': 'transfer',
                    'name': 'Receive Bitcoin', 'merchant_name': None, 'counterparty': address,
                    'btc_quantity': float(btc_qty), 'original_cost_cad': _money(cost_cad),
                    'source_file': source_file, 'source_statement': 'account',
                })
            break
        if not matched:
            transactions.append({'id': _make_id('crypto-unparsed', chunk), 'unparsed': True,
                                  'raw': chunk, 'source_file': source_file, 'source_statement': 'account'})
    return transactions, skipped_roundup_mirrors


def parse_account_statement(text, source_file):
    cleaned = _strip_boilerplate(text)
    cash_section = _slice_section(cleaned, 'Cash transactions (CAD)', ['US Dollar (USD) transactions'])
    crypto_section = _slice_section(cleaned, 'Crypto transactions', ['Audit Notice', 'Disclosures'])
    cash_txns, skipped_funding = parse_cash_section(cash_section, source_file)
    crypto_txns, skipped_roundups = parse_crypto_section(crypto_section, source_file)
    return cash_txns + crypto_txns, {
        'skipped_card_funding_transfers': skipped_funding,
        'skipped_roundup_mirrors': skipped_roundups,
    }


# --- Card statement -------------------------------------------------

_CARD_PATTERNS = [
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) Transfer Transfer from Shakepay Inc\. to Shakepay Financial '
                rf'Inc\. for Card purchase \+\$([\d,]+\.\d{{2}})$'), 'card_funding'),
    (re.compile(rf'^({DATE_RE}) ({TIME_RE}) Card purchase (.+?) -\$([\d,]+\.\d{{2}})$'), 'purchase'),
]
_GENERIC_SIGNED_LINE = re.compile(rf'^({DATE_RE}) ({TIME_RE}) (.+?) ([+-])\$([\d,]+\.\d{{2}})$')


def parse_card_subsection(text, source_file, default_category):
    transactions = []
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
            merchant = merchant.strip()
            amount = -_money(amount)
            transactions.append({
                'id': _make_id('card', date, time, 'purchase', merchant, amount),
                'date': date, 'time': time, 'amount': amount, 'currency': 'CAD',
                'account': 'shakepay_card', 'category': 'card_purchase', 'kind': 'expense',
                'name': f'Card purchase {merchant}', 'merchant_name': merchant, 'counterparty': None,
                'source_file': source_file, 'source_statement': 'card',
            })
            break
        if matched:
            continue
        generic = _GENERIC_SIGNED_LINE.match(chunk)
        if generic:
            date, time, description, sign, amount = generic.groups()
            amount = _money(amount) * (1 if sign == '+' else -1)
            transactions.append({
                'id': _make_id('card', date, time, default_category, description, amount),
                'date': date, 'time': time, 'amount': amount, 'currency': 'CAD',
                'account': 'shakepay_card', 'category': default_category,
                'kind': 'expense' if amount < 0 else 'income',
                'name': description.strip(), 'merchant_name': None, 'counterparty': None,
                'source_file': source_file, 'source_statement': 'card',
            })
        else:
            transactions.append({'id': _make_id('card-unparsed', chunk), 'unparsed': True,
                                  'raw': chunk, 'source_file': source_file, 'source_statement': 'card'})
    return transactions, skipped_funding


def parse_card_statement(text, source_file):
    cleaned = _strip_boilerplate(text)
    card_section = _slice_section(cleaned, 'Card transactions', ['Bill payments'])
    bills_section = _slice_section(cleaned, 'Bill payments', ['Pre-authorized debits'])
    preauth_section = _slice_section(cleaned, 'Pre-authorized debits', ['Disclosures'])
    card_txns, skipped_funding = parse_card_subsection(card_section, source_file, 'card_purchase')
    bill_txns, _ = parse_card_subsection(bills_section, source_file, 'bill_payment')
    preauth_txns, _ = parse_card_subsection(preauth_section, source_file, 'preauth_debit')
    return card_txns + bill_txns + preauth_txns, {'skipped_card_funding_transfers': skipped_funding}


def parse_pdf(pdf_path):
    text = extract_text(pdf_path)
    stype = detect_statement_type(text)
    source_file = os.path.basename(pdf_path)
    period = statement_period(text)
    if stype == 'account':
        txns, stats = parse_account_statement(text, source_file)
    elif stype == 'card':
        txns, stats = parse_card_statement(text, source_file)
    else:
        raise ValueError(f'{pdf_path}: could not detect statement type (not a recognized Shakepay statement)')
    return stype, period, txns, stats


def load_store(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        records = json.load(f)
    return {r['id']: r for r in records}


def write_store(path, by_id):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    records = [r for r in by_id.values() if not r.get('unparsed')]
    records.sort(key=lambda r: (r['date'], r.get('time') or ''))
    with open(path, 'w') as f:
        json.dump(records, f, indent=2)
    return records


def write_csv(path, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fields = ['date', 'time', 'amount', 'currency', 'account', 'category', 'kind',
              'name', 'merchant_name', 'counterparty', 'source_file', 'source_statement']
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for record in records:
            writer.writerow(record)


def print_summary(period, all_new_txns, all_stats, unparsed):
    start, end = period
    if start:
        print(f'Statement period: {start} to {end}')
    purchases = [t for t in all_new_txns if t.get('category') == 'card_purchase']
    if purchases:
        total = sum(t['amount'] for t in purchases)
        print(f'Card purchases: {len(purchases)} totaling ${-total:,.2f}')
        by_merchant = {}
        for t in purchases:
            by_merchant[t['merchant_name']] = by_merchant.get(t['merchant_name'], 0) + t['amount']
        print('Top merchants:')
        for merchant, amount in sorted(by_merchant.items(), key=lambda kv: kv[1])[:10]:
            print(f'  {merchant:<30} ${-amount:,.2f}')
    for stats in all_stats:
        for key, value in stats.items():
            if value:
                print(f'{key}: {value} (skipped - see finance/README.md)')
    if unparsed:
        print(f'\n{len(unparsed)} line(s) could not be parsed - review and extend import_shakepay.py:')
        for record in unparsed:
            print(f'  [{record["source_file"]}] {record["raw"]}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('pdfs', nargs='+', help='Shakepay statement PDF(s), any month, any order')
    parser.add_argument('--out', default='data/finance/shakepay_transactions.json',
                         help='cumulative JSON store to upsert into (default: %(default)s)')
    parser.add_argument('--csv', default=None, help='also write a CSV export to this path')
    parser.add_argument('--dry-run', action='store_true', help='parse and print a summary, write nothing')
    args = parser.parse_args()

    by_id = {} if args.dry_run else load_store(args.out)
    all_new_txns, all_stats, unparsed, period = [], [], [], (None, None)

    for pdf_path in args.pdfs:
        stype, this_period, txns, stats = parse_pdf(pdf_path)
        print(f'{pdf_path}: detected as "{stype}" statement, {len(txns)} line(s) parsed')
        period = this_period if this_period[0] else period
        all_stats.append(stats)
        for txn in txns:
            by_id[txn['id']] = txn
            if txn.get('unparsed'):
                unparsed.append(txn)
            else:
                all_new_txns.append(txn)

    print()
    print_summary(period, all_new_txns, all_stats, unparsed)

    if args.dry_run:
        print('\n(dry run - nothing written)')
        return

    records = write_store(args.out, by_id)
    print(f'\nWrote {len(records)} transaction(s) to {args.out}')
    if args.csv:
        write_csv(args.csv, records)
        print(f'Wrote CSV export to {args.csv}')


if __name__ == '__main__':
    main()
