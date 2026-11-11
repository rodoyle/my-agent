#!/usr/bin/env python3
"""Build and smoke-test native amd64 agent images with Kaniko on Linux CI.

Builds use an unauthenticated loopback registry and an explicit source allowlist.
No publication credentials are available while image code executes. Tested image
archives are handed to a separate publication job.
"""

import argparse
import hashlib
import importlib.util
import json
import platform
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("image_build", ROOT / "scripts/kaniko-build.py")
assert SPEC is not None and SPEC.loader is not None
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)
EXECUTOR = "gcr.io/kaniko-project/executor:v1.23.2"
Runner = Callable[[list[str], int], None]


def command(arguments: list[str], timeout: int) -> None:
    """Stream public build logs; auth material never appears in arguments."""
    subprocess.run(arguments, check=True, timeout=timeout, stdin=subprocess.DEVNULL)


def owned_container(arguments: list[str], name: str, timeout: int, runner: Runner) -> None:
    """Remove our named container even when the client times out or build fails."""
    try:
        runner(["docker", "run", "--rm", "--label=agent-image-ci=true", "--name", name, *arguments], timeout)
    finally:
        # --rm already removed successful containers; cleanup is best effort.
        with suppress(subprocess.SubprocessError, OSError):
            runner(["docker", "rm", "--force", name], 30)


def stage_context(root: Path, target: Path) -> None:
    """Materialize only allowed regular source files, rejecting escaping links."""
    for relative in BUILD.CONTEXT_FILES:
        source = (root / relative).resolve(strict=True)
        if not source.is_relative_to(root.resolve()):
            raise ValueError(f"Context source escapes checkout: {relative}")
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def build_image(
    context: Path,
    output: Path,
    image: str,
    reference: str,
    tag: str,
    revision: str,
    source: str,
    base: str | None,
    runner: Runner,
) -> str:
    """Push a unique run tag and accept only an executor-produced digest."""
    digest_file = output / "digests" / image
    digest_file.parent.mkdir(exist_ok=True)
    digest_file.unlink(missing_ok=True)
    arguments = [
        "--network=host",
        "--volume",
        f"{context}:/context:ro",
        "--volume",
        f"{digest_file.parent}:/digests",
        EXECUTOR,
        "--context=dir:///context",
        f"--dockerfile=/context/{BUILD.DOCKERFILES[image]}",
        "--insecure-registry=localhost:5000",
        f"--destination={reference}:{tag}",
        f"--digest-file=/digests/{image}",
        "--cache=false",
        "--snapshot-mode=full",
        f"--label=org.opencontainers.image.source={source}",
        f"--label=org.opencontainers.image.revision={revision}",
        f"--label=org.opencontainers.image.version={tag}",
    ]
    if base:
        arguments.append(f"--build-arg=BASE_IMAGE={base}")
    owned_container(arguments, f"agent-build-{image}-{tag}", 2400, runner)
    digest = digest_file.read_text().strip()
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError(f"Invalid or missing build digest: {image}")
    return digest


def smoke(reference: str, image: str, tag: str, runner: Runner, default_command: bool = False) -> None:
    """Exercise the real entrypoint with fresh state and no network/credentials."""
    arguments = [
        "--read-only",
        "--user=1000:1000",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--network=none",
        "--tmpfs=/tmp:rw,nosuid,nodev,size=256m",
        "--tmpfs=/home/agent:rw,nosuid,nodev,uid=1000,gid=1000,size=1g",
        "--tmpfs=/workspace:rw,nosuid,nodev,uid=1000,gid=1000,size=256m",
        reference,
    ]
    if not default_command:
        arguments.extend(["node", "/opt/agent-tests/image-smoke.mjs"])
    suffix = "default" if default_command else "rpc"
    owned_container(arguments, f"agent-smoke-{image}-{suffix}-{tag}", 180, runner)


def validate_inputs(namespace: str, tag: str, revision: str, source: str) -> None:
    """Limit builds to the credential-free loopback registry and unique tags."""
    if namespace != "localhost:5000":
        raise ValueError("Build namespace must be localhost:5000; publication is a separate job")
    if not re.fullmatch(r"run-[0-9]+-[0-9]+", tag):
        raise ValueError("Use a unique run-<id>-<attempt> tag, never latest")
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Source revision must be a full git commit")
    if not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+", source):
        raise ValueError("Source must be a GitHub repository URL")


def release(
    root: Path,
    output: Path,
    namespace: str,
    tag: str,
    revision: str,
    source: str,
    runner: Runner = command,
) -> dict[str, Any]:
    """Export an image archive only after every exact digest passes smoke."""
    validate_inputs(namespace, tag, revision, source)
    root, output = root.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "status": "building",
        "revision": revision,
        "source": source,
        "tag": tag,
        "platform": "linux/amd64",
        "images": {},
        "inputs": {},
    }
    for filename in ("package.json", "package-lock.json"):
        content = (root / "base/runtime" / filename).read_bytes()
        (output / filename).write_bytes(content)
        report["inputs"][filename] = hashlib.sha256(content).hexdigest()
    try:
        with tempfile.TemporaryDirectory(prefix="agent-image-context-") as temporary:
            context = Path(temporary)
            stage_context(root, context)
            base = None
            for image in BUILD.DOCKERFILES:
                reference = f"{namespace}/agents-{image}"
                digest = build_image(context, output, image, reference, tag, revision, source, base, runner)
                exact = f"{reference}@{digest}"
                report["images"][image] = {"reference": exact, "smoke": "pending"}
                smoke(exact, image, tag, runner)
                if image == "headless":
                    smoke(exact, image, tag, runner, default_command=True)
                report["images"][image]["smoke"] = "passed"
                if image == "base":
                    base = exact
            tags = []
            for image, record in report["images"].items():
                local_tag = f"{namespace}/agents-{image}:{tag}"
                runner(["docker", "tag", record["reference"], local_tag], 30)
                record["archive_tag"] = local_tag
                tags.append(local_tag)
            runner(["docker", "save", "--output", str(output / "images.tar"), *tags], 300)
            with (output / "images.tar").open("rb") as archive:
                report["archive_sha256"] = hashlib.file_digest(archive, "sha256").hexdigest()
            report["status"] = "passed"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report["status"] = "failed"
        report["failure"] = type(error).__name__
        raise
    finally:
        (output / "release.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    """Run only on native Linux amd64; Docker is a runner, not the builder."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="localhost:5000")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    options = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("Release verification requires native Linux amd64")
    release(
        ROOT,
        options.output_directory,
        options.namespace,
        options.tag,
        options.revision,
        options.source,
    )


if __name__ == "__main__":
    main()
