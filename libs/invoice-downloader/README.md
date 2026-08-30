# Invoice Downloader

Amazon Seller Central Invoice Downloader with multi-browser session auto-detection and deduplication.

## Features
- **Auto Browser Detection**: Automatically detects active Amazon sessions across installed browsers (`Chrome`, `Firefox`, `Edge`, `Brave`, `Arc`, `Safari`, `Opera`, etc.).
- **B2B Intra-EU Filtering**: By default, targets intra-EU cross-border zero-rated transactions requiring VAT documentation.
- **Universal Mode (`--all`)**: Downloads all invoice documents found in any Amazon VAT / VCS report.
- **Multi-Item Deduplication**: Downloads each unique invoice PDF once even when an order has multiple transaction rows.

## Usage

```bash
# Download B2B intra-EU invoices with auto browser detection:
uv run invoice-downloader -r "path/to/taxReport.csv"

# Download ALL invoices from an Amazon report:
uv run invoice-downloader -r "path/to/taxReport.csv" --all

# Target a specific browser:
uv run invoice-downloader -r "path/to/taxReport.csv" --browser firefox
```
