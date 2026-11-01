# Course 03 · Packaging software

**You will:** package C, Go, Rust and Python programs the way nixpkgs does: fetch sources
with verified hashes, patch and wrap programs that assume a "normal" Linux, split outputs,
and ship tests with every package.

Course 01 showed you what a derivation *is*. Course 02 gave you the language. This course
is the craft: `stdenv.mkDerivation` and the builders layered on top of it. Everything you
write here is nixpkgs style, so it could go into `pkgs/by-name` with little change
(course 07 does exactly that).

## Goals

After this course you can:

- write a `package.nix` with `stdenv.mkDerivation (finalAttrs: { … })`, and explain each
  phase and hook it goes through;
- fetch sources with `fetchurl` / `fetchFromGitHub`, get their hashes by trust-on-first-use,
  and spot a stale hash;
- use `callPackage`, and choose between `override` and `overrideAttrs`;
- repair builds that hard-code `/usr` paths or expect tools on `$PATH`, using `patches`,
  `substituteInPlace` and `wrapProgram`;
- split a package into `out` and `dev` outputs;
- package Go, Rust and Python programs with `buildGoModule`, `buildRustPackage` and
  `buildPythonApplication`;
- attach tests to a package with `passthru.tests` and `versionCheckHook`.

## Prerequisites

- Course 00 (Nix ≥ 2.35.3 installed, multi-user).
- Courses 01 and 02, or equivalent: you know what a store path and a derivation are, and
  you can read a function that takes an attribute set.

This course uses the classic commands (`nix-build`, `nix-instantiate`) with nixpkgs pinned
in a file. That keeps the focus on packaging. Course 04 moves the same ideas into flakes.

```bash
nix --version
nix-instantiate --eval --expr 'builtins.compareVersions builtins.nixVersion "2.35.3" >= 0'
```

```text expect
true
```

## Structure

| File | What you do |
|---|---|
| [01-mkderivation.md](01-mkderivation.md) | Build a C program with `stdenv.mkDerivation (finalAttrs: …)`; read the phases; add hooks; see `__structuredAttrs` and `strictDeps` at work |
| [02-fetchers-hashes.md](02-fetchers-hashes.md) | `fetchurl`, `fetchFromGitHub`, flat vs recursive hashes, the `lib.fakeHash` workflow, the stale-hash trap, `lib.fileset` for local sources |
| [03-callpackage-override.md](03-callpackage-override.md) | `callPackage`, `override` vs `overrideAttrs`, why `finalAttrs` beats `rec`, `meta`, `passthru.tests`, `versionCheckHook` |
| [04-fixing-builds.md](04-fixing-builds.md) | `patches`, `substitute`/`substituteInPlace`, `makeWrapper`/`wrapProgram`, multiple outputs |
| [05-language-builders.md](05-language-builders.md) | `buildGoModule`, `buildRustPackage`, `buildPythonApplication` and the dependency derivations behind them |
| [project-a-hello-tarball.md](project-a-hello-tarball.md) | **Project 03a:** GNU hello from its release tarball, with a deliberate hash mismatch |
| [project-b-repair-build.md](project-b-repair-build.md) | **Project 03b:** repair a C tool with a hard-coded `/usr` path and a runtime dependency; prove it in `env -i` |
| [project-c-three-languages.md](project-c-three-languages.md) | **Project 03c:** one CLI, three languages, each with a `passthru.tests` version check |

Every file is self-contained: it creates its own sources in an empty directory. To check
your own work, run a file the way CI does:

```bash skip
mkdir -p ~/scratch/03 && cd ~/scratch/03
python3 ~/nix-on-xfce-guide/mastery/ci/mdrun.py ~/nix-on-xfce-guide/mastery/courses/03-packaging/01-mkderivation.md
```

## Patterns you will drill

- **`package.nix` is a function of its dependencies.** It never imports nixpkgs itself.
  Whoever calls it (`callPackage`) decides which `stdenv`, which `fetchurl`, which
  version of each library. That is what makes overriding and cross-compiling possible.
- **Trust on first use (TOFU) for hashes.** You never invent a hash. You write a fake one,
  let Nix download and tell you the real one, check it, and commit it. From then on the
  hash *is* the source.
- **Tests travel with the package.** `passthru.tests` and `versionCheckHook` live in the
  same file as the build, so whoever changes the package runs them.
- **Patch the path in, don't search for it at runtime.** A Nix package names its
  dependencies by store path. `substituteInPlace` and `wrapProgram` are the two ways to
  get those paths into a program that was written for `/usr`.

## Primary sources

- Nixpkgs manual, *The Standard Environment* (`doc/stdenv/stdenv.chapter.md` in nixpkgs):
  phases, hooks, `__structuredAttrs`, `strictDeps`, `substituteInPlace`, `makeWrapper`.
- Nixpkgs manual, *Fetchers* (`doc/build-helpers/fetchers.chapter.md`) and *Obtaining
  source hash* (`doc/contributing/coding-conventions.chapter.md`).
- Nixpkgs manual, *Overriding* (`doc/using/overrides.chapter.md`), *Meta-attributes*
  (`doc/stdenv/meta.chapter.md`), *Passthru-attributes* (`doc/stdenv/passthru.chapter.md`),
  *Testers* (`doc/build-helpers/testers.chapter.md`).
- Nixpkgs manual, language sections: `doc/languages-frameworks/{go,rust,python}.section.md`.
- The real thing: `pkgs/by-name/he/hello/package.nix` in nixpkgs 26.05.

## Check yourself

<details><summary>Why does a <code>package.nix</code> take <code>stdenv</code> and <code>fetchurl</code> as arguments instead of importing nixpkgs?</summary>

So the caller controls them. `callPackage` fills them from one package set, so every
package in that set agrees on one compiler and one libc. An overlay, `override`, or
cross-compilation (`pkgsCross.aarch64-multiplatform.callPackage`) can swap them without
touching the file.

</details>

<details><summary>Where does the hash of a source come from, the first time?</summary>

From a build that is meant to fail. You set `hash = lib.fakeHash;`, Nix downloads the file,
computes its hash, reports the mismatch with the real value, and you copy that value in.
That is trust on first use. Check it against upstream's published checksum or signature
where one exists.

</details>

<details><summary>A program runs fine in your terminal but fails under <code>env -i</code>. What does that tell you?</summary>

It depends on something in your environment, usually `$PATH`, that the package did not
declare. In Nix that is a bug. Fix it by patching the store path into the program
(`substituteInPlace`) or by wrapping it (`wrapProgram --prefix PATH`).

</details>
