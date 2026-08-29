#!/usr/bin/env bash
# Double-clickable launcher for macOS (powered by uv)
set -euo pipefail

cd "$(dirname "$0")"

echo "=========================================================================="
echo "    Amazon VAT Report - FC_Transfer Price Automation & Country Summary"
echo "=========================================================================="
echo ""

# Ensure standard user & Homebrew binary paths are in PATH
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# Auto-install uv if not present on system
if ! command -v uv &> /dev/null; then
    echo "Installing uv (fast Python package runner)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

uv run process_report.py "$@"

echo ""
echo "Press [Enter] to close this window..."
read -r
