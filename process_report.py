# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "openpyxl",
# ]
# ///
"""
Amazon VAT Transaction Report - FC_Transfer Price Automation

This script fills unit price (Column T: COST_PRICE_OF_ITEMS) and total line price
(Column U: PRICE_OF_ITEMS_AMT_VAT_EXCL) for FC_TRANSFER rows by matching ASINs
against a provided Excel price catalog.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


def clean_path_input(raw_input: str) -> Path:
    """Clean path strings obtained from user input / drag-and-drop."""
    cleaned = raw_input.strip().strip("'\"").strip()
    return Path(cleaned).expanduser().resolve()


def load_price_catalog(excel_path: Path | str) -> Dict[str, float]:
    """
    Load ASIN -> unit price mapping from the Excel catalog.
    
    Finds the ASIN column and the unit price column either by header name
    or defaults to columns 1 and 2.
    """
    import openpyxl

    path = Path(excel_path)
    if not path.exists():
        raise FileNotFoundError(f"Excel price catalog not found at: {path}")

    workbook = openpyxl.load_workbook(filename=path, data_only=True, read_only=True)
    sheet = workbook.active
    if sheet is None:
        raise ValueError(f"No active sheet found in {path}")

    rows_iter = sheet.iter_rows(values_only=True)
    header_row = next(rows_iter, None)
    if not header_row:
        raise ValueError(f"The Excel file {path} is empty.")

    # Find ASIN and Price column indexes
    asin_col_idx = 0
    price_col_idx = 1

    for idx, cell in enumerate(header_row):
        if cell is None:
            continue
        cell_str = str(cell).strip().lower()
        if "asin" in cell_str:
            asin_col_idx = idx
        elif any(k in cell_str for k in ["price cost", "prix d'achat", "cogs", "cost", "price", "prix"]):
            # Prefer price cost / cogs
            price_col_idx = idx

    price_map: Dict[str, float] = {}
    for row in rows_iter:
        if not row or len(row) <= asin_col_idx:
            continue
        raw_asin = row[asin_col_idx]
        if raw_asin is None:
            continue

        asin = str(raw_asin).strip()
        if not asin or asin.lower() == "asin":
            continue

        raw_price = row[price_col_idx] if len(row) > price_col_idx else None
        if raw_price is None:
            continue

        try:
            if isinstance(raw_price, (int, float)):
                price = float(raw_price)
            else:
                price = float(str(raw_price).replace(",", ".").strip())
            price_map[asin] = price
        except (ValueError, TypeError):
            continue

    workbook.close()
    return price_map


def process_vat_report(
    csv_path: Path | str,
    excel_path: Path | str,
    output_path: Path | str | None = None,
) -> dict:
    """
    Process the Amazon VAT CSV report and fill FC_TRANSFER prices.
    
    Returns a dictionary with processing statistics.
    """
    csv_path = Path(csv_path)
    excel_path = Path(excel_path)

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV report not found at: {csv_path}")

    if output_path is None:
        output_path = csv_path.parent / f"{csv_path.stem}_processed{csv_path.suffix}"
    else:
        output_path = Path(output_path)

    price_catalog = load_price_catalog(excel_path)

    # Read CSV
    with open(csv_path, mode="r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.reader(infile)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError(f"CSV file is empty: {csv_path}")

        # Map column names to indexes
        col_indices = {col.strip(): i for i, col in enumerate(header)}

        # Helper to find column index with fallback
        def get_col_index(name: str, fallback: int) -> int:
            return col_indices.get(name, fallback)

        idx_type = get_col_index("TRANSACTION_TYPE", 5)
        idx_asin = get_col_index("ASIN", 13)
        idx_qty = get_col_index("QTY", 16)
        idx_cost_price = get_col_index("COST_PRICE_OF_ITEMS", 19)
        idx_item_price_vat_excl = get_col_index("PRICE_OF_ITEMS_AMT_VAT_EXCL", 20)
        idx_total_price_vat_excl = get_col_index("TOTAL_PRICE_OF_ITEMS_AMT_VAT_EXCL", 22)
        idx_total_activity_vat_excl = get_col_index("TOTAL_ACTIVITY_VALUE_AMT_VAT_EXCL", 29)

        total_rows = 0
        fc_transfer_count = 0
        fc_transfer_updated = 0
        missing_asins: Set[str] = set()
        missing_rows_count = 0
        total_value_added = 0.0

        output_rows: List[List[str]] = [header]

        for row in reader:
            total_rows += 1
            if not row:
                continue

            # Ensure row length matches header
            if len(row) < len(header):
                row.extend([""] * (len(header) - len(row)))

            trans_type = row[idx_type].strip().upper() if len(row) > idx_type else ""

            if trans_type == "FC_TRANSFER":
                fc_transfer_count += 1
                asin = row[idx_asin].strip() if len(row) > idx_asin else ""
                
                # Parse quantity
                qty_str = row[idx_qty].strip() if len(row) > idx_qty else "1"
                try:
                    qty = float(qty_str) if qty_str else 1.0
                except ValueError:
                    qty = 1.0

                if asin in price_catalog:
                    unit_price = price_catalog[asin]
                    total_price = unit_price * qty

                    # Format numbers with 2 decimal places
                    row[idx_cost_price] = f"{unit_price:.2f}"
                    row[idx_item_price_vat_excl] = f"{total_price:.2f}"
                    
                    # Columns W and AD should be empty for FC_TRANSFER
                    if idx_total_price_vat_excl < len(row):
                        row[idx_total_price_vat_excl] = ""
                    if idx_total_activity_vat_excl < len(row):
                        row[idx_total_activity_vat_excl] = ""

                    fc_transfer_updated += 1
                    total_value_added += total_price
                else:
                    missing_asins.add(asin)
                    missing_rows_count += 1

            output_rows.append(row)

    # Write output CSV with utf-8-sig, CRLF, and quote all fields
    with open(output_path, mode="w", encoding="utf-8-sig", newline="") as outfile:
        writer = csv.writer(outfile, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        writer.writerows(output_rows)

    return {
        "csv_path": csv_path,
        "excel_path": excel_path,
        "output_path": output_path,
        "catalog_size": len(price_catalog),
        "total_rows": total_rows,
        "fc_transfer_count": fc_transfer_count,
        "fc_transfer_updated": fc_transfer_updated,
        "missing_asins": sorted(missing_asins),
        "missing_rows_count": missing_rows_count,
        "total_value_added": total_value_added,
    }


def print_summary(stats: dict) -> None:
    """Print a clean execution summary to the console."""
    print("\n" + "=" * 60)
    print("  AMAZON VAT REPORT PROCESSING COMPLETE")
    print("=" * 60)
    print(f"  Input CSV:          {stats['csv_path']}")
    print(f"  Price Catalog:      {stats['excel_path']} ({stats['catalog_size']} ASINs loaded)")
    print(f"  Output CSV:         {stats['output_path']}")
    print("-" * 60)
    print(f"  Total Rows:         {stats['total_rows']:,}")
    print(f"  FC_TRANSFER Rows:   {stats['fc_transfer_count']:,}")
    print(f"  Successfully Filled:{stats['fc_transfer_updated']:,}")
    print(f"  Total Cost Filled:  €{stats['total_value_added']:,.2f}")

    if stats["missing_asins"]:
        print("-" * 60)
        print(f"  [WARNING] {len(stats['missing_asins'])} ASIN(s) were not found in the price catalog ({stats['missing_rows_count']} rows):")
        for asin in stats["missing_asins"]:
            print(f"    - {asin}")
        print("  (These rows were left with empty price columns)")
    else:
        print(f"  Missing ASINs:      0 (100% matched)")

    print("=" * 60 + "\n")


def prompt_for_path(prompt_text: str, default_pattern: str | None = None) -> Path:
    """Prompt the user interactively for a file path with drag & drop support."""
    while True:
        try:
            user_input = input(f"{prompt_text}: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled by user.")
            sys.exit(0)

        if not user_input:
            print("  Please provide a file path.")
            continue

        path = clean_path_input(user_input)
        if not path.exists():
            print(f"  Error: File not found at '{path}'. Please try again.")
            continue
        return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fill missing prices for FC_TRANSFER rows in Amazon VAT Transaction Reports."
    )
    parser.add_argument(
        "-c", "--csv",
        dest="csv_path",
        type=str,
        help="Path to the Amazon VAT CSV report (e.g. 01-24.csv)",
    )
    parser.add_argument(
        "-p", "--prices", "--excel",
        dest="excel_path",
        type=str,
        help="Path to the Excel price catalog (e.g. amazon_asin_prix_achat_cogs_maj.xlsx)",
    )
    parser.add_argument(
        "-o", "--output",
        dest="output_path",
        type=str,
        default=None,
        help="Optional path for the output CSV (defaults to <name>_processed.csv)",
    )

    args = parser.parse_args()

    csv_path = clean_path_input(args.csv_path) if args.csv_path else None
    excel_path = clean_path_input(args.excel_path) if args.excel_path else None
    output_path = clean_path_input(args.output_path) if args.output_path else None

    # Interactive mode if arguments are missing
    if not csv_path or not excel_path:
        print("\n" + "=" * 60)
        print("   Amazon VAT Report - FC_Transfer Price Automation")
        print("=" * 60)
        print(" Tip: You can drag and drop files directly into this terminal window.\n")

        if not csv_path:
            csv_path = prompt_for_path("1. Enter or Drag & Drop the Amazon VAT CSV report")
        if not excel_path:
            excel_path = prompt_for_path("2. Enter or Drag & Drop the Excel price catalog (.xlsx)")

    try:
        stats = process_vat_report(
            csv_path=csv_path,
            excel_path=excel_path,
            output_path=output_path,
        )
        print_summary(stats)
    except Exception as e:
        print(f"\n[ERROR] Failed to process report: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
