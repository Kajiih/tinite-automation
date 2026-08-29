"""
Amazon VAT Report Automation Package
"""

from __future__ import annotations

from amazon_vat_automation.process_report import (
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
    serve_web,
)

__version__: str = "0.1.0"
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
    "serve_web",
]
