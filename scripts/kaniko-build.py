#!/usr/bin/env python3
"""Render a credential-free Kaniko ConfigMap + Job for the build namespace.

Only explicitly selected image sources enter the context. No git credentials,
model settings, task files, sessions, host HOME, or kubeconfig are copied.
"""

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTEXT_FILES = (
    "base/Dockerfile",
    "base/agent-entrypoint.sh",
    "base/ovis.sh",
    "base/runtime/package.json",
    "base/runtime/package-lock.json",
    "devpod/Dockerfile",
    "headless_agent/Dockerfile",
    "_template/Dockerfile",
    "tests/image-smoke.mjs",
)
DOCKERFILES = {
    "base": "base/Dockerfile",
    "devpod": "devpod/Dockerfile",
    "headless": "headless_agent/Dockerfile",
    "template": "_template/Dockerfile",
}


def render(
    image: str,
    destination: str,
    base_image: str | None = None,
    name: str | None = None,
    insecure_registry: str | None = None,
    node: str = "med-laptop-2",
    root: Path = ROOT,
) -> dict[str, Any]:
    """Render an isolated, namespace-scoped build with a materialized context."""
    if image not in DOCKERFILES:
        raise ValueError("Unknown image")
    if image != "base" and not base_image:
        raise ValueError("Derived images require --base-image from a verified build")
    sources = {path: (root / path).read_bytes() for path in CONTEXT_FILES}
    digest = hashlib.sha256()
    for path, content in sources.items():
        digest.update(path.encode() + b"\0" + content + b"\0")
    digest.update(json.dumps([image, destination, base_image, node, insecure_registry], separators=(",", ":")).encode())
    fingerprint = digest.hexdigest()
    name = name or f"agents-{image}-{fingerprint[:10]}"
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?", name):
        raise ValueError("Job name must be a DNS label of at most 50 characters")
    payload = {f"file-{i}": base64.b64encode(content).decode() for i, content in enumerate(sources.values())}
    if sum(len(value) for value in payload.values()) > 900_000:
        raise ValueError("Build context exceeds the conservative ConfigMap limit")
    labels = {"app.kubernetes.io/name": "agent-image-build", "app.kubernetes.io/instance": name}
    configmap = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": name, "namespace": "build", "labels": labels},
        "immutable": True,
        "binaryData": payload,
    }
    args = [
        f"--dockerfile=/context/{DOCKERFILES[image]}",
        "--context=dir:///context",
        f"--destination={destination}",
        "--cache=false",
        "--snapshot-mode=full",
        "--digest-file=/dev/termination-log",
    ]
    if base_image:
        args.append(f"--build-arg=BASE_IMAGE={base_image}")
    if insecure_registry:
        args.append(f"--insecure-registry={insecure_registry}")
    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name,
            "namespace": "build",
            "labels": labels,
            "annotations": {"agents/context-sha256": fingerprint},
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 2400,
            "ttlSecondsAfterFinished": 86400,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "nodeSelector": {"kubernetes.io/hostname": node},
                    "securityContext": {"seccompProfile": {"type": "RuntimeDefault"}},
                    "initContainers": [
                        {
                            "name": "stage-context",
                            "image": "docker.io/library/busybox:1.37.0",
                            "command": ["sh", "-ec", "cp -LR /input/* /context/"],
                            "securityContext": {"allowPrivilegeEscalation": False},
                            "resources": {
                                "requests": {"cpu": "10m", "memory": "16Mi"},
                                "limits": {"cpu": "100m", "memory": "64Mi"},
                            },
                            "volumeMounts": [
                                {"name": "source", "mountPath": "/input", "readOnly": True},
                                {"name": "context", "mountPath": "/context"},
                            ],
                        }
                    ],
                    "containers": [
                        {
                            "name": "kaniko",
                            "image": "gcr.io/kaniko-project/executor:v1.23.2",
                            "args": args,
                            "securityContext": {"allowPrivilegeEscalation": False},
                            "resources": {
                                "requests": {"cpu": "500m", "memory": "1Gi", "ephemeral-storage": "4Gi"},
                                "limits": {"cpu": "2", "memory": "4Gi", "ephemeral-storage": "12Gi"},
                            },
                            "volumeMounts": [{"name": "context", "mountPath": "/context"}],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "source",
                            "configMap": {
                                "name": name,
                                "items": [{"key": f"file-{i}", "path": path} for i, path in enumerate(sources)],
                            },
                        },
                        {"name": "context", "emptyDir": {"sizeLimit": "2Gi"}},
                    ],
                },
            },
        },
    }
    return {"apiVersion": "v1", "kind": "List", "items": [configmap, job]}


def main() -> None:
    """Print the manifest without contacting Kubernetes or a registry."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", choices=DOCKERFILES)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--base-image")
    parser.add_argument("--name")
    parser.add_argument("--insecure-registry", help="Only for the internal build registry")
    parser.add_argument("--node", default="med-laptop-2")
    options = parser.parse_args()
    try:
        manifest = render(
            options.image,
            options.destination,
            options.base_image,
            options.name,
            options.insecure_registry,
            options.node,
        )
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
