#!/usr/bin/env python3
"""Refresh only Pi and the declared extension catalog, resolving exact stable pins.

Resolution happens in isolation and never changes source inputs. An atomic
new-directory rename publishes the validated manifest/lock snapshot as a pair.
CI publishes these resolved inputs with its images, not to git.
"""

import argparse
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PI = "@earendil-works/pi-coding-agent"
PACKAGE = re.compile(r"(?:@[a-z0-9-]+/)?[a-z0-9][a-z0-9._-]*")
STABLE = re.compile(r"\d+\.\d+\.\d+")
Runner = Callable[[list[str], Path], str]


def npm(arguments: list[str], directory: Path) -> str:
    """Use the public registry without loading personal npm configuration."""
    result = subprocess.run(
        ["npm", *arguments, "--registry=https://registry.npmjs.org", "--userconfig=" + os.devnull],
        cwd=directory,
        env={**os.environ, "NPM_CONFIG_USERCONFIG": os.devnull},
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    )
    return result.stdout


def parse_json(content: str | bytes) -> Any:
    """Reject malformed metadata explicitly instead of accepting partial input."""
    try:
        return json.loads(content)
    except (ValueError, TypeError) as error:
        raise ValueError("Invalid runtime JSON metadata") from error


def selected_packages(manifest: dict[str, Any]) -> list[str]:
    """Validate the explicit update boundary before any registry queries."""
    dependencies = manifest["dependencies"]
    catalog = manifest["piImage"]["extensions"]
    if not isinstance(catalog, list) or not all(isinstance(name, str) for name in catalog):
        raise ValueError("Extension catalog must be a string array")
    selected = [PI, *catalog]
    if len(set(selected)) != len(selected):
        raise ValueError("Duplicate runtime selection")
    for name in selected:
        if not PACKAGE.fullmatch(name) or name not in dependencies:
            raise ValueError(f"Invalid or uninstalled runtime package: {name}")
        if not isinstance(dependencies[name], str) or not STABLE.fullmatch(dependencies[name]):
            raise ValueError(f"Existing runtime pin must be stable and exact: {name}")
    return selected


def resolve_versions(manifest: dict[str, Any], candidate: Path, runner: Runner) -> list[dict[str, str]]:
    """Resolve stable versions only for the approved direct dependencies."""
    dependencies = manifest["dependencies"]
    updates = []
    for name in selected_packages(manifest):
        version = parse_json(runner(["view", name + "@latest", "version", "--json"], candidate))
        if not isinstance(version, str) or not STABLE.fullmatch(version):
            raise ValueError(f"Registry latest is not a stable exact version: {name}")
        if tuple(map(int, version.split("."))) < tuple(map(int, dependencies[name].split("."))):
            raise ValueError(f"Refusing registry downgrade: {name}")
        if version != dependencies[name]:
            updates.append({"package": name, "from": dependencies[name], "to": version})
            dependencies[name] = version
    return updates


def validate_lock(candidate: Path, dependencies: dict[str, str]) -> None:
    """Require the resolver's root and installed pins to agree with the input."""
    lock = parse_json((candidate / "package-lock.json").read_text())
    if lock["packages"][""]["dependencies"] != dependencies:
        raise ValueError("Resolved lockfile does not match the candidate manifest")
    for name, version in dependencies.items():
        if lock["packages"]["node_modules/" + name]["version"] != version:
            raise ValueError(f"Resolved dependency differs from exact pin: {name}")


def refresh(directory: Path, output: Path, runner: Runner = npm) -> dict[str, Any]:
    """Publish a fresh snapshot atomically; never rewrite a source input pair."""
    if output.exists():
        raise FileExistsError("Resolved output directory must not already exist")
    output.parent.mkdir(parents=True, exist_ok=True)
    files = [directory / name for name in ("package.json", "package-lock.json")]
    original = [file.read_bytes() for file in files]
    manifest = parse_json(original[0])
    dependencies = manifest["dependencies"]
    with tempfile.TemporaryDirectory(prefix="agent-runtime-refresh-", dir=output.parent) as temporary:
        candidate = Path(temporary)
        updates = resolve_versions(manifest, candidate, runner)
        for file, content in zip(files, original, strict=True):
            (candidate / file.name).write_bytes(content)
        if updates:
            (candidate / "package.json").write_text(json.dumps(manifest, indent=2) + "\n")
            runner(["install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"], candidate)
        validate_lock(candidate, dependencies)
        snapshot = candidate / "snapshot"
        snapshot.mkdir()
        for file in files:
            (snapshot / file.name).write_bytes((candidate / file.name).read_bytes())
        snapshot.rename(output)
    return {"updates": updates, "dependencies": dependencies}


def main() -> None:
    """Print credential-free resolved version metadata."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-directory", type=Path, default=ROOT / "base/runtime")
    parser.add_argument("--output-directory", type=Path, required=True)
    options = parser.parse_args()
    print(json.dumps(refresh(options.runtime_directory, options.output_directory), indent=2))


if __name__ == "__main__":
    main()
