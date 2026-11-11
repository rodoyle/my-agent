"""Behavioral checks for the build context and container startup boundary."""

import base64
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("kaniko_build", ROOT / "scripts/kaniko-build.py")
assert SPEC is not None and SPEC.loader is not None
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class ImageBuildTests(unittest.TestCase):
    """Protect build isolation, truthful context staging and startup behavior."""

    def test_context_excludes_unrelated_and_sensitive_state(self):
        """Only the explicit Docker context enters the ConfigMap payload."""
        manifest = BUILD.render("base", "registry.example/base:test")
        configmap, job = manifest["items"]
        pod = job["spec"]["template"]["spec"]
        paths = [item["path"] for item in pod["volumes"][0]["configMap"]["items"]]
        self.assertEqual(set(paths), set(BUILD.CONTEXT_FILES))
        for item in pod["volumes"][0]["configMap"]["items"]:
            self.assertEqual(base64.b64decode(configmap["binaryData"][item["key"]]), (ROOT / item["path"]).read_bytes())
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual(job["metadata"]["namespace"], "build")
        self.assertEqual(configmap["metadata"]["namespace"], "build")
        self.assertNotIn('"secret"', json.dumps(pod))
        self.assertNotIn('"hostPath"', json.dumps(pod))
        self.assertEqual(pod["containers"][0]["volumeMounts"][0]["name"], "context")
        self.assertTrue(any(v["name"] == "context" and "emptyDir" in v for v in pod["volumes"]))

    def test_projected_context_symlinks_are_materialized(self):
        """Kaniko COPY must receive regular files, not ConfigMap symlinks."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            projected = root / "input"
            output = root / "output"
            (projected / "..data/base").mkdir(parents=True)
            output.mkdir()
            source = projected / "..data/base/Dockerfile"
            source.write_text("FROM scratch\n")
            (projected / "base").symlink_to("..data/base", target_is_directory=True)
            pod = BUILD.render("base", "test")["items"][1]["spec"]["template"]["spec"]
            command = pod["initContainers"][0]["command"][-1]
            command = command.replace("/input", str(projected)).replace("/context", str(output))
            subprocess.run(["sh", "-ec", command], check=True, timeout=5)
            self.assertFalse((output / "base").is_symlink())
            self.assertEqual((output / "base/Dockerfile").read_bytes(), source.read_bytes())

    def test_meaningful_source_changes_invalidate_build_identity(self):
        """A harmless README change is ignored; runtime changes force a new job."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in BUILD.CONTEXT_FILES:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            before = BUILD.render("base", "test", root=root)
            (root / "README.md").write_text("Harmless documentation change\n")
            self.assertEqual(before, BUILD.render("base", "test", root=root))
            with (root / "base/agent-entrypoint.sh").open("a") as handle:
                handle.write("\n# changed runtime fixture\n")
            self.assertNotEqual(
                before["items"][1]["metadata"]["name"],
                BUILD.render("base", "test", root=root)["items"][1]["metadata"]["name"],
            )

    def test_derived_build_requires_explicit_base(self):
        """Do not accidentally consume a mutable, unrelated latest base."""
        with self.assertRaises(ValueError):
            BUILD.render("devpod", "test")
        manifest = BUILD.render("devpod", "test", base_image="registry.example/base@sha256:abc")
        args = manifest["items"][1]["spec"]["template"]["spec"]["containers"][0]["args"]
        self.assertIn("--build-arg=BASE_IMAGE=registry.example/base@sha256:abc", args)

    def test_effective_build_options_invalidate_job_identity(self):
        """A different node or registry transport must create a fresh Job."""
        baseline = BUILD.render("base", "test")["items"][1]["metadata"]["name"]
        for options in [{"node": "rpi-four-2"}, {"insecure_registry": "registry.example"}]:
            changed = BUILD.render("base", "test", **options)["items"][1]["metadata"]["name"]
            self.assertNotEqual(baseline, changed)

    def test_empty_home_seeds_defaults_but_preserves_operator_settings(self):
        """A mounted HOME must not hide packages or overwrite existing config."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seed = root / "seed"
            state = root / "state"
            (seed / "base").mkdir(parents=True)
            (seed / "base/settings.json").write_text('{"packages":["fixture"]}\n')
            script = root / "entrypoint.sh"
            script.write_text(
                (ROOT / "base/agent-entrypoint.sh").read_text()
                .replace("/opt/pi-defaults", str(seed))
                .replace("/opt/pi-runtime/profile-config.mjs", str(ROOT / "base/profile-config.mjs"))
            )
            env = {
                **os.environ,
                "HOME": str(root),
                "PI_CODING_AGENT_DIR": str(state),
                "AGENT_PROFILE": "base",
            }
            subprocess.run(["sh", str(script), "sh", "-c", "exit 0"], env=env, check=True, timeout=5)
            self.assertEqual((state / "settings.json").read_bytes(), (seed / "base/settings.json").read_bytes())
            custom = '{"packages":[],"theme":"light"}\n'
            (state / "settings.json").write_text(custom)
            subprocess.run(["sh", str(script), "sh", "-c", "exit 0"], env=env, check=True, timeout=5)
            self.assertEqual((state / "settings.json").read_text(), custom)
            result = subprocess.run(["sh", str(script), "sh", "-c", "exit 17"], env=env, timeout=5)
            self.assertEqual(result.returncode, 17)

    def test_remote_ovis_binding_fails_without_operator_credential(self):
        """Do not expose write-capable terminals unauthenticated on a LAN."""
        env = {key: value for key, value in os.environ.items() if key != "OVIS_TOKEN"}
        for host in ["0.0.0.0", "::", "192.0.2.1"]:
            result = subprocess.run(
                ["sh", str(ROOT / "base/ovis.sh")], env={**env, "HOST": host}, capture_output=True, timeout=5
            )
            self.assertEqual(result.returncode, 64)
            self.assertIn(b"user-supplied OVIS_TOKEN", result.stderr)


if __name__ == "__main__":
    unittest.main()
