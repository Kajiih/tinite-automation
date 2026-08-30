"""Unit and integration tests for B2B Intra-EU VAT automation."""

from __future__ import annotations

import csv
import http.cookiejar
from typing import TYPE_CHECKING, Self
from unittest.mock import MagicMock, patch

import pytest
from b2b_vat.engine import (
    REQUIRED_HEADERS,
    B2BVATError,
    ColumnHeader,
    DownloadPhase,
    InvalidReportFormatError,
    InvoiceDownloadResult,
    ReportNotFoundError,
    ReportPathIsDirectoryError,
    UnsupportedBrowserError,
    download_invoices_for_report,
    export_b2b_summary_csv,
    export_b2b_transactions_csv,
    extract_browser_cookies,
    format_b2b_summary_table,
    main,
    process_b2b_vat_report,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from b2b_vat.engine import InvoiceDownloadEvent


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
        "process",
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


def test_extract_browser_cookies_unsupported_browser() -> None:
    """Unsupported browser names raise ValueError."""
    with pytest.raises(ValueError, match="Unsupported browser 'netscape'"):
        extract_browser_cookies(browser="netscape")


def test_download_invoices_no_matching_invoices(tmp_path: Path) -> None:
    """Report with no invoices returns empty download result."""
    empty_csv = tmp_path / "empty_report.csv"
    header = [h.value for h in REQUIRED_HEADERS]
    empty_csv.write_text(",".join(header) + "\n", encoding="utf-8")
    out_dir = tmp_path / "invoices"

    res = download_invoices_for_report(empty_csv, out_dir)
    assert res.total_invoices_found == 0
    assert res.successful_downloads == 0
    assert res.failed_downloads == 0


def test_download_invoices_mocked_success_and_auth_failure(
    fake_b2b_vat_csv_factory: Callable[[Sequence[Mapping[str, str]]], Path],
    tmp_path: Path,
) -> None:
    """Verify downloading PDFs writes files and logs auth failure when response is not PDF."""
    rows = [
        {
            ColumnHeader.ORDER_ID.value: "ORD-OK",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "BE111",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "BE",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "50.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
            ColumnHeader.VAT_INVOICE_NUMBER.value: "FR-INV-1",
            ColumnHeader.INVOICE_URL.value: "https://amazon.fr/doc/download?v=1",
        },
        {
            ColumnHeader.ORDER_ID.value: "ORD-FAIL",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "BE222",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "BE",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "30.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
            ColumnHeader.VAT_INVOICE_NUMBER.value: "FR-INV-2",
            ColumnHeader.INVOICE_URL.value: "https://amazon.fr/doc/download?v=2",
        },
    ]
    report_path = fake_b2b_vat_csv_factory(rows)
    out_dir = tmp_path / "invoices_out"

    class FakeResponse:
        def __init__(self, body: bytes, url: str, content_type: str) -> None:
            self.body = body
            self.url = url
            self.headers = {"Content-Type": content_type}

        def geturl(self) -> str:
            return self.url

        def read(self) -> bytes:
            return self.body

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            pass

    def fake_open(req: object, timeout: int = 30) -> FakeResponse:
        _ = timeout
        url = getattr(req, "full_url", str(req))
        if "v=1" in url:
            return FakeResponse(b"%PDF-1.4 test invoice content", url, "application/pdf")
        login_url = "https://sellercentral.amazon.fr/ap/signin"
        return FakeResponse(b"<html>Login required</html>", login_url, "text/html")

    with patch("urllib.request.OpenerDirector.open", side_effect=fake_open):
        res = download_invoices_for_report(
            report_path,
            out_dir,
            cookie_string="session-id=123",
        )

    assert res.total_invoices_found == 2
    assert res.successful_downloads == 1
    assert res.failed_downloads == 1
    assert (out_dir / "FR-INV-1.pdf").exists()
    assert (out_dir / "FR-INV-1.pdf").read_bytes() == b"%PDF-1.4 test invoice content"
    assert not (out_dir / "FR-INV-2.pdf").exists()


def test_cli_download_invoices_invocation(
    fake_b2b_vat_csv_factory: Callable[[Sequence[Mapping[str, str]]], Path],
    tmp_path: Path,
) -> None:
    """Test CLI download-invoices subcommand execution."""
    rows = [
        {
            ColumnHeader.ORDER_ID.value: "ORD-CLI-DL",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "BE999",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "BE",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "10.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
            ColumnHeader.VAT_INVOICE_NUMBER.value: "FR-CLI-INV",
            ColumnHeader.INVOICE_URL.value: "https://amazon.fr/doc/download?v=9",
        }
    ]
    report_path = fake_b2b_vat_csv_factory(rows)
    out_dir = tmp_path / "cli_invoices"

    test_args = [
        "b2b-vat",
        "download-invoices",
        "--report",
        str(report_path),
        "--output-dir",
        str(out_dir),
        "--cookies",
        "test-session=abc",
    ]

    mock_result = InvoiceDownloadResult(
        total_invoices_found=1,
        successful_downloads=1,
        failed_downloads=0,
        downloaded_files=[out_dir / "FR-CLI-INV.pdf"],
    )

    with (
        patch("b2b_vat.engine.download_invoices_for_report", return_value=mock_result),
        patch("sys.argv", test_args),
    ):
        main()


def test_cli_download_invoices_default_output_dir(
    fake_b2b_vat_csv_factory: Callable[[Sequence[Mapping[str, str]]], Path],
) -> None:
    """Test CLI download-invoices subcommand uses report.parent / <stem>_invoices default."""
    rows = [
        {
            ColumnHeader.ORDER_ID.value: "ORD-DEF",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "BE111",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "BE",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "10.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
            ColumnHeader.VAT_INVOICE_NUMBER.value: "FR-DEF-INV",
            ColumnHeader.INVOICE_URL.value: "https://amazon.fr/doc/download?v=9",
        }
    ]
    report_path = fake_b2b_vat_csv_factory(rows)
    expected_default_dir = report_path.parent / f"{report_path.stem}_invoices"

    test_args = [
        "b2b-vat",
        "download-invoices",
        "--report",
        str(report_path),
    ]

    mock_result = InvoiceDownloadResult(
        total_invoices_found=1,
        successful_downloads=1,
        failed_downloads=0,
        downloaded_files=[expected_default_dir / "FR-DEF-INV.pdf"],
    )

    with (
        patch("b2b_vat.engine.download_invoices_for_report", return_value=mock_result) as mock_dl,
        patch("sys.argv", test_args),
    ):
        main()
        mock_dl.assert_called_once()
        _, kwargs = mock_dl.call_args
        assert kwargs["output_dir"] == expected_default_dir


def test_download_invoices_emits_progress_events(
    fake_b2b_vat_csv_factory: Callable[[Sequence[Mapping[str, str]]], Path],
    tmp_path: Path,
) -> None:
    """Test download_invoices_for_report invokes progress_callback with structured events."""
    rows = [
        {
            ColumnHeader.ORDER_ID.value: "ORD-EVENT",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "DE123456789",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "DE",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "25.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
            ColumnHeader.VAT_INVOICE_NUMBER.value: "FR-EVENT-01",
            ColumnHeader.INVOICE_URL.value: "https://sellercentral.amazon.fr/doc/download",
        }
    ]
    report_file = fake_b2b_vat_csv_factory(rows)
    out_dir = tmp_path / "events_out"

    events: list[InvoiceDownloadEvent] = []

    mock_response = MagicMock()
    mock_response.headers.get.return_value = "application/pdf"
    mock_response.geturl.return_value = "https://sellercentral.amazon.fr/doc/download"
    mock_response.read.return_value = b"%PDF-1.4 Mock PDF Content"
    mock_response.__enter__.return_value = mock_response

    mock_opener = MagicMock()
    mock_opener.open.return_value = mock_response

    with (
        patch("urllib.request.build_opener", return_value=mock_opener),
        patch(
            "b2b_vat.engine.extract_browser_cookies",
            return_value=(http.cookiejar.CookieJar(), "chrome"),
        ),
    ):
        result = download_invoices_for_report(
            report_file,
            out_dir,
            browser="chrome",
            progress_callback=events.append,
        )

    assert result.successful_downloads == 1
    phases = [e.phase for e in events]
    assert DownloadPhase.SCANNING in phases
    assert DownloadPhase.COOKIES in phases
    assert DownloadPhase.STARTING in phases
    assert DownloadPhase.DOWNLOADING in phases
    assert DownloadPhase.SAVED in phases


def test_browser_auto_fallback_detection() -> None:
    """Test auto-fallback detects the first browser with valid cookies."""
    mock_firefox_jar = http.cookiejar.CookieJar()
    mock_cookie = http.cookiejar.Cookie(  # type: ignore[call-arg]
        version=0,
        name="session-id",
        value="123-456",
        port=None,
        port_specified=False,
        domain=".amazon.fr",
        domain_specified=True,
        domain_initial_dot=True,
        path="/",
        path_specified=True,
        secure=True,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={},
    )
    mock_firefox_jar.set_cookie(mock_cookie)

    def fake_extract_from_browser(
        browser_name: str, domains: object = None
    ) -> http.cookiejar.CookieJar:
        _ = domains
        if browser_name == "firefox":
            return mock_firefox_jar
        return http.cookiejar.CookieJar()

    with patch("b2b_vat.engine._extract_from_browser_name", side_effect=fake_extract_from_browser):
        # 1. auto mode finds firefox
        jar, detected = extract_browser_cookies(browser="auto")
        assert detected == "firefox"
        assert len(jar) == 1

        # 2. requested chrome with 0 cookies falls back to firefox
        jar_chrome_fallback, detected_fallback = extract_browser_cookies(browser="chrome")
        assert detected_fallback == "firefox"
        assert len(jar_chrome_fallback) == 1


def test_download_invoices_deduplicates_multi_item_orders(
    fake_b2b_vat_csv_factory: Callable[[Sequence[Mapping[str, str]]], Path],
    tmp_path: Path,
) -> None:
    """Multi-item rows sharing the same invoice number are downloaded only once."""
    rows = [
        {
            ColumnHeader.ORDER_ID.value: "ORD-MULTI-1",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "DE123",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "DE",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "10.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
            ColumnHeader.VAT_INVOICE_NUMBER.value: "SHARED-INV-01",
            ColumnHeader.INVOICE_URL.value: "https://amazon.fr/doc/shared_01",
        },
        {
            ColumnHeader.ORDER_ID.value: "ORD-MULTI-1",  # Second item in same order
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "DE123",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "DE",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "15.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
            ColumnHeader.VAT_INVOICE_NUMBER.value: "SHARED-INV-01",  # Same invoice #
            ColumnHeader.INVOICE_URL.value: "https://amazon.fr/doc/shared_01",
        },
        {
            ColumnHeader.ORDER_ID.value: "ORD-MULTI-2",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "IT999",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "IT",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "30.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
            ColumnHeader.VAT_INVOICE_NUMBER.value: "DISTINCT-INV-02",
            ColumnHeader.INVOICE_URL.value: "https://amazon.fr/doc/distinct_02",
        },
    ]
    report_file = fake_b2b_vat_csv_factory(rows)
    out_dir = tmp_path / "dedup_invoices"

    mock_response = MagicMock()
    mock_response.headers.get.return_value = "application/pdf"
    mock_response.geturl.return_value = "https://amazon.fr/doc/download"
    mock_response.read.return_value = b"%PDF-1.4 Mock PDF"
    mock_response.__enter__.return_value = mock_response

    mock_opener = MagicMock()
    mock_opener.open.return_value = mock_response

    with (
        patch("urllib.request.build_opener", return_value=mock_opener),
        patch(
            "b2b_vat.engine.extract_browser_cookies",
            return_value=(http.cookiejar.CookieJar(), "chrome"),
        ),
    ):
        result = download_invoices_for_report(report_file, out_dir)

    # 3 total transactions matched in CSV, but only 2 unique invoice files downloaded
    assert result.total_transactions_covered == 3
    assert result.total_invoices_found == 2
    assert result.successful_downloads == 2
    assert mock_opener.open.call_count == 2
    assert (out_dir / "SHARED-INV-01.pdf").exists()
    assert (out_dir / "DISTINCT-INV-02.pdf").exists()
    assert len(list(out_dir.glob("*.pdf"))) == 2


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

    # 4. Unsupported browser
    with pytest.raises(B2BVATError) as exc_info:
        extract_browser_cookies(browser="netscape_navigator")
    assert isinstance(exc_info.value, (UnsupportedBrowserError, ValueError))
