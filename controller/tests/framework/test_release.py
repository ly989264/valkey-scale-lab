from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from controller.release import FrameworkIntegrityError, verify_framework_release


FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_PATH = FRAMEWORK_ROOT / "CONTROLLER_LAUNCH.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReleaseFixture:
    def __init__(self, root: Path):
        self.root = root / "framework"
        self.receipt = root / "operator/framework_receipt.json"
        (self.root / "src/controller").mkdir(parents=True)
        (self.root / "codex").mkdir(parents=True)
        self.receipt.parent.mkdir(parents=True)
        shutil.copyfile(LAUNCHER_PATH, self.root / "CONTROLLER_LAUNCH.py")
        (self.root / "src/controller/__init__.py").write_text(
            "print('IMPORTED_CONTROLLER_PACKAGE')\n", encoding="utf-8"
        )
        (self.root / "src/controller/__main__.py").write_text(
            "print('CONTROLLER_BOOTED')\n", encoding="utf-8"
        )
        self.reseal_for_test()

    @property
    def manifest(self) -> Path:
        return self.root / "codex/framework_manifest.json"

    def reseal_for_test(self) -> None:
        files = []
        for raw in ("CONTROLLER_LAUNCH.py", "src"):
            path = self.root / raw
            candidates = [path] if path.is_file() else sorted(
                candidate for candidate in path.rglob("*") if candidate.is_file()
            )
            files.extend(
                {
                    "path": candidate.relative_to(self.root).as_posix(),
                    "sha256": digest(candidate),
                }
                for candidate in candidates
            )
        value = {
            "schema_version": "controller-framework-manifest-v1",
            "framework_version": "2.0.0",
            "roots": ["CONTROLLER_LAUNCH.py", "src"],
            "files": files,
            "protected_paths": [
                "CONTROLLER_LAUNCH.py",
                "codex/framework_manifest.json",
            ],
        }
        self.manifest.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        receipt = {
            "schema_version": "controller-framework-receipt-v1",
            "framework_version": "2.0.0",
            "manifest_sha256": digest(self.manifest),
        }
        self.receipt.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.receipt.chmod(0o600)

    def launch(self, *, with_receipt: bool = True) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.pop("CONTROLLER_FRAMEWORK_RECEIPT", None)
        if with_receipt:
            environment["CONTROLLER_FRAMEWORK_RECEIPT"] = str(self.receipt)
        return subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(self.root / "CONTROLLER_LAUNCH.py")],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )


class FrameworkReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = ReleaseFixture(Path(temporary.name).resolve())

    def test_release_verifier_accepts_an_authorized_complete_closure(self) -> None:
        release = verify_framework_release(
            self.fixture.root,
            self.fixture.manifest,
            self.fixture.receipt,
        )

        self.assertEqual(release.version, "2.0.0")
        self.assertEqual(release.manifest_digest, digest(self.fixture.manifest))
        self.assertIn("CONTROLLER_LAUNCH.py", release.protected_paths)

    def test_external_receipt_must_authorize_the_exact_manifest(self) -> None:
        receipt = json.loads(self.fixture.receipt.read_text(encoding="utf-8"))
        receipt["manifest_sha256"] = "0" * 64
        self.fixture.receipt.write_text(json.dumps(receipt), encoding="utf-8")
        self.fixture.receipt.chmod(0o600)

        with self.assertRaisesRegex(FrameworkIntegrityError, "not authorized"):
            verify_framework_release(
                self.fixture.root,
                self.fixture.manifest,
                self.fixture.receipt,
            )

    def test_receipt_inside_framework_is_not_an_external_authority(self) -> None:
        embedded = self.fixture.root / "embedded_receipt.json"
        shutil.copyfile(self.fixture.receipt, embedded)
        embedded.chmod(0o600)

        with self.assertRaisesRegex(FrameworkIntegrityError, "outside"):
            verify_framework_release(
                self.fixture.root,
                self.fixture.manifest,
                embedded,
            )

    def test_file_drift_and_unlisted_files_break_the_closure(self) -> None:
        (self.fixture.root / "src/controller/__main__.py").write_text(
            "print('TAMPERED')\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(FrameworkIntegrityError, "file drift"):
            verify_framework_release(
                self.fixture.root,
                self.fixture.manifest,
                self.fixture.receipt,
            )

        self.fixture.reseal_for_test()
        (self.fixture.root / "src/controller/unlisted.py").write_text("pass\n", encoding="utf-8")
        with self.assertRaisesRegex(FrameworkIntegrityError, "closure mismatch"):
            verify_framework_release(
                self.fixture.root,
                self.fixture.manifest,
                self.fixture.receipt,
            )

    def test_symlink_in_hashed_closure_is_rejected(self) -> None:
        target = self.fixture.root / "outside.py"
        target.write_text("pass\n", encoding="utf-8")
        link = self.fixture.root / "src/controller/link.py"
        link.symlink_to(target)

        with self.assertRaisesRegex(FrameworkIntegrityError, "symlink"):
            verify_framework_release(
                self.fixture.root,
                self.fixture.manifest,
                self.fixture.receipt,
            )

    def test_launcher_verifies_before_importing_controller(self) -> None:
        completed = self.fixture.launch()
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("IMPORTED_CONTROLLER_PACKAGE", completed.stdout)
        self.assertIn("CONTROLLER_BOOTED", completed.stdout)

        (self.fixture.root / "src/controller/__main__.py").write_text(
            "print('SHOULD_NOT_IMPORT')\n", encoding="utf-8"
        )
        completed = self.fixture.launch()
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("framework file drift", completed.stdout)
        self.assertNotIn("IMPORTED_CONTROLLER_PACKAGE", completed.stdout)
        self.assertNotIn("SHOULD_NOT_IMPORT", completed.stdout)

    def test_launcher_fails_closed_without_external_receipt(self) -> None:
        completed = self.fixture.launch(with_receipt=False)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("CONTROLLER_FRAMEWORK_RECEIPT", completed.stdout)
        self.assertNotIn("IMPORTED_CONTROLLER_PACKAGE", completed.stdout)

    def test_launcher_bootstrap_imports_only_the_standard_library(self) -> None:
        source = LAUNCHER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module != "__future__"
        }
        self.assertEqual(
            imported,
            {"hashlib", "json", "os", "re", "runpy", "sys", "pathlib"},
        )
        self.assertLess(source.index("_verify_release("), source.index("sys.path.insert("))
        self.assertLess(source.index("sys.path.insert("), source.index('runpy.run_module("controller"'))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
