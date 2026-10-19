#!/usr/bin/env python3
"""Backward-compatible alias for the safe live candidate diagnostic."""
from scripts.debug_candidates import main

if __name__ == "__main__":
    raise SystemExit(main())
