#!/usr/bin/env python3
"""Copy configured ignored paths and create shared-path links in a new worktree."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def configured_directory_paths(source_root: Path, patterns_file: Path) -> list[str]:
    directories = set()
    for raw_pattern in patterns_file.read_text(encoding="utf-8").splitlines():
        pattern = raw_pattern.strip()
        if not pattern or pattern.startswith("#") or pattern.startswith("!"):
            continue
        if pattern.endswith("/**"):
            pattern = pattern[:-2]
        elif not pattern.endswith("/"):
            continue

        pattern = pattern.lstrip("/").rstrip("/")
        if not pattern:
            continue
        if "/" not in pattern:
            pattern = f"**/{pattern}"
        for path in source_root.glob(pattern):
            if path.is_dir() and not path.is_symlink():
                directories.add(f"{path.relative_to(source_root).as_posix()}/")
    return sorted(directories)


def ignored_paths(source_root: Path, patterns_file: Path) -> list[str]:
    # Avoid --directory: it would widen file matches to their ignored parent dirs.
    list_command = [
        "git",
        "-C",
        str(source_root),
        "ls-files",
        "--others",
        "--ignored",
        "-z",
        f"--exclude-from={patterns_file}",
    ]
    output = subprocess.check_output(list_command)
    candidates = {os.fsdecode(path) for path in output.split(b"\0") if path}
    candidates.update(configured_directory_paths(source_root, patterns_file))
    if not candidates:
        return []
    candidates = sorted(candidates)

    check_command = [
        "git",
        "-C",
        str(source_root),
        "check-ignore",
        "--no-index",
        "--stdin",
        "-z",
    ]
    result = subprocess.run(
        check_command,
        input=b"\0".join(os.fsencode(path) for path in candidates) + b"\0",
        capture_output=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            result.returncode,
            check_command,
            output=result.stdout,
            stderr=result.stderr,
        )

    ignored = {os.fsdecode(path) for path in result.stdout.split(b"\0") if path}
    matching = [path for path in candidates if path in ignored]
    matching.sort(key=lambda path: path.rstrip("/").count("/"))

    selected = []
    selected_paths = []
    for path in matching:
        normalized_path = path.rstrip("/")
        if any(
            normalized_path == parent or normalized_path.startswith(f"{parent}/")
            for parent in selected_paths
        ):
            continue
        selected.append(path)
        selected_paths.append(normalized_path)
    return selected


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def warn_skipped_symlink(source_path: Path, source_root: Path, reason: str) -> None:
    relative_path = source_path.relative_to(source_root)
    print(
        f"worktree includes: warning: skipping symlink {relative_path} ({reason})",
        file=sys.stderr,
    )


def copy_symlink_target(
    source_path: Path,
    target_path: Path,
    source_root: Path,
    copy_symlinks: bool,
) -> None:
    try:
        resolved_target = source_path.resolve(strict=True)
    except (OSError, RuntimeError):
        warn_skipped_symlink(source_path, source_root, "target cannot be resolved")
        return

    if is_within(resolved_target, source_root):
        target_root = source_root
    elif resolved_target.is_dir():
        target_root = resolved_target
    else:
        target_root = resolved_target.parent

    print(
        f"worktree includes: copying target contents for symlink "
        f"{source_path.relative_to(source_root)}",
        file=sys.stderr,
    )
    copy_included_entry(resolved_target, target_path, target_root, copy_symlinks)


def copy_included_entry(
    source_path: Path,
    target_path: Path,
    source_root: Path,
    copy_symlinks: bool = False,
    copy_external_symlink_targets: bool = False,
) -> None:
    if source_path.is_symlink():
        link_target = os.readlink(source_path)
        resolves_inside_source = False
        if not os.path.isabs(link_target):
            resolved_target = (source_path.parent / link_target).resolve(strict=False)
            resolves_inside_source = is_within(resolved_target, source_root)

        target_is_external = os.path.isabs(link_target) or not resolves_inside_source
        if target_is_external and copy_external_symlink_targets:
            copy_symlink_target(source_path, target_path, source_root, copy_symlinks)
            return

        if not copy_symlinks:
            reason = "symlink copying is disabled"
            if target_is_external:
                reason = (
                    "absolute target"
                    if os.path.isabs(link_target)
                    else "target escapes source worktree"
                )
            warn_skipped_symlink(source_path, source_root, reason)
            return

        if target_is_external and not os.path.isabs(link_target):
            print(
                "worktree includes: warning: copying relative external symlink "
                f"{source_path.relative_to(source_root)}; its target may resolve differently",
                file=sys.stderr,
            )

        target_path.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(target_path):
            if target_path.is_symlink() and os.readlink(target_path) == link_target:
                return
            raise FileExistsError(f"refusing to replace existing path: {target_path}")
        target_path.symlink_to(link_target)
        return

    if source_path.is_dir():
        if target_path.is_symlink():
            raise FileExistsError(f"refusing to copy through existing symlink: {target_path}")
        target_path.mkdir(parents=True, exist_ok=True)
        for child in source_path.iterdir():
            copy_included_entry(
                child,
                target_path / child.name,
                source_root,
                copy_symlinks,
                copy_external_symlink_targets,
            )
        return

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.is_symlink():
        raise FileExistsError(f"refusing to replace existing symlink: {target_path}")
    if target_path.exists():
        if target_path.is_file():
            return
        raise FileExistsError(f"refusing to replace existing path: {target_path}")
    shutil.copy2(source_path, target_path)


def copy_included_paths(
    source_root: Path,
    target_root: Path,
    patterns_file: Path,
    copy_symlinks: bool = False,
    copy_external_symlink_targets: bool = False,
) -> None:
    for relative_path in ignored_paths(source_root, patterns_file):
        relative_path = relative_path.rstrip("/")
        copy_included_entry(
            source_root / relative_path,
            target_root / relative_path,
            source_root,
            copy_symlinks,
            copy_external_symlink_targets,
        )


def git_bool_config(source_root: Path, key: str) -> bool:
    command = [
        "git",
        "-C",
        str(source_root),
        "config",
        "--local",
        "--bool",
        "--get",
        key,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode == 1:
        return False
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, command, output=result.stdout, stderr=result.stderr
        )
    return result.stdout.strip() == "true"


def external_symlink_copy_enabled(source_root: Path) -> bool:
    return git_bool_config(source_root, "worktree.copyExternalSymlinkTargets")


def symlink_copy_enabled(source_root: Path) -> bool:
    return git_bool_config(source_root, "worktree.copySymlinks")


def existing_source_path(source_path: Path) -> bool:
    return os.path.lexists(source_path)


def target_is_expected_link(target_path: Path, link_target: str) -> bool:
    return target_path.is_symlink() and os.readlink(target_path) == link_target


def create_link(source_root: Path, target_root: Path, relative_path: str) -> None:
    relative_path = relative_path.rstrip("/")
    if not relative_path:
        return

    source_path = source_root / relative_path
    target_path = target_root / relative_path
    if not existing_source_path(source_path):
        return

    link_target = str(source_path)
    if os.path.lexists(target_path):
        if target_is_expected_link(target_path, link_target):
            return
        raise FileExistsError(f"refusing to replace existing path: {target_path}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.symlink_to(link_target)


def main() -> int:
    if len(sys.argv) != 3:
        print(
            f"Usage: {Path(sys.argv[0]).name} SOURCE_WORKTREE TARGET_WORKTREE",
            file=sys.stderr,
        )
        return 2

    source_root = Path(sys.argv[1]).resolve(strict=True)
    target_root = Path(sys.argv[2]).resolve(strict=True)
    try:
        patterns_file = source_root / ".worktreelinks"
        include_patterns_file = source_root / ".worktreeinclude"
        if include_patterns_file.is_file():
            copy_included_paths(
                source_root,
                target_root,
                include_patterns_file,
                symlink_copy_enabled(source_root),
                external_symlink_copy_enabled(source_root),
            )
        if patterns_file.is_file():
            for relative_path in ignored_paths(source_root, patterns_file):
                create_link(source_root, target_root, relative_path)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"worktree setup: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
