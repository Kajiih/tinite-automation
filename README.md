# Tinite Automation

A production-grade Python monorepo using **Astral `uv` Workspaces** with clean **`apps/` + `libs/`** domain separation.

Includes full client-side WebAssembly execution in the browser (Pyodide) and high-performance CLI commands.

---

## Workspace Architecture

```
tinite-automation/
├── pyproject.toml                  # Root workspace manifest
├── uv.lock                         # Universal workspace lockfile
├── README.md
├── run.command                     # macOS 1-click launcher (starts Web Hub)
├── run.bat                         # Windows 1-click launcher (starts Web Hub)
│
├── apps/
│   └── web-hub/                    # User-Facing Web Hub Application
│       ├── pyproject.toml          # App package (depends on workspace libs)
│       └── src/web_server/
│           ├── __init__.py
│           ├── server.py           # Port fallback server & Pyodide engine streamer
│           ├── updater.py          # Cross-platform in-browser updater
│           └── static/             # WebAssembly Multi-Tool Web Hub (HTML, CSS, JS)
│
└── libs/
    ├── vat-report/                 # Pure VAT Report Automation Engine
    │   ├── pyproject.toml          # Independent package (openpyxl)
    │   ├── src/vat_report/
    │   │   ├── __init__.py
    │   │   └── engine.py
    │   ├── tests/
    │   │   └── test_vat_report.py
    │   └── example_data/
    │       ├── sample_vat_report.csv
    │       └── amazon_asin_prix_achat_cogs_maj.xlsx
    │
    ├── b2b-vat/                    # Pure B2B Intra-EU VAT Engine
    │   ├── pyproject.toml          # Independent package
    │   ├── src/b2b_vat/
    │   │   ├── __init__.py
    │   │   └── engine.py
    │   └── tests/
    │       └── test_b2b_vat.py
    │
    └── image-renamer/              # Pure ASIN Image Duplicator & Renamer Engine
        ├── pyproject.toml          # Independent package
        ├── src/image_renamer/
        │   ├── __init__.py
        │   └── engine.py
        ├── tests/
        │   └── test_image_renamer.py
        └── example_data/
            └── sample_asins.txt
```

---

## 1-Click Launchers (Browser Web Hub)

- **macOS**: Double-click `run.command`
- **Windows**: Double-click `run.bat`

*Starts the local server on an available port (`http://localhost:8000`) and opens the Web Hub in your default browser.*

---

## Command-Line Usage (CLI)

```bash
# Launch the Web Hub:
uv run --package web-hub amazon-tools

# B2B Intra-EU VAT Automation:
uv run --package b2b-vat b2b-vat \
  --report "taxReport_Juillet 2026.csv" \
  --departure "FR" \
  --output-summary "b2b_summary.csv" \
  --output-transactions "b2b_transactions.csv"

# VAT Report Automation (FC Transfers):
uv run --package vat-report vat-report \
  --vat-report "libs/vat-report/example_data/sample_vat_report.csv" \
  --price-catalog "libs/vat-report/example_data/amazon_asin_prix_achat_cogs_maj.xlsx"

# ASIN Image Duplicator:
uv run --package image-renamer duplicate-images \
  --images "path/to/templates" \
  --asins "libs/image-renamer/example_data/sample_asins.txt" \
  --output "output_images" \
  --hardlinks
```
