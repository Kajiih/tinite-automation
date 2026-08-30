#!/bin/bash
INVOCATION_DIR="$(pwd)"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

CSV_PATH="$1"
if [ -z "$CSV_PATH" ]; then
    echo "========================================================"
    echo "  Amazon B2B Intra-EU Invoice Downloader (macOS)"
    echo "========================================================"
    echo ""
    read -r -p "Glissez-déposez votre rapport TVA (.csv) ici et appuyez sur Entrée : " CSV_PATH
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
    echo "[ERROR] Fichier introuvable : $CSV_PATH"
    echo ""
    read -r -p "Appuyez sur Entrée pour quitter..."
    exit 1
fi

"$REPO_ROOT/run.command" b2b-vat download-invoices -r "$CSV_PATH"
echo ""
read -r -p "Appuyez sur Entrée pour quitter..."
