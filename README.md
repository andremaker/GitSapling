# GitSapling

Reduce build time and storage use across worktrees in multi-agent workflows. GitSapling automatically shares selected Git-ignored folders and files through symlinks. It also brings `.worktreeinclude` support to tools that do not provide it natively, copying selected paths into each new worktree.

## Sharing and copying selected paths

After installation, GitSapling runs when you create a linked worktree with `git worktree add`:
- Paths in `.worktreeinclude` are copied into the new worktree. Later changes to the original copies do not appear in the new worktree.
- Paths in `.worktreelinks` are symlinked back to the primary checkout. Both worktrees use the same files.

GitSapling uses the same Git-style pattern matching and ignore checks for both files. Paths selected by `.worktreeinclude` are excluded from `.worktreelinks`, whether copying is enabled or not. Paths Git does not consider ignored in the primary checkout are skipped.

`.worktreeinclude` copying is disabled by default to avoid duplicating support provided by other worktree tools like Claude or Codex. To enable copying for a tool without native support, run:

```sh
git config --local worktree.copyIncludes true
```


## Install

Requirements: Git and Python 3.

From the repository's primary checkout, run:

```sh
python3 path/to/gitsapling/install-worktree-hook
```

This installs the hook used by GitSapling. To avoid conflict, if Git already uses a custom hooks directory (`core.hooksPath`), or a different `post-checkout` hook is already installed, the installer stops rather than replace it. The current primary-checkout lookup expects a standard clone with a `.git` directory at its root.

## Choose what to share or copy

Create either or both of these files in the primary checkout's root:

- `.worktreeinclude` for paths to copy
- `.worktreelinks` for paths to share through symlinks

Each file uses Git ignore-pattern syntax. Patterns select which ignored paths GitSapling should handle; Git's ignore rules determine whether a selected path is eligible. For example, if `.vscode/` is ignored, you can select one file inside it without copying or linking the whole folder:

```text
# .worktreelinks
/.vscode/settings.json
```

To share an ignored media folder and copy an ignored environment file, you could use:

```text
# .worktreelinks
/media/

# .worktreeinclude
/.env
```

Use a trailing slash, such as `/folder/`, to share a whole directory with one symlink. To share matching files individually, use a wildcard pattern such as `/folder/*.ext`; GitSapling creates a separate symlink for each matching file.

Paths that Git does not ignore are skipped, even when listed, as are already copied by git itself. Either pattern file may be absent if you only need the other behavior.

## Symlinks in copied paths

This section applies when a path selected in `.worktreeinclude` is itself a symlink. By default, GitSapling skips that symlink and prints a warning.

To preserve the symlink in the new worktree, enable this setting in the primary checkout:

```sh
git config --local worktree.copySymlinks true
```

The new symlink keeps its original target. The target's contents are not copied along with it; select the target separately if you need a copy. Absolute symlinks stay absolute. Relative symlinks that point outside the checkout may resolve to a different location from the new worktree.

To copy the contents of an absolute or outside symlink target instead of preserving the symlink, enable:

```sh
git config --local worktree.copyExternalSymlinkTargets true
```

This option is off by default. It can copy files from outside the checkout. Both settings are local to the clone and affect copying through `.worktreeinclude`; they do not change the symlinks created by `.worktreelinks`.

## Run the tests

From the repository root, run:

```sh
python3 -m unittest discover -s tests -v
```
