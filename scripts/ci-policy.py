#!/usr/bin/env python3
"""Select safe automatic release behavior; only manual runs may use old pins."""

import argparse


def policy(event: str, refresh: bool, promote: bool) -> tuple[bool, bool]:
    """Refresh promoting automatic pushes to avoid undoing scheduled updates."""
    if event in ("push", "schedule"):
        return True, True
    if event == "workflow_dispatch":
        return refresh, promote
    raise ValueError("Only trusted main push, schedule and manual events may release")


def main() -> None:
    """Emit plain GitHub step outputs, not shell commands."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True)
    parser.add_argument("--refresh", choices=("true", "false"), default="false")
    parser.add_argument("--promote", choices=("true", "false"), default="false")
    options = parser.parse_args()
    refresh, promote = policy(options.event, options.refresh == "true", options.promote == "true")
    print(f"refresh={str(refresh).lower()}")
    print(f"promote={str(promote).lower()}")


if __name__ == "__main__":
    main()
