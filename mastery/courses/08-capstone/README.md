# Course 08 · Capstone

**Goal:** combine everything from courses 01–07 in one repository you could show an employer: a
small network service that is packaged, developed, tested, deployed and shipped entirely with
Nix.

By the end you have a Git repository containing:

- **kvstore**, an HTTP key-value service in Python (standard library only:
  `GET`/`PUT /kv/<key>`), packaged nixpkgs-style with `python3Packages.buildPythonApplication`,
  its unit tests run during the build;
- a **flake** exposing `packages`, `devShells`, `checks`, `formatter`, `overlays.default` and
  `nixosModules.default`;
- a **NixOS module** with typed options and systemd sandboxing (`DynamicUser`,
  `StateDirectory`, a hardened unit), and a **two-machine VM test** in which a client `PUT`s and
  then `GET`s a value over the network;
- a **container image** built with `dockerTools.buildLayeredImage`, and a **signed binary cache**
  holding the package;
- a **GitHub Actions workflow** that runs `nix flake check` on every push, validated with
  `actionlint`.

## Prerequisites

Courses 00–06 (07 helps with the nixpkgs conventions used in `nix/package.nix`). About 4 GB of
free disk. The VM test runs fastest with KVM; without it, it still works, just slowly.

## Structure

The capstone is one project in five stages, in one file, because each stage builds on the files
of the previous one:

| Stage | You build | Course it draws on |
|---|---|---|
| [1 · The service, packaged nixpkgs-style](project-a-kvstore.md#stage-1--the-service-packaged-nixpkgs-style) | Python package with `pyproject = true`, tests in the build, `callPackage`-able `nix/package.nix` | 03, 07 |
| [2 · The flake](project-a-kvstore.md#stage-2--the-flake) | overlay, packages, dev shell, formatter, checks; `nix develop`, `nix fmt`, `nix run` | 04, 05 |
| [3 · NixOS module and VM test](project-a-kvstore.md#stage-3--a-nixos-module-and-a-vm-test) | typed options, assertion, hardened unit, `runNixOSTest` with two machines | 06 |
| [4 · Container image and signed cache](project-a-kvstore.md#stage-4--a-container-image-and-a-signed-cache) | `buildLayeredImage`, inspecting an image without Docker, `nix copy` with a signing key | 05 |
| [5 · CI for your repository](project-a-kvstore.md#stage-5--ci-for-your-own-repository) | `.github/workflows/ci.yml`, `actionlint`, the final `nix flake check` | 04, 07 |

File: [project-a-kvstore.md](project-a-kvstore.md).

## The repository you end up with

```text
kvstore/
├── flake.nix            outputs: packages, devShells, checks, formatter, overlays, nixosModules
├── flake.lock           the pinned nixpkgs
├── pyproject.toml       the single source of the version number
├── src/kvstore/         the service (http.server, no dependencies)
├── tests/               unittest suite, run by the Nix build
├── nix/
│   ├── package.nix      buildPythonApplication, callPackage-style
│   ├── module.nix       services.kvstore.*
│   ├── vm-test.nix      runNixOSTest: server + client
│   └── image.nix        dockerTools.buildLayeredImage
├── eval-system.nix      helper to inspect the NixOS configuration
└── .github/workflows/ci.yml
```

## Patterns you'll use

- **`package.nix` as a function of its dependencies** (`callPackage`), shared by the overlay,
  the flake, the module and the image — one definition, many consumers.
- **One source of truth for the version**: `pyproject.toml`, read with `lib.importTOML`.
- **Overlay for the package set, module for the machine**: `overlays.default` adds `kvstore` to
  any nixpkgs; `nixosModules.default` adds `services.kvstore` to any NixOS.
- **Lazy outputs**: a flake output costs nothing until you evaluate it.
- **Least privilege by default**: `DynamicUser`, `StateDirectory`, and a syscall filter instead
  of a hand-made system user.
- **Tests boot real machines**: the module is only "done" when a VM test proves it.
- **Images and caches are just outputs**: no Dockerfile, no separate CI cache tooling.
- **CI is `nix flake check`**: the workflow is a thin shell around what you run locally.

## Check yourself

<details><summary>Why is the package a separate <code>nix/package.nix</code> instead of being written inline in <code>flake.nix</code>?</summary>

So it is an ordinary `callPackage` function: it can be built without flakes
(`callPackage ./nix/package.nix { }`), applied to any nixpkgs through the overlay, overridden
with `.override`, and moved into nixpkgs' `pkgs/by-name` unchanged.
</details>

<details><summary>The module uses <code>DynamicUser = true</code>. Where does the data go, and who owns it?</summary>

systemd creates `StateDirectory=kvstore` as `/var/lib/private/kvstore` with a symlink
`/var/lib/kvstore`, and chowns it to the UID it allocates for the service at each start. No
user exists in `/etc/passwd`; nothing else on the machine can read the data.
</details>

<details><summary>What does the CI workflow actually need to know about the project?</summary>

Almost nothing: install Nix, enable KVM, run `nix flake check`. Everything else — formatting,
unit tests, the VM test — is declared in the flake, so CI and your laptop run the same thing.
</details>
