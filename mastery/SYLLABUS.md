# Nix mastery path — syllabus

Nine courses, from how the store works to contributing to nixpkgs. Each course lists its
**goals** (what you can do afterwards), its **structure** (lessons → projects), and the
**patterns** it drills. Every lesson and project is runnable and tested on Xubuntu by CI.

Target: Xubuntu 26.04 (or any Ubuntu-based Xfce desktop) with Nix 2.35.3+ installed the
multi-user way. Course 00 sets that up.

```
00 Setup ─► 01 How Nix works ─► 02 The Nix language ─► 03 Packaging ─► 04 Flakes & versioning
                                                                         │
             08 Capstone ◄─ 07 Contributing ◄─ 06 Modules & NixOS ◄─ 05 Nix in practice
```

---

## 00 · Setup and first contact
**Goals:** install Nix correctly on Xubuntu; know the two CLIs (classic, `nix`); run software
without installing it; read a store path.
**Structure:**
- L1 Install and verify (version ≥ 2.35.3, daemon, `nix.conf`, flakes on)
- L2 First commands: `nix-shell -p`, `nix shell`, `nix run`, `nix search`, store paths
- **Project 00 — Throwaway tool belt:** a script with a `nix-shell` shebang that pins its own
  tools; runs identically on any machine with Nix.
**Patterns:** ad-hoc environments; reproducible scripts.

## 01 · How Nix works
**Goals:** explain the store, derivations, input addressing, realisation, closures, the
sandbox, the daemon, substituters and garbage collection — and prove each claim with a command.
**Structure:**
- L1 The store and store paths (hash parts, immutability, `nix path-info`)
- L2 Derivations: instantiate vs realise; `.drv` files; `nix derivation show`
- L3 Closures, references and the binary cache (`nix-store -q --tree`, substituters, signatures)
- L4 Purity: the sandbox, build users, what a builder can and cannot see
- L5 Garbage collection and GC roots
- **Project 01a — A derivation by hand:** write a raw `derivation { … }` with only bash and
  coreutils; change one input and watch the output path change.
- **Project 01b — Prove reproducibility:** rebuild and compare (`--rebuild`), find a
  non-deterministic build and fix it, compare closures.
**Patterns:** input addressing; dependency discovery by scanning; content-addressed fetches.

## 02 · The Nix language
**Goals:** read and write any Nix expression; understand laziness, functions, attribute sets,
string context and fixed points well enough to read nixpkgs code.
**Structure:**
- L1 Values, attribute sets, `let`/`inherit`/`with`, lists, strings and interpolation
- L2 Functions: currying, attribute-set patterns, defaults, `@`-patterns
- L3 Laziness, recursion, `rec`, and why `nix-instantiate --eval --strict` exists
- L4 Paths, imports, string context (why `"${./file}"` copies to the store)
- L5 Fixed points and overlays from scratch (`lib.fix`, `lib.extends`)
- **Project 02a — A tested mini library:** small functions with unit tests run by
  `lib.debug.runTests` via `nix eval`.
- **Project 02b — Build your own overlay system:** implement `fix` and `extends`, then show
  nixpkgs' overlays behave identically.
**Patterns:** function-of-attrset interfaces; laziness as configuration; fixed-point extension.

## 03 · Packaging software
**Goals:** package C, Go, Rust and Python software the way nixpkgs does; handle fetching,
hashes, patches, wrappers, multiple outputs and tests.
**Structure:**
- L1 `stdenv.mkDerivation (finalAttrs: …)`, phases and hooks, `__structuredAttrs`
- L2 Fetchers and hashes: `fetchurl`, `fetchFromGitHub`, the `lib.fakeHash` workflow
- L3 `callPackage`, overriding (`override` vs `overrideAttrs`), `meta`, `passthru.tests`
- L4 Fixing builds: patches, `substituteInPlace`, `makeWrapper`, outputs
- L5 Language builders: `buildGoModule`, `buildRustPackage`, `buildPythonApplication`
- **Project 03a — GNU hello from a tarball,** including a deliberate hash mismatch.
- **Project 03b — Repair a broken build:** a C tool with a hard-coded path and a runtime
  dependency; patch and wrap it.
- **Project 03c — One tool, three languages:** the same CLI packaged with the Go, Rust and
  Python builders, each with a `passthru.tests` version check.
**Patterns:** `package.nix` as a function of its dependencies; trust-on-first-use hashes;
tests travel with the package.

## 04 · Flakes, pinning and versioning
**Goals:** structure projects as flakes; control exactly which versions you get; run several
versions side by side; update deliberately and roll back.
**Structure:**
- L1 Flake anatomy: inputs, outputs, `flake.lock`, `follows`, systems
- L2 Pinning strategies: branch vs commit, `nix flake update <input>`, `nix flake metadata`
- L3 Changing versions: `overrideAttrs` with `finalAttrs.version`, overlays, a second nixpkgs
- L4 `checks`, `formatter`, `nix flake check`, classic compatibility (`default.nix`)
- **Project 04a — Versions on demand:** one flake that exposes hello from 26.05, from 25.11
  and a custom version via overlay, all buildable side by side.
- **Project 04b — Lock hygiene:** add `follows`, update a single input, inspect and revert
  the lock, prove a rollback rebuilds the old result.
**Patterns:** the lock file is the version; overlays for policy, `overrideAttrs` for one package.

## 05 · Nix in practice
**Goals:** use Nix day to day: dev shells, caches, containers and cross-compilation.
**Structure:**
- L1 Dev shells: `mkShell`, `inputsFrom`, `shellHook`, direnv
- L2 Binary caches: signing keys, `nix copy`, a file cache, trust settings
- L3 Containers with `dockerTools` (no Dockerfile)
- L4 Cross-compilation and static builds: `pkgsCross`, `pkgsStatic`
- **Project 05a — Signed cache round trip:** build, sign, push to a local cache, delete from
  the store, substitute back, and see an unsigned path rejected.
- **Project 05b — Container from your package:** a layered image run with Docker.
- **Project 05c — Build for ARM on x86:** cross-compile and run under QEMU user emulation.
**Patterns:** cache keys as trust; images as Nix outputs; platforms as package-set arguments.

## 06 · The module system and NixOS
**Goals:** write modules with typed options; understand how a NixOS system is assembled from
nixpkgs; build, boot and test NixOS machines from Xubuntu.
**Structure:**
- L1 The module system standalone: `lib.evalModules`, options, types, defaults, priorities,
  `mkIf`/`mkMerge`, `imports`, assertions
- L2 How NixOS is built: `nixos/lib/eval-config.nix`, `system.build.toplevel`, `/etc`,
  systemd units, activation, generations
- L3 `nixosConfigurations` in a flake, `build-vm`, running a VM from Xubuntu
- L4 Writing a service module; testing it with `runNixOSTest`
- **Project 06a — Typed config generator:** evalModules-based tool that renders a validated
  config file.
- **Project 06b — Service module + VM test:** a NixOS module for the course's web service,
  tested by a two-machine `runNixOSTest`.
- **Project 06c — Take a system apart:** build a toplevel and trace a config option to the
  file it produces.
**Patterns:** options are an interface; config is a fixed point; tests boot real machines.

## 07 · Contributing to nixpkgs and Nix
**Goals:** make a contribution nixpkgs would accept and know how the project works.
**Structure:**
- L1 nixpkgs layout and workflow: by-name, `callPackage`, branches (master, staging, release)
- L2 The checklist: package.nix conventions, `meta`, `__structuredAttrs`, nixfmt, `nixpkgs-vet`
- L3 Testing like CI: `nix-build -A`, `passthru.tests`, `nixpkgs-review`
- L4 Commits, PRs, maintainers, update scripts, backports; beyond packages: NixOS modules,
  docs, Nix itself, RFCs
- **Project 07 — Contribution rehearsal:** add a real package under `pkgs/by-name` in a nixpkgs
  checkout, pass every check CI runs, and produce the commit as a patch, ready for a PR.
**Patterns:** small reviewable commits; tests and maintainers with every package.

## 08 · Capstone
**Goals:** combine everything in one project you could show an employer.
**Structure:** one project in stages:
1. A small HTTP key-value service packaged in nixpkgs style
2. A flake with `packages`, `devShells`, `checks`, `formatter`, `overlays`, `nixosModules`
3. A NixOS module and a VM test
4. A container image and a signed cache
5. A GitHub Actions workflow for your own repository
**Patterns:** everything above, in one repository.
