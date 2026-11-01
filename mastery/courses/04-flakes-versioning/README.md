# Course 04 · Flakes, pinning and versioning

**You will:** structure projects as flakes, decide exactly which version of everything you
get, run several versions of one program side by side, and update deliberately — with a
way back.

Course 03 pinned nixpkgs by hand in a `nixpkgs.nix` file. That works, but every project
invents its own way, and updating means editing hashes. Flakes standardise it: a
`flake.nix` declares **inputs** and **outputs**, and a machine-written `flake.lock` records
the exact revision and content hash of every input, transitively. The lock file *is* the
version of your project.

## Goals

After this course you can:

- read and write a `flake.nix`: inputs, outputs, systems, `self`;
- read a `flake.lock` and explain every field; deduplicate inputs with `follows`;
- choose a pinning strategy (branch, tag, commit) and update one input at a time with
  `nix flake update <input>` or by moving the pin and running `nix flake lock`;
- get a different version of a package in four ways: another nixpkgs, `overrideAttrs` with
  `finalAttrs.version`, an overlay, or a second nixpkgs input side by side;
- add `checks` and a `formatter`, and run `nix flake check` and `nix fmt`;
- keep non-flake users working with a `default.nix` that reads the same lock file;
- roll back an update with Git and prove the old result comes back bit for bit.

## Prerequisites

- Course 03 (you can write a `package.nix` and use `callPackage`, `overrideAttrs`,
  `lib.fakeHash`).
- `git` (installed in course 00). Flakes in a Git repository only see files that Git
  tracks — every lesson runs `git init` and `git add` for that reason.
- The `flakes` and `nix-command` experimental features, enabled in course 00:

```bash
nix config show experimental-features
git --version
```

```text expect
flakes
nix-command
git version
```

**Status of flakes.** As of Nix 2.35, flakes and the `nix` command are still *experimental
features*: very widely used, documented in the Nix manual, but their interface may still
change. The Nix team is stabilising them piece by piece. This course uses them, and lesson 4
shows how to keep a flake usable from the stable classic commands too.

## Structure

| File | What you do |
|---|---|
| [01-flake-anatomy.md](01-flake-anatomy.md) | Write a flake; the Git-tracking rule; `nix flake show`; read `flake.lock`; systems; `follows` |
| [02-pinning.md](02-pinning.md) | Branch vs commit pins; `nix flake metadata`; `nix flake update <input>`; moving a pin; `--override-input`; the registry |
| [03-changing-versions.md](03-changing-versions.md) | `overrideAttrs` with `finalAttrs.version` and a new `src`; overlays; a second nixpkgs input |
| [04-checks-formatter-compat.md](04-checks-formatter-compat.md) | `checks`, `nix flake check`, `formatter` with `nixfmt-tree`, `nix fmt`, a `default.nix` that reads `flake.lock` |
| [project-a-versions-on-demand.md](project-a-versions-on-demand.md) | **Project 04a:** hello from 26.05, from 25.11 and a custom version, side by side |
| [project-b-lock-hygiene.md](project-b-lock-hygiene.md) | **Project 04b:** add `follows`, update one input, inspect and revert the lock, prove the rollback |

Pins used throughout (from `CURATION.md`):

| nixpkgs | Commit | Channel |
|---|---|---|
| 26.05 | `fa1373130d5a21c040a47c5dbe1913d59ed91808` | nixos-26.05.13297 |
| 25.11 | `b6018f87da91d19d0ab4cf979885689b469cdd41` | nixos-25.11.12484 |

Both are channel commits: Hydra built them, so their packages come from `cache.nixos.org`.

## Patterns you will drill

- **The lock file is the version.** Not the branch name in `flake.nix`, not the date you
  last ran an update: the `rev` and `narHash` in `flake.lock`. Commit it, review its diffs,
  revert it like code.
- **Update one thing at a time.** `nix flake update nixpkgs`, not a blanket update before a
  release. A small lock diff is a reviewable change.
- **Overlays for policy, `overrideAttrs` for one package.** If *everything* that depends on
  a package should get your version, use an overlay. If you need one variant next to the
  original, use `overrideAttrs` and give it its own name.
- **`follows` to keep one nixpkgs.** Every flake you depend on brings its own nixpkgs
  unless you tell it to follow yours.

## Primary sources

- Nix reference manual 2.35: `nix flake` (`nix3-flake`), *Flake inputs*, *Lock files*,
  `nix flake lock`, `nix flake update`, `nix flake check`, `nix fmt`.
- Nixpkgs manual: *Overlays* (`doc/using/overlays.chapter.md`), *Overriding*
  (`doc/using/overrides.chapter.md`), *Fixed-point arguments of mkDerivation*.
- nixpkgs `flake.nix` (how `legacyPackages`, `lib` and `formatter` are exposed) and
  `pkgs/by-name/ni/nixfmt-tree/package.nix`.

## Check yourself

<details><summary>Your <code>flake.nix</code> says <code>github:NixOS/nixpkgs/nixos-26.05</code>. Which nixpkgs do you get?</summary>

The commit recorded in `flake.lock`, whenever it was locked — not today's tip of the
branch. The branch name only matters when the lock is created or updated
(`nix flake update nixpkgs`).

</details>

<details><summary>Why must new files be <code>git add</code>ed before <code>nix build</code> sees them?</summary>

For a flake in a Git repository, Nix copies only the files Git tracks into the store as
the flake's source. That keeps build results, secrets and editor junk out — and makes an
untracked file invisible. Staging is enough; you do not have to commit.

</details>

<details><summary>Overlay or <code>overrideAttrs</code>: you need curl with a patch for every package in your system that uses curl.</summary>

An overlay (`final: prev: { curl = prev.curl.overrideAttrs …; }`): it replaces `curl` in the
package set, so every dependent is rebuilt against the patched one. A plain `overrideAttrs`
gives you one patched curl next to the unpatched one that everything else still uses.

</details>
