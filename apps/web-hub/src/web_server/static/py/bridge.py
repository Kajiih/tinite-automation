"""Pyodide WebAssembly Bridge Module.

Provides strongly typed JSON-serialized execution wrappers for vat_report and image_renamer
called by JavaScript in the browser.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypedDict

from image_renamer.engine import generate_image_manifest, parse_asins
from vat_report.engine import load_price_catalog, process_batch, process_vat_report


class RoutePayload(TypedDict):
    """Route data transfer metric payload."""

    departure: str
    arrival: str
    transfers: int
    quantity: float
    amount: float


class FileSummaryPayload(TypedDict):
    """Summary of a single report within a batch execution."""

    filename: str
    total_rows: int
    fc_transfer_count: int
    fc_transfer_updated: int
    total_value_added: float
    missing_asins: list[str]
    routes: list[RoutePayload]


class SingleReportResponse(TypedDict):
    """Execution response payload for single report processing."""

    mode: Literal["single"]
    total_rows: int
    fc_transfer_count: int
    fc_transfer_updated: int
    total_value_added: float
    missing_asins: list[str]
    routes: list[RoutePayload]


class BatchReportResponse(TypedDict):
    """Execution response payload for batch report processing."""

    mode: Literal["batch"]
    files_count: int
    total_rows: int
    fc_transfer_count: int
    fc_transfer_updated: int
    total_value_added: float
    missing_asins: list[str]
    routes: list[RoutePayload]
    files: list[FileSummaryPayload]


class ImageManifestEntry(TypedDict):
    """Manifest item representing a generated target image file."""

    asin: str
    source_filename: str
    target_folder: str
    target_filename: str
    target_relative_path: str


def run_vat_single(
    report_filename: str, catalog_filename: str, output_filename: str | None = None
) -> str:
    """Process a single VAT report and return strongly typed JSON summary."""
    price_catalog = load_price_catalog(Path(catalog_filename))
    out_path = (
        Path(output_filename) if output_filename else Path(report_filename).parent / "output.csv"
    )
    result = process_vat_report(
        Path(report_filename),
        price_catalog,
        out_path,
        export_summary=True,
    )

    routes: list[RoutePayload] = [
        {
            "departure": key.departure_country,
            "arrival": key.arrival_country,
            "transfers": metric.transfer_count,
            "quantity": metric.total_quantity,
            "amount": metric.total_amount_eur,
        }
        for key, metric in sorted(result.route_statistics.items())
    ]

    response: SingleReportResponse = {
        "mode": "single",
        "total_rows": result.total_rows,
        "fc_transfer_count": result.fc_transfer_count,
        "fc_transfer_updated": result.fc_transfer_updated,
        "total_value_added": result.total_value_added,
        "missing_asins": list(result.missing_asins),
        "routes": routes,
    }

    return json.dumps(response)


def run_vat_batch(input_dir_name: str, catalog_filename: str) -> str:
    """Process a folder of VAT reports and return strongly typed consolidated JSON summary."""
    batch_result = process_batch(
        Path(input_dir_name),
        Path(catalog_filename),
    )

    consolidated_routes: list[RoutePayload] = [
        {
            "departure": key.departure_country,
            "arrival": key.arrival_country,
            "transfers": metric.transfer_count,
            "quantity": metric.total_quantity,
            "amount": metric.total_amount_eur,
        }
        for key, metric in sorted(batch_result.consolidated_routes.items())
    ]

    files_data: list[FileSummaryPayload] = []
    for file_result in batch_result.file_results:
        file_routes: list[RoutePayload] = [
            {
                "departure": key.departure_country,
                "arrival": key.arrival_country,
                "transfers": metric.transfer_count,
                "quantity": metric.total_quantity,
                "amount": metric.total_amount_eur,
            }
            for key, metric in sorted(file_result.route_statistics.items())
        ]
        files_data.append({
            "filename": file_result.report_path.name,
            "total_rows": file_result.total_rows,
            "fc_transfer_count": file_result.fc_transfer_count,
            "fc_transfer_updated": file_result.fc_transfer_updated,
            "total_value_added": file_result.total_value_added,
            "missing_asins": list(file_result.missing_asins),
            "routes": file_routes,
        })

    response: BatchReportResponse = {
        "mode": "batch",
        "files_count": batch_result.files_count,
        "total_rows": batch_result.grand_total_rows,
        "fc_transfer_count": batch_result.grand_fc_transfers,
        "fc_transfer_updated": batch_result.grand_fc_updated,
        "total_value_added": batch_result.grand_value_added,
        "missing_asins": sorted(batch_result.all_missing_asins),
        "routes": consolidated_routes,
        "files": files_data,
    }

    return json.dumps(response)


def run_parse_asins(source_text: str) -> str:
    """Parse, clean, and deduplicate ASINs from text and return JSON array."""
    asins: list[str] = parse_asins(source_text)
    return json.dumps(asins)


def run_generate_image_manifest(image_names_json: str, asins_json: str) -> str:
    """Generate strongly typed image manifest for target ASINs and return JSON array."""
    parsed_images = json.loads(image_names_json)
    image_names: list[str] = (
        [str(x) for x in parsed_images] if isinstance(parsed_images, list) else []
    )
    parsed_asins = json.loads(asins_json)
    asins: list[str] = [str(x) for x in parsed_asins] if isinstance(parsed_asins, list) else []
    manifest = generate_image_manifest(image_names, asins)

    payload: list[ImageManifestEntry] = [
        {
            "asin": item.asin,
            "source_filename": item.source_filename,
            "target_folder": item.target_folder,
            "target_filename": item.target_filename,
            "target_relative_path": item.target_relative_path,
        }
        for item in manifest
    ]

    return json.dumps(payload)
