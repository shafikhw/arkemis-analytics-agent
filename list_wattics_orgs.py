"""Backward-compatible entry point for the safe access validator."""

from scripts.validate_access import main

if __name__ == "__main__":
    raise SystemExit(main())
