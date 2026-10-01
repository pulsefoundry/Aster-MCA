#!/bin/zsh
set -e
SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"
exec /usr/bin/env python3 astermca_gui.py
