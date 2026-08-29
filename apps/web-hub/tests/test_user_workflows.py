"""End-to-End User Workflow & WebAssembly Bridge Contract Tests."""

from __future__ import annotations

import importlib.resources
import importlib.util
import json
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


# TODO: Extract the output in a dataclass, same for other tuple output
@pytest.fixture
def prepared_inputs(tmp_path: Path) -> tuple[Path, Path]:
    """Prepare copies of sample report and catalog in isolated directory."""
    report = tmp_path / "report.csv"
    catalog = tmp_path / "catalog.xlsx"
    report.write_bytes(SAMPLE_REPORT_PATH.read_bytes())
    catalog.write_bytes(PRICE_CATALOG_PATH.read_bytes())
    return report, catalog


def test_single_vat_report_web_workflow(prepared_inputs: tuple[Path, Path]) -> None:
    """Verify single VAT report WebAssembly execution returns complete valid JSON payload."""
    report_file, catalog_file = prepared_inputs
    data = json.loads(bridge.run_vat_single(str(report_file), str(catalog_file)))
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
