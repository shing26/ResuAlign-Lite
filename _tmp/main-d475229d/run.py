#!/usr/bin/env python3
"""Thin entry point. During development, run with PYTHONPATH=src."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from resualign.cli import main

if __name__ == "__main__":
    main()
