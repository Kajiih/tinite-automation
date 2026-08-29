"""
Behavioral and End-to-End Tests for Amazon VAT Report Automation
"""

from __future__ import annotations

import csv
import logging
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
import pytest

from vat_report.engine import (
    ColumnHeader,
    RouteKey,
    TransactionType,
    process_batch,
    process_vat_report,
)

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


class TestSingleVatReportProcessing:
    """Tests for single VAT report execution and calculations."""

    def test_single_file_processing_golden_dataset(
        self,
        tmp_path: Path,
        sample_vat_report_path: Path,
        price_catalog: dict[str, float],
    ):
        """Verify row-by-row invariance and full cross-border summary matrix."""
        output_report_path = tmp_path / "processed_vat_report.csv"

        result = process_vat_report(
            report_path=sample_vat_report_path,
            price_catalog=price_catalog,
            output_path=output_report_path,
            export_summary=True,
        )

        assert result.total_rows == 100
        assert result.fc_transfer_count == 40
        assert result.fc_transfer_updated == 40
        assert result.total_value_added == pytest.approx(234.99, abs=0.01)
        assert not result.missing_asins
        assert output_report_path.exists()

        # Row-by-Row Invariance Validation
        with open(sample_vat_report_path, mode="r", encoding="utf-8-sig") as f_in:
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

        for original_row, processed_row in zip(original_rows[1:], processed_rows[1:]):
            if original_row[index_type] != TransactionType.FC_TRANSFER.value:
                # Guarantees SALE, REFUND, and RETURN transactions are 100% untouched
                assert processed_row == original_row
            else:
                unit_cost = processed_row[index_cost]
                line_total = processed_row[index_price_vat_excl]
                assert unit_cost != ""
                assert line_total != ""
                assert processed_row[index_total_price_vat_excl] == ""
                assert processed_row[index_total_activity_vat_excl] == ""

                # Golden samples verification
                asin = processed_row[index_asin]
                qty = processed_row[index_qty]
                if asin == "B089WJC6Z4" and qty == "1":
                    assert unit_cost == "3.10"
                    assert line_total == "3.10"
                elif asin == "B089N1ND4V" and qty == "3":
                    assert unit_cost == "3.30"
                    assert line_total == "9.90"

        # Country Summary Full Matrix Validation
        assert result.summary_path is not None and result.summary_path.exists()
        with open(result.summary_path, mode="r", encoding="utf-8-sig") as file_handle:
            summary_rows = list(csv.reader(file_handle))

        assert summary_rows == EXPECTED_SINGLE_COUNTRY_SUMMARY


class TestBatchVatReportProcessing:
    """Tests for multi-file batch folder processing."""

    def test_batch_folder_processing_golden_dataset(
        self,
        tmp_path: Path,
        sample_vat_report_path: Path,
        price_catalog_path: Path,
    ):
        """Verify batch folder aggregation and consolidated matrix generation."""
        batch_input_dir = tmp_path / "batch_input"
        batch_input_dir.mkdir()

        (batch_input_dir / "report_january.csv").write_bytes(sample_vat_report_path.read_bytes())
        (batch_input_dir / "report_february.csv").write_bytes(sample_vat_report_path.read_bytes())

        batch_result = process_batch(
            input_directory=batch_input_dir,
            price_catalog_path=price_catalog_path,
        )

        consolidated_summary_path = batch_input_dir / "processed" / "batch_country_summary.csv"

        assert batch_result.files_count == 2
        assert batch_result.grand_total_rows == 200
        assert batch_result.grand_fc_updated == 80
        assert batch_result.grand_value_added == pytest.approx(469.98, abs=0.01)
        assert not batch_result.all_missing_asins
        assert consolidated_summary_path.exists()

        with open(consolidated_summary_path, mode="r", encoding="utf-8-sig") as f:
            summary_rows = list(f)
            reader = csv.reader(summary_rows)
            assert list(reader) == EXPECTED_BATCH_COUNTRY_SUMMARY


class TestVatReportEdgeCases:
    """Tests for edge cases, missing ASINs, decimal quantities, and fallbacks."""

    @pytest.mark.parametrize(
        ("raw_qty", "unit_price", "expected_qty", "expected_total"),
        [
            ("1", 3.10, 1.0, 3.10),
            ("3", 3.10, 3.0, 9.30),
            ("2,5", 4.00, 2.5, 10.00),
            ("1.75", 10.00, 1.75, 17.50),
            ("", 5.00, 1.0, 5.00),         # Empty defaults to 1
            ("invalid", 5.00, 1.0, 5.00),  # Unparseable defaults to 1
        ],
    )
    def test_quantity_parsing_and_total_calculation(
        self,
        tmp_path: Path,
        fake_vat_csv_factory,
        raw_qty: str,
        unit_price: float,
        expected_qty: float,
        expected_total: float,
    ):
        """Verify robust quantity parsing and total pricing across various formats."""
        custom_catalog = {"TEST_ASIN": unit_price}
        report_file = fake_vat_csv_factory([
            {"transaction_type": "FC_TRANSFER", "asin": "TEST_ASIN", "qty": raw_qty, "departure": "DE", "arrival": "FR"},
        ])
        output_file = tmp_path / "out.csv"

        result = process_vat_report(report_file, custom_catalog, output_file, export_summary=False)
        route = result.route_statistics[RouteKey("DE", "FR")]

        assert result.fc_transfer_updated == 1
        assert result.total_value_added == pytest.approx(expected_total, abs=0.01)
        assert route.total_quantity == pytest.approx(expected_qty, abs=0.01)
        assert route.total_amount_eur == pytest.approx(expected_total, abs=0.01)

    def test_missing_asin_handling(
        self,
        tmp_path: Path,
        fake_vat_csv_factory,
    ):
        """Verify that unmatched ASINs are cleanly tracked and left unfilled."""
        custom_catalog = {"KNOWN_ASIN": 10.0}
        report_file = fake_vat_csv_factory([
            {"transaction_type": "FC_TRANSFER", "asin": "KNOWN_ASIN", "qty": "2", "departure": "DE", "arrival": "FR"},
            {"transaction_type": "FC_TRANSFER", "asin": "UNKNOWN_ASIN_1", "qty": "1", "departure": "DE", "arrival": "PL"},
            {"transaction_type": "FC_TRANSFER", "asin": "UNKNOWN_ASIN_2", "qty": "1", "departure": "FR", "arrival": "IT"},
        ])
        output_file = tmp_path / "out.csv"

        result = process_vat_report(report_file, custom_catalog, output_file, export_summary=False)

        assert result.fc_transfer_count == 3
        assert result.fc_transfer_updated == 1
        assert result.missing_asins == ["UNKNOWN_ASIN_1", "UNKNOWN_ASIN_2"]
        assert result.missing_rows_count == 2
        assert result.total_value_added == 20.00


class TestVatReportCli:
    """Tests for CLI invocation."""

    def test_cli_invocation_e2e(
        self,
        tmp_path: Path,
        sample_vat_report_path: Path,
        price_catalog_path: Path,
    ):
        """Verify CLI script invocation produces identical output files."""
        output_destination = tmp_path / "cli_output.csv"
        script_path = Path(__file__).resolve().parent.parent / "src" / "vat_report" / "engine.py"

        command = [
            sys.executable,
            str(script_path),
            "--vat-report",
            str(sample_vat_report_path),
            "--price-catalog",
            str(price_catalog_path),
            "--output",
            str(output_destination),
        ]

        execution = subprocess.run(command, capture_output=True, text=True, check=True)

        assert execution.returncode == 0
        assert "AMAZON VAT REPORT PROCESSING COMPLETE" in execution.stdout
        assert output_destination.exists()

        with open(output_destination, mode="r", encoding="utf-8-sig") as f:
            assert len(list(csv.reader(f))) == 101
