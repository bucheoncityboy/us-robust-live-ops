"""Ops CLI launcher (thin wrapper; real code lives in the ops/ package).

Usage: python ops.py <command> ...   (same as: python -m ops.ops <command> ...)
"""
import sys
from ops.ops import main

if __name__ == "__main__":
    sys.exit(main())
