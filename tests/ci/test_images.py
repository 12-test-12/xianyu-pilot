import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.ci import images


SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64


class ImagePublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for component in images.COMPONENTS:
            record = {"component": component, "revision": SHA, "image": images.image_name("12-test-12", component), "digest": DIGEST}
            (self.root / f"{component}.json").write_text(json.dumps(record), encoding="utf-8")

    def mutate(self, **values):
        path = self.root / "api.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(values)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_owner_scoped_names_and_safe_release_refs(self):
        self.assertEqual(images.image_name("User-Name", "api"), "ghcr.io/user-name/xianyu-assistant-api")
        self.assertEqual(images.release_tag("refs/heads/main"), "latest")
        self.assertEqual(images.release_tag("refs/tags/v1.2.3-rc.1"), "v1.2.3-rc.1")
        for ref in ("refs/heads/feature/test", "refs/tags/vinvalid", "refs/tags/v1/unsafe"):
            with self.assertRaises(ValueError):
                images.release_tag(ref)

    def test_missing_component_blocks_the_entire_promotion(self):
        (self.root / "crawler.json").unlink()
        with self.assertRaises(ValueError):
            images.validate_manifests(self.root, "12-test-12", SHA)

    def test_wrong_revision_namespace_and_invalid_digest_are_rejected(self):
        for values in ({"revision": "c" * 40}, {"image": "ghcr.io/other/api"}, {"digest": "latest"}):
            self.mutate(revision=SHA, image=images.image_name("12-test-12", "api"), digest=DIGEST)
            self.mutate(**values)
            with self.assertRaises(ValueError):
                images.validate_manifests(self.root, "12-test-12", SHA)

    def test_acr_mirror_uses_exact_digest_and_full_revision(self):
        records = images.validate_manifests(self.root, "12-test-12", SHA)
        commands = images.promotion_commands(records, "latest", "registry.example.com", "my-images")
        self.assertEqual(len(commands), 6)
        for command in commands:
            self.assertTrue(command[-1].endswith("@" + DIGEST))
            self.assertNotIn(":latest", command[-1])
        self.assertIn("registry.example.com/my-images/xianyu-assistant-api:sha-" + SHA, commands[1])

    def test_registry_injection_and_partial_configuration_are_rejected(self):
        records = images.validate_manifests(self.root, "12-test-12", SHA)
        for registry, owner in (("https://registry.example.com", "owner"), ("registry.example.com", ""), ("registry.example.com", "owner\nunsafe")):
            with self.assertRaises(ValueError):
                images.promotion_commands(records, "latest", registry, owner)

    def test_stale_main_never_updates_latest(self):
        env = {"GITHUB_REPOSITORY_OWNER": "12-test-12", "GITHUB_SHA": SHA, "GITHUB_REF": "refs/heads/main", "CURRENT_MAIN_SHA": "c" * 40}
        with patch.dict(os.environ, env, clear=True), patch("sys.argv", ["images.py", "promote", "--directory", str(self.root)]), patch.object(images.subprocess, "run") as run:
            images.main()
            run.assert_not_called()

    def test_no_docker_command_runs_if_any_manifest_is_invalid(self):
        self.mutate(digest="invalid")
        env = {"GITHUB_REPOSITORY_OWNER": "12-test-12", "GITHUB_SHA": SHA, "GITHUB_REF": "refs/heads/main", "CURRENT_MAIN_SHA": SHA}
        with patch.dict(os.environ, env, clear=True), patch("sys.argv", ["images.py", "promote", "--directory", str(self.root)]), patch.object(images.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                images.main()
            run.assert_not_called()
