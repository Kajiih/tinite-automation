#!/bin/bash
set -e

# Change directory to the repository root
cd "$(dirname "$0")"

# Expand common user and Homebrew binary paths
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# Auto-install uv if not found
if ! command -v uv &> /dev/null; then
    echo "========================================================"
    echo " 'uv' is not installed. Installing automatically..."
    echo "========================================================"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

if ! command -v uv &> /dev/null; then
    echo "Error: Failed to install 'uv'. Please install it from https://astral.sh/uv"
    read -p "Press Enter to exit..."
    exit 1
fi

# Execute Python application (opens Web App by default or CLI with arguments)
uv run python -m amazon_vat_automation.process_report "$@"
