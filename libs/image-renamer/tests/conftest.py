"""Shared Pytest Fixtures and Factories for ASIN Image Duplicator Tests."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

PACKAGE_DIR: Path = Path(__file__).resolve().parent.parent


@pytest.fixture
def sample_asins_file_path() -> Path:
    """Path to sample ASINs text file."""
    return PACKAGE_DIR / "example_data" / "sample_asins.txt"


@pytest.fixture
def sample_template_images_dir(tmp_path: Path) -> Path:
    """Fixture providing a directory populated with sample template images."""
    img_dir = tmp_path / "template_images"
    img_dir.mkdir()

    (img_dir / "MAIN.jpg").write_bytes(b"sample-main-image-bytes")
    (img_dir / "PT01.png").write_bytes(b"sample-pt01-image-bytes")
    (img_dir / "02.webp").write_bytes(b"sample-02-webp-image-bytes")
    (img_dir / "lifestyle.tif").write_bytes(b"sample-tif-image-bytes")
    (img_dir / "notes.txt").write_bytes(b"ignored-non-image-file")

    return img_dir


@pytest.fixture
def fake_asin_file_factory(tmp_path: Path) -> Callable[[Sequence[str], str], Path]:
    """Factory fixture to create sample ASIN files in .txt, .csv, or .xlsx format."""

    def _create_file(asins: Sequence[str], file_type: str = "txt") -> Path:
        if file_type == "txt":
            path = tmp_path / "asins.txt"
            path.write_text("\n".join(asins), encoding="utf-8-sig")
            return path
        if file_type == "csv":
            path = tmp_path / "asins.csv"
            with path.open(mode="w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Product Title", "ASIN", "Category"])
                for idx, asin in enumerate(asins, 1):
                    writer.writerow([f"Product {idx}", asin, "Electronics"])
            return path
        if file_type == "xlsx":
            import openpyxl

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["Title", "ASIN", "Price"])
            for idx, asin in enumerate(asins, 1):
                ws.append([f"Item {idx}", asin, 19.99])
            path = tmp_path / "asins.xlsx"
            wb.save(path)
            wb.close()
            return path
        msg = f"Unsupported test file type: {file_type}"
        raise ValueError(msg)

    return _create_file
