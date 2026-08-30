#!/bin/bash
INVOCATION_DIR="$(pwd)"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

CSV_PATH="$1"
if [ -z "$CSV_PATH" ]; then
    echo "========================================================"
    echo "  Amazon B2B Intra-EU Invoice Downloader (macOS)"
    echo "========================================================"
    echo ""
    read -r -p "Drag and drop your VAT report (.csv) here and press Enter: " CSV_PATH
fi

# Strip quotes and leading/trailing escaped characters from drag-and-drop
CSV_PATH="${CSV_PATH%\"}"
CSV_PATH="${CSV_PATH#\"}"
CSV_PATH="${CSV_PATH%\'}"
CSV_PATH="${CSV_PATH#\'}"
CSV_PATH="$(eval echo "$CSV_PATH" 2>/dev/null || echo "$CSV_PATH")"

# If relative, check if exists relative to INVOCATION_DIR or REPO_ROOT
if [ ! -f "$CSV_PATH" ]; then
    if [ -f "$INVOCATION_DIR/$CSV_PATH" ]; then
        CSV_PATH="$INVOCATION_DIR/$CSV_PATH"
    elif [ -f "$REPO_ROOT/$CSV_PATH" ]; then
        CSV_PATH="$REPO_ROOT/$CSV_PATH"
    fi
fi

if [ -z "$CSV_PATH" ] || [ ! -f "$CSV_PATH" ]; then
    echo ""
    echo "[ERROR] File not found: $CSV_PATH"
    echo ""
    read -r -p "Press Enter to exit..."
    exit 1
fi

"$REPO_ROOT/run.command" invoice-downloader --report "$CSV_PATH"
echo ""
read -r -p "Press Enter to exit..."
