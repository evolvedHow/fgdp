"""
Run all data quality checks against a repo and produce a report.

This is a convenience wrapper around `fdp validate`.

Usage:
    uv run python scripts/validate.py
    uv run python scripts/validate.py --repo my_workspace
    uv run python scripts/validate.py --category boundaries
    uv run python scripts/validate.py --halt
"""

import subprocess
import sys


def main():
    args = ["fdp", "validate"] + sys.argv[1:]
    sys.exit(subprocess.call(args))


if __name__ == "__main__":
    main()
