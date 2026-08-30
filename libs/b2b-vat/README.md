# B2B Intra-EU VAT Automation (`b2b-vat`)

Pure Python domain library and CLI to filter and aggregate zero-rated cross-border B2B transactions from Amazon VAT reports, with automatic invoice PDF downloading.

## Filtering Rules

1. **Buyer VAT**: Column `Buyer Tax Registration` must be non-empty.
2. **Cross-Border**: `Ship From Country` equals the departure country (default: `FR`) and `Ship To Country` is NOT the departure country.
3. **No Special Scheme**: `Tax Reporting Scheme` is empty (skips OSS, VOEC, deemed reseller).
4. **Zero Tax**: `OUR_PRICE Tax Amount` is `0.00`.

## Calculations

- **Line Net Difference** = `OUR_PRICE Tax Exclusive Selling Price` + `OUR_PRICE Tax Inclusive Promo Amount`
- **VAT Aggregation** = Grouped by `Buyer Tax Registration` with totals for sales HT, promo amounts TTC, and net difference.

## CLI Usage

### Process Report and Export Summaries
```bash
uv run b2b-vat process \
  --report "path/to/report.csv" \
  --departure "FR" \
  --output-summary "summary.csv" \
  --output-transactions "transactions.csv"
```

### Download Invoices (with browser auto-detection)
```bash
# Automatically finds your active Amazon Seller Central session across installed browsers:
uv run b2b-vat download-invoices -r "path/to/report.csv"

# Or explicitly select a browser / override cookies:
uv run b2b-vat download-invoices -r "path/to/report.csv" --browser edge
uv run b2b-vat download-invoices -r "path/to/report.csv" --browser firefox
uv run b2b-vat download-invoices -r "path/to/report.csv" --cookies "session-id=..."
```
