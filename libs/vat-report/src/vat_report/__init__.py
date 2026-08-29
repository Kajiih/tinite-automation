"""
Amazon VAT Report Automation Package
"""

from __future__ import annotations

from vat_report.engine import (
    BatchProcessingResult,
    ColumnHeader,
    FileProcessingResult,
    RouteKey,
    RouteMetric,
    TransactionType,
    export_country_summary,
    load_price_catalog,
    main,
    process_batch,
    process_vat_report,
)

__version__: str = "0.2.0"
__all__: list[str] = [
    "BatchProcessingResult",
    "ColumnHeader",
    "FileProcessingResult",
    "RouteKey",
    "RouteMetric",
    "TransactionType",
    "export_country_summary",
    "load_price_catalog",
    "main",
    "process_batch",
    "process_vat_report",
]
