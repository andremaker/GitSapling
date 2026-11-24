from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path


TEST_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = Path(
    subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], cwd=TEST_DIRECTORY, text=True
    ).strip()
)
SCRIPT_PATH = REPOSITORY_ROOT / "worktree-setup" / "setup-worktree-links.py"
SPEC = importlib.util.spec_from_file_location("copy_worktree_includes", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
copier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(copier)


class CopyWorktreeIncludesTest(unittest.TestCase):
    def test_does_not_copy_unignored_path_matching_include_pattern(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wt-") as temporary_directory:
            temporary_path = Path(temporary_directory)
            source_root = temporary_path / "source"
            target_root = temporary_path / "target"
            source_root.mkdir()
            target_root.mkdir()

            (source_root / ".gitignore").write_text(
                "/ignored.txt\n/sandbox\n", encoding="utf-8"
            )
            (source_root / "ignored.txt").write_text("ignored value\n", encoding="utf-8")
            (source_root / "plain.txt").write_text("plain value\n", encoding="utf-8")
            (source_root / "plain-link").symlink_to("ignored.txt")
            sandbox = source_root / "sandbox"
            sandbox.mkdir()
            (sandbox / "copied.txt").write_text("sandbox value\n", encoding="utf-8")
            (sandbox / "copied-link").symlink_to("copied.txt")
            (sandbox / "unlisted.txt").write_text("unlisted sandbox value\n", encoding="utf-8")
            patterns_file = source_root / ".worktreeinclude"
            patterns_file.write_text(
                "/ignored.txt\n/sandbox/copied.txt\n/sandbox/copied-link\n"
                "/plain.txt\n/plain-link\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init", str(source_root)], check=True, capture_output=True)

            paths = copier.ignored_paths(source_root, patterns_file)
            copier.copy_included_paths(source_root, target_root, patterns_file, copy_symlinks=True)

            self.assertCountEqual(
                ["ignored.txt", "sandbox/copied.txt", "sandbox/copied-link"],
                paths,
            )
            self.assertEqual("ignored value\n", (target_root / "ignored.txt").read_text(encoding="utf-8"))
            self.assertEqual("sandbox value\n", (target_root / "sandbox/copied.txt").read_text(encoding="utf-8"))
            self.assertTrue((target_root / "sandbox/copied-link").is_symlink())
            self.assertEqual("copied.txt", os.readlink(target_root / "sandbox/copied-link"))
            self.assertFalse((target_root / "sandbox/unlisted.txt").exists())
            self.assertFalse((target_root / "plain.txt").exists())
            self.assertFalse(os.path.lexists(target_root / "plain-link"))

    def test_copies_relative_symlink_resolving_inside_source_worktree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wt-") as temporary_directory:
            temporary_path = Path(temporary_directory)
            source_root = temporary_path / "source"
            target_root = temporary_path / "target"
            resource_file = source_root / "resources" / "data" / "item.txt"
            link_path = source_root / "build" / "cache" / "data"
            resource_file.parent.mkdir(parents=True)
            link_path.parent.mkdir(parents=True)
            target_root.mkdir()

            resource_file.write_text("resource contents", encoding="utf-8")
            link_path.symlink_to("../../resources/data")
            (source_root / ".gitignore").write_text("/build/\n/resources/\n", encoding="utf-8")
            patterns_file = source_root / ".worktreeinclude"
            patterns_file.write_text("/build/**\n/resources/**\n", encoding="utf-8")
            subprocess.run(["git", "init", str(source_root)], check=True, capture_output=True)

            paths = copier.ignored_paths(source_root, patterns_file)
            self.assertIn("build/", paths)
            self.assertIn("resources/", paths)
            copier.copy_included_paths(
                source_root.resolve(),
                target_root,
                patterns_file,
                copy_symlinks=True,
            )
            copied_link = target_root / "build" / "cache" / "data"

            self.assertTrue(copied_link.is_symlink())
            self.assertEqual("../../resources/data", str(copied_link.readlink()))
            copied_resource = target_root / "resources/data/item.txt"
            self.assertEqual("resource contents", copied_resource.read_text(encoding="utf-8"))

    def test_skips_and_warns_for_internal_symlink_by_default(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wt-") as temporary_directory:
            temporary_path = Path(temporary_directory)
            source_root = temporary_path / "source"
            target_root = temporary_path / "target"
            source_file = source_root / "source.txt"
            source_link = source_root / "included-link"
            source_root.mkdir()
            target_root.mkdir()

            source_file.write_text("source value\n", encoding="utf-8")
            source_link.symlink_to("source.txt")

            warnings = io.StringIO()
            with redirect_stderr(warnings):
                copier.copy_included_entry(source_link, target_root / "included-link", source_root)

            self.assertFalse((target_root / "included-link").exists())
            self.assertFalse((target_root / "included-link").is_symlink())
            self.assertIn("symlink copying is disabled", warnings.getvalue())

    def test_preserves_existing_target_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wt-") as temporary_directory:
            temporary_path = Path(temporary_directory)
            source_root = temporary_path / "source"
            target_root = temporary_path / "target"
            source_file = source_root / ".env"
            target_file = target_root / ".env"
            source_root.mkdir()
            target_root.mkdir()

            source_file.write_text("source value\n", encoding="utf-8")
            target_file.write_text("target value\n", encoding="utf-8")

            copier.copy_included_entry(source_file, target_file, source_root)

            self.assertEqual("target value\n", target_file.read_text(encoding="utf-8"))

    def test_warns_when_symlink_target_escapes_source_worktree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wt-") as temporary_directory:
            temporary_path = Path(temporary_directory)
            source_root = temporary_path / "source"
            target_root = temporary_path / "target"
            outside_file = temporary_path / "secret"
            source_path = source_root / "build" / "cache"
            source_path.mkdir(parents=True)
            target_root.mkdir()

            outside_file.write_text("outside source", encoding="utf-8")
            (source_path / "escape").symlink_to(os.path.relpath(outside_file, source_path))

            warnings = io.StringIO()
            with redirect_stderr(warnings):
                copier.copy_included_entry(
                    source_root / "build",
                    target_root / "build",
                    source_root.resolve(),
                )

            self.assertFalse((target_root / "build/cache/escape").exists())
            self.assertFalse((target_root / "build/cache/escape").is_symlink())
            self.assertIn(
                "warning: skipping symlink build/cache/escape",
                warnings.getvalue(),
            )
            self.assertIn("target escapes source worktree", warnings.getvalue())
            self.assertNotIn(str(outside_file), warnings.getvalue())

    def test_warns_when_symlink_target_is_absolute(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wt-") as temporary_directory:
            temporary_path = Path(temporary_directory)
            source_root = temporary_path / "source"
            target_root = temporary_path / "target"
            source_path = source_root / "build" / "cache"
            source_path.mkdir(parents=True)
            target_root.mkdir()

            (source_path / "absolute").symlink_to(temporary_path / "outside")

            warnings = io.StringIO()
            with redirect_stderr(warnings):
                copier.copy_included_entry(
                    source_root / "build",
                    target_root / "build",
                    source_root.resolve(),
                )

            self.assertFalse((target_root / "build/cache/absolute").exists())
            self.assertFalse((target_root / "build/cache/absolute").is_symlink())
            self.assertIn(
                "warning: skipping symlink build/cache/absolute",
                warnings.getvalue(),
            )
            self.assertIn("absolute target", warnings.getvalue())


if __name__ == "__main__":
    unittest.main()
