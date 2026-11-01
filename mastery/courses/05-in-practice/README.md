# Course 05 · Nix in practice

**You will:** use Nix as a daily tool: project dev shells (with direnv), your own signed binary
cache, container images built without a Dockerfile, and binaries for other CPUs and for static
linking.

Courses 01–04 explained how Nix works and how to package and pin software. This course is about
the four things most people use Nix for at work. None of them is a new mechanism. Each one is a
derivation, a store path or a trust setting you already know, used in a new way.

## Goals

After this course you can:

- give any project a `devShells.default` that sets up compilers, libraries, tools and variables,
  enter it with `nix develop` or automatically with direnv, and run commands in it from scripts
  and CI with `nix develop --command`;
- explain how a Nix client decides to trust a binary cache (`substituters`,
  `trusted-public-keys`, `require-sigs`, `trusted-users`, `trusted-substituters`) and run your
  own signed cache in a directory;
- build OCI/Docker images with `dockerTools`, explain why they need no Dockerfile and no base
  image, and run them with Docker;
- cross-compile with `pkgsCross`, build static binaries with `pkgsStatic`, and run foreign
  binaries with QEMU user emulation.

## Prerequisites

- Course 00 (Nix ≥ 2.35.3 multi-user, flakes on).
- Course 03 (`stdenv.mkDerivation`, `callPackage`, `package.nix`) and course 04 (flake anatomy,
  `flake.lock`).
- `sudo` on your machine. Lesson 02 and project 05a read the daemon's settings; project 05a
  changes `/etc/nix/nix.conf` for a while and puts it back at the end. Project 05b installs
  Docker from Ubuntu.

Check the basics before you start:

```bash
nix --version
nix config show experimental-features
```

```text expect
nix (Nix) 2.35
flakes
nix-command
```

## Structure

| File | What you do |
|---|---|
| `01-dev-shells.md` | `mkShell`, `packages`, `inputsFrom`, `shellHook`, `env`; `nix develop --command`; direnv with `use flake`, then nix-direnv |
| `02-binary-caches.md` | read a narinfo, check signatures, sign while pushing to a `file://` cache, see where trust is enforced |
| `03-containers.md` | `dockerTools.buildLayeredImage` and `streamLayeredImage`; look inside the image tarball |
| `04-cross-and-static.md` | `pkgsCross.aarch64-multiplatform`, `pkgsStatic`, build vs host platform, QEMU user mode |
| `project-a-signed-cache.md` | **05a** build → sign → push → delete → substitute back; unsigned and forged paths are rejected |
| `project-b-container.md` | **05b** a layered image of your own package, loaded and run by Docker |
| `project-c-arm.md` | **05c** one `package.nix` built for x86-64, aarch64 and static musl, tested under QEMU |

Every file stands alone. Each one starts in an empty directory and creates what it needs.

## Patterns this course drills

- **Dev environment = build environment.** `mkShell` is `stdenv.mkDerivation` that never builds.
  `inputsFrom` reuses a package's own inputs, so the shell and the package can't drift apart.
- **Cache keys as trust.** A binary cache is only a directory of files. Trust comes from
  signatures that are checked against keys the *daemon* trusts, never the client.
- **Images as Nix outputs.** An image is a derivation whose output is a tarball. Its contents are
  the runtime closure of your program. You don't pick a base image and you don't need
  `apt-get` inside it.
- **Platforms as package-set arguments.** `pkgsCross.<platform>` and `pkgsStatic` are nixpkgs
  called again with a different `crossSystem`. The same `package.nix` builds for all of them.

## Primary sources

- Nix manual 2.35: *Command Reference* → `nix develop`, `nix copy`, `nix store sign`,
  `nix key`; *Configuration file* → `substituters`, `trusted-public-keys`, `require-sigs`,
  `trusted-users`, `trusted-substituters`; *Store Types* → *Local Binary Cache Store*.
- nixpkgs 26.05: `pkgs/build-support/mkshell/default.nix`, `pkgs/build-support/docker/default.nix`,
  `doc/build-helpers/images/dockertools.section.md`, `doc/stdenv/cross-compilation.chapter.md`,
  `pkgs/top-level/stage.nix` (`pkgsCross`, `pkgsStatic`), `lib/systems/default.nix`
  (`emulator`).

## Check yourself (before you start)

<details><summary>What is the difference between <code>nix shell</code> and <code>nix develop</code>?</summary>

`nix shell` puts the *outputs* of packages on your `PATH`, so you can run the programs.
`nix develop` reproduces the *build environment* of a derivation: its inputs, its environment
variables and the stdenv setup hooks, so you can build it yourself. The dev shells in this course
are derivations made only to be entered with `nix develop`.
</details>

<details><summary>Why can Nix download a package instead of building it?</summary>

The output path is fixed by the derivation's inputs (input addressing, course 01). If a
substituter has a signed `.narinfo` for that exact path, the daemon can download the NAR and
trust it without building. You will write such a substituter in lesson 02 and project 05a.
</details>
