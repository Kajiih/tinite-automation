# B2B Intra-EU VAT Automation (`b2b-vat`)

Pure Python domain library and CLI to filter and aggregate zero-rated cross-border B2B transactions from Amazon VAT reports.

## Filtering Rules

1. **Buyer VAT**: Column `Buyer Tax Registration` must be non-empty.
2. **Cross-Border**: `Ship From Country` equals the departure country (default: `FR`) and `Ship To Country` is NOT the departure country.
3. **No Special Scheme**: `Tax Reporting Scheme` is empty (skips OSS, VOEC, deemed reseller).
4. **Zero Tax**: `OUR_PRICE Tax Amount` is `0.00`.

## Calculations

- **Line Net Difference** = `OUR_PRICE Tax Exclusive Selling Price` + `OUR_PRICE Tax Inclusive Promo Amount`
- **VAT Aggregation** = Grouped by `Buyer Tax Registration` with totals for sales HT, promo amounts TTC, and net difference.

## CLI Usage

```bash
# Process report and display summary table in terminal:
uv run b2b-vat -r "path/to/report.csv"

# Process report with custom departure country and CSV exports:
uv run b2b-vat \
  -r "path/to/report.csv" \
  -d "FR" \
  -s "summary.csv" \
  -t "transactions.csv"
```

> To download invoice PDFs, use the companion package `invoice-downloader`:
> ```bash
> uv run invoice-downloader -r "path/to/report.csv"
> ```
