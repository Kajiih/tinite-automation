# Amazon VAT Report - FC_Transfer Price Automation

A lightweight, user-friendly tool to automatically populate missing prices for `FC_TRANSFER` rows in Amazon VAT Transaction Reports (AVTR CSV files) based on an Excel price catalog.

---

## What It Does

1. Matches items by **ASIN** (Column N) against the Excel catalog.
2. Fills **Column T (`COST_PRICE_OF_ITEMS`)** with the unit cost price from Excel.
3. Fills **Column U (`PRICE_OF_ITEMS_AMT_VAT_EXCL`)** with the total price for the line (`Unit Cost × QTY`).
4. Ensures **Column W (`TOTAL_PRICE_OF_ITEMS_AMT_VAT_EXCL`)** and **Column AD (`TOTAL_ACTIVITY_VALUE_AMT_VAT_EXCL`)** remain empty for `FC_TRANSFER` rows.
5. Leaves all other transactions (`SALE`, `REFUND`, `RETURN`) and columns untouched.
6. Preserves UTF-8 BOM encoding (`utf-8-sig`) and exact CSV formatting.

---

## How to Run

### Method 1: Double-Click Launcher (Easiest for non-technical users)

- **macOS**: Double-click `run.command`.
- **Windows**: Double-click `run.bat`.

When prompted, simply **drag and drop** your CSV file and Excel price file into the terminal window and press **Enter**.

---

### Method 2: Command Line (CLI)

Run directly with `uv` (recommended, auto-installs dependencies on the fly) or `python3`:

```bash
# Basic usage (output defaults to <input>_processed.csv)
uv run process_report.py --csv "example_data/01-24.csv" --prices "example_data/amazon_asin_prix_achat_cogs_maj.xlsx"

# Custom output destination
uv run process_report.py --csv "example_data/01-24.csv" --prices "example_data/amazon_asin_prix_achat_cogs_maj.xlsx" --output "output/01-24_filled.csv"
```

#### CLI Options
| Option | Short | Description |
| :--- | :--- | :--- |
| `--csv` | `-c` | Path to the Amazon VAT CSV report |
| `--prices`, `--excel` | `-p` | Path to the Excel price catalog (`.xlsx`) |
| `--output` | `-o` | *(Optional)* Custom output CSV path (default: `<csv_name>_processed.csv`) |
| `--help` | `-h` | Show help message and exit |

---

## Missing ASIN Handling
If any ASIN in `FC_TRANSFER` rows is not found in the Excel price list:
- The script continues processing without failing.
- The corresponding price cells remain empty.
- A summary warning is displayed at the end of the run listing all missing ASINs.
