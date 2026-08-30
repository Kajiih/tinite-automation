"""Tests for Amazon ASIN Image Duplicator & Renamer Engine."""

from __future__ import annotations

import re
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from image_renamer.engine import (
    duplicate_images,
    extract_suffix,
    generate_image_manifest,
    parse_asins,
    parse_asins_from_text,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


@pytest.mark.parametrize(
    ("input_filename", "expected_suffix", "expected_extension"),
    [
        ("MAIN.jpg", "MAIN", "jpg"),
        ("PT01.png", "PT01", "png"),
        ("01.jpeg", "01", "jpeg"),
        ("lifestyle_photo.webp", "lifestyle_photo", "webp"),
        ("B089WJC6Z4.MAIN.jpg", "MAIN", "jpg"),  # Strips 10-char ASIN with dot
        ("B089WJC6Z4_PT02.png", "PT02", "png"),  # Strips 10-char ASIN with underscore
        ("B000000000.PT01.TIFF", "PT01", "tiff"),  # Uppercase extension
        ("SWATCH.gif", "SWATCH", "gif"),
    ],
)
def test_extract_suffix_patterns(
    input_filename: str,
    expected_suffix: str,
    expected_extension: str,
) -> None:
    """Verify suffix extraction across standard, prefixed, and case-varying image names."""
    assert extract_suffix(input_filename) == (expected_suffix, expected_extension)


@pytest.mark.parametrize(
    ("raw_input", "expected_asins"),
    [
        (
            "B089WJC6Z4, B089N1ND4V, B07XYZ1234",
            ["B089WJC6Z4", "B089N1ND4V", "B07XYZ1234"],
        ),
        (
            "b089wjc6z4\nB089WJC6Z4\nb089wjc6z4",  # Deduplication + Uppercase
            ["B089WJC6Z4"],
        ),
        (
            "asin\nB011111111; B022222222\tB033333333",  # Strips header + various delimiters
            ["B011111111", "B022222222", "B033333333"],
        ),
    ],
)
def test_parse_asins_from_text_delimiters(
    raw_input: str,
    expected_asins: list[str],
) -> None:
    """Verify parsing across various delimiters, case normalizations, and duplicate entries."""
    assert parse_asins_from_text(raw_input) == expected_asins


@pytest.mark.parametrize("file_format", ["txt", "csv", "xlsx"])
def test_parse_asins_from_different_file_formats(
    fake_asin_file_factory: Callable[[Sequence[str], str], Path],
    file_format: str,
) -> None:
    """Verify parsing ASINs across .txt, .csv, and .xlsx files."""
    expected_asins = ["B089WJC6Z4", "B089N1ND4V", "B07XYZ1234"]
    file_path = fake_asin_file_factory(expected_asins, file_format)

    assert parse_asins(file_path) == expected_asins


def test_generate_image_manifest_cartesian_product() -> None:
    """Verify manifest generates Cartesian product of templates x ASINs."""
    images = ["MAIN.jpg", "PT01.png"]
    asins = ["B089WJC6Z4", "B089N1ND4V"]

    assert [item.target_relative_path for item in generate_image_manifest(images, asins)] == [
        "B089WJC6Z4/B089WJC6Z4.MAIN.jpg",
        "B089WJC6Z4/B089WJC6Z4.PT01.png",
        "B089N1ND4V/B089N1ND4V.MAIN.jpg",
        "B089N1ND4V/B089N1ND4V.PT01.png",
    ]


@pytest.mark.parametrize("use_hardlinks", [False, True])
def test_duplicate_images_execution(
    tmp_path: Path,
    sample_template_images_dir: Path,
    *,
    use_hardlinks: bool,
) -> None:
    """Verify creating folders and copies/hardlinks for each ASIN."""
    output_dir = tmp_path / f"output_{'hardlink' if use_hardlinks else 'copy'}"

    result = duplicate_images(
        images_dir=sample_template_images_dir,
        asins=["B089WJC6Z4", "B089N1ND4V"],
        output_dir=output_dir,
        use_hardlinks=use_hardlinks,
    )

    assert result.total_created_files == 8
    assert (output_dir / "B089WJC6Z4" / "B089WJC6Z4.MAIN.jpg").is_file()
    assert (output_dir / "B089WJC6Z4" / "B089WJC6Z4.PT01.png").is_file()
    assert (output_dir / "B089N1ND4V" / "B089N1ND4V.MAIN.jpg").is_file()
    assert (output_dir / "B089N1ND4V" / "B089N1ND4V.PT01.png").is_file()


def test_image_renamer_cli_execution(
    tmp_path: Path,
    sample_template_images_dir: Path,
    fake_asin_file_factory: Callable[[Sequence[str], str], Path],
) -> None:
    """Verify image renamer CLI execution with clear separation of concerns."""
    asins_file = fake_asin_file_factory(["B011111111", "B022222222"], "txt")
    output_dir = tmp_path / "cli_out"
    script_path = Path(__file__).resolve().parent.parent / "src" / "image_renamer" / "engine.py"

    cmd = [
        sys.executable,
        str(script_path),
        "--images",
        str(sample_template_images_dir),
        "--asins",
        str(asins_file),
        "--output",
        str(output_dir),
    ]

    exec_result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        cmd, capture_output=True, text=True, check=True
    )

    assert exec_result.returncode == 0
    assert "AMAZON ASIN IMAGE DUPLICATOR" in exec_result.stdout


def test_unsupported_file_extension_raises_value_error(tmp_path: Path) -> None:
    """Unsupported ASIN file extension raises ValueError."""
    bad_file = tmp_path / "asins.pdf"
    bad_file.write_text("dummy", encoding="utf-8")
    with pytest.raises(ValueError, match=re.escape("Unsupported ASIN file format: .pdf")):
        parse_asins(bad_file)


def test_missing_asin_file_raises_error(tmp_path: Path) -> None:
    """Non-existent ASIN file path raises FileNotFoundError."""
    missing = tmp_path / "non_existent_asins.txt"
    with pytest.raises(FileNotFoundError):
        parse_asins(missing)


def test_duplicate_images_missing_images_dir_raises_error(tmp_path: Path) -> None:
    """Non-existent template image directory raises NotADirectoryError."""
    missing_dir = tmp_path / "non_existent_images"
    out_dir = tmp_path / "out"
    with pytest.raises(NotADirectoryError):
        duplicate_images(missing_dir, ["B011111111"], out_dir)


def test_generate_image_manifest_empty_inputs() -> None:
    """Empty ASINs or template files yield empty manifest."""
    assert generate_image_manifest([], ["B011111111"]) == []
    assert generate_image_manifest(["template.jpg"], []) == []
