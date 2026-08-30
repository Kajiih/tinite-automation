"""End-to-End User Workflow & WebAssembly Bridge Contract Tests."""

from __future__ import annotations

import csv
import importlib.resources
import importlib.util
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from web_server.updater import resolve_workspace_root

if TYPE_CHECKING:
    from pathlib import Path

# Dynamically import bridge module
BRIDGE_FILE = importlib.resources.files("web_server") / "static" / "py" / "bridge.py"
spec = importlib.util.spec_from_file_location("bridge", str(BRIDGE_FILE))
if spec is None or spec.loader is None:
    msg = f"Could not load bridge module from {BRIDGE_FILE}"
    raise ImportError(msg)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

REPO_ROOT: Path = resolve_workspace_root()
SAMPLE_REPORT_PATH: Path = (
    REPO_ROOT / "libs" / "vat-report" / "example_data" / "sample_vat_report.csv"
)
PRICE_CATALOG_PATH: Path = (
    REPO_ROOT / "libs" / "vat-report" / "example_data" / "amazon_asin_prix_achat_cogs_maj.xlsx"
)


@dataclass(slots=True)
class WorkflowPreparedInputs:
    """Encapsulates prepared VAT report and price catalog sample file paths."""

    report_path: Path
    catalog_path: Path


@pytest.fixture
def prepared_inputs(tmp_path: Path) -> WorkflowPreparedInputs:
    """Prepare copies of sample report and catalog in isolated directory."""
    report = tmp_path / "report.csv"
    catalog = tmp_path / "catalog.xlsx"
    report.write_bytes(SAMPLE_REPORT_PATH.read_bytes())
    catalog.write_bytes(PRICE_CATALOG_PATH.read_bytes())
    return WorkflowPreparedInputs(report_path=report, catalog_path=catalog)


def test_single_vat_report_web_workflow(prepared_inputs: WorkflowPreparedInputs) -> None:
    """Verify single VAT report WebAssembly execution returns complete valid JSON payload."""
    data = json.loads(
        bridge.run_vat_single(str(prepared_inputs.report_path), str(prepared_inputs.catalog_path))
    )
    routes = data.pop("routes")

    assert data == {
        "mode": "single",
        "total_rows": 100,
        "fc_transfer_count": 40,
        "fc_transfer_updated": 40,
        "total_value_added": 234.99,
        "missing_asins": [],
    }
    assert len(routes) == 14


def test_batch_vat_report_web_workflow(tmp_path: Path) -> None:
    """Verify batch VAT reports WebAssembly execution returns consolidated JSON payload."""
    batch_dir = tmp_path / "batch_reports"
    batch_dir.mkdir()

    (batch_dir / "january.csv").write_bytes(SAMPLE_REPORT_PATH.read_bytes())
    (batch_dir / "february.csv").write_bytes(SAMPLE_REPORT_PATH.read_bytes())
    catalog_copy = tmp_path / "catalog.xlsx"
    catalog_copy.write_bytes(PRICE_CATALOG_PATH.read_bytes())

    data = json.loads(bridge.run_vat_batch(str(batch_dir), str(catalog_copy)))
    routes = data.pop("routes")
    files = data.pop("files")

    assert data == {
        "mode": "batch",
        "files_count": 2,
        "total_rows": 200,
        "fc_transfer_count": 80,
        "fc_transfer_updated": 80,
        "total_value_added": 469.98,
        "missing_asins": [],
    }
    assert len(files) == 2
    assert len(routes) == 14


@pytest.mark.parametrize(
    ("raw_input", "expected_asins"),
    [
        (
            "b089wjc6z4, B089N1ND4V\nB089WJC6Z4\nB07XYZ1234",
            ["B089WJC6Z4", "B089N1ND4V", "B07XYZ1234"],
        ),
        ("B011111111; B022222222\nB033333333", ["B011111111", "B022222222", "B033333333"]),
    ],
)
def test_parse_asins_web_workflow(raw_input: str, expected_asins: list[str]) -> None:
    """Verify ASIN string parsing and deduplication returns clean JSON array."""
    assert json.loads(bridge.run_parse_asins(raw_input)) == expected_asins


def test_generate_image_manifest_web_workflow() -> None:
    """Verify image manifest generation returns structured JSON tree."""
    image_names = json.dumps(["MAIN.jpg", "PT01.png"])
    asins = json.dumps(["B089WJC6Z4", "B089N1ND4V"])

    manifest = json.loads(bridge.run_generate_image_manifest(image_names, asins))
    assert [item["target_relative_path"] for item in manifest] == [
        "B089WJC6Z4/B089WJC6Z4.MAIN.jpg",
        "B089WJC6Z4/B089WJC6Z4.PT01.png",
        "B089N1ND4V/B089N1ND4V.MAIN.jpg",
        "B089N1ND4V/B089N1ND4V.PT01.png",
    ]


def test_b2b_vat_web_workflow(tmp_path: Path) -> None:
    """Verify B2B Intra-EU VAT WebAssembly execution returns valid JSON response."""
    test_csv = tmp_path / "test_vat.csv"
    headers = [
        "Order ID",
        "Buyer Tax Registration",
        "Ship From Country",
        "Ship To Country",
        "Tax Reporting Scheme",
        "OUR_PRICE Tax Amount",
        "OUR_PRICE Tax Exclusive Selling Price",
        "OUR_PRICE Tax Inclusive Promo Amount",
    ]
    rows = [
        headers,
        ["ORD-1", "BE0123456789", "FR", "BE", "", "0.00", "50.00", "-5.00"],
        ["ORD-2", "BE0123456789", "FR", "BE", "", "0.00", "-20.00", "0.00"],
        ["ORD-3", "DE987654321", "FR", "DE", "", "0.00", "30.00", "0.00"],
    ]
    with test_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    summary_out = tmp_path / "summary.csv"
    tx_out = tmp_path / "tx.csv"

    data = json.loads(
        bridge.run_b2b_vat(
            str(test_csv),
            departure_country="FR",
            summary_output_filename=str(summary_out),
            transactions_output_filename=str(tx_out),
        )
    )

    assert data["departure_country"] == "FR"
    assert data["total_rows_scanned"] == 3
    assert data["matched_rows_count"] == 3
    assert data["unique_vats_count"] == 2
    assert data["grand_total_selling_price"] == pytest.approx(60.00)
    assert data["grand_total_promo_amount"] == pytest.approx(-5.00)
    assert data["grand_total_net_difference"] == pytest.approx(55.00)
    assert len(data["vat_summaries"]) == 2
    assert len(data["transactions"]) == 3
    assert summary_out.exists()
    assert tx_out.exists()


def test_b2b_vat_web_workflow_missing_headers(tmp_path: Path) -> None:
    """Verify bridge raises ValueError on CSV missing required columns."""
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("Col1,Col2\nVal1,Val2\n", encoding="utf-8")

    expected_msg = "Invalid Amazon VAT Report format: missing required columns"
    with pytest.raises(ValueError, match=expected_msg):
        bridge.run_b2b_vat(str(bad_csv))
