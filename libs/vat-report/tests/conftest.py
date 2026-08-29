"""Shared Pytest Fixtures and Fakes for VAT Report Testing."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from vat_report.engine import ColumnHeader, TransactionType, load_price_catalog

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

PACKAGE_DIR: Path = Path(__file__).resolve().parent.parent


@pytest.fixture
def sample_vat_report_path() -> Path:
    """Path to the golden sample Amazon VAT CSV report."""
    return PACKAGE_DIR / "example_data" / "sample_vat_report.csv"


@pytest.fixture
def price_catalog_path() -> Path:
    """Path to the sample Excel price catalog (.xlsx)."""
    return PACKAGE_DIR / "example_data" / "amazon_asin_prix_achat_cogs_maj.xlsx"


@pytest.fixture
def price_catalog(price_catalog_path: Path) -> dict[str, float]:
    """Pre-loaded ASIN -> price mapping fixture."""
    return dict(load_price_catalog(price_catalog_path))


@pytest.fixture
def fake_vat_csv_factory(tmp_path: Path) -> Callable[[Sequence[dict[str, str]]], Path]:
    """Factory fixture to build synthetic Amazon VAT CSV reports for targeted behavioral testing."""

    def _create_report(
        custom_rows: Sequence[dict[str, str]], filename: str = "synthetic_vat.csv"
    ) -> Path:
        headers = (
            [
                "TRANSACTION_EVENT_ID",
                "ACTIVITY_PERIOD",
                "TAX_CALCULATION_DATE",
                "TRANSACTION_COMPLETE_DATE",
                "ACTIVITY_TYPE",
                ColumnHeader.TRANSACTION_TYPE.value,  # Index 5
                "MERCHANT_SELLER_VAT_NUMBER",
                "BUYER_VAT_NUMBER",
                "TAX_COLLECTION_RESPONSIBILITY",
                "TRANSACTION_SELLER_ROLE",
                "SELLER_TAX_REGISTRATION_JURISDICTION",
                "BUYER_TAX_REGISTRATION_JURISDICTION",
                "MARKETPLACE_VAT_INVOICE_NUMBER",
                ColumnHeader.ASIN.value,  # Index 13
                "SKU",
                "ITEM_DESCRIPTION",
                ColumnHeader.QUANTITY.value,  # Index 16
                "ITEM_MANUFACTURE_COUNTRY",
                "TAXABLE_JURISDICTION",
                ColumnHeader.COST_PRICE_OF_ITEMS.value,  # Index 19
                ColumnHeader.PRICE_OF_ITEMS_AMT_VAT_EXCL.value,  # Index 20
                "PROMO_PRICE_OF_ITEMS_AMT_VAT_EXCL",
                ColumnHeader.TOTAL_PRICE_OF_ITEMS_AMT_VAT_EXCL.value,  # Index 22
                "ITEM_PRICE_VAT_RATE_PERCENT",
                "PRICE_OF_ITEMS_VAT_AMT",
                "PROMO_PRICE_OF_ITEMS_VAT_AMT",
                "TOTAL_PRICE_OF_ITEMS_VAT_AMT",
                "PRICE_OF_ITEMS_AMT_VAT_INCL",
                "PROMO_PRICE_OF_ITEMS_AMT_VAT_INCL",
                ColumnHeader.TOTAL_ACTIVITY_VALUE_AMT_VAT_EXCL.value,  # Index 29
                "TOTAL_ACTIVITY_VALUE_VAT_AMT",
                "TOTAL_ACTIVITY_VALUE_AMT_VAT_INCL",
                "DEPARTURE_CITY",
                "DEPARTURE_COUNTRY",  # Index 33 in short or 62 in full
            ]
            + [f"EXTRA_COL_{i}" for i in range(34, 62)]
            + [
                ColumnHeader.DEPARTURE_COUNTRY.value,  # Index 62
                "DEPARTURE_POST_CODE",
                "ARRIVAL_CITY",
                ColumnHeader.ARRIVAL_COUNTRY.value,  # Index 65
            ]
        )

        csv_path = tmp_path / filename
        rows_to_write = [headers]

        for custom in custom_rows:
            row = [""] * len(headers)
            # Default values
            row[5] = custom.get("transaction_type", TransactionType.FC_TRANSFER.value)
            row[13] = custom.get("asin", "B089WJC6Z4")
            row[16] = custom.get("qty", "1")
            row[62] = custom.get("departure", "DE")
            row[65] = custom.get("arrival", "FR")

            # Custom overrides by header name
            for key, val in custom.items():
                if key in headers:
                    row[headers.index(key)] = val

            rows_to_write.append(row)

        with csv_path.open(mode="w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
            writer.writerows(rows_to_write)

        return csv_path

    return _create_report
