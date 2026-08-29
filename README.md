# Amazon VAT Report - FC_Transfer Price Automation

A lightweight, robust, production-grade tool to automatically populate missing prices for `FC_TRANSFER` rows in Amazon VAT Transaction Reports (AVTR CSV files) using an Excel price catalog.

Supports both **single CSV file** and **batch folder** processing.

---

## What It Does

1. Matches items by **ASIN** (Column N) against the Excel catalog.
2. Fills **Column T (`COST_PRICE_OF_ITEMS`)** with the unit cost price from Excel.
3. Fills **Column U (`PRICE_OF_ITEMS_AMT_VAT_EXCL`)** with the total line price (`Unit Cost × QTY`).
4. Ensures **Column W (`TOTAL_PRICE_OF_ITEMS_AMT_VAT_EXCL`)** and **Column AD (`TOTAL_ACTIVITY_VALUE_AMT_VAT_EXCL`)** remain empty for `FC_TRANSFER` rows.
5. Preserves all other transaction types (`SALE`, `REFUND`, `RETURN`) and columns untouched.
6. Preserves UTF-8 BOM encoding (`utf-8-sig`) and RFC-compliant CSV formatting.

---

## How to Run

### Method 1: Double-Click Launcher (Easiest for non-technical users)

- **macOS**: Double-click [`run.command`](file:///Users/paquerot/Documents/dev_projects/tinite_script/alex_automation/run.command).
- **Windows**: Double-click [`run.bat`](file:///Users/paquerot/Documents/dev_projects/tinite_script/alex_automation/run.bat).

When prompted:
1. Drag and drop your **CSV file** OR **folder containing CSVs** into the terminal window and press **Enter**.
2. Drag and drop your **Excel price catalog (`.xlsx`)** and press **Enter**.

---

### Method 2: Command Line (CLI)

Run directly with `uv` (recommended, installs dependencies on the fly) or `python3`:

#### Single File Mode
```bash
# Saves output to example_data/01-24_processed.csv
uv run process_report.py --csv "example_data/01-24.csv" --prices "example_data/amazon_asin_prix_achat_cogs_maj.xlsx"
```

#### Batch Folder Mode
```bash
# Processes all CSVs in the folder and saves outputs into example_data/processed/
uv run process_report.py --csv "example_data/" --prices "example_data/amazon_asin_prix_achat_cogs_maj.xlsx"
```

#### CLI Options
| Option | Short | Description |
| :--- | :--- | :--- |
| `--csv` | `-c` | Path to a single CSV file or a directory of CSVs |
| `--prices`, `--excel` | `-p` | Path to the Excel price catalog (`.xlsx`) |
| `--output` | `-o` | *(Optional)* Custom output path (file for single mode, directory for batch mode) |
| `--help` | `-h` | Show help message and exit |

---

## Output Destinations
- **Single File Mode**: Saved alongside the original file as `<filename>_processed.csv` (e.g. `01-24_processed.csv`).
- **Batch Folder Mode**: Saved in a `processed/` subfolder within the input directory (e.g. `folder/processed/01-24.csv`, `folder/processed/02-24.csv`).
