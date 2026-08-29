# Amazon VAT Report - FC_Transfer Price Automation

Production-grade automation to populate unit cost (Column T: `COST_PRICE_OF_ITEMS`) and line total (Column U: `PRICE_OF_ITEMS_AMT_VAT_EXCL`) for `FC_TRANSFER` rows in Amazon VAT Transaction Reports (AVTR) based on an Excel price catalog, and calculate Departure Country × Arrival Country cross-border summaries.

---

## Quickstart

### 1. 1-Click Double-Click Launcher (Default: Web App)
- **macOS**: Double-click `run.command`
- **Windows**: Double-click `run.bat`

*Starts the local web server on an available port and automatically opens the application in your browser.*

---

### 2. Command Line (CLI)

#### Interactive Terminal Mode:
```bash
uv run process-report --cli
# or via launcher:
./run.command --cli
```

#### Direct Invocation:
```bash
# Single file processing
uv run process-report --vat-report "example_data/sample_vat_report.csv" --price-catalog "example_data/amazon_asin_prix_achat_cogs_maj.xlsx"

# Batch folder processing
uv run process-report --vat-report "example_data/" --price-catalog "example_data/amazon_asin_prix_achat_cogs_maj.xlsx"
```

---

## Project Structure

```
amazon-vat-report-automation/
├── .gitignore
├── pyproject.toml
├── README.md
├── run.command                     # macOS 1-click launcher
├── run.bat                         # Windows 1-click launcher
├── example_data/                   # Sample CSV reports and Excel catalog
│   ├── sample_vat_report.csv
│   └── amazon_asin_prix_achat_cogs_maj.xlsx
├── src/
│   └── amazon_vat_automation/
│       ├── __init__.py
│       └── process_report.py       # Core domain engine, CLI, & Web server
├── web/
│   └── index.html                  # WebAssembly browser application
└── tests/
    └── test_e2e.py                 # End-to-end test suite
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
