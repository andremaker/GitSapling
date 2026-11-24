from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TEST_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = Path(
    subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], cwd=TEST_DIRECTORY, text=True
    ).strip()
)
LIBRARY_DIRECTORY = REPOSITORY_ROOT / "worktree-setup"


def git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


def create_primary_worktree(temporary_path: Path) -> tuple[Path, Path, Path]:
    primary_worktree = temporary_path / "project"
    external_target = temporary_path / "external config"
    primary_worktree.mkdir()
    external_target.write_text("external config value\n", encoding="utf-8")

    git(primary_worktree, "init", "--initial-branch=feature/source")
    git(primary_worktree, "config", "user.name", "Worktree Test")
    git(primary_worktree, "config", "user.email", "worktree-test@example.invalid")

    tool_directory = primary_worktree / "support" / "toolbox" / "hook-kit"
    tool_directory.parent.mkdir(parents=True)
    shutil.copytree(LIBRARY_DIRECTORY, tool_directory)

    (primary_worktree / ".gitignore").write_text(
        "/.env\n/shared-data/\n/external-link\n/internal-link\n",
        encoding="utf-8",
    )
    (primary_worktree / ".worktreeinclude").write_text(
        "/.env\n/external-link\n/internal-link\n", encoding="utf-8"
    )
    (primary_worktree / ".worktreelinks").write_text("/shared-data/\n", encoding="utf-8")
    (primary_worktree / ".env").write_text("local config\n", encoding="utf-8")

    shared_data = primary_worktree / "shared-data"
    shared_data.mkdir()
    (shared_data / "asset.txt").write_text("shared asset\n", encoding="utf-8")
    (primary_worktree / "external-link").symlink_to(external_target)
    (primary_worktree / "internal-link").symlink_to("shared-data/asset.txt")
    (primary_worktree / "tracked.txt").write_text("tracked\n", encoding="utf-8")

    git(
        primary_worktree,
        "add",
        ".gitignore",
        ".worktreeinclude",
        ".worktreelinks",
        "support/toolbox/hook-kit",
        "tracked.txt",
    )
    git(primary_worktree, "commit", "-m", "initial commit")

    return primary_worktree, shared_data, external_target


def install_hook(primary_worktree: Path) -> subprocess.CompletedProcess[str]:
    installer = primary_worktree / "support/toolbox/hook-kit/install-worktree-hook"
    return subprocess.run(
        [sys.executable, str(installer)],
        cwd=primary_worktree,
        capture_output=True,
        text=True,
        check=False,
    )


def add_detached_worktree(
    primary_worktree: Path,
    target_worktree: Path,
) -> subprocess.CompletedProcess[str]:
    return git(primary_worktree, "worktree", "add", "--detach", str(target_worktree), "HEAD")


class TemporaryDirectoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="wt-")
        self.addCleanup(self._temporary_directory.cleanup)
        self.temporary_path = Path(self._temporary_directory.name)


class WorktreeCheckoutHookTest(TemporaryDirectoryTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.primary_worktree, self.shared_data, self.external_target = create_primary_worktree(self.temporary_path)

    def test_post_checkout_hook_sets_up_detached_worktree(self) -> None:
        target_worktree = self.temporary_path / "codex worktree"
        tool_directory = self.primary_worktree / "support/toolbox/hook-kit"

        installer = install_hook(self.primary_worktree)

        self.assertEqual(0, installer.returncode, installer.stderr)
        self.assertEqual(
            (tool_directory / "post-checkout").read_bytes(),
            (self.primary_worktree / ".git/hooks/post-checkout").read_bytes(),
        )
        self.assertEqual(
            (tool_directory / "setup-worktree-links.py").read_bytes(),
            (self.primary_worktree / ".git/hooks/setup-worktree-links.py").read_bytes(),
        )

        worktree_add = add_detached_worktree(self.primary_worktree, target_worktree)

        self.assertIn("warning: skipping symlink external-link", worktree_add.stderr)
        self.assertIn("symlink copying is disabled", worktree_add.stderr)
        self.assertEqual(
            "local config\n",
            (target_worktree / ".env").read_text(encoding="utf-8"),
        )
        self.assertFalse((target_worktree / "external-link").exists())
        self.assertFalse((target_worktree / "external-link").is_symlink())
        self.assertFalse((target_worktree / "internal-link").exists())
        self.assertFalse((target_worktree / "internal-link").is_symlink())

        linked_shared_data = target_worktree / "shared-data"
        self.assertTrue(linked_shared_data.is_symlink())
        self.assertEqual(self.shared_data.resolve(), linked_shared_data.resolve())
        self.assertEqual(
            "shared asset\n",
            (linked_shared_data / "asset.txt").read_text(encoding="utf-8"),
        )

    def test_checkout_hook_skips_file_checkout(self) -> None:
        target_worktree = self.temporary_path / "codex worktree"
        installer = install_hook(self.primary_worktree)
        self.assertEqual(0, installer.returncode, installer.stderr)
        add_detached_worktree(self.primary_worktree, target_worktree)

        (target_worktree / ".env").unlink()
        (target_worktree / "shared-data").unlink()

        ignored_checkout = subprocess.run(
            [
                sys.executable,
                str(self.primary_worktree / "support/toolbox/hook-kit/post-checkout"),
                "old-commit",
                "new-commit",
                "0",
            ],
            cwd=target_worktree,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, ignored_checkout.returncode, ignored_checkout.stderr)
        self.assertFalse((target_worktree / ".env").exists())
        self.assertFalse((target_worktree / "shared-data").is_symlink())

    def test_copy_symlinks_setting_preserves_included_symlinks(self) -> None:
        installer = install_hook(self.primary_worktree)
        self.assertEqual(0, installer.returncode, installer.stderr)
        git(self.primary_worktree, "config", "--local", "worktree.copySymlinks", "true")

        target_worktree = self.temporary_path / "symlink copy worktree"
        add_detached_worktree(self.primary_worktree, target_worktree)

        copied_internal_link = target_worktree / "internal-link"
        self.assertTrue(copied_internal_link.is_symlink())
        self.assertEqual("shared-data/asset.txt", str(copied_internal_link.readlink()))

        copied_external_link = target_worktree / "external-link"
        self.assertTrue(copied_external_link.is_symlink())
        self.assertEqual(str(self.external_target), str(copied_external_link.readlink()))

    def test_copy_external_symlink_targets_setting_copies_target_contents(self) -> None:
        installer = install_hook(self.primary_worktree)
        self.assertEqual(0, installer.returncode, installer.stderr)
        git(
            self.primary_worktree,
            "config",
            "--local",
            "worktree.copyExternalSymlinkTargets",
            "true",
        )

        target_worktree = self.temporary_path / "external copy worktree"
        external_copy = add_detached_worktree(self.primary_worktree, target_worktree)

        self.assertIn(
            "copying target contents for symlink external-link",
            external_copy.stderr,
        )
        self.assertIn("symlink copying is disabled", external_copy.stderr)

        copied_external_target = target_worktree / "external-link"
        self.assertEqual(
            "external config value\n",
            copied_external_target.read_text(encoding="utf-8"),
        )
        self.assertFalse(copied_external_target.is_symlink())
        self.assertFalse((target_worktree / "internal-link").exists())
        self.assertFalse((target_worktree / "internal-link").is_symlink())

    def test_installer_is_idempotent(self) -> None:
        first_install = install_hook(self.primary_worktree)
        second_install = install_hook(self.primary_worktree)

        self.assertEqual(0, first_install.returncode, first_install.stderr)
        self.assertEqual(0, second_install.returncode, second_install.stderr)
        self.assertEqual(
            (self.primary_worktree / "support/toolbox/hook-kit/post-checkout").read_bytes(),
            (self.primary_worktree / ".git/hooks/post-checkout").read_bytes(),
        )
        self.assertEqual(
            (self.primary_worktree / "support/toolbox/hook-kit/setup-worktree-links.py").read_bytes(),
            (self.primary_worktree / ".git/hooks/setup-worktree-links.py").read_bytes(),
        )


class WorktreeHookInstallerTest(TemporaryDirectoryTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.repository = self.temporary_path / "project"
        self.repository.mkdir()
        git(self.repository, "init", "--initial-branch=feature/source")

        self.tool_directory = self.repository / "tooling" / "git-hooks"
        self.tool_directory.parent.mkdir(parents=True)
        shutil.copytree(LIBRARY_DIRECTORY, self.tool_directory)
        self.installer = self.tool_directory / "install-worktree-hook"

    def test_installer_refuses_to_replace_existing_hook(self) -> None:
        hooks_directory = self.repository / ".git/hooks"
        hooks_directory.mkdir(parents=True, exist_ok=True)
        installed_hook = hooks_directory / "post-checkout"
        installed_hook.write_text("existing hook\n", encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(self.installer)],
            cwd=self.repository,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("refusing to replace existing hook", result.stderr)
        self.assertEqual("existing hook\n", installed_hook.read_text(encoding="utf-8"))

    def test_installer_refuses_to_replace_existing_helper(self) -> None:
        hooks_directory = self.repository / ".git/hooks"
        hooks_directory.mkdir(parents=True, exist_ok=True)
        installed_helper = hooks_directory / "setup-worktree-links.py"
        installed_helper.write_text("existing helper\n", encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(self.installer)],
            cwd=self.repository,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("refusing to replace existing helper", result.stderr)
        self.assertEqual("existing helper\n", installed_helper.read_text(encoding="utf-8"))

    def test_installer_refuses_custom_hooks_path(self) -> None:
        git(self.repository, "config", "core.hooksPath", ".githooks")

        result = subprocess.run(
            [sys.executable, str(self.installer)],
            cwd=self.repository,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("core.hooksPath is already configured", result.stderr)
        self.assertFalse((self.repository / ".git/hooks/post-checkout").exists())


if __name__ == "__main__":
    unittest.main()
