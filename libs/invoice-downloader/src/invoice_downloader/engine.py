"""Amazon Seller Central Invoice Downloader with Multi-Browser Session Auto-Detection.

Downloads PDF invoices referenced in Amazon VAT transaction reports using
active browser sessions (Chrome, Firefox, Edge, Brave, Arc, Safari, Opera, etc.)
or explicit authentication cookies.
"""

from __future__ import annotations

import argparse
import csv
import http.cookiejar
import logging
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import browser_cookie3
from b2b_vat.engine import (
    DEFAULT_DEPARTURE_COUNTRY,
    B2BVATError,
    process_b2b_vat_report,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

HEADER_BANNER_LENGTH = 82
CHUNK_SIZE = 64 * 1024  # 64 KB streaming buffer
AMAZON_DOMAINS: tuple[str, ...] = (
    ".amazon.fr",
    ".amazon.de",
    ".amazon.it",
    ".amazon.es",
    ".amazon.co.uk",
    ".amazon.com",
    ".sellercentral.amazon.fr",
    ".sellercentral-europe.amazon.com",
    ".sellercentral.amazon.com",
)

BROWSER_CANDIDATES: tuple[str, ...] = (
    "chrome",
    "firefox",
    "edge",
    "brave",
    "arc",
    "opera",
    "vivaldi",
    "safari",
    "chromium",
)


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------


class InvoiceDownloaderError(Exception):
    """Base domain exception for all invoice downloader operations."""


class ReportNotFoundError(InvoiceDownloaderError, FileNotFoundError):
    """Raised when the specified report file does not exist."""


class ReportPathIsDirectoryError(InvoiceDownloaderError, ValueError):
    """Raised when a directory is passed where a CSV report file is required."""


class InvalidReportFormatError(InvoiceDownloaderError, ValueError):
    """Raised when the CSV report cannot be parsed or lacks required headers."""


class UnsupportedBrowserError(InvoiceDownloaderError, ValueError):
    """Raised when an unsupported browser name is requested."""


class AuthenticationRequiredError(InvoiceDownloaderError):
    """Raised when an Amazon session is expired or not authenticated."""


# ---------------------------------------------------------------------------
# Observable Progress Events
# ---------------------------------------------------------------------------


class DownloadPhase(StrEnum):
    """Lifecycle phase of an invoice download process."""

    SCANNING = "SCANNING"
    COOKIES = "COOKIES"
    STARTING = "STARTING"
    DOWNLOADING = "DOWNLOADING"
    SAVED = "SAVED"
    AUTH_FAILED = "AUTH_FAILED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class InvoiceDownloadEvent:
    """Event emitted during the invoice downloading lifecycle."""

    phase: DownloadPhase
    current: int = 0
    total: int = 0
    order_id: str = ""
    filename: str = ""
    size_bytes: int = 0
    message: str = ""


InvoiceProgressCallback = Callable[[InvoiceDownloadEvent], None]


@dataclass(slots=True)
class InvoiceDownloadResult:
    """Summary metrics of an invoice download operation."""

    total_invoices_found: int
    successful_downloads: int
    failed_downloads: int
    downloaded_files: list[Path] = field(default_factory=list)
    total_transactions_covered: int = 0


@dataclass(frozen=True, slots=True)
class DownloadableInvoiceItem:
    """Represents a single invoice document to be downloaded."""

    order_id: str
    invoice_number: str
    invoice_url: str


# ---------------------------------------------------------------------------
# Cookie Extraction & Session Management
# ---------------------------------------------------------------------------


def _extract_from_browser_name(
    browser_name: str,
    domains: Sequence[str] = AMAZON_DOMAINS,
) -> http.cookiejar.CookieJar:
    """Extract cookies from a specific browser engine."""
    browser_map = {
        "chrome": browser_cookie3.chrome,
        "firefox": browser_cookie3.firefox,
        "edge": browser_cookie3.edge,
        "brave": browser_cookie3.brave,
        "arc": browser_cookie3.arc,
        "safari": browser_cookie3.safari,
        "opera": browser_cookie3.opera,
        "vivaldi": browser_cookie3.vivaldi,
        "chromium": browser_cookie3.chromium,
    }

    loader = browser_map.get(browser_name.lower().strip())
    if loader is None:
        valid_opts = ", ".join(sorted(BROWSER_CANDIDATES))
        msg = f"Unsupported browser '{browser_name}'. Valid options: {valid_opts}, auto"
        raise UnsupportedBrowserError(msg)

    jar = http.cookiejar.CookieJar()
    for query in ("amazon", "sellercentral", ""):
        try:
            query_jar = loader(domain_name=query)
            for cookie in query_jar:
                jar.set_cookie(cookie)
            if len(jar) > 0:
                return jar
        except (browser_cookie3.BrowserCookieError, OSError, ValueError) as err:
            logger.debug("Failed query '%s' for browser %s: %s", query, browser_name, err)

    for domain in domains:
        try:
            domain_jar = loader(domain_name=domain)
            for cookie in domain_jar:
                jar.set_cookie(cookie)
        except (browser_cookie3.BrowserCookieError, OSError, ValueError) as err:
            logger.debug("Failed domain '%s' for browser %s: %s", domain, browser_name, err)

    return jar


def _find_session_in_candidates(
    candidates: Sequence[str],
    domains: Sequence[str],
) -> tuple[http.cookiejar.CookieJar, str] | None:
    """Search given browser candidates for active Amazon cookies."""
    for candidate in candidates:
        try:
            jar = _extract_from_browser_name(candidate, domains=domains)
            if len(jar) > 0:
                return jar, candidate
        except (UnsupportedBrowserError, browser_cookie3.BrowserCookieError, OSError, ValueError):
            continue
    return None


def extract_browser_cookies(
    browser: str = "auto",
    domains: Sequence[str] = AMAZON_DOMAINS,
) -> tuple[http.cookiejar.CookieJar, str]:
    """Extract Amazon Seller Central session cookies with multi-browser auto-fallback."""
    target = browser.lower().strip()
    if target != "auto" and target not in BROWSER_CANDIDATES:
        valid_opts = ", ".join(sorted(BROWSER_CANDIDATES))
        msg = f"Unsupported browser '{browser}'. Valid options: {valid_opts}, auto"
        raise UnsupportedBrowserError(msg)

    if target == "auto":
        match = _find_session_in_candidates(BROWSER_CANDIDATES, domains=domains)
        if match:
            jar, detected = match
            logger.info("Detected %d cookies from browser '%s'", len(jar), detected)
            return jar, detected
        return http.cookiejar.CookieJar(), "auto (no session found)"

    try:
        jar = _extract_from_browser_name(target, domains=domains)
        if len(jar) > 0:
            return jar, target
        logger.warning(
            "No active Amazon cookies in '%s'. Checking other installed browsers...",
            target,
        )
    except (browser_cookie3.BrowserCookieError, OSError, ValueError) as err:
        logger.warning(
            "Could not read session from '%s' (%s). Checking other installed browsers...",
            target,
            err,
        )

    fallbacks = [c for c in BROWSER_CANDIDATES if c != target]
    match = _find_session_in_candidates(fallbacks, domains=domains)
    if match:
        jar, detected = match
        logger.info("Fell back to browser '%s' with %d active cookies", detected, len(jar))
        return jar, detected

    return http.cookiejar.CookieJar(), target


def _build_http_opener(
    *,
    browser: str,
    cookie_string: str | None,
    cookie_file: Path | None,
    progress_callback: InvoiceProgressCallback | None,
) -> tuple[urllib.request.OpenerDirector, str]:
    """Build and configure urllib HTTP opener with session cookies."""
    if cookie_file and cookie_file.exists():
        if progress_callback:
            progress_callback(
                InvoiceDownloadEvent(
                    phase=DownloadPhase.COOKIES,
                    message=f"Loading cookies from file: {cookie_file}",
                )
            )
        jar: http.cookiejar.CookieJar = http.cookiejar.MozillaCookieJar(cookie_file)
        jar.load(ignore_discard=True, ignore_expires=True)  # type: ignore[attr-defined]
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), "cookie_file"

    if cookie_string:
        if progress_callback:
            progress_callback(
                InvoiceDownloadEvent(
                    phase=DownloadPhase.COOKIES,
                    message="Using provided cookie header string",
                )
            )
        return urllib.request.build_opener(), "header_string"

    if progress_callback:
        progress_callback(
            InvoiceDownloadEvent(
                phase=DownloadPhase.COOKIES,
                message=(
                    "Auto-detecting Amazon browser session..."
                    if browser == "auto"
                    else f"Extracting cookies from '{browser}' (with auto-fallback)..."
                ),
            )
        )
    extracted_jar, resolved_browser = extract_browser_cookies(browser=browser)
    if progress_callback and len(extracted_jar) > 0:
        progress_callback(
            InvoiceDownloadEvent(
                phase=DownloadPhase.COOKIES,
                message=f"Found {len(extracted_jar)} cookie(s) from '{resolved_browser}'",
            )
        )

    return (
        urllib.request.build_opener(urllib.request.HTTPCookieProcessor(extracted_jar)),
        resolved_browser,
    )


# ---------------------------------------------------------------------------
# Invoice Scanning & Deduplication
# ---------------------------------------------------------------------------


def _scan_all_report_invoices(report_path: Path) -> list[DownloadableInvoiceItem]:
    """Scan any Amazon CSV report and extract all rows containing invoice URLs."""
    if not report_path.exists():
        raise ReportNotFoundError(str(report_path))
    if report_path.is_dir():
        raise ReportPathIsDirectoryError(str(report_path))

    with report_path.open("r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return []
        header_map = {col.strip().lower(): col for col in reader.fieldnames if col}
        order_id_col = header_map.get("order id") or header_map.get("order-id") or ""
        invoice_num_col = (
            header_map.get("vat invoice number")
            or header_map.get("invoice number")
            or header_map.get("invoice-number")
            or ""
        )
        invoice_url_col = (
            header_map.get("invoice url")
            or header_map.get("invoice-url")
            or header_map.get("invoiceurl")
            or ""
        )

        if not invoice_url_col and not invoice_num_col:
            return []

        items: list[DownloadableInvoiceItem] = []
        for row in reader:
            url = row.get(invoice_url_col, "").strip() if invoice_url_col else ""
            inv_num = row.get(invoice_num_col, "").strip() if invoice_num_col else ""
            order_id = row.get(order_id_col, "").strip() if order_id_col else ""
            if url:
                items.append(
                    DownloadableInvoiceItem(
                        order_id=order_id,
                        invoice_number=inv_num,
                        invoice_url=url,
                    )
                )
        return items


def _deduplicate_invoices(
    items: Sequence[DownloadableInvoiceItem],
) -> list[DownloadableInvoiceItem]:
    """Retain only the first occurrence for each unique invoice document."""
    unique: list[DownloadableInvoiceItem] = []
    seen_doc_keys: set[str] = set()
    for item in items:
        doc_key = (
            item.invoice_number.strip().upper()
            if item.invoice_number and item.invoice_number.strip()
            else (item.invoice_url.strip() if item.invoice_url else item.order_id.strip())
        )
        if doc_key not in seen_doc_keys:
            seen_doc_keys.add(doc_key)
            unique.append(item)
    return unique


# ---------------------------------------------------------------------------
# Invoice Downloading Engine
# ---------------------------------------------------------------------------


def _download_single_invoice(
    opener: urllib.request.OpenerDirector,
    item: DownloadableInvoiceItem,
    *,
    output_dir: Path,
    user_agent: str,
    cookie_string: str | None = None,
    browser: str = "",
) -> Path | None:
    """Download a single invoice PDF to disk using session opener."""
    doc_name = (
        f"{item.invoice_number}.pdf" if item.invoice_number else f"invoice_{item.order_id}.pdf"
    )
    dest_path = output_dir / doc_name

    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Upgrade-Insecure-Requests": "1",
    }
    if cookie_string:
        headers["Cookie"] = cookie_string

    req = urllib.request.Request(item.invoice_url, headers=headers)  # ruff: ignore[suspicious-url-open-usage]

    try:
        resp = opener.open(req, timeout=30)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as err:
        logger.warning("Download failed for order %s (%s): %s", item.order_id, doc_name, err)
        return None

    with resp as response:
        content_type = response.headers.get("Content-Type", "").lower()
        final_url = response.geturl().lower()

        if "signin" in final_url or "ap/signin" in final_url:
            logger.warning(
                "Auth required for order %s (%s). Please log in via %s.",
                item.order_id,
                doc_name,
                browser or "your browser",
            )
            return None

        data = response.read()

    if data.startswith(b"%PDF") or "pdf" in content_type:
        dest_path.write_bytes(data)
        return dest_path

    if b"signin" in data[:1024].lower() or b"sign in" in data[:1024].lower():
        logger.warning("Amazon login page returned for order %s (%s)", item.order_id, doc_name)
        return None

    dest_path.write_bytes(data)
    return dest_path


def _collect_report_invoices(
    report_path: Path,
    departure_country: str,
    *,
    all_invoices: bool,
) -> list[DownloadableInvoiceItem]:
    """Extract raw downloadable items based on mode (B2B intra-EU vs all)."""
    if all_invoices:
        return _scan_all_report_invoices(report_path)

    try:
        b2b_res = process_b2b_vat_report(report_path, departure_country=departure_country)
    except B2BVATError as err:
        raise InvalidReportFormatError(str(err)) from err

    return [
        DownloadableInvoiceItem(
            order_id=tx.order_id,
            invoice_number=tx.invoice_number,
            invoice_url=tx.invoice_url,
        )
        for tx in b2b_res.transactions
        if tx.invoice_url and tx.invoice_url.strip()
    ]


def _stream_all_invoices(
    unique_invoices: Sequence[DownloadableInvoiceItem],
    opener: urllib.request.OpenerDirector,
    *,
    output_dir: Path,
    resolved_browser: str,
    cookie_string: str | None,
    progress_callback: InvoiceProgressCallback | None,
) -> tuple[int, int, list[Path]]:
    """Iterate and download each unique invoice item."""
    successful = 0
    failed = 0
    downloaded_paths: list[Path] = []
    total = len(unique_invoices)
    user_agent = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )

    for idx, item in enumerate(unique_invoices, start=1):
        doc_name = (
            f"{item.invoice_number}.pdf" if item.invoice_number else f"invoice_{item.order_id}.pdf"
        )
        if progress_callback:
            progress_callback(
                InvoiceDownloadEvent(
                    phase=DownloadPhase.DOWNLOADING,
                    current=idx,
                    total=total,
                    order_id=item.order_id,
                    filename=doc_name,
                )
            )

        saved_path = _download_single_invoice(
            opener,
            item,
            output_dir=output_dir,
            user_agent=user_agent,
            cookie_string=cookie_string,
            browser=resolved_browser,
        )

        if saved_path is not None:
            successful += 1
            downloaded_paths.append(saved_path)
            file_size = saved_path.stat().st_size
            if progress_callback:
                progress_callback(
                    InvoiceDownloadEvent(
                        phase=DownloadPhase.SAVED,
                        current=idx,
                        total=total,
                        order_id=item.order_id,
                        filename=doc_name,
                        size_bytes=file_size,
                    )
                )
        else:
            failed += 1
            if progress_callback:
                progress_callback(
                    InvoiceDownloadEvent(
                        phase=DownloadPhase.AUTH_FAILED,
                        current=idx,
                        total=total,
                        order_id=item.order_id,
                        filename=doc_name,
                    )
                )

    return successful, failed, downloaded_paths


def download_invoices_for_report(
    report_path: Path,
    output_dir: Path,
    *,
    departure_country: str = DEFAULT_DEPARTURE_COUNTRY,
    all_invoices: bool = False,
    browser: str = "auto",
    cookie_string: str | None = None,
    cookie_file: Path | None = None,
    progress_callback: InvoiceProgressCallback | None = None,
) -> InvoiceDownloadResult:
    """Scan report, filter transactions, and download invoice PDFs."""
    if not report_path.exists():
        raise ReportNotFoundError(str(report_path))
    if report_path.is_dir():
        raise ReportPathIsDirectoryError(str(report_path))

    if progress_callback:
        progress_callback(
            InvoiceDownloadEvent(
                phase=DownloadPhase.SCANNING,
                filename=report_path.name,
                message=f"Scanning report: {report_path.name}",
            )
        )

    raw_items = _collect_report_invoices(
        report_path,
        departure_country,
        all_invoices=all_invoices,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    total_matched_rows = len(raw_items)

    if not raw_items:
        if progress_callback:
            progress_callback(
                InvoiceDownloadEvent(
                    phase=DownloadPhase.COMPLETED,
                    total=0,
                    message="No matching transactions with invoice URLs found.",
                )
            )
        return InvoiceDownloadResult(0, 0, 0, total_transactions_covered=0)

    unique_invoices = _deduplicate_invoices(raw_items)
    total_unique = len(unique_invoices)

    opener, resolved_browser = _build_http_opener(
        browser=browser,
        cookie_string=cookie_string,
        cookie_file=cookie_file,
        progress_callback=progress_callback,
    )

    if progress_callback:
        progress_callback(
            InvoiceDownloadEvent(
                phase=DownloadPhase.STARTING,
                total=total_unique,
                current=total_matched_rows,
                message=str(output_dir),
            )
        )

    succ, fail, paths = _stream_all_invoices(
        unique_invoices,
        opener,
        output_dir=output_dir,
        resolved_browser=resolved_browser,
        cookie_string=cookie_string,
        progress_callback=progress_callback,
    )

    return InvoiceDownloadResult(
        total_invoices_found=total_unique,
        successful_downloads=succ,
        failed_downloads=fail,
        downloaded_files=paths,
        total_transactions_covered=total_matched_rows,
    )


# ---------------------------------------------------------------------------
# CLI Interface
# ---------------------------------------------------------------------------


def _cli_progress_callback(event: InvoiceDownloadEvent) -> None:
    """Format and print real-time progress events to standard output."""
    if event.phase == DownloadPhase.SCANNING:
        print(f"\n  [1/3] Scanning VAT report: {event.filename}...", flush=True)
    elif event.phase == DownloadPhase.COOKIES:
        print(f"  [2/3] {event.message}...", flush=True)
    elif event.phase == DownloadPhase.STARTING:
        if event.current > 0 and event.current != event.total:
            print(
                f"  [3/3] Downloading {event.total} unique invoice(s) "
                f"(covering {event.current} transaction rows) into: {event.message}\n",
                flush=True,
            )
        else:
            print(
                f"  [3/3] Downloading {event.total} invoice(s) into: {event.message}\n",
                flush=True,
            )
    elif event.phase == DownloadPhase.DOWNLOADING:
        prefix = (
            f"    [{event.current}/{event.total}] Order {event.order_id} ({event.filename})... "
        )
        print(prefix, end="", flush=True)
    elif event.phase == DownloadPhase.SAVED:
        size_kb = event.size_bytes / 1024
        print(f"✅ Saved ({size_kb:.1f} KB)", flush=True)
    elif event.phase == DownloadPhase.AUTH_FAILED:
        print("❌ Failed (not logged in or session expired)", flush=True)
    elif event.phase == DownloadPhase.FAILED:
        print(f"❌ Failed ({event.message})", flush=True)


def create_cli_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for invoice-downloader."""
    parser = argparse.ArgumentParser(
        prog="invoice-downloader",
        description="Amazon Seller Central Invoice Downloader with Auto-Detection.",
    )
    parser.add_argument(
        "-r",
        "--report",
        type=Path,
        required=True,
        help="Path to the Amazon VAT / Monthly transaction report CSV.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to save downloaded invoice PDFs (default: <report_name>_invoices).",
    )
    parser.add_argument(
        "-d",
        "--departure",
        type=str,
        default=DEFAULT_DEPARTURE_COUNTRY,
        help=f"Departure country for filtering (default: {DEFAULT_DEPARTURE_COUNTRY}).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Download all invoice URLs found in report, instead of B2B intra-EU only.",
    )
    parser.add_argument(
        "-b",
        "--browser",
        type=str,
        default="auto",
        help="Browser for session cookies (auto, chrome, firefox, edge, brave, arc, etc.).",
    )
    parser.add_argument(
        "--cookies",
        type=str,
        default=None,
        help='Raw cookie header string (e.g. "session-id=...; at-main=...").',
    )
    parser.add_argument(
        "--cookie-file",
        type=Path,
        default=None,
        help="Path to a Netscape/Mozilla format cookies.txt file.",
    )
    return parser


def main() -> None:
    """CLI entrypoint for invoice-downloader."""
    parser = create_cli_parser()
    args = parser.parse_args()

    target_out_dir = args.output_dir or (args.report.parent / f"{args.report.stem}_invoices")
    try:
        dl_res = download_invoices_for_report(
            report_path=args.report,
            output_dir=target_out_dir,
            departure_country=args.departure,
            all_invoices=args.all,
            browser=args.browser,
            cookie_string=args.cookies,
            cookie_file=args.cookie_file,
            progress_callback=_cli_progress_callback,
        )
    except InvoiceDownloaderError as err:
        print(f"\n  [ERROR] {err}\n", file=sys.stderr)
        sys.exit(1)
    except OSError:
        logger.exception("Unexpected system error during invoice downloading")
        sys.exit(1)

    print("\n" + "=" * HEADER_BANNER_LENGTH)
    print("  AMAZON INVOICE DOWNLOAD SUMMARY")
    print("=" * HEADER_BANNER_LENGTH)
    if dl_res.total_transactions_covered > dl_res.total_invoices_found:
        print(
            f"  Total Unique Invoices: {dl_res.total_invoices_found} "
            f"(covering {dl_res.total_transactions_covered} transactions)"
        )
    else:
        print(f"  Total Unique Invoices: {dl_res.total_invoices_found}")
    print(f"  Successfully Saved:    {dl_res.successful_downloads}")
    print(f"  Failed / Skipped:      {dl_res.failed_downloads}")
    print(f"  Output Directory:      {target_out_dir}")
    print("=" * HEADER_BANNER_LENGTH)

    if dl_res.failed_downloads > 0 and dl_res.successful_downloads == 0:
        print("\n  💡 Windows / Chrome Tip:")
        print("     Chrome (127+) on Windows locks session cookies with App-Bound encryption.")
        print("     Quick alternatives to download immediately:")
        print("     1. Log in via Firefox or Edge and run:")
        print("        uv run invoice-downloader -r <report> --browser edge")
        print("        uv run invoice-downloader -r <report> --browser firefox")
        print("     2. Or copy the Cookie header from DevTools (F12 -> Network):")
        print('        uv run invoice-downloader -r <report> --cookies "session-id=..."\n')
    else:
        print()


if __name__ == "__main__":
    main()
