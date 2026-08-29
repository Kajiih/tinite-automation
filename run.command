#!/usr/bin/env bash
# Double-clickable launcher for macOS

cd "$(dirname "$0")" || exit 1

echo "============================================================"
echo "    Amazon VAT Report - FC_Transfer Price Automation"
echo "============================================================"
echo ""

# Prefer uv if available, fallback to python3
if command -v uv &> /dev/null; then
    uv run process_report.py "$@"
elif command -v python3 &> /dev/null; then
    python3 process_report.py "$@"
else
    echo "Error: Neither 'uv' nor 'python3' was found on your system."
    echo "Please install uv (https://docs.astral.sh/uv/) or Python 3."
fi

echo ""
echo "Press [Enter] to close this window..."
read -r
