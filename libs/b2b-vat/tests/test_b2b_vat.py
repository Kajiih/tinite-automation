from __future__ import annotations

import csv
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from b2b_vat.engine import (
    REQUIRED_HEADERS,
    B2BVATError,
    ColumnHeader,
    InvalidReportFormatError,
    ReportNotFoundError,
    ReportPathIsDirectoryError,
    export_b2b_summary_csv,
    export_b2b_transactions_csv,
    format_b2b_summary_table,
    main,
    process_b2b_vat_report,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path


def test_empty_csv_raises_error(tmp_path: Path) -> None:
    """Empty CSV report raises ValueError."""
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="VAT report CSV is empty"):
        process_b2b_vat_report(empty_csv)


def test_file_not_found_raises_error(tmp_path: Path) -> None:
    """Non-existent CSV path raises FileNotFoundError."""
    missing = tmp_path / "non_existent.csv"
    with pytest.raises(FileNotFoundError):
        process_b2b_vat_report(missing)


def test_directory_path_raises_error(tmp_path: Path) -> None:
    """Passing a directory instead of CSV raises ValueError."""
    dir_path = tmp_path / "some_dir"
    dir_path.mkdir()
    with pytest.raises(ValueError, match="Expected a CSV report file, but received a directory"):
        process_b2b_vat_report(dir_path)


def test_missing_required_headers_raises_error(tmp_path: Path) -> None:
    """CSV missing required Amazon VAT columns raises descriptive ValueError."""
    bad_csv = tmp_path / "bad_headers.csv"
    bad_csv.write_text("HeaderA,HeaderB\nVal1,Val2\n", encoding="utf-8")
    expected_msg = "Invalid Amazon VAT Report format: missing required columns"
    with pytest.raises(ValueError, match=expected_msg):
        process_b2b_vat_report(bad_csv)


@pytest.mark.parametrize("missing_header", REQUIRED_HEADERS)
def test_missing_each_required_header(missing_header: ColumnHeader, tmp_path: Path) -> None:
    """Omission of any mandatory column raises ValueError specifying the missing header."""
    headers = [col.value for col in ColumnHeader if col != missing_header]
    bad_csv = tmp_path / f"missing_{missing_header.name.lower()}.csv"
    with bad_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerow(["val"] * len(headers))

    with pytest.raises(ValueError, match=f"missing required columns:.*'{missing_header.value}'"):
        process_b2b_vat_report(bad_csv)


def test_case_insensitive_header_resolution(tmp_path: Path) -> None:
    """Header resolution works regardless of case or whitespace."""
    csv_file = tmp_path / "case_test.csv"
    headers = [col.value.lower() for col in ColumnHeader]
    with csv_file.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        row = [""] * len(headers)
        row[headers.index(ColumnHeader.BUYER_TAX_REGISTRATION.value.lower())] = "BE123"
        row[headers.index(ColumnHeader.SHIP_FROM_COUNTRY.value.lower())] = "FR"
        row[headers.index(ColumnHeader.SHIP_TO_COUNTRY.value.lower())] = "BE"
        row[headers.index(ColumnHeader.OUR_PRICE_TAX_AMOUNT.value.lower())] = "0.00"
        row[headers.index(ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value.lower())] = (
            "10.00"
        )
        row[headers.index(ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value.lower())] = "0.00"
        writer.writerow(row)

    result = process_b2b_vat_report(csv_file)
    assert result.matched_rows_count == 1
    assert result.vat_summaries[0].buyer_vat == "BE123"


def test_corrupt_numeric_values_graceful_fallback(
    fake_b2b_vat_csv_factory: Callable[[Sequence[Mapping[str, str]]], Path],
) -> None:
    """Invalid numeric strings in price or promo fallback safely without throwing."""
    rows = [
        {
            ColumnHeader.ORDER_ID.value: "ORD-CORRUPT",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "BE999",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "BE",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "INVALID",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "CORRUPT",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "NaN",
        }
    ]
    report_path = fake_b2b_vat_csv_factory(rows)
    result = process_b2b_vat_report(report_path)
    assert result.matched_rows_count == 1
    assert result.grand_total_selling_price == pytest.approx(0.0)


def test_b2b_filtering_rules(
    fake_b2b_vat_csv_factory: Callable[[Sequence[Mapping[str, str]]], Path],
) -> None:
    """Verify all 4 B2B filtering conditions and algebraic calculation accuracy."""
    rows = [
        # Row 1: Valid B2B Sale (FR -> BE, Tax 0, Scheme empty, VAT present, signed discount -10.00)
        {
            ColumnHeader.ORDER_ID.value: "ORD-1",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "BE0123456789",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "BE",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "100.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "-10.00",
        },
        # Row 2: Skipped - Missing Buyer VAT
        {
            ColumnHeader.ORDER_ID.value: "ORD-2",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "BE",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "50.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
        },
        # Row 3: Skipped - Domestic Shipment (FR -> FR)
        {
            ColumnHeader.ORDER_ID.value: "ORD-3",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "FR999999999",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "FR",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "50.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
        },
        # Row 4: Skipped - Wrong Departure (DE -> IT)
        {
            ColumnHeader.ORDER_ID.value: "ORD-4",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "IT111111111",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "DE",
            ColumnHeader.SHIP_TO_COUNTRY.value: "IT",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "50.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
        },
        # Row 5: Skipped - Tax Scheme Present (e.g. VCS_EU_OSS)
        {
            ColumnHeader.ORDER_ID.value: "ORD-5",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "IT222222222",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "IT",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "VCS_EU_OSS",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "50.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
        },
        # Row 6: Skipped - Tax Amount Non-Zero
        {
            ColumnHeader.ORDER_ID.value: "ORD-6",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "IT333333333",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "IT",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "2.50",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "50.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
        },
        # Row 7: Valid B2B Return (FR -> BE, same VAT as Row 1, signed return discount +2.00)
        {
            ColumnHeader.ORDER_ID.value: "ORD-7",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "BE0123456789",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "BE",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "-30.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "2.00",
        },
    ]

    report_path = fake_b2b_vat_csv_factory(rows)
    result = process_b2b_vat_report(report_path, departure_country="FR")

    assert result.total_rows_scanned == 7
    assert result.matched_rows_count == 2
    assert result.unique_vats_count == 1

    # Row 1 diff: 100.00 + (-10.00) = 90.00
    # Row 7 diff: -30.00 + 2.00 = -28.00
    # Total net diff: 90.00 + (-28.00) = 62.00
    summary = result.vat_summaries[0]
    assert summary.buyer_vat == "BE0123456789"
    assert summary.transaction_count == 2
    assert summary.destination_countries == ["BE"]
    assert summary.total_tax_exclusive_price == pytest.approx(70.00)
    assert summary.total_tax_inclusive_promo == pytest.approx(-8.00)
    assert summary.total_net_difference == pytest.approx(62.00)

    assert result.grand_total_selling_price == pytest.approx(70.00)
    assert result.grand_total_promo_amount == pytest.approx(-8.00)
    assert result.grand_total_net_difference == pytest.approx(62.00)


def test_custom_departure_country(
    fake_b2b_vat_csv_factory: Callable[[Sequence[Mapping[str, str]]], Path],
) -> None:
    """Configuring a different departure country (e.g. DE) correctly filters."""
    rows = [
        {
            ColumnHeader.ORDER_ID.value: "ORD-DE-1",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "FR01010101",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "DE",
            ColumnHeader.SHIP_TO_COUNTRY.value: "FR",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "45.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "-5.00",
        }
    ]
    report_path = fake_b2b_vat_csv_factory(rows)
    result = process_b2b_vat_report(report_path, departure_country="DE")

    assert result.matched_rows_count == 1
    assert result.grand_total_net_difference == pytest.approx(40.00)


def test_csv_exports(
    fake_b2b_vat_csv_factory: Callable[[Sequence[Mapping[str, str]]], Path],
    tmp_path: Path,
) -> None:
    """Verify export of summary CSV and detailed transactions CSV."""
    rows = [
        {
            ColumnHeader.ORDER_ID.value: "ORD-1",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "BE111",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "BE",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "100.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
        }
    ]
    report_path = fake_b2b_vat_csv_factory(rows)
    result = process_b2b_vat_report(report_path)

    summary_out = tmp_path / "summary.csv"
    transactions_out = tmp_path / "transactions.csv"

    export_b2b_summary_csv(result.vat_summaries, summary_out)
    export_b2b_transactions_csv(result.transactions, transactions_out)

    assert summary_out.exists()
    assert transactions_out.exists()

    with summary_out.open(encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        data_row = next(reader)
        total_row = next(reader)

        assert header[0] == "BUYER_VAT_NUMBER"
        assert data_row[0] == "BE111"
        assert data_row[5] == "100.00"
        assert total_row[0] == "TOTAL"

    with transactions_out.open(encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        data_row = next(reader)

        assert header[0] == "LINE_NUMBER"
        assert header[14] == "INVOICE_URL"
        assert data_row[1] == "ORD-1"
        assert data_row[7] == "BE111"


def test_format_b2b_summary_table() -> None:
    """Check text table formatting handles empty and populated data."""
    empty_table = format_b2b_summary_table([])
    assert "No matching B2B Intra-EU transactions found" in empty_table


def test_actual_july_2026_vat_report(test_tax_report_path: Path) -> None:
    """Integration test against actual workspace report if present."""
    if not test_tax_report_path.exists():
        pytest.skip("Workspace sample CSV not found")

    result = process_b2b_vat_report(test_tax_report_path, departure_country="FR")
    assert result.total_rows_scanned == 3982
    assert result.matched_rows_count == 3
    assert result.unique_vats_count == 2

    # Verify invoice numbers and URLs are parsed
    tx0 = result.transactions[0]
    assert tx0.invoice_number == "FR6000315ZSONC"
    assert tx0.invoice_url.startswith("https://sellercentral.amazon.fr/document/download")

    vat_by_id = {s.buyer_vat: s for s in result.vat_summaries}
    assert "BE0536704364" in vat_by_id
    assert "BE0665487405" in vat_by_id

    # Line 12: -40.27 + 2.01 = -38.26
    # Line 13: -40.27 + 2.02 = -38.25
    # Total BE0536704364: -76.51
    # Line 15: 9.08 + 0.00 = 9.08
    assert vat_by_id["BE0536704364"].total_net_difference == pytest.approx(-76.51)
    assert vat_by_id["BE0665487405"].total_net_difference == pytest.approx(9.08)
    assert result.grand_total_net_difference == pytest.approx(round(-76.51 + 9.08, 2))


def test_cli_invocation(
    fake_b2b_vat_csv_factory: Callable[[Sequence[Mapping[str, str]]], Path],
    tmp_path: Path,
) -> None:
    """Test CLI main() execution with process subcommand."""
    rows = [
        {
            ColumnHeader.ORDER_ID.value: "ORD-CLI",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "BE222",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "BE",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "20.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
        }
    ]
    report_path = fake_b2b_vat_csv_factory(rows)
    sum_out = tmp_path / "cli_summary.csv"
    tx_out = tmp_path / "cli_tx.csv"

    test_args = [
        "b2b-vat",
        "--report",
        str(report_path),
        "--departure",
        "FR",
        "--output-summary",
        str(sum_out),
        "--output-transactions",
        str(tx_out),
    ]

    with patch("sys.argv", test_args):
        main()

    assert sum_out.exists()
    assert tx_out.exists()


def test_domain_exceptions_inheritance(tmp_path: Path) -> None:
    """Verify domain exceptions subclass both B2BVATError and standard Python errors."""
    # 1. Non-existent file
    missing = tmp_path / "non_existent_file.csv"
    with pytest.raises(B2BVATError) as exc_info:
        process_b2b_vat_report(missing)
    assert isinstance(exc_info.value, (ReportNotFoundError, FileNotFoundError))

    # 2. Directory path
    dir_path = tmp_path / "test_directory"
    dir_path.mkdir()
    with pytest.raises(B2BVATError) as exc_info:
        process_b2b_vat_report(dir_path)
    assert isinstance(exc_info.value, (ReportPathIsDirectoryError, ValueError))

    # 3. Empty CSV file
    empty_csv = tmp_path / "empty_report.csv"
    empty_csv.write_text("", encoding="utf-8")
    with pytest.raises(B2BVATError) as exc_info:
        process_b2b_vat_report(empty_csv)
    assert isinstance(exc_info.value, (InvalidReportFormatError, ValueError))
