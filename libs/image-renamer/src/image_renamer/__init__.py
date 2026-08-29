"""
Amazon ASIN Image Duplicator & Renamer Package
"""

from __future__ import annotations

from image_renamer.engine import (
    DuplicationResult,
    duplicate_images,
    extract_suffix,
    generate_image_manifest,
    main,
    parse_asins,
)

__version__: str = "0.2.0"
__all__: list[str] = [
    "DuplicationResult",
    "duplicate_images",
    "extract_suffix",
    "generate_image_manifest",
    "main",
    "parse_asins",
]
