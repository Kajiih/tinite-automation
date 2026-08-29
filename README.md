# Amazon VAT Report - FC_Transfer Price Automation

A lightweight tool to automatically populate missing prices for `FC_TRANSFER` rows in Amazon VAT Transaction Reports (AVTR CSV files) using an Excel price catalog, and calculate **Departure Country × Arrival Country cross-border transfer summaries**.

---

## What It Does

1. **ASIN Price Matching**: Matches items by `ASIN` (Column N) against the Excel catalog.
2. **Unit Cost (Column T: `COST_PRICE_OF_ITEMS`)**: Populated with the unit cost price from Excel.
3. **Line Total (Column U: `PRICE_OF_ITEMS_AMT_VAT_EXCL`)**: Populated with `Unit Cost × QTY`.
6. **Country Departure × Arrival Summary**: Calculates transfers count, total units moved, and total value in EUR for each cross-border route (e.g. `FR -> DE`, `DE -> CZ`), displaying an aligned table in the terminal and exporting dedicated summary CSVs.

---

## How to Run

### Method 1: Double-Click Launcher (Zero setup for non-technical users)

- **macOS**: Double-click [`run.command`](file:///Users/paquerot/Documents/dev_projects/tinite_script/alex_automation/run.command).
- **Windows**: Double-click [`run.bat`](file:///Users/paquerot/Documents/dev_projects/tinite_script/alex_automation/run.bat).

*(If `uv` is not already installed on the machine, the launcher installs it automatically on the first run).*

When prompted:
1. Drag and drop your **CSV file** OR **folder containing CSVs** into the terminal window and press **Enter**.
2. Drag and drop your **Excel price catalog (`.xlsx`)** and press **Enter**.

---

### Method 2: Command Line (CLI)

```bash
# Single file mode
uv run process_report.py --csv "example_data/01-24.csv" --prices "example_data/amazon_asin_prix_achat_cogs_maj.xlsx"

# Batch folder mode
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

## Output Files
- **Processed Report**:
  - Single Mode: `<filename>_processed.csv`
  - Batch Mode: `processed/<filename>.csv`
- **Country Departure × Arrival Summary**:
  - Single Mode: `<filename>_country_summary.csv`
  - Batch Mode: `processed/<filename>_country_summary.csv` (per file) and `processed/batch_country_summary.csv` (consolidated total)

### Country Summary CSV Format
| DEPARTURE_COUNTRY | ARRIVAL_COUNTRY | TRANSFER_COUNT | TOTAL_QTY | TOTAL_AMOUNT_EUR |
| :--- | :--- | :--- | :--- | :--- |
| CZ | DE | 5 | 6 | 23.80 |
| CZ | IT | 3 | 16 | 48.00 |
| DE | CZ | 41 | 96 | 323.93 |
| FR | DE | 84 | 453 | 3058.52 |
| **TOTAL** | | **215** | **1249** | **7904.53** |
