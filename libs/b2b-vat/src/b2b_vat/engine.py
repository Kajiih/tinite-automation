"""Amazon VAT Transaction Report - B2B Intra-EU Transaction Automation Engine.

Filters zero-rated cross-border B2B transactions from Amazon VAT reports:
1. Valid Buyer Tax Registration number (Column AR).
2. Ship From Country is the designated departure country (default: FR) and Ship To Country is NOT.
3. Tax Reporting Scheme (Column S) is empty (no special scheme like OSS/VOEC).
4. OUR_PRICE Tax Amount (Column Y) is 0.00.

Calculates the net difference per line:
(OUR_PRICE Tax Exclusive Selling Price + OUR_PRICE Tax Inclusive Promo Amount)
and aggregates totals grouped by Buyer VAT registration.
"""

from __future__ import annotations

import argparse
import csv
import http.cookiejar
import logging
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

import browser_cookie3

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableSequence, Sequence

logger: logging.Logger = logging.getLogger(__name__)

DEFAULT_ENCODING: str = "utf-8-sig"
CSV_LINE_TERMINATOR: str = "\r\n"
DEFAULT_DEPARTURE_COUNTRY: str = "FR"
TAX_ZERO_TOLERANCE: float = 0.001
MAX_DEST_DISPLAY_LENGTH: int = 8
TABLE_DIVIDER_LENGTH: int = 78
HEADER_BANNER_LENGTH: int = 82


class ColumnHeader(StrEnum):
    """Standard column header names in Amazon VAT transaction reports."""

    MARKETPLACE_ID = "Marketplace ID"
    TRANSACTION_TYPE = "Transaction Type"
    ORDER_ID = "Order ID"
    ORDER_DATE = "Order Date"
    SHIPMENT_DATE = "Shipment Date"
    ASIN = "ASIN"
    SKU = "SKU"
    QUANTITY = "Quantity"
    TAX_REPORTING_SCHEME = "Tax Reporting Scheme"
    OUR_PRICE_TAX_AMOUNT = "OUR_PRICE Tax Amount"
    OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE = "OUR_PRICE Tax Exclusive Selling Price"
    OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT = "OUR_PRICE Tax Inclusive Promo Amount"
    BUYER_TAX_REGISTRATION = "Buyer Tax Registration"
    VAT_INVOICE_NUMBER = "VAT Invoice Number"
    INVOICE_URL = "Invoice Url"
    SHIP_FROM_COUNTRY = "Ship From Country"
    SHIP_TO_COUNTRY = "Ship To Country"


@dataclass(frozen=True, slots=True)
class B2BTransactionRow:
    """Represents a single filtered B2B cross-border transaction."""

    row_index: int
    order_id: str
    transaction_type: str
    order_date: str
    asin: str
    sku: str
    quantity: str
    buyer_vat: str
    ship_from_country: str
    ship_to_country: str
    tax_exclusive_selling_price: float
    tax_inclusive_promo_amount: float
    net_difference: float
    invoice_number: str
    invoice_url: str
    marketplace_id: str


@dataclass(slots=True)
class B2BVATSummary:
    """Aggregated B2B metrics for a specific Buyer VAT registration."""

    buyer_vat: str
    destination_countries: list[str] = field(default_factory=list)
    transaction_count: int = 0
    total_tax_exclusive_price: float = 0.0
    total_tax_inclusive_promo: float = 0.0
    total_net_difference: float = 0.0

    def add_transaction(self, row: B2BTransactionRow) -> None:
        """Accumulate a transaction row into this VAT summary."""
        self.transaction_count += 1
        if row.ship_to_country and row.ship_to_country not in self.destination_countries:
            self.destination_countries.append(row.ship_to_country)
            self.destination_countries.sort()
        self.total_tax_exclusive_price = round(
            self.total_tax_exclusive_price + row.tax_exclusive_selling_price, 2
        )
        self.total_tax_inclusive_promo = round(
            self.total_tax_inclusive_promo + row.tax_inclusive_promo_amount, 2
        )
        self.total_net_difference = round(self.total_net_difference + row.net_difference, 2)


@dataclass(slots=True)
class B2BProcessingResult:
    """Consolidated result of processing an Amazon VAT report for B2B transactions."""

    report_path: Path
    departure_country: str
    total_rows_scanned: int
    matched_rows_count: int
    unique_vats_count: int
    grand_total_selling_price: float
    grand_total_promo_amount: float
    grand_total_net_difference: float
    vat_summaries: Sequence[B2BVATSummary]
    transactions: Sequence[B2BTransactionRow]


# ---------------------------------------------------------------------------
# Domain Exceptions (Grounding: requests.exceptions, urllib3.exceptions)
# ---------------------------------------------------------------------------


class B2BVATError(Exception):
    """Base domain exception for all B2B VAT operations."""


class ReportNotFoundError(B2BVATError, FileNotFoundError):
    """Raised when the specified Amazon VAT report file does not exist."""


class ReportPathIsDirectoryError(B2BVATError, ValueError):
    """Raised when a directory path is supplied where a CSV file is required."""


class InvalidReportFormatError(B2BVATError, ValueError):
    """Raised when required headers or data rows in the VAT report are invalid."""


class InvoiceDownloadError(B2BVATError):
    """Base domain exception for invoice downloading errors."""


class UnsupportedBrowserError(InvoiceDownloadError, ValueError):
    """Raised when an unsupported browser name is requested for cookie extraction."""


class AuthenticationRequiredError(InvoiceDownloadError):
    """Raised when an Amazon Seller Central session is unauthenticated or expired."""


# ---------------------------------------------------------------------------
# Observable Progress Events (Grounding: huggingface_hub, pip.utils.logging)
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


def _parse_decimal_value(raw_value: object) -> float:
    """Parse string or numeric cell into float, handling commas and whitespace."""
    if raw_value is None:
        return 0.0
    if isinstance(raw_value, (int, float)):
        return float(raw_value)
    sanitized = (
        str(raw_value)
        .replace(",", ".")
        .replace("€", "")
        .replace("$", "")
        .replace("£", "")
        .replace("\xa0", "")
        .strip()
    )
    if not sanitized:
        return 0.0
    try:
        return float(Decimal(sanitized))
    except (InvalidOperation, ValueError):
        return 0.0


REQUIRED_HEADERS: tuple[ColumnHeader, ...] = (
    ColumnHeader.BUYER_TAX_REGISTRATION,
    ColumnHeader.SHIP_FROM_COUNTRY,
    ColumnHeader.SHIP_TO_COUNTRY,
    ColumnHeader.OUR_PRICE_TAX_AMOUNT,
    ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE,
    ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT,
)


def _resolve_indices(header: Sequence[str]) -> Mapping[ColumnHeader, int]:
    """Map expected ColumnHeader names to column positions in CSV header.

    Returns:
        Mapping of ColumnHeader to 0-based column index in the header row.

    Raises:
        InvalidReportFormatError: If mandatory Amazon VAT report columns are missing.
    """
    normalized_header: dict[str, int] = {
        col_name.strip().lower(): idx for idx, col_name in enumerate(header)
    }

    resolved: dict[ColumnHeader, int] = {}
    missing_required: list[str] = []

    for col in ColumnHeader:
        key = col.value.strip().lower()
        if key in normalized_header:
            resolved[col] = normalized_header[key]
        else:
            resolved[col] = -1
            if col in REQUIRED_HEADERS:
                missing_required.append(col.value)
            else:
                logger.warning("Optional column header '%s' not found in CSV header.", col.value)

    if missing_required:
        missing_str = ", ".join(f"'{h}'" for h in missing_required)
        msg = f"Invalid Amazon VAT Report format: missing required columns: {missing_str}"
        raise InvalidReportFormatError(msg)

    return resolved


def _get_cell_value(row: Sequence[str], index: int) -> str:
    """Safely extract stripped string from row at specified index."""
    if 0 <= index < len(row):
        return row[index].strip()
    return ""


def _parse_transaction_row(
    row: Sequence[str],
    indices: Mapping[ColumnHeader, int],
    target_dep: str,
    row_idx: int,
) -> B2BTransactionRow | None:
    """Evaluate whether a single row matches B2B Intra-EU criteria and parse it."""
    buyer_vat = _get_cell_value(row, indices[ColumnHeader.BUYER_TAX_REGISTRATION])
    if not buyer_vat:
        return None

    ship_from = _get_cell_value(row, indices[ColumnHeader.SHIP_FROM_COUNTRY]).upper()
    ship_to = _get_cell_value(row, indices[ColumnHeader.SHIP_TO_COUNTRY]).upper()

    if ship_from != target_dep or ship_to == target_dep:
        return None

    tax_scheme = _get_cell_value(row, indices[ColumnHeader.TAX_REPORTING_SCHEME])
    if tax_scheme:
        return None

    raw_tax_amt = _get_cell_value(row, indices[ColumnHeader.OUR_PRICE_TAX_AMOUNT])
    tax_amt = _parse_decimal_value(raw_tax_amt)
    if abs(tax_amt) > TAX_ZERO_TOLERANCE:
        return None

    raw_excl_price = _get_cell_value(
        row, indices[ColumnHeader.OUR_PRICE_TAX_EXCLUSIVE_SELLING_PRICE]
    )
    raw_incl_promo = _get_cell_value(
        row, indices[ColumnHeader.OUR_PRICE_TAX_INCLUSIVE_PROMO_AMOUNT]
    )

    tax_excl_price = round(_parse_decimal_value(raw_excl_price), 2)
    tax_incl_promo = round(_parse_decimal_value(raw_incl_promo), 2)
    net_diff = round(tax_excl_price + tax_incl_promo, 2)

    return B2BTransactionRow(
        row_index=row_idx,
        order_id=_get_cell_value(row, indices[ColumnHeader.ORDER_ID]),
        transaction_type=_get_cell_value(row, indices[ColumnHeader.TRANSACTION_TYPE]),
        order_date=_get_cell_value(row, indices[ColumnHeader.ORDER_DATE]),
        asin=_get_cell_value(row, indices[ColumnHeader.ASIN]),
        sku=_get_cell_value(row, indices[ColumnHeader.SKU]),
        quantity=_get_cell_value(row, indices[ColumnHeader.QUANTITY]),
        buyer_vat=buyer_vat,
        ship_from_country=ship_from,
        ship_to_country=ship_to,
        tax_exclusive_selling_price=tax_excl_price,
        tax_inclusive_promo_amount=tax_incl_promo,
        net_difference=net_diff,
        invoice_number=_get_cell_value(row, indices[ColumnHeader.VAT_INVOICE_NUMBER]),
        invoice_url=_get_cell_value(row, indices[ColumnHeader.INVOICE_URL]),
        marketplace_id=_get_cell_value(row, indices[ColumnHeader.MARKETPLACE_ID]),
    )


def scan_b2b_vat_csv(
    file_handle: TextIO,
    departure_country: str = DEFAULT_DEPARTURE_COUNTRY,
) -> tuple[int, Sequence[B2BTransactionRow], Sequence[B2BVATSummary]]:
    """Scan and filter CSV rows matching B2B Intra-EU criteria.

    Args:
        file_handle: Open text reader for the CSV file.
        departure_country: 2-letter ISO departure country code (e.g. "FR").

    Returns:
        Tuple of (total_rows_scanned, list of transaction rows, list of VAT summaries).

    Raises:
        InvalidReportFormatError: If the CSV file is empty or headers are invalid.
    """
    reader = csv.reader(file_handle)
    try:
        header = next(reader)
    except StopIteration:
        msg = "VAT report CSV is empty"
        raise InvalidReportFormatError(msg) from None

    indices = _resolve_indices(header)
    target_dep = departure_country.strip().upper()

    total_rows = 0
    matched_rows: MutableSequence[B2BTransactionRow] = []
    vat_map: dict[str, B2BVATSummary] = defaultdict(lambda: B2BVATSummary(buyer_vat=""))

    for row_idx, row in enumerate(reader, start=2):
        total_rows += 1
        if not row:
            continue

        tx = _parse_transaction_row(row, indices, target_dep, row_idx)
        if tx is None:
            continue

        matched_rows.append(tx)
        if tx.buyer_vat not in vat_map:
            vat_map[tx.buyer_vat].buyer_vat = tx.buyer_vat
        vat_map[tx.buyer_vat].add_transaction(tx)

    summaries = [vat_map[k] for k in sorted(vat_map.keys())]
    return total_rows, matched_rows, summaries


def process_b2b_vat_report(
    report_path: Path,
    departure_country: str = DEFAULT_DEPARTURE_COUNTRY,
) -> B2BProcessingResult:
    """Process an Amazon VAT CSV report and calculate B2B Intra-EU metrics.

    Args:
        report_path: Path to the input Amazon VAT CSV report.
        departure_country: Country of departure to filter (default: "FR").

    Returns:
        B2BProcessingResult containing summaries, transactions, and grand totals.

    Raises:
        ReportNotFoundError: If the report file does not exist.
        ReportPathIsDirectoryError: If report_path is a directory instead of a file.
    """
    if not report_path.exists():
        msg = f"VAT report file not found at: {report_path}"
        raise ReportNotFoundError(msg)

    if report_path.is_dir():
        msg = (
            f"Expected a CSV report file, but received a directory: {report_path}\n"
            f"Please specify the full path to the .csv file."
        )
        raise ReportPathIsDirectoryError(msg)

    with report_path.open(encoding=DEFAULT_ENCODING, newline="") as file_handle:
        total_rows, transactions, summaries = scan_b2b_vat_csv(
            file_handle, departure_country=departure_country
        )

    grand_selling = round(sum(s.total_tax_exclusive_price for s in summaries), 2)
    grand_promo = round(sum(s.total_tax_inclusive_promo for s in summaries), 2)
    grand_diff = round(sum(s.total_net_difference for s in summaries), 2)

    return B2BProcessingResult(
        report_path=report_path,
        departure_country=departure_country.strip().upper(),
        total_rows_scanned=total_rows,
        matched_rows_count=len(transactions),
        unique_vats_count=len(summaries),
        grand_total_selling_price=grand_selling,
        grand_total_promo_amount=grand_promo,
        grand_total_net_difference=grand_diff,
        vat_summaries=summaries,
        transactions=transactions,
    )


def export_b2b_summary_csv(
    vat_summaries: Sequence[B2BVATSummary],
    output_path: Path,
) -> None:
    """Export aggregated B2B metrics grouped by Buyer VAT to a clean CSV file.

    Args:
        vat_summaries: Sequence of aggregated B2BVATSummary records.
        output_path: Destination path for the CSV output.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "BUYER_VAT_NUMBER",
        "DESTINATION_COUNTRIES",
        "TRANSACTION_COUNT",
        "TOTAL_TAX_EXCLUSIVE_PRICE",
        "TOTAL_TAX_INCLUSIVE_PROMO",
        "TOTAL_NET_DIFFERENCE_EUR",
    ]

    rows: list[list[str]] = [header]
    total_trans = 0
    total_price = 0.0
    total_promo = 0.0
    total_diff = 0.0

    for s in vat_summaries:
        total_trans += s.transaction_count
        total_price = round(total_price + s.total_tax_exclusive_price, 2)
        total_promo = round(total_promo + s.total_tax_inclusive_promo, 2)
        total_diff = round(total_diff + s.total_net_difference, 2)

        rows.append([
            s.buyer_vat,
            ", ".join(s.destination_countries),
            str(s.transaction_count),
            f"{s.total_tax_exclusive_price:.2f}",
            f"{s.total_tax_inclusive_promo:.2f}",
            f"{s.total_net_difference:.2f}",
        ])

    rows.append([
        "TOTAL",
        "",
        str(total_trans),
        f"{total_price:.2f}",
        f"{total_promo:.2f}",
        f"{total_diff:.2f}",
    ])

    with output_path.open(mode="w", encoding=DEFAULT_ENCODING, newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL, lineterminator=CSV_LINE_TERMINATOR)
        writer.writerows(rows)


def export_b2b_transactions_csv(
    transactions: Sequence[B2BTransactionRow],
    output_path: Path,
) -> None:
    """Export detailed filtered B2B transaction lines to CSV.

    Args:
        transactions: Sequence of filtered B2BTransactionRow items.
        output_path: Destination path for the CSV output.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "LINE_NUMBER",
        "ORDER_ID",
        "TRANSACTION_TYPE",
        "ORDER_DATE",
        "ASIN",
        "SKU",
        "QTY",
        "BUYER_VAT",
        "SHIP_FROM",
        "SHIP_TO",
        "TAX_EXCLUSIVE_SELLING_PRICE",
        "TAX_INCLUSIVE_PROMO_AMOUNT",
        "NET_DIFFERENCE_EUR",
        "VAT_INVOICE_NUMBER",
        "INVOICE_URL",
        "MARKETPLACE_ID",
    ]

    rows: list[list[str]] = [header]
    rows.extend(
        [
            str(tx.row_index),
            tx.order_id,
            tx.transaction_type,
            tx.order_date,
            tx.asin,
            tx.sku,
            tx.quantity,
            tx.buyer_vat,
            tx.ship_from_country,
            tx.ship_to_country,
            f"{tx.tax_exclusive_selling_price:.2f}",
            f"{tx.tax_inclusive_promo_amount:.2f}",
            f"{tx.net_difference:.2f}",
            tx.invoice_number,
            tx.invoice_url,
            tx.marketplace_id,
        ]
        for tx in transactions
    )

    with output_path.open(mode="w", encoding=DEFAULT_ENCODING, newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL, lineterminator=CSV_LINE_TERMINATOR)
        writer.writerows(rows)


def format_b2b_summary_table(summaries: Sequence[B2BVATSummary]) -> str:
    """Format VAT summary rows into a clean terminal table.

    Args:
        summaries: Sequence of B2BVATSummary objects.

    Returns:
        Formatted multi-line text table.
    """
    if not summaries:
        return "  No matching B2B Intra-EU transactions found.\n"

    header_line = (
        f"  {'Buyer VAT Number':<20} | {'Dest':<8} | {'Count':<6} | "
        f"{'Sales (HT)':<12} | {'Promo (TTC)':<12} | {'Net Diff (€)':<12}"
    )
    divider = "  " + "-" * TABLE_DIVIDER_LENGTH
    table_lines: list[str] = [header_line, divider]

    grand_count = 0
    grand_sales = 0.0
    grand_promo = 0.0
    grand_diff = 0.0

    for s in summaries:
        grand_count += s.transaction_count
        grand_sales = round(grand_sales + s.total_tax_exclusive_price, 2)
        grand_promo = round(grand_promo + s.total_tax_inclusive_promo, 2)
        grand_diff = round(grand_diff + s.total_net_difference, 2)

        dest_str = ",".join(s.destination_countries)
        if len(dest_str) > MAX_DEST_DISPLAY_LENGTH:
            dest_str = dest_str[: MAX_DEST_DISPLAY_LENGTH - 1] + "…"

        line = (
            f"  {s.buyer_vat:<20} | {dest_str:<8} | {s.transaction_count:<6d} | "
            f"€{s.total_tax_exclusive_price:<11.2f} | €{s.total_tax_inclusive_promo:<11.2f} | "
            f"€{s.total_net_difference:<11.2f}"
        )
        table_lines.append(line)

    table_lines.append(divider)
    total_line = (
        f"  {'TOTAL':<20} | {'':<8} | {grand_count:<6d} | "
        f"€{grand_sales:<11.2f} | €{grand_promo:<11.2f} | "
        f"€{grand_diff:<11.2f}"
    )
    table_lines.append(total_line)
    return "\n".join(table_lines)


DEFAULT_AMAZON_DOMAINS: tuple[str, ...] = (
    "amazon.fr",
    "amazon.de",
    "amazon.it",
    "amazon.es",
    "amazon.com.be",
    "sellercentral.amazon.fr",
    "sellercentral.amazon.de",
    "sellercentral.amazon.it",
    "sellercentral.amazon.es",
    "sellercentral.amazon.com.be",
)


def extract_browser_cookies(
    browser: str = "chrome",
    domains: Sequence[str] = DEFAULT_AMAZON_DOMAINS,
) -> http.cookiejar.CookieJar:
    """Extract Amazon Seller Central session cookies from local browser.

    Args:
        browser: Browser name (chrome, arc, brave, edge, safari, firefox, opera, vivaldi).
        domains: Target domain names to search cookies for.

    Returns:
        CookieJar containing extracted browser cookies.

    Raises:
        UnsupportedBrowserError: If the browser name is unsupported.
    """
    browser_map = {
        "chrome": browser_cookie3.chrome,
        "arc": browser_cookie3.arc,
        "brave": browser_cookie3.brave,
        "edge": browser_cookie3.edge,
        "firefox": browser_cookie3.firefox,
        "safari": browser_cookie3.safari,
        "opera": browser_cookie3.opera,
        "vivaldi": browser_cookie3.vivaldi,
        "chromium": browser_cookie3.chromium,
    }

    loader = browser_map.get(browser.lower().strip())
    if loader is None:
        valid_opts = ", ".join(sorted(browser_map.keys()))
        msg = f"Unsupported browser '{browser}'. Valid options: {valid_opts}"
        raise UnsupportedBrowserError(msg)

    jar = http.cookiejar.CookieJar()
    for domain in domains:
        try:
            domain_jar = loader(domain_name=domain)
            for cookie in domain_jar:
                jar.set_cookie(cookie)
        except (browser_cookie3.BrowserCookieError, OSError, ValueError) as err:
            logger.debug("Failed extracting cookies from %s for %s: %s", browser, domain, err)

    return jar


def _download_single_invoice(
    opener: urllib.request.OpenerDirector,
    tx: B2BTransactionRow,
    *,
    output_dir: Path,
    user_agent: str,
    cookie_string: str | None,
    browser: str,
) -> Path | None:
    """Download a single transaction invoice and save to output_dir if authenticated."""
    if not (tx.invoice_url.startswith("https://") or tx.invoice_url.startswith("http://")):
        logger.warning("Skipping invalid invoice URL scheme for order %s", tx.order_id)
        return None

    doc_filename = f"{tx.invoice_number}.pdf" if tx.invoice_number else f"invoice_{tx.order_id}.pdf"
    target_file = output_dir / doc_filename

    req = urllib.request.Request(  # ruff: ignore[suspicious-url-open-usage]
        tx.invoice_url,
        headers={"User-Agent": user_agent},
    )
    if cookie_string:
        req.add_header("Cookie", cookie_string)

    try:
        with opener.open(req, timeout=30) as response:
            content_type = response.headers.get("Content-Type", "")
            final_url = response.geturl()
            body = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Failed downloading invoice for order %s: %s", tx.order_id, exc)
        return None

    if "signin" in final_url or "ap/signin" in final_url:
        logger.warning(
            "Auth required for order %s (%s). Please log in via %s.",
            tx.order_id,
            doc_filename,
            browser,
        )
        return None

    if body.startswith(b"%PDF") or "application/pdf" in content_type:
        target_file.write_bytes(body)
        return target_file

    logger.warning(
        "Non-PDF content for order %s (%s). Type: %s. Not authenticated.",
        tx.order_id,
        doc_filename,
        content_type,
    )
    return None


def _build_http_opener(
    *,
    browser: str,
    cookie_string: str | None,
    cookie_file: Path | None,
    progress_callback: InvoiceProgressCallback | None,
) -> urllib.request.OpenerDirector:
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
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    if cookie_string:
        if progress_callback:
            progress_callback(
                InvoiceDownloadEvent(
                    phase=DownloadPhase.COOKIES,
                    message="Using provided cookie header string",
                )
            )
        return urllib.request.build_opener()

    if progress_callback:
        progress_callback(
            InvoiceDownloadEvent(
                phase=DownloadPhase.COOKIES,
                message=f"Extracting cookies from browser: '{browser}'",
            )
        )
    extracted_jar = extract_browser_cookies(browser=browser)
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(extracted_jar))


def download_invoices_for_report(
    report_path: Path,
    output_dir: Path,
    *,
    departure_country: str = DEFAULT_DEPARTURE_COUNTRY,
    browser: str = "chrome",
    cookie_string: str | None = None,
    cookie_file: Path | None = None,
    progress_callback: InvoiceProgressCallback | None = None,
) -> InvoiceDownloadResult:
    """Scan report, filter B2B cross-border transactions, and download invoice PDFs."""
    if progress_callback:
        progress_callback(
            InvoiceDownloadEvent(
                phase=DownloadPhase.SCANNING,
                filename=report_path.name,
                message=f"Scanning report: {report_path.name}",
            )
        )

    result = process_b2b_vat_report(report_path, departure_country=departure_country)
    valid_transactions = [
        tx for tx in result.transactions if tx.invoice_url and tx.invoice_url.strip()
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    total_count = len(valid_transactions)

    if not valid_transactions:
        if progress_callback:
            progress_callback(
                InvoiceDownloadEvent(
                    phase=DownloadPhase.COMPLETED,
                    total=0,
                    message="No matching B2B transactions with invoice URLs found.",
                )
            )
        return InvoiceDownloadResult(
            total_invoices_found=0,
            successful_downloads=0,
            failed_downloads=0,
        )

    opener = _build_http_opener(
        browser=browser,
        cookie_string=cookie_string,
        cookie_file=cookie_file,
        progress_callback=progress_callback,
    )

    if progress_callback:
        progress_callback(
            InvoiceDownloadEvent(
                phase=DownloadPhase.STARTING,
                total=total_count,
                message=str(output_dir),
            )
        )

    successful = 0
    failed = 0
    downloaded_paths: list[Path] = []
    user_agent = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )

    for idx, tx in enumerate(valid_transactions, start=1):
        doc_name = f"{tx.invoice_number}.pdf" if tx.invoice_number else f"invoice_{tx.order_id}.pdf"
        if progress_callback:
            progress_callback(
                InvoiceDownloadEvent(
                    phase=DownloadPhase.DOWNLOADING,
                    current=idx,
                    total=total_count,
                    order_id=tx.order_id,
                    filename=doc_name,
                )
            )

        saved_path = _download_single_invoice(
            opener,
            tx,
            output_dir=output_dir,
            user_agent=user_agent,
            cookie_string=cookie_string,
            browser=browser,
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
                        total=total_count,
                        order_id=tx.order_id,
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
                        total=total_count,
                        order_id=tx.order_id,
                        filename=doc_name,
                    )
                )

    return InvoiceDownloadResult(
        total_invoices_found=total_count,
        successful_downloads=successful,
        failed_downloads=failed,
        downloaded_files=downloaded_paths,
    )


def _handle_process_command(args: argparse.Namespace) -> None:
    """Handle CLI process subcommand execution."""
    try:
        result = process_b2b_vat_report(args.report, departure_country=args.departure)
    except B2BVATError as err:
        print(f"\n  [ERROR] Processing failed: {err}\n", file=sys.stderr)
        sys.exit(1)
    except OSError:
        logger.exception("Unexpected system error during processing")
        sys.exit(1)

    print("\n" + "=" * HEADER_BANNER_LENGTH)
    print("  AMAZON B2B INTRA-EU VAT REPORT SUMMARY")
    print("=" * HEADER_BANNER_LENGTH)
    print(f"  Input Report:       {result.report_path}")
    dep = result.departure_country
    print(f"  Departure Country:  {dep} (Shipping to Non-{dep})")
    print(f"  Total Scanned Rows: {result.total_rows_scanned:,}")
    print(f"  Matched B2B Rows:   {result.matched_rows_count:,}")
    print(f"  Unique Buyer VATs:  {result.unique_vats_count:,}")
    print(f"  Total Net Sales HT: €{result.grand_total_selling_price:,.2f}")
    print(f"  Total Promos TTC:   €{result.grand_total_promo_amount:,.2f}")
    print(f"  Total Net Diff:     €{result.grand_total_net_difference:,.2f}")
    print("-" * HEADER_BANNER_LENGTH)
    print("  AGGREGATED VAT SUMMARY:")
    print(format_b2b_summary_table(result.vat_summaries))
    print("=" * HEADER_BANNER_LENGTH + "\n")

    if args.output_summary:
        export_b2b_summary_csv(result.vat_summaries, args.output_summary)
        print(f"  [SAVED] VAT summary exported to: {args.output_summary}")

    if args.output_transactions:
        export_b2b_transactions_csv(result.transactions, args.output_transactions)
        print(f"  [SAVED] Transactions exported to: {args.output_transactions}")


def _cli_progress_callback(event: InvoiceDownloadEvent) -> None:
    """Format and print real-time progress events to standard output."""
    if event.phase == DownloadPhase.SCANNING:
        print(f"\n  [1/3] Scanning VAT report: {event.filename}...", flush=True)
    elif event.phase == DownloadPhase.COOKIES:
        print(f"  [2/3] {event.message}...", flush=True)
    elif event.phase == DownloadPhase.STARTING:
        print(f"  [3/3] Downloading {event.total} invoice(s) into: {event.message}\n", flush=True)
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


def _handle_download_invoices_command(args: argparse.Namespace) -> None:
    """Handle CLI download-invoices subcommand execution."""
    target_out_dir = args.output_dir or (args.report.parent / f"{args.report.stem}_invoices")
    try:
        dl_res = download_invoices_for_report(
            report_path=args.report,
            output_dir=target_out_dir,
            departure_country=args.departure,
            browser=args.browser,
            cookie_string=args.cookies,
            cookie_file=args.cookie_file,
            progress_callback=_cli_progress_callback,
        )
    except B2BVATError as err:
        print(f"\n  [ERROR] {err}\n", file=sys.stderr)
        sys.exit(1)
    except OSError:
        logger.exception("Unexpected system error during invoice downloading")
        sys.exit(1)

    print("\n" + "=" * HEADER_BANNER_LENGTH)
    print("  AMAZON B2B INVOICE DOWNLOAD SUMMARY")
    print("=" * HEADER_BANNER_LENGTH)
    print(f"  Total Invoices Found: {dl_res.total_invoices_found}")
    print(f"  Successfully Saved:   {dl_res.successful_downloads}")
    print(f"  Failed / Skipped:     {dl_res.failed_downloads}")
    print(f"  Output Directory:     {target_out_dir}")
    print("=" * HEADER_BANNER_LENGTH + "\n")


def main() -> None:
    """CLI entry point for b2b-vat."""
    logging.basicConfig(level=logging.INFO, format="  [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(
        prog="b2b-vat",
        description="Amazon B2B Intra-EU VAT Report & Invoice Automation CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Subcommand")

    proc = subparsers.add_parser("process", help="Filter and aggregate B2B transactions")
    proc.add_argument("-r", "--report", type=Path, required=True, help="Amazon VAT CSV report")
    proc.add_argument("-d", "--departure", type=str, default=DEFAULT_DEPARTURE_COUNTRY)
    proc.add_argument("-s", "--output-summary", type=Path, default=None)
    proc.add_argument("-t", "--output-transactions", type=Path, default=None)

    dl = subparsers.add_parser("download-invoices", help="Download B2B invoice PDFs to directory")
    dl.add_argument("-r", "--report", type=Path, required=True, help="Amazon VAT CSV report")
    dl.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Destination directory (default: <report_name>_invoices/)",
    )
    dl.add_argument("-d", "--departure", type=str, default=DEFAULT_DEPARTURE_COUNTRY)
    browser_help = "Browser for cookies (chrome, arc, brave, edge, safari, firefox)"
    dl.add_argument("-b", "--browser", type=str, default="chrome", help=browser_help)
    dl.add_argument("--cookies", type=str, default=None, help="Raw cookie header override")
    dl.add_argument("--cookie-file", type=Path, default=None, help="Path to cookie file")

    args = parser.parse_args()
    if args.command == "process":
        _handle_process_command(args)
    elif args.command == "download-invoices":
        _handle_download_invoices_command(args)


if __name__ == "__main__":
    main()
