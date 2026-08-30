"""Shared fixtures for invoice downloader testing."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from b2b_vat.engine import ColumnHeader

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

WORKSPACE_ROOT: Path = Path(__file__).resolve().parent.parent.parent.parent


@pytest.fixture
def test_tax_report_path() -> Path:
    """Path to the workspace tax report CSV if present."""
    return WORKSPACE_ROOT / "taxReport_Juillet 2026.csv"


@pytest.fixture
def fake_b2b_vat_csv_factory(tmp_path: Path) -> Callable[[Sequence[Mapping[str, str]]], Path]:
    """Factory fixture to build synthetic Amazon VAT CSV reports for testing."""

    def _create_report(
        custom_rows: Sequence[Mapping[str, str]], filename: str = "synthetic_b2b_vat.csv"
    ) -> Path:
        headers = [col.value for col in ColumnHeader]
        csv_path = tmp_path / filename
        rows_to_write = [headers]

        for custom in custom_rows:
            row: list[str] = []
            for col in ColumnHeader:
                key = col.value
                val = custom.get(key, "")
                row.append(val)
            rows_to_write.append(row)

        with csv_path.open(mode="w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
            writer.writerows(rows_to_write)

        return csv_path

    return _create_report
