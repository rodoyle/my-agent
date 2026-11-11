"""Protect runtime update boundaries and fail-closed image publication."""

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, filename: str) -> Any:
    """Load CLI modules without executing them."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


UPDATE = load("runtime_update", "refresh-runtime.py")
RELEASE = load("image_release", "ci-release.py")
PUBLISH = load("image_publish", "publish-images.py")
POLICY = load("release_policy", "ci-policy.py")


class RuntimeUpdateTests(unittest.TestCase):
    """Only selected stable packages change, and failures preserve both inputs."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest = {
            "piImage": {"extensions": ["pi-example"]},
            "dependencies": {UPDATE.PI: "1.0.0", "pi-example": "1.0.0", "unrelated": "3.0.0"},
        }
        (self.root / "package.json").write_text(json.dumps(self.manifest))
        dependencies = self.manifest["dependencies"]
        packages = {"": {"dependencies": dependencies}}
        packages.update({"node_modules/" + name: {"version": version} for name, version in dependencies.items()})
        (self.root / "package-lock.json").write_text(json.dumps({"packages": packages}))
        self.output = self.root / "resolved"
        self.before = self.snapshot()
        self.calls = []

    def snapshot(self):
        """Read the two intentional outputs, excluding incidental files."""
        return [(self.root / name).read_bytes() for name in ("package.json", "package-lock.json")]

    def registry(self, arguments, directory):
        """Stand in for registry/lock resolution, never invoke a test runner."""
        self.calls.append(arguments)
        if arguments[0] == "view":
            return '"2.0.0"'
        candidate = json.loads((directory / "package.json").read_text())
        dependencies = candidate["dependencies"]
        packages = {"": {"dependencies": dependencies}}
        packages.update({"node_modules/" + name: {"version": version} for name, version in dependencies.items()})
        (directory / "package-lock.json").write_text(json.dumps({"packages": packages}))
        return ""

    def test_updates_only_pi_and_catalog_and_preserves_harmless_metadata(self):
        """A descriptive field must not affect selection; non-catalog deps stay pinned."""
        self.manifest["description"] = "Harmless metadata edit"
        (self.root / "package.json").write_text(json.dumps(self.manifest))
        report = UPDATE.refresh(self.root, self.output, self.registry)
        actual = json.loads((self.output / "package.json").read_text())
        self.assertEqual(json.loads((self.root / "package.json").read_text()), self.manifest)
        self.assertEqual(actual["dependencies"], {UPDATE.PI: "2.0.0", "pi-example": "2.0.0", "unrelated": "3.0.0"})
        self.assertEqual(actual["description"], "Harmless metadata edit")
        self.assertEqual({entry["package"] for entry in report["updates"]}, {UPDATE.PI, "pi-example"})
        self.assertIn("--ignore-scripts", self.calls[-1])

    def test_invalid_latest_and_registry_failures_preserve_both_inputs(self):
        """Prereleases, downgrades and resolver failures leave both inputs intact."""
        for value in ['"2.0.0-beta.1"', '"0.9.0"', "{broken"]:
            with self.assertRaises(ValueError):
                UPDATE.refresh(self.root, self.output, lambda _args, _directory, value=value: value)
            self.assertEqual(self.snapshot(), self.before)

        def broken_lock(arguments, directory):
            if arguments[0] == "install":
                raise subprocess.CalledProcessError(1, ["npm"])
            return self.registry(arguments, directory)

        with self.assertRaises(subprocess.CalledProcessError):
            UPDATE.refresh(self.root, self.output, broken_lock)
        self.assertEqual(self.snapshot(), self.before)

    def test_no_change_is_byte_identical(self):
        """An up-to-date release does not churn the lockfile or source formatting."""
        report = UPDATE.refresh(self.root, self.output, lambda _args, _directory: '"1.0.0"')
        self.assertEqual(report["updates"], [])
        self.assertEqual(self.snapshot(), self.before)
        resolved = [(self.output / name).read_bytes() for name in ("package.json", "package-lock.json")]
        self.assertEqual(resolved, self.before)

    def test_mismatched_lock_is_not_published(self):
        """A successful command alone is not evidence of a valid resolved graph."""

        def wrong_lock(arguments, directory):
            output = self.registry(arguments, directory)
            if arguments[0] == "install":
                (directory / "package-lock.json").write_text('{"packages":{"":{"dependencies":{}}}}')
            return output

        with self.assertRaises(ValueError):
            UPDATE.refresh(self.root, self.output, wrong_lock)
        self.assertEqual(self.snapshot(), self.before)

    def test_interrupted_snapshot_never_rewrites_source_or_selects_partial_pair(self):
        """Interrupted output publication leaves no visible resolved directory."""
        with patch.object(Path, "rename", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            UPDATE.refresh(self.root, self.output, self.registry)
        self.assertEqual(self.snapshot(), self.before)
        self.assertFalse(self.output.exists())


class ImageReleaseTests(unittest.TestCase):
    """Use an inert Docker adapter to check ordering and meaningful failures."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.checkout = self.root / "checkout"
        for relative in RELEASE.BUILD.CONTEXT_FILES:
            destination = self.checkout / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        (self.checkout / "README.md").write_text("Harmless edit outside context")
        self.calls = []
        self.fail_smoke = False
        self.bad_digest = False
        self.digests = {}

    def docker(self, arguments, _timeout):
        """Model executor digest outputs and runtime failure without Docker."""
        self.calls.append(arguments)
        if RELEASE.EXECUTOR in arguments:
            mounted = next(value for value in arguments if value.endswith(":/context:ro"))
            context = Path(mounted.removesuffix(":/context:ro"))
            self.assertFalse((context / "README.md").exists())
            self.assertEqual(
                {str(file.relative_to(context)) for file in context.rglob("*") if file.is_file()},
                set(RELEASE.BUILD.CONTEXT_FILES),
            )
            image = next(value for value in arguments if value.startswith("--digest-file=")).rsplit("/", 1)[-1]
            output = Path(next(value for value in arguments if value.endswith(":/digests")).removesuffix(":/digests"))
            digest = "sha256:" + str(len(self.digests) + 1) * 64
            self.digests[image] = digest
            (output / image).write_text("invalid" if self.bad_digest else digest)
        elif arguments[1] == "save":
            Path(arguments[arguments.index("--output") + 1]).write_bytes(b"inert tested archive fixture")
        elif "run" in arguments and self.fail_smoke:
            raise subprocess.CalledProcessError(1, arguments)

    def run_release(self):
        """Use unique run tags and a full source revision like CI."""
        return RELEASE.release(
            self.checkout,
            self.root / "output",
            "localhost:5000",
            "run-123-1",
            "a" * 40,
            "https://github.com/example/agents",
            self.docker,
        )

    def test_exact_base_and_runtime_gates_precede_archive_export(self):
        """Credential-free builds use exact base references and gate archive creation."""
        report = self.run_release()
        builds = [args for args in self.calls if RELEASE.EXECUTOR in args]
        self.assertEqual(set(report["images"]), set(RELEASE.BUILD.DOCKERFILES))
        base = "localhost:5000/agents-base@" + self.digests["base"]
        for args in builds:
            self.assertIn("--context=dir:///context", args)
            self.assertFalse(any("/kaniko/.docker" in argument for argument in args))
        for args in builds[1:]:
            self.assertIn("--build-arg=BASE_IMAGE=" + base, args)
        first_promotion = next(index for index, args in enumerate(self.calls) if args[1] == "tag")
        self.assertTrue(all(args[1] != "run" for args in self.calls[first_promotion:]))
        for args in self.calls:
            if args[1] == "run" and RELEASE.EXECUTOR not in args:
                self.assertIn("--network=none", args)
                self.assertIn("--read-only", args)
        self.assertEqual(report["status"], "passed")

    def test_smoke_failure_stops_builds_and_never_promotes_latest(self):
        """A broken runtime cannot become a release through a successful build alone."""
        self.fail_smoke = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_release()
        self.assertFalse(any(args[1] in ("push", "tag") for args in self.calls))
        self.assertEqual(set(self.digests), {"base"})
        self.assertTrue(any(args[1] == "rm" for args in self.calls))
        report = json.loads((self.root / "output/release.json").read_text())
        self.assertEqual(report["status"], "failed")

    def test_invalid_digest_cannot_fall_back_to_run_tag(self):
        """Stale/malformed executor output is not accepted as an immutable base."""
        self.bad_digest = True
        with self.assertRaises(ValueError):
            self.run_release()
        self.assertFalse(any(args[1] in ("push", "tag") for args in self.calls))

    def test_timeout_attempts_owned_cleanup_and_stops_publication(self):
        """A hung docker client must not leave a build running into promotion."""

        def hung(arguments, timeout):
            self.calls.append(arguments)
            if RELEASE.EXECUTOR in arguments:
                raise subprocess.TimeoutExpired(arguments, timeout)

        with self.assertRaises(subprocess.TimeoutExpired):
            RELEASE.release(
                self.checkout,
                self.root / "output",
                "localhost:5000",
                "run-123-1",
                "a" * 40,
                "https://github.com/example/agents",
                hung,
            )
        self.assertTrue(any(args[1] == "rm" for args in self.calls))
        self.assertFalse(any(args[1] in ("tag", "push") for args in self.calls))

    def test_allowed_source_cannot_link_to_material_outside_checkout(self):
        """Allowlisted names do not authorize reading arbitrary host files."""
        allowed = self.checkout / "base/agent-entrypoint.sh"
        allowed.unlink()
        outside = self.root / "outside.txt"
        outside.write_text("Harmless fixture representing excluded host state")
        allowed.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.run_release()
        self.assertEqual(self.calls, [])

    def publisher(self, arguments, _timeout):
        """Return a registry receipt without running image or build commands."""
        self.publish_calls.append(arguments)
        if arguments[0] == "git":
            return getattr(self, "remote_head", "a" * 40) + "\trefs/heads/main\n"
        if arguments[1] == "push":
            if self.fail_push:
                raise subprocess.CalledProcessError(1, arguments)
            image = arguments[-1].split("agents-", 1)[1].split(":", 1)[0]
            digest = "sha256:" + str(PUBLISH.IMAGES.index(image) + 1) * 64
            return f"tag: digest: {digest} size: 123\n"
        return ""

    def test_authenticated_publisher_only_loads_tags_and_pushes_tested_images(self):
        """Registry authority is used after execution, never in Docker run/build."""
        self.run_release()
        self.publish_calls = []
        self.fail_push = False
        report = PUBLISH.publish(
            self.root / "output",
            "ghcr.io/example",
            "run-123-1",
            "a" * 40,
            True,
            self.publisher,
        )
        self.assertEqual(report["status"], "passed")
        self.assertFalse(any(args[1] in ("run", "build") for args in self.publish_calls))
        pushes = [args[-1] for args in self.publish_calls if args[1] == "push"]
        first_latest = next(index for index, reference in enumerate(pushes) if reference.endswith(":latest"))
        self.assertEqual(
            set(pushes[:first_latest]), {f"ghcr.io/example/agents-{image}:run-123-1" for image in PUBLISH.IMAGES}
        )

    def test_stale_source_rerun_cannot_promote_latest(self):
        """Preserve unique tags but reject alias changes after main advances."""
        self.run_release()
        self.publish_calls = []
        self.fail_push = False
        self.remote_head = "b" * 40
        with self.assertRaisesRegex(ValueError, "no longer main HEAD"):
            PUBLISH.publish(self.root / "output", "ghcr.io/example", "run-123-1", "a" * 40, True, self.publisher)
        self.assertEqual(sum(args[1] == "push" for args in self.publish_calls), 4)
        self.assertFalse(any(args[-1].endswith(":latest") for args in self.publish_calls))

    def test_publication_failure_cannot_promote_latest(self):
        """A failed unique-tag push prevents all alias updates."""
        self.run_release()
        self.publish_calls = []
        self.fail_push = True
        with self.assertRaises(subprocess.CalledProcessError):
            PUBLISH.publish(self.root / "output", "ghcr.io/example", "run-123-1", "a" * 40, True, self.publisher)
        self.assertFalse(any(args[-1].endswith(":latest") for args in self.publish_calls))

    def test_changed_archive_is_rejected_before_authentication_is_used(self):
        """A receipt cannot authorize arbitrary replacement image bytes."""
        self.run_release()
        (self.root / "output/images.tar").write_bytes(b"different archive")
        self.publish_calls = []
        with self.assertRaises(ValueError):
            PUBLISH.publish(self.root / "output", "ghcr.io/example", "run-123-1", "a" * 40, True, self.publisher)
        self.assertEqual(self.publish_calls, [])


class PolicyTests(unittest.TestCase):
    """Automatic publication must not revert scheduled dependency refreshes."""

    def test_schedule_then_push_both_refresh_before_promoting(self):
        for event in ("schedule", "push"):
            self.assertEqual(POLICY.policy(event, False, False), (True, True))
        self.assertEqual(POLICY.policy("workflow_dispatch", False, False), (False, False))
        with self.assertRaises(ValueError):
            POLICY.policy("pull_request", True, True)


if __name__ == "__main__":
    unittest.main()
