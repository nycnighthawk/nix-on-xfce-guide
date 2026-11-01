# Course 01 · How Nix works

Most Nix confusion comes from one missing picture: what the store is and how a build gets
into it. This course builds that picture one piece at a time, and you test each claim with a
command instead of taking it on trust.

## Goals

After this course you can:

- read a store path and say what its hash depends on;
- explain the two steps of every build, **instantiation** (Nix code → `.drv` file) and
  **realisation** (`.drv` → output paths), and look at both;
- explain why output paths are known *before* anything is built (**input addressing**), and
  why fetches are the exception (**content addressing**, fixed-output derivations);
- find a path's references and closure, and say why Nix finds runtime dependencies by
  *scanning* outputs;
- say what a builder can and cannot see in the sandbox, who runs it (the daemon, build
  users), and where substitutes come from (binary caches, signatures);
- keep what you need and delete what you don't, using GC roots.

## Prerequisites

- Course 00: Nix ≥ 2.35.3 installed in multi-user mode, with `nix-command flakes` enabled.
- A shell and a text editor. No Nix language knowledge yet: course 02 covers it. Every Nix
  file here is short and explained line by line.

Check the machine before you start:

```bash
nix --version
nix config show experimental-features
```

```text expect
nix (Nix) 2.35
nix-command
```

## Structure

| File | What you do |
|---|---|
| [01-store-paths.md](01-store-paths.md) | Add files to the store, take a store path apart, prove it is immutable |
| [02-derivations.md](02-derivations.md) | Instantiate and realise a derivation; read the `.drv` file two ways |
| [03-closures-and-caches.md](03-closures-and-caches.md) | References by scanning, closures, `why-depends`, binary caches and signatures |
| [04-sandbox-and-purity.md](04-sandbox-and-purity.md) | Look inside the sandbox; watch the network fail; fixed-output derivations |
| [05-garbage-collection.md](05-garbage-collection.md) | GC roots, `--print-roots`, deleting one path safely |
| [project-a-derivation-by-hand.md](project-a-derivation-by-hand.md) | A raw `derivation { … }` with only bash and coreutils |
| [project-b-prove-reproducibility.md](project-b-prove-reproducibility.md) | `--check` / `--rebuild`, a non-deterministic build and its fix, closure diffs |

Each file runs on its own: it writes every file it needs, starting with `nixpkgs.nix`, the
pin from [CONVENTIONS.md](../../CONVENTIONS.md). Run any of them with
`python3 mastery/ci/mdrun.py <file>` to check your machine gives the same results.

## Patterns you will practise

- **Input addressing.** An output path is a hash of the build recipe and all its inputs, so it
  is known before the build and changes whenever any input changes.
- **Dependency discovery by scanning.** Nix doesn't trust you to declare runtime
  dependencies. After a build it scans the output for the hash parts of its inputs' store
  paths.
- **Content-addressed fetches.** A fixed-output derivation declares the hash of its result up
  front. That's why it may use the network, and why its output path doesn't depend on the URL.

## Primary sources

- Nix reference manual 2.35: *Store* (Store Object, Store Path, Store Derivation and Deriving
  Path, Building), *Language → Derivations*, *Command Reference* (`nix-store`, `nix-build`,
  `nix derivation show`, `nix path-info`), *Package Management → Garbage Collection*,
  `nix.conf` (`sandbox`, `substituters`, `trusted-public-keys`, `keep-outputs`).
- Eelco Dolstra, *The Purely Functional Software Deployment Model* (PhD thesis, 2006),
  chapters 2, 3 and 5. This is where the store model, reference scanning ("pointer
  discovery") and input addressing come from.
- Nix Pills, chapters 6–8. Project 01a modernises their hand-written derivation.

## Check yourself (after the course)

<details><summary>Why can Nix print an output path before it has built anything?</summary>

For an input-addressed derivation, the output path is computed from the derivation itself:
its builder, arguments, environment and the paths of all its inputs. Nothing about the
build's *result* goes into it, so the path is known at instantiation time. That's also why
a binary cache can be asked "do you have `/nix/store/<hash>-hello-2.12.3`?" before building.
</details>

<details><summary>Your package's runtime closure is missing a library you passed in as an input. Why might that be?</summary>

Runtime dependencies are found by scanning the output for store-path hashes. If the output
never contains the library's path (it was only used at build time, or the path was stored
compressed or transformed), there's no reference, so it isn't part of the closure. That's
usually correct. When it isn't, the output needs to keep the path in plain text, for example
in a wrapper script or an RPATH.
</details>

<details><summary>Why can a fixed-output derivation use the network but a normal one can't?</summary>

The result of a fixed-output derivation is checked against a hash declared in advance, so
whatever the network gives back, the store only ever gets the expected bytes. A normal
derivation's output isn't known in advance. Network access there would make the result
depend on the outside world without anything noticing.
</details>

<details><summary>What keeps a store path from being garbage-collected?</summary>

Being reachable from a GC root: a symlink registered under `/nix/var/nix/gcroots` (directly,
or indirectly through `gcroots/auto`, as `result` symlinks are), a profile generation, or a
running process that uses the path. Anything reachable through references from a root is
alive too.
</details>
