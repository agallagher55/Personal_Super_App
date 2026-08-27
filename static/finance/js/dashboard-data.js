// Sample data for the /finance dashboard template.
//
// Nothing here is live - there is no Plaid sync yet (see
// finance/ARCHITECTURE.md, still Phase 0). Every figure below is
// illustrative so the layout can be reviewed before any real account is
// connected; field names loosely mirror finance/schema.sql (institution,
// account type/subtype, holdings) so swapping this module for a fetch
// against a real `/finance/api/*` endpoint later is a data-shape-only
// change, not a template rewrite.

export const SAMPLE_DATA_NOTE =
  "Sample data — no accounts are connected yet. See finance/ARCHITECTURE.md for the real sync plan.";

export const cashAccounts = [
  { institution: "Wealthsimple", name: "Cash", balance: 4250.18 },
  { institution: "TD", name: "Chequing", balance: 1830.52 },
  { institution: "TD", name: "Savings", balance: 6400.0 },
  { institution: "Tangerine", name: "Savings", balance: 12150.75 },
  { institution: "Shakepay", name: "CAD balance", balance: 320.4 },
];

// Grouped by Canadian tax-advantaged account type rather than institution,
// per the request - all currently at Wealthsimple, the first Plaid-linked
// institution per ARCHITECTURE.md §2.
export const investmentAccounts = [
  {
    accountType: "TFSA",
    institution: "Wealthsimple",
    holdings: [
      { symbol: "VEQT", name: "Vanguard All-Equity ETF", value: 4944.0 },
      { symbol: "AAPL", name: "Apple Inc.", value: 2275.0 },
    ],
  },
  {
    accountType: "RRSP",
    institution: "Wealthsimple",
    holdings: [
      { symbol: "VFV", name: "Vanguard S&P 500 ETF", value: 8718.0 },
      { symbol: "XGRO", name: "iShares Core Growth ETF", value: 1405.0 },
    ],
  },
  {
    accountType: "FHSA",
    institution: "Wealthsimple",
    holdings: [{ symbol: "VEQT", name: "Vanguard All-Equity ETF", value: 1236.0 }],
  },
  {
    accountType: "Non-Registered",
    institution: "Wealthsimple",
    holdings: [
      { symbol: "SHOP", name: "Shopify Inc.", value: 1653.75 },
      { symbol: "TD", name: "TD Bank", value: 1682.0 },
    ],
  },
];

export const bitcoinHoldings = [
  { location: "Shakepay", btc: 0.085, valueCad: 7854.0 },
  { location: "Hardware wallet (cold storage)", btc: 0.041, valueCad: 3788.4 },
];

// Single source of truth for lines of credit: the "Debt" section's Line of
// Credit total and the standalone "Lines of Credit Available" section both
// read from this array instead of duplicating balances.
export const linesOfCredit = [
  { institution: "Wealthsimple", interestRate: 6.7, limit: 15000, balance: 0 },
  { institution: "Tangerine", interestRate: 9.6, limit: 10000, balance: 3500.0 },
  { institution: "TD", interestRate: 7.95, limit: 20000, balance: 0 },
];

export const debt = {
  studentLoan: [{ name: "NSLSC", balance: 8200.0 }],
  creditCards: [
    { institution: "TD", balance: 1240.55 },
    { institution: "RBC", balance: 560.2 },
    { institution: "Tangerine", balance: 85.3 },
    { institution: "Wealthsimple", balance: 210.0 },
  ],
  bills: [
    { name: "Hydro", balance: 145.0 },
    { name: "Internet", balance: 85.0 },
    { name: "Phone", balance: 60.0 },
  ],
};

// Illustrative monthly net-worth snapshots. Independent of the live totals
// above by design: Plaid's investment_holdings table is a snapshot, not a
// history, so a real trend line needs the investment_holdings_history table
// noted as deferred in ARCHITECTURE.md §3/§7 before this can be real data.
export const netWorthHistory = [
  { month: "2025-09", value: 33800 },
  { month: "2025-10", value: 34950 },
  { month: "2025-11", value: 35600 },
  { month: "2025-12", value: 36900 },
  { month: "2026-01", value: 37450 },
  { month: "2026-02", value: 38100 },
  { month: "2026-03", value: 39300 },
  { month: "2026-04", value: 40150 },
  { month: "2026-05", value: 41500 },
  { month: "2026-06", value: 42300 },
  { month: "2026-07", value: 43400 },
  { month: "2026-08", value: 44421.95 },
];
