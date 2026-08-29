#!/usr/bin/env bash
# Double-clickable launcher for macOS (powered by uv)

cd "$(dirname "$0")" || exit 1

echo "============================================================"
echo "    Amazon VAT Report - FC_Transfer Price Automation"
echo "============================================================"
echo ""

# Ensure uv install locations are in PATH
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# Auto-install uv if not present
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

uv run process_report.py "$@"

echo ""
echo "Press [Enter] to close this window..."
read -r
