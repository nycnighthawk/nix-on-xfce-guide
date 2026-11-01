# Course 07 · Contributing to nixpkgs and Nix

**Goal:** make a contribution nixpkgs would accept, and know how the project around it works:
where the code lives, which branch a change goes to, what CI checks, who reviews it, and how it
reaches users.

By the end you can:

- find any package's file and explain how `pkgs/by-name` turns a directory into an attribute;
- pick the right base branch (`master`, `staging`, `release-26.05`) and backport correctly;
- write a `package.nix` that passes review on the first round: `finalAttrs`,
  `__structuredAttrs`, `strictDeps`, a correct `meta`, tests, an update script;
- run the checks CI runs — build, `passthru.tests`, `checkMeta` evaluation, nixfmt/treefmt,
  `nixpkgs-vet`, commit-message lint — on your own machine, before you push;
- write commit messages and a PR description in nixpkgs' format, and add yourself as a
  maintainer;
- see where else you can contribute: NixOS modules and tests, the manuals, `lib`, Nix itself
  (C++), and RFCs.

## Prerequisites

- Courses 00–03 (you can write and build a `stdenv.mkDerivation (finalAttrs: …)` package).
- Course 06 L4 helps for the NixOS-module part of lesson 4, but isn't required.
- About 3 GB of free disk for the project (a shallow nixpkgs checkout plus what CI's tools
  copy into the store) and a GitHub account if you want to open a real PR afterwards (none of
  the commands here need one, or a token).

## Structure

| File | What you do |
|---|---|
| [01-layout-and-workflow.md](01-layout-and-workflow.md) | Tour the tree; reproduce `pkgs/by-name` auto-wiring with nixpkgs' own overlay; branches, channels, staging, backports |
| [02-the-checklist.md](02-the-checklist.md) | Build a package that follows every convention; see *why* `finalAttrs`, `__structuredAttrs` and `strictDeps` matter; `meta` rules; nixfmt; what `nixpkgs-vet` enforces |
| [03-testing-like-ci.md](03-testing-like-ci.md) | What CI runs on a PR; `nix-build -A`, `--check`, `passthru.tests`, cross evaluation; `nixpkgs-review wip` / `pr` |
| [04-commits-prs-and-beyond.md](04-commits-prs-and-beyond.md) | Commit conventions (with a local lint), the PR template, maintainer entries, `passthru.updateScript`, backports with `cherry-pick -x`; NixOS modules, docs, Nix itself, RFCs |
| [project-a-contribution-rehearsal.md](project-a-contribution-rehearsal.md) | Package a real upstream (`greet`, in this repository) in a nixpkgs checkout at the pinned commit, pass every CI check locally, and produce the commits as patches ready for a PR |

The upstream you package in the project lives in [`mastery/src/greet/`](../../src/greet/): a
small C program with a `Makefile` that honours `PREFIX` and `DESTDIR`, released as the git tag
`greet-v1.0.0` of this repository.

## Patterns you'll drill

- **The package directory is the unit of review.** Everything a package needs is in
  `pkgs/by-name/<sh>/<name>/`; nothing outside it refers in, and it refers to nothing outside.
- **Arguments are the interface.** `package.nix` is a function of exactly the dependencies it
  uses; `callPackage` fills them in by name and `.override` replaces them.
- **Small reviewable commits.** One logical change per commit, titled `attr: what changed`,
  because the title is also what CI uses to decide what to build.
- **Tests and maintainers travel with the package.** `passthru.tests` lets anyone (and CI, and
  the update bot) check a change; `meta.maintainers` says who gets asked.
- **Run CI before CI does.** Every check in the project is the same command, or the same
  derivation, that nixpkgs' GitHub workflows run.

## Primary sources

All in the nixpkgs 26.05 tree (the pinned commit):
`CONTRIBUTING.md`, `pkgs/README.md`, `pkgs/by-name/README.md`, `maintainers/README.md`,
`maintainers/maintainer-list.nix` (header comment), `doc/stdenv/stdenv.chapter.md`,
`doc/build-helpers/testers.chapter.md`, `doc/hooks/versionCheckHook.section.md`,
`pkgs/top-level/by-name-overlay.nix`, `pkgs/top-level/stage.nix`, `ci/default.nix`,
`ci/nixpkgs-vet.nix`, `ci/treefmt.nix`, `ci/github-script/lint-commits.ts`,
`.github/workflows/lint.yml`, `.github/PULL_REQUEST_TEMPLATE.md`.
Outside nixpkgs: the RFC repository (github.com/NixOS/rfcs) and the Nix repository
(github.com/NixOS/nix).

## Check yourself

<details><summary>Why does a new package not need a line in <code>all-packages.nix</code>?</summary>

Because `pkgs/top-level/stage.nix` applies the overlay from
`pkgs/top-level/by-name-overlay.nix`, which reads `pkgs/by-name/*/*` and defines each
directory name as an attribute: `name = self.callPackage ./by-name/<sh>/<name>/package.nix { }`.
You still edit `all-packages.nix` only to pass non-default arguments.
</details>

<details><summary>Your change rebuilds 1 400 packages. Which branch?</summary>

`staging`. The rule of thumb in `CONTRIBUTING.md` ("Changes causing mass rebuilds"): 500 or
more rebuilds, consider `staging`; 1000 or more is a mass rebuild and must target `staging`.
CI's `rebuild` labels tell you the number.
</details>

<details><summary>What does the commit title <code>greet: init at 1.0.0</code> do besides describe the change?</summary>

The `greet:` prefix tells CI which attribute to build (and its `passthru.tests`); see the
"Commit conventions" table in `pkgs/README.md`. CI also lints titles: they need `: `, no
trailing period, and no Conventional-Commits style `feat:`.
</details>
