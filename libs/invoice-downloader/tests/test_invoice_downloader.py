from __future__ import annotations

import http.cookiejar
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from b2b_vat.engine import ColumnHeader
from invoice_downloader.engine import (
    DownloadPhase,
    InvoiceDownloaderError,
    ReportNotFoundError,
    ReportPathIsDirectoryError,
    UnsupportedBrowserError,
    download_invoices_for_report,
    extract_browser_cookies,
    main,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from invoice_downloader.engine import InvoiceDownloadEvent


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

    with patch(
        "invoice_downloader.engine._extract_from_browser_name",
        side_effect=fake_extract_from_browser,
    ):
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
            ColumnHeader.ORDER_ID.value: "ORD-MULTI-1",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "DE123",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "DE",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "15.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
            ColumnHeader.VAT_INVOICE_NUMBER.value: "SHARED-INV-01",
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
    mock_response.read.return_value = b"%PDF-1.4 Mock PDF Content"
    mock_response.__enter__.return_value = mock_response

    mock_opener = MagicMock()
    mock_opener.open.return_value = mock_response

    with (
        patch("urllib.request.build_opener", return_value=mock_opener),
        patch(
            "invoice_downloader.engine.extract_browser_cookies",
            return_value=(http.cookiejar.CookieJar(), "chrome"),
        ),
    ):
        result = download_invoices_for_report(report_file, out_dir)

    assert result.total_transactions_covered == 3
    assert result.total_invoices_found == 2
    assert result.successful_downloads == 2
    assert mock_opener.open.call_count == 2
    assert (out_dir / "SHARED-INV-01.pdf").exists()
    assert (out_dir / "DISTINCT-INV-02.pdf").exists()


def test_download_invoices_all_mode(
    fake_b2b_vat_csv_factory: Callable[[Sequence[Mapping[str, str]]], Path],
    tmp_path: Path,
) -> None:
    """Test --all mode downloads domestic/B2C transactions as well as B2B."""
    rows = [
        {
            ColumnHeader.ORDER_ID.value: "ORD-DOMESTIC",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "",  # No VAT number (B2C)
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "FR",  # Domestic
            ColumnHeader.TAX_REPORTING_SCHEME.value: "STANDARD",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "2.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "10.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
            ColumnHeader.VAT_INVOICE_NUMBER.value: "FR-DOM-01",
            ColumnHeader.INVOICE_URL.value: "https://amazon.fr/doc/domestic_01",
        },
    ]
    report_file = fake_b2b_vat_csv_factory(rows)
    out_dir = tmp_path / "all_invoices"

    mock_response = MagicMock()
    mock_response.headers.get.return_value = "application/pdf"
    mock_response.geturl.return_value = "https://amazon.fr/doc/download"
    mock_response.read.return_value = b"%PDF-1.4 Mock PDF Content"
    mock_response.__enter__.return_value = mock_response

    mock_opener = MagicMock()
    mock_opener.open.return_value = mock_response

    with (
        patch("urllib.request.build_opener", return_value=mock_opener),
        patch(
            "invoice_downloader.engine.extract_browser_cookies",
            return_value=(http.cookiejar.CookieJar(), "firefox"),
        ),
    ):
        # 1. Default (B2B only) finds 0
        res_default = download_invoices_for_report(report_file, out_dir, all_invoices=False)
        assert res_default.total_invoices_found == 0

        # 2. --all finds the domestic invoice
        res_all = download_invoices_for_report(report_file, out_dir, all_invoices=True)
        assert res_all.total_invoices_found == 1
        assert res_all.successful_downloads == 1
        assert (out_dir / "FR-DOM-01.pdf").exists()


def test_download_invoices_emits_progress_events(
    fake_b2b_vat_csv_factory: Callable[[Sequence[Mapping[str, str]]], Path],
    tmp_path: Path,
) -> None:
    """Verify progress events are emitted across lifecycle phases."""
    rows = [
        {
            ColumnHeader.ORDER_ID.value: "ORD-EVENT-1",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "DE123",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "DE",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "10.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
            ColumnHeader.VAT_INVOICE_NUMBER.value: "EVT-INV-01",
            ColumnHeader.INVOICE_URL.value: "https://amazon.fr/doc/evt_01",
        },
    ]
    report_file = fake_b2b_vat_csv_factory(rows)
    out_dir = tmp_path / "events_out"
    events: list[InvoiceDownloadEvent] = []

    mock_response = MagicMock()
    mock_response.headers.get.return_value = "application/pdf"
    mock_response.geturl.return_value = "https://amazon.fr/doc/download"
    mock_response.read.return_value = b"%PDF-1.4 Mock PDF Content"
    mock_response.__enter__.return_value = mock_response

    mock_opener = MagicMock()
    mock_opener.open.return_value = mock_response

    with (
        patch("urllib.request.build_opener", return_value=mock_opener),
        patch(
            "invoice_downloader.engine.extract_browser_cookies",
            return_value=(http.cookiejar.CookieJar(), "chrome"),
        ),
    ):
        result = download_invoices_for_report(
            report_file,
            out_dir,
            progress_callback=events.append,
        )

    assert result.successful_downloads == 1
    phases = [e.phase for e in events]
    assert DownloadPhase.SCANNING in phases
    assert DownloadPhase.COOKIES in phases
    assert DownloadPhase.STARTING in phases
    assert DownloadPhase.DOWNLOADING in phases
    assert DownloadPhase.SAVED in phases


def test_cli_invoice_downloader_invocation(
    fake_b2b_vat_csv_factory: Callable[[Sequence[Mapping[str, str]]], Path],
    tmp_path: Path,
) -> None:
    """Verify CLI main entry point for invoice-downloader."""
    rows = [
        {
            ColumnHeader.ORDER_ID.value: "ORD-CLI-1",
            ColumnHeader.BUYER_TAX_REGISTRATION.value: "DE123",
            ColumnHeader.SHIP_FROM_COUNTRY.value: "FR",
            ColumnHeader.SHIP_TO_COUNTRY.value: "DE",
            ColumnHeader.TAX_REPORTING_SCHEME.value: "",
            ColumnHeader.OUR_PRICE_TAX_AMOUNT.value: "0.00",
            ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE.value: "10.00",
            ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT.value: "0.00",
            ColumnHeader.VAT_INVOICE_NUMBER.value: "CLI-INV-01",
            ColumnHeader.INVOICE_URL.value: "https://amazon.fr/doc/cli_01",
        },
    ]
    report_file = fake_b2b_vat_csv_factory(rows)
    out_dir = tmp_path / "cli_invoices"

    mock_response = MagicMock()
    mock_response.headers.get.return_value = "application/pdf"
    mock_response.geturl.return_value = "https://amazon.fr/doc/download"
    mock_response.read.return_value = b"%PDF-1.4 Mock PDF Content"
    mock_response.__enter__.return_value = mock_response

    mock_opener = MagicMock()
    mock_opener.open.return_value = mock_response

    with (
        patch(
            "sys.argv",
            [
                "invoice-downloader",
                "-r",
                str(report_file),
                "-o",
                str(out_dir),
                "--browser",
                "chrome",
            ],
        ),
        patch("urllib.request.build_opener", return_value=mock_opener),
        patch(
            "invoice_downloader.engine.extract_browser_cookies",
            return_value=(http.cookiejar.CookieJar(), "chrome"),
        ),
    ):
        main()

    assert (out_dir / "CLI-INV-01.pdf").exists()


def test_domain_exceptions(tmp_path: Path) -> None:
    """Verify domain exception hierarchy in invoice-downloader."""
    missing = tmp_path / "missing.csv"
    with pytest.raises(InvoiceDownloaderError) as exc_info:
        download_invoices_for_report(missing, tmp_path / "out")
    assert isinstance(exc_info.value, (ReportNotFoundError, FileNotFoundError))

    dir_path = tmp_path / "some_dir"
    dir_path.mkdir()
    with pytest.raises(InvoiceDownloaderError) as exc_info:
        download_invoices_for_report(dir_path, tmp_path / "out")
    assert isinstance(exc_info.value, (ReportPathIsDirectoryError, ValueError))

    with pytest.raises(InvoiceDownloaderError) as exc_info:
        extract_browser_cookies(browser="invalid_browser")
    assert isinstance(exc_info.value, (UnsupportedBrowserError, ValueError))
