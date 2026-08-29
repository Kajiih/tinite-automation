# Amazon VAT Report - FC_Transfer Price Automation

A lightweight, robust, production-grade tool to automatically populate missing prices for `FC_TRANSFER` rows in Amazon VAT Transaction Reports (AVTR CSV files) using an Excel price catalog, and calculate **Departure Country × Arrival Country cross-border transfer summaries**.

Supports both **single CSV file** and **batch folder** processing.

---

## What It Does

1. **ASIN Price Matching**: Matches items by `ASIN` (Column N) against the Excel catalog.
2. **Unit Cost (Column T: `COST_PRICE_OF_ITEMS`)**: Populated with the unit cost price from Excel.
3. **Line Total (Column U: `PRICE_OF_ITEMS_AMT_VAT_EXCL`)**: Populated with `Unit Cost × QTY`.
4. **Clean Columns**: Ensures Columns W and AD remain empty for `FC_TRANSFER` rows.
5. **Preserves Non-Transfer Data**: Leaves all `SALE`, `REFUND`, and `RETURN` rows 100% untouched.
6. **Country Departure × Arrival Summary**: Calculates transfers count, total units moved, and total value in EUR for each cross-border route (e.g. `FR -> DE`, `DE -> CZ`), displaying an aligned table in the terminal and exporting dedicated summary CSVs.
7. **Encoding & Standards**: Uses UTF-8 BOM (`utf-8-sig`) and RFC-compliant quoting.

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

#### Single File Mode
```bash
uv run process_report.py --csv "example_data/01-24.csv" --prices "example_data/amazon_asin_prix_achat_cogs_maj.xlsx"
```
Outputs created:
- `example_data/01-24_processed.csv` (Filled Amazon VAT report)
- `example_data/01-24_country_summary.csv` (Departure × Arrival summary table)

#### Batch Folder Mode
```bash
uv run process_report.py --csv "example_data/" --prices "example_data/amazon_asin_prix_achat_cogs_maj.xlsx"
```
Outputs created:
- `example_data/processed/<filename>.csv` (Filled report per file)
- `example_data/processed/<filename>_country_summary.csv` (Route summary per file)
- `example_data/processed/batch_country_summary.csv` (Consolidated route summary for all files)

#### CLI Options
| Option | Short | Description |
| :--- | :--- | :--- |
| `--csv` | `-c` | Path to a single CSV file or a directory of CSVs |
| `--prices`, `--excel` | `-p` | Path to the Excel price catalog (`.xlsx`) |
| `--output` | `-o` | *(Optional)* Custom output path (file for single mode, directory for batch mode) |
| `--help` | `-h` | Show help message and exit |

---

## Country Summary CSV Format
| DEPARTURE_COUNTRY | ARRIVAL_COUNTRY | TRANSFER_COUNT | TOTAL_QTY | TOTAL_AMOUNT_EUR |
| :--- | :--- | :--- | :--- | :--- |
| CZ | DE | 5 | 87 | 258.85 |
| CZ | IT | 3 | 12 | 34.80 |
| DE | CZ | 41 | 370 | 1204.60 |
| FR | DE | 84 | 473 | 1637.75 |
| **TOTAL** | | **215** | **1723** | **7904.53** |
