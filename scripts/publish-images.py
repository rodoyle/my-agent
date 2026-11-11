#!/usr/bin/env python3
"""Publish a tested image archive without executing Dockerfile or image code.

Authentication is provided by GitHub's publication job, never by the builder.
"""

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

IMAGES = ("base", "devpod", "headless", "template")
Runner = Callable[[list[str], int], str]


def command(arguments: list[str], timeout: int) -> str:
    """Capture public Docker receipts, not credentials (which are never args)."""
    result = subprocess.run(
        arguments,
        timeout=timeout,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print(result.stdout, end="")
    result.check_returncode()
    return result.stdout


def read_report(filename: Path) -> dict[str, Any]:
    """Reject malformed release metadata before loading an archive."""
    try:
        result = json.loads(filename.read_text())
    except (ValueError, OSError) as error:
        raise ValueError("Invalid build report") from error
    if not isinstance(result, dict):
        raise TypeError("Build report must be an object")
    return result


def validate(report: dict[str, Any], directory: Path, tag: str, revision: str, namespace: str) -> None:
    """Require a complete current-revision receipt and the exact tested archive."""
    if not re.fullmatch(r"ghcr\.io/[a-z0-9]+(?:[._-][a-z0-9]+)*", namespace):
        raise ValueError("Publication namespace must be ghcr.io/<lowercase-owner>")
    if not re.fullmatch(r"run-[0-9]+-[0-9]+", tag) or not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Invalid publication tag or source revision")
    if report.get("status") != "passed" or report.get("tag") != tag or report.get("revision") != revision:
        raise ValueError("Build receipt is not a passed result for this run and revision")
    if set(report["images"]) != set(IMAGES):
        raise ValueError("Build receipt is missing required images")
    for image, record in report["images"].items():
        if record.get("smoke") != "passed" or record.get("archive_tag") != f"localhost:5000/agents-{image}:{tag}":
            raise ValueError(f"Image was not smoke-tested and archived: {image}")
    with (directory / "images.tar").open("rb") as archive:
        digest = hashlib.file_digest(archive, "sha256").hexdigest()
    if digest != report.get("archive_sha256"):
        raise ValueError("Image archive does not match the tested build receipt")


def push(reference: str, runner: Runner) -> str:
    """Accept only a successful registry push with a digest receipt."""
    output = runner(["docker", "push", reference], 300)
    matches = re.findall(r"\bdigest: (sha256:[a-f0-9]{64})\b", output)
    if len(matches) != 1:
        raise ValueError(f"Push did not provide one image digest: {reference}")
    return matches[0]


def publish(
    directory: Path,
    namespace: str,
    tag: str,
    revision: str,
    promote: bool = False,
    runner: Runner = command,
) -> dict[str, Any]:
    """Load tested bytes; push unique tags before optionally updating aliases."""
    build = read_report(directory / "release.json")
    validate(build, directory, tag, revision, namespace)
    report: dict[str, Any] = {"status": "publishing", "revision": revision, "tag": tag, "images": {}}
    try:
        runner(["docker", "load", "--input", str(directory / "images.tar")], 300)
        for image in IMAGES:
            reference = f"{namespace}/agents-{image}"
            target = f"{reference}:{tag}"
            runner(["docker", "tag", build["images"][image]["archive_tag"], target], 30)
            digest = push(target, runner)
            report["images"][image] = {"reference": f"{reference}@{digest}"}
        if promote:
            for image, record in report["images"].items():
                reference = f"{namespace}/agents-{image}"
                latest = reference + ":latest"
                runner(["docker", "tag", reference + ":" + tag, latest], 30)
                digest = push(latest, runner)
                if record["reference"] != f"{reference}@{digest}":
                    raise ValueError(f"Promoted alias differs from tested publication: {image}")
                record["latest"] = latest
        report["status"] = "passed"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report["status"] = "failed"
        report["failure"] = type(error).__name__
        raise
    finally:
        (directory / "publication.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    """Publish only the source revision selected by the workflow."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-directory", type=Path, required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--promote-latest", action="store_true")
    options = parser.parse_args()
    publish(options.input_directory, options.namespace, options.tag, options.revision, options.promote_latest)


if __name__ == "__main__":
    main()
