# Amazon VAT Report - FC_Transfer Price Automation

Fills unit prices and line totals for `FC_TRANSFER` rows in Amazon VAT Transaction Reports (AVTR) using an Excel price catalog, and generates Departure Country × Arrival Country cross-border summaries.

---

## Quickstart

### Option 1: Double-Click Launcher
1. Double-click `run.command` (macOS) or `run.bat` (Windows).
2. Drag and drop your VAT report CSV file or folder containing reports, then press **Enter**.
3. Drag and drop your Excel price catalog (`.xlsx`), then press **Enter**.

---

### Option 2: Command Line (CLI)

```bash
# Single file
uv run process_report.py --vat-report "example_data/sample_vat_report.csv" --price-catalog "example_data/amazon_asin_prix_achat_cogs_maj.xlsx"

# Batch folder
uv run process_report.py --vat-report "example_data/" --price-catalog "example_data/amazon_asin_prix_achat_cogs_maj.xlsx"
```

---

## Output Files

### Single File Mode
- `<filename>_processed.csv`: VAT report with filled `COST_PRICE_OF_ITEMS` (Col T) and `PRICE_OF_ITEMS_AMT_VAT_EXCL` (Col U).
- `<filename>_country_summary.csv`: Route summary table of transfers, units, and total value.

### Batch Folder Mode
- `processed/<filename>.csv`: Processed report for each input CSV.
- `processed/<filename>_country_summary.csv`: Route summary for each file.
- `processed/batch_country_summary.csv`: Consolidated cross-border totals for all files.
