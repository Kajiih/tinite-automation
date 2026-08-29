# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "openpyxl",
# ]
# ///
"""
Amazon VAT Transaction Report - FC_Transfer Price Automation

Production-grade automation to populate unit cost (Column T: COST_PRICE_OF_ITEMS)
and line total (Column U: PRICE_OF_ITEMS_AMT_VAT_EXCL) for FC_TRANSFER rows in
Amazon VAT reports based on an Excel price catalog.

Supports both single CSV file processing and batch folder processing.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


def clean_path_input(raw_input: str) -> Path:
    """Sanitize path strings from CLI arguments or terminal drag-and-drop."""
    cleaned = raw_input.strip().strip("'\"").strip()
    return Path(cleaned).expanduser().resolve()


def load_price_catalog(excel_path: Path | str) -> Dict[str, float]:
    """
    Load ASIN -> unit price mapping from the Excel catalog (.xlsx).
    
    Dynamically identifies ASIN and Price columns by header name,
    falling back to columns 0 and 1 if standard headers are not found.
    """
    import openpyxl

    path = Path(excel_path)
    if not path.exists():
        raise FileNotFoundError(f"Excel price catalog not found: {path}")

    workbook = openpyxl.load_workbook(filename=path, data_only=True, read_only=True)
    sheet = workbook.active
    if sheet is None:
        raise ValueError(f"No active worksheet found in: {path}")

    rows_iter = sheet.iter_rows(values_only=True)
    header_row = next(rows_iter, None)
    if not header_row:
        raise ValueError(f"Excel file is empty: {path}")

    asin_col_idx = 0
    price_col_idx = 1

    for idx, cell in enumerate(header_row):
        if cell is None:
            continue
        cell_str = str(cell).strip().lower()
        if "asin" in cell_str:
            asin_col_idx = idx
        elif any(kw in cell_str for kw in ["price cost", "prix d'achat", "cogs", "cost", "price", "prix"]):
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
    if not price_map:
        raise ValueError(f"No valid ASIN price entries found in: {path}")

    return price_map


def process_vat_report(
    csv_path: Path | str,
    price_catalog: Dict[str, float],
    output_path: Path | str,
) -> Dict[str, Any]:
    """
    Process a single Amazon VAT CSV report using a pre-loaded price catalog.
    
    Populates Column T (unit price) and Column U (price * qty) for FC_TRANSFER rows.
    Leaves Columns W and AD empty for FC_TRANSFER rows.
    """
    csv_path = Path(csv_path)
    output_path = Path(output_path)

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV report not found: {csv_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(csv_path, mode="r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.reader(infile)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError(f"CSV file is empty: {csv_path}")

        col_indices = {col.strip(): i for i, col in enumerate(header)}

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

            if len(row) < len(header):
                row.extend([""] * (len(header) - len(row)))

            trans_type = row[idx_type].strip().upper() if len(row) > idx_type else ""

            if trans_type == "FC_TRANSFER":
                fc_transfer_count += 1
                asin = row[idx_asin].strip() if len(row) > idx_asin else ""
                qty_str = row[idx_qty].strip() if len(row) > idx_qty else "1"
                
                try:
                    qty = float(qty_str) if qty_str else 1.0
                except ValueError:
                    qty = 1.0

                if asin in price_catalog:
                    unit_price = price_catalog[asin]
                    total_price = unit_price * qty

                    row[idx_cost_price] = f"{unit_price:.2f}"
                    row[idx_item_price_vat_excl] = f"{total_price:.2f}"

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

    with open(output_path, mode="w", encoding="utf-8-sig", newline="") as outfile:
        writer = csv.writer(outfile, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        writer.writerows(output_rows)

    return {
        "csv_path": csv_path,
        "output_path": output_path,
        "total_rows": total_rows,
        "fc_transfer_count": fc_transfer_count,
        "fc_transfer_updated": fc_transfer_updated,
        "missing_asins": sorted(missing_asins),
        "missing_rows_count": missing_rows_count,
        "total_value_added": total_value_added,
    }


def process_batch(
    input_dir: Path | str,
    excel_path: Path | str,
    output_dir: Path | str | None = None,
) -> Dict[str, Any]:
    """
    Process all CSV reports in a folder in batch mode.
    
    Saves outputs into input_dir/processed/<filename> (or output_dir if provided).
    Loads the Excel price catalog once to maximize efficiency.
    """
    input_dir = Path(input_dir)
    excel_path = Path(excel_path)

    if not input_dir.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_dir}")

    target_output_dir = Path(output_dir) if output_dir else input_dir / "processed"
    target_output_dir.mkdir(parents=True, exist_ok=True)

    # Collect all CSVs in input_dir, excluding the output directory itself
    csv_files = [
        p for p in input_dir.glob("*.csv")
        if p.is_file() and p.parent != target_output_dir and not p.name.startswith(".")
    ]

    if not csv_files:
        raise FileNotFoundError(f"No .csv files found in directory: {input_dir}")

    csv_files.sort()
    price_catalog = load_price_catalog(excel_path)

    file_results: List[Dict[str, Any]] = []
    grand_total_rows = 0
    grand_fc_transfers = 0
    grand_fc_updated = 0
    grand_value_added = 0.0
    all_missing_asins: Set[str] = set()

    for csv_file in csv_files:
        out_file = target_output_dir / csv_file.name
        stats = process_vat_report(csv_file, price_catalog, out_file)
        file_results.append(stats)

        grand_total_rows += stats["total_rows"]
        grand_fc_transfers += stats["fc_transfer_count"]
        grand_fc_updated += stats["fc_transfer_updated"]
        grand_value_added += stats["total_value_added"]
        all_missing_asins.update(stats["missing_asins"])

    return {
        "mode": "batch",
        "input_dir": input_dir,
        "output_dir": target_output_dir,
        "excel_path": excel_path,
        "catalog_size": len(price_catalog),
        "files_count": len(csv_files),
        "file_results": file_results,
        "grand_total_rows": grand_total_rows,
        "grand_fc_transfers": grand_fc_transfers,
        "grand_fc_updated": grand_fc_updated,
        "grand_value_added": grand_value_added,
        "all_missing_asins": sorted(all_missing_asins),
    }


def print_single_summary(stats: Dict[str, Any], catalog_size: int, excel_path: Path) -> None:
    """Display single-file execution summary."""
    print("\n" + "=" * 65)
    print("  AMAZON VAT REPORT PROCESSING COMPLETE")
    print("=" * 65)
    print(f"  Input CSV:          {stats['csv_path']}")
    print(f"  Price Catalog:      {excel_path} ({catalog_size} ASINs loaded)")
    print(f"  Output CSV:         {stats['output_path']}")
    print("-" * 65)
    print(f"  Total Rows:         {stats['total_rows']:,}")
    print(f"  FC_TRANSFER Rows:   {stats['fc_transfer_count']:,}")
    print(f"  Successfully Filled:{stats['fc_transfer_updated']:,}")
    print(f"  Total Cost Filled:  €{stats['total_value_added']:,.2f}")

    if stats["missing_asins"]:
        print("-" * 65)
        print(f"  [WARNING] {len(stats['missing_asins'])} ASIN(s) not found in price catalog ({stats['missing_rows_count']} rows):")
        for asin in stats["missing_asins"]:
            print(f"    - {asin}")
        print("  (These rows were left with empty price columns)")
    else:
        print(f"  Missing ASINs:      0 (100% matched)")

    print("=" * 65 + "\n")


def print_batch_summary(stats: Dict[str, Any]) -> None:
    """Display batch execution summary with per-file details."""
    print("\n" + "=" * 70)
    print("  BATCH PROCESSING COMPLETE")
    print("=" * 70)
    print(f"  Input Directory:    {stats['input_dir']}")
    print(f"  Output Directory:   {stats['output_dir']}")
    print(f"  Price Catalog:      {stats['excel_path']} ({stats['catalog_size']} ASINs loaded)")
    print(f"  Files Processed:    {stats['files_count']}")
    print("-" * 70)
    print(f"  {'Filename':<30} | {'Rows':<7} | {'FC Rows':<8} | {'Filled Value':<12}")
    print("-" * 70)

    for item in stats["file_results"]:
        fname = item["csv_path"].name
        if len(fname) > 28:
            fname = fname[:25] + "..."
        print(
            f"  {fname:<30} | {item['total_rows']:<7,d} | {item['fc_transfer_updated']:<8,d} | €{item['total_value_added']:<11,.2f}"
        )

    print("-" * 70)
    print(f"  GRAND TOTALS:")
    print(f"    Total Rows:       {stats['grand_total_rows']:,}")
    print(f"    FC_TRANSFER Rows: {stats['grand_fc_transfers']:,}")
    print(f"    Filled Rows:      {stats['grand_fc_updated']:,}")
    print(f"    Total Cost Added: €{stats['grand_value_added']:,.2f}")

    if stats["all_missing_asins"]:
        print("-" * 70)
        print(f"  [WARNING] {len(stats['all_missing_asins'])} ASIN(s) not found in price catalog:")
        for asin in stats["all_missing_asins"]:
            print(f"    - {asin}")
        print("  (Unmatched rows were left with empty price columns)")
    else:
        print(f"    Missing ASINs:    0 (100% matched)")

    print("=" * 70 + "\n")


def prompt_for_path(prompt_text: str) -> Path:
    """Prompt user interactively for a file or directory path."""
    while True:
        try:
            user_input = input(f"{prompt_text}: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled by user.")
            sys.exit(0)

        if not user_input:
            print("  Please provide a valid path.")
            continue

        path = clean_path_input(user_input)
        if not path.exists():
            print(f"  Error: Path not found at '{path}'. Please try again.")
            continue
        return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fill missing prices for FC_TRANSFER rows in Amazon VAT Transaction Reports (Single file or Batch folder)."
    )
    parser.add_argument(
        "-c", "--csv",
        dest="input_path",
        type=str,
        help="Path to a single Amazon VAT CSV report or a folder containing multiple CSVs",
    )
    parser.add_argument(
        "-p", "--prices", "--excel",
        dest="excel_path",
        type=str,
        help="Path to the Excel price catalog (.xlsx)",
    )
    parser.add_argument(
        "-o", "--output",
        dest="output_path",
        type=str,
        default=None,
        help="Optional custom output path (file for single mode, directory for batch mode)",
    )

    args = parser.parse_args()

    input_path = clean_path_input(args.input_path) if args.input_path else None
    excel_path = clean_path_input(args.excel_path) if args.excel_path else None
    output_path = clean_path_input(args.output_path) if args.output_path else None

    # Interactive prompts if paths are missing
    if not input_path or not excel_path:
        print("\n" + "=" * 65)
        print("   Amazon VAT Report - FC_Transfer Price Automation")
        print("=" * 65)
        print(" Tip: You can drag and drop a file or folder into this window.\n")

        if not input_path:
            input_path = prompt_for_path("1. Enter or Drag & Drop the CSV file or folder containing CSVs")
        if not excel_path:
            excel_path = prompt_for_path("2. Enter or Drag & Drop the Excel price catalog (.xlsx)")

    try:
        if input_path.is_dir():
            # Batch mode
            batch_stats = process_batch(
                input_dir=input_path,
                excel_path=excel_path,
                output_dir=output_path,
            )
            print_batch_summary(batch_stats)
        else:
            # Single file mode
            price_catalog = load_price_catalog(excel_path)
            default_out = input_path.parent / f"{input_path.stem}_processed{input_path.suffix}"
            target_out = output_path if output_path else default_out
            stats = process_vat_report(input_path, price_catalog, target_out)
            print_single_summary(stats, len(price_catalog), excel_path)
    except Exception as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
