# GitSapling

GitSapling prepares new linked worktrees by copying selected ignored files and linking shared paths from an existing checkout. Paths matched by the configuration are used only when Git also considers them ignored.

## Install

Copy the `worktree-setup/` directory into any folder inside the repository, then run its installer:

```sh
python3 path/to/worktree-setup/install-worktree-hook
```

The installer locates its sibling files from its own path and asks Git for the checkout root. It installs `post-checkout` and `setup-worktree-links.py` together in Git's hooks directory, so the bundle folder can have any name and location inside the checkout.

Requirements: Git and Python 3. The current primary-checkout lookup assumes a standard clone where the shared Git directory is `<checkout>/.git`. The installer refuses to override `core.hooksPath` or different existing hook/helper files; integrate the bundle manually if the repository already manages hooks.

## Configure paths

Create either or both of these files in the primary checkout root:

- `.worktreeinclude` lists ignored paths whose contents should be copied into a new worktree.
- `.worktreelinks` lists ignored paths that should be shared through symlinks pointing back to the primary checkout.

The files use Git exclude-pattern syntax. For example:

```text
# .worktreeinclude
/.env
/cache/**
```

```text
# .worktreelinks
/media/
```

Do not list a path in both files. Copying runs first, and a path copied into the target conflicts with creating a link at that same path.

Unignored paths listed in either file are skipped.

## Symlink behavior

By default, symlinks listed in `.worktreeinclude` are skipped with a warning. Configure either behavior in the primary checkout's local Git config:

```sh
git config --local worktree.copySymlinks true
```

This preserves the symlink itself. Absolute links are preserved as absolute links; relative links that point outside the source checkout may resolve differently from the new worktree.

To copy the contents of absolute or outside symlink targets instead, use:

```sh
git config --local worktree.copyExternalSymlinkTargets true
```

This setting takes precedence for external targets. It is opt-in because it can copy files from outside the repository. Both settings are local to the clone.

## Tests

Run the test suite with:

```sh
python3 -m unittest discover -s tests -v
```
