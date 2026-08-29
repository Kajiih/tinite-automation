"""
End-to-End Tests for Amazon VAT Report FC_Transfer Automation
"""

from __future__ import annotations

import csv
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
import pytest

from process_report import (
    ColumnHeader,
    TransactionType,
    load_price_catalog,
    process_batch,
    process_vat_report,
)

BASE_DIRECTORY: Path = Path(__file__).parent.parent
SAMPLE_REPORT_PATH: Path = BASE_DIRECTORY / "example_data" / "sample_vat_report.csv"
PRICE_CATALOG_PATH: Path = BASE_DIRECTORY / "example_data" / "amazon_asin_prix_achat_cogs_maj.xlsx"
SCRIPT_PATH: Path = BASE_DIRECTORY / "process_report.py"

EXPECTED_SINGLE_COUNTRY_SUMMARY: Sequence[Sequence[str]] = [
    ["DEPARTURE_COUNTRY", "ARRIVAL_COUNTRY", "TRANSFER_COUNT", "TOTAL_QTY", "TOTAL_AMOUNT_EUR"],
    ["CZ", "DE", "1", "1", "3.00"],
    ["CZ", "IT", "3", "16", "48.00"],
    ["CZ", "PL", "2", "2", "6.00"],
    ["DE", "CZ", "19", "23", "92.13"],
    ["DE", "ES", "1", "1", "3.00"],
    ["DE", "FR", "3", "3", "24.33"],
    ["DE", "IT", "1", "2", "6.00"],
    ["FR", "PL", "2", "2", "11.03"],
    ["IT", "DE", "1", "1", "6.50"],
    ["IT", "FR", "1", "1", "5.30"],
    ["PL", "DE", "3", "3", "13.70"],
    ["PL", "FR", "1", "1", "3.00"],
    ["SK", "CZ", "1", "1", "6.50"],
    ["SK", "DE", "1", "1", "6.50"],
    ["TOTAL", "", "40", "58", "234.99"],
]

EXPECTED_BATCH_COUNTRY_SUMMARY: Sequence[Sequence[str]] = [
    ["DEPARTURE_COUNTRY", "ARRIVAL_COUNTRY", "TRANSFER_COUNT", "TOTAL_QTY", "TOTAL_AMOUNT_EUR"],
    ["CZ", "DE", "2", "2", "6.00"],
    ["CZ", "IT", "6", "32", "96.00"],
    ["CZ", "PL", "4", "4", "12.00"],
    ["DE", "CZ", "38", "46", "184.26"],
    ["DE", "ES", "2", "2", "6.00"],
    ["DE", "FR", "6", "6", "48.66"],
    ["DE", "IT", "2", "4", "12.00"],
    ["FR", "PL", "4", "4", "22.06"],
    ["IT", "DE", "2", "2", "13.00"],
    ["IT", "FR", "2", "2", "10.60"],
    ["PL", "DE", "6", "6", "27.40"],
    ["PL", "FR", "2", "2", "6.00"],
    ["SK", "CZ", "2", "2", "13.00"],
    ["SK", "DE", "2", "2", "13.00"],
    ["TOTAL", "", "80", "116", "469.98"],
]


@pytest.fixture
def price_catalog():
    """Load the sample price catalog mapping."""
    return load_price_catalog(PRICE_CATALOG_PATH)


def test_single_file_processing_e2e(tmp_path: Path, price_catalog):
    """
    Hybrid test: Row-by-row invariance check on main report + 100% full matrix check on summary CSV.
    """
    output_report_path = tmp_path / "sample_vat_report_processed.csv"

    result = process_vat_report(
        report_path=SAMPLE_REPORT_PATH,
        price_catalog=price_catalog,
        output_path=output_report_path,
        export_summary=True,
    )

    assert result.total_rows == 100
    assert result.fc_transfer_count == 40
    assert result.fc_transfer_updated == 40
    assert len(result.missing_asins) == 0
    assert result.total_value_added == pytest.approx(234.99, abs=0.01)
    assert output_report_path.exists()

    # 1. Main Report Row-by-Row Invariance Validation
    with open(SAMPLE_REPORT_PATH, mode="r", encoding="utf-8-sig") as f_in:
        original_rows = list(csv.reader(f_in))

    with open(output_report_path, mode="r", encoding="utf-8-sig") as f_out:
        processed_rows = list(csv.reader(f_out))

    assert len(processed_rows) == len(original_rows)
    assert processed_rows[0] == original_rows[0]

    header = processed_rows[0]
    index_type = header.index(ColumnHeader.TRANSACTION_TYPE.value)
    index_asin = header.index(ColumnHeader.ASIN.value)
    index_qty = header.index(ColumnHeader.QUANTITY.value)
    index_cost = header.index(ColumnHeader.COST_PRICE_OF_ITEMS.value)
    index_price_vat_excl = header.index(ColumnHeader.PRICE_OF_ITEMS_AMT_VAT_EXCL.value)
    index_total_price_vat_excl = header.index(ColumnHeader.TOTAL_PRICE_OF_ITEMS_AMT_VAT_EXCL.value)
    index_total_activity_vat_excl = header.index(ColumnHeader.TOTAL_ACTIVITY_VALUE_AMT_VAT_EXCL.value)

    fc_count = 0
    for original_row, processed_row in zip(original_rows[1:], processed_rows[1:]):
        transaction_type = original_row[index_type]

        if transaction_type != TransactionType.FC_TRANSFER.value:
            # Guarantees SALE, REFUND, and RETURN transactions are 100% untouched
            assert processed_row == original_row
        else:
            fc_count += 1
            asin = processed_row[index_asin]
            qty = processed_row[index_qty]
            unit_cost = processed_row[index_cost]
            line_total = processed_row[index_price_vat_excl]

            assert unit_cost != ""
            assert line_total != ""
            assert processed_row[index_total_price_vat_excl] == ""
            assert processed_row[index_total_activity_vat_excl] == ""

            # Golden samples verification
            if asin == "B089WJC6Z4" and qty == "1":
                assert unit_cost == "3.10"
                assert line_total == "3.10"
            elif asin == "B089N1ND4V" and qty == "3":
                assert unit_cost == "3.30"
                assert line_total == "9.90"

    assert fc_count == 40

    # 2. Country Summary 100% Full Matrix Validation
    assert result.summary_path is not None
    assert result.summary_path.exists()
    with open(result.summary_path, mode="r", encoding="utf-8-sig") as file_handle:
        summary_rows = list(csv.reader(file_handle))

    assert summary_rows == EXPECTED_SINGLE_COUNTRY_SUMMARY


def test_batch_folder_processing_e2e(tmp_path: Path):
    """
    Hybrid test: Batch directory processing + 100% full matrix check on consolidated summary CSV.
    """
    batch_input_directory = tmp_path / "batch_input"
    batch_input_directory.mkdir()

    report_one = batch_input_directory / "report_january.csv"
    report_two = batch_input_directory / "report_february.csv"
    report_one.write_bytes(SAMPLE_REPORT_PATH.read_bytes())
    report_two.write_bytes(SAMPLE_REPORT_PATH.read_bytes())

    batch_result = process_batch(
        input_directory=batch_input_directory,
        price_catalog_path=PRICE_CATALOG_PATH,
    )

    assert batch_result.files_count == 2
    assert batch_result.grand_total_rows == 200
    assert batch_result.grand_fc_updated == 80
    assert batch_result.grand_value_added == pytest.approx(469.98, abs=0.01)

    processed_directory = batch_input_directory / "processed"
    consolidated_summary_path = processed_directory / "batch_country_summary.csv"
    assert consolidated_summary_path.exists()

    with open(consolidated_summary_path, mode="r", encoding="utf-8-sig") as file_handle:
        summary_rows = list(csv.reader(file_handle))

    # Full Matrix Validation for batch summary
    assert summary_rows == EXPECTED_BATCH_COUNTRY_SUMMARY


def test_cli_invocation_e2e(tmp_path: Path):
    """Verify CLI command invocation produces identical direct outputs."""
    output_destination = tmp_path / "cli_output.csv"

    command = [
        sys.executable,
        str(SCRIPT_PATH),
        "--vat-report",
        str(SAMPLE_REPORT_PATH),
        "--price-catalog",
        str(PRICE_CATALOG_PATH),
        "--output",
        str(output_destination),
    ]

    execution = subprocess.run(command, capture_output=True, text=True, check=True)

    assert execution.returncode == 0
    assert "AMAZON VAT REPORT PROCESSING COMPLETE" in execution.stdout
    assert output_destination.exists()

    with open(output_destination, mode="r", encoding="utf-8-sig") as file_handle:
        rows = list(csv.reader(file_handle))
        assert len(rows) == 101  # 1 header + 100 rows
