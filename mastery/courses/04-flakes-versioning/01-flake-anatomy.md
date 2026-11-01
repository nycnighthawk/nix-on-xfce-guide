# Lesson 04.1 — Flake anatomy

**You will:** turn a package into a flake, meet the Git-tracking rule the hard way, read
every part of `flake.lock`, expose outputs for several systems, and remove a duplicate
nixpkgs with `follows`.

## What a flake is

A flake is a directory (usually a Git repository) with a `flake.nix` at its root. That
file is an attribute set with three top-level attributes:

- `description` — one line for humans;
- `inputs` — other flakes (or plain sources) this one depends on, by URL;
- `outputs` — a **function** that receives the fetched inputs (and `self`, this flake) and
  returns an attribute set with conventional names.

Nix evaluates flakes in **pure mode**: no `<nixpkgs>` from `NIX_PATH`, no
`builtins.currentSystem`, no reading files outside the flake or its inputs. Everything a
flake uses must come through `inputs`. Next to `flake.nix`, Nix writes `flake.lock`, which
pins every input to an exact revision and content hash. Source: Nix manual, `nix flake`
(*Flake format*, *Flake inputs*, *Lock files*).

Common output attributes, and the commands that read them:

| Output | Read by |
|---|---|
| `packages.<system>.<name>` (and `.default`) | `nix build .#name`, `nix run`, `nix shell` |
| `apps.<system>.<name>` | `nix run .#name` |
| `devShells.<system>.default` | `nix develop` (course 05) |
| `checks.<system>.<name>` | `nix flake check` (lesson 4) |
| `formatter.<system>` | `nix fmt` (lesson 4) |
| `overlays.<name>` | other flakes, `import nixpkgs { overlays = …; }` (lesson 3) |
| `nixosModules.<name>`, `nixosConfigurations.<name>` | NixOS (course 06) |
| `lib` | other flakes — any value you like |

## A flake for a small program

```c file=src/greet.c
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
  if (argc > 1 && strcmp(argv[1], "--version") == 0) {
    printf("greet %s\n", VERSION);
    return 0;
  }
  printf("Hello, %s!\n", argc > 1 ? argv[1] : "world");
  return 0;
}
```

The package is an ordinary course-03 `package.nix`. Flakes change how you *pin and wire*
packages, not how you write them.

```nix file=package.nix
{ lib, stdenv }:

stdenv.mkDerivation (finalAttrs: {
  pname = "greet";
  version = "1.0";
  src = ./src;

  __structuredAttrs = true;
  strictDeps = true;

  buildPhase = ''
    runHook preBuild
    $CC -O2 -DVERSION='"${finalAttrs.version}"' -o greet greet.c
    runHook postBuild
  '';
  installPhase = ''
    runHook preInstall
    install -Dm755 greet $out/bin/greet
    runHook postInstall
  '';

  meta = {
    description = "Prints a friendly greeting";
    license = lib.licenses.mit;
    mainProgram = "greet";
  };
})
```

```nix file=flake.nix
{
  description = "greet: a tiny C program, packaged as a flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";
  };

  outputs =
    { self, nixpkgs }:
    let
      # Flakes have no "current system": you list the systems you support.
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAllSystems (
        pkgs:
        let
          greet = pkgs.callPackage ./package.nix { };
        in
        {
          inherit greet;
          default = greet;
        }
      );
    };
}
```

- `nixpkgs.legacyPackages.${system}` is nixpkgs imported for that system. (The name is
  historical: `packages` must be a flat set of derivations, and nixpkgs is a deep tree. See
  the comment in nixpkgs' own `flake.nix`.)
- `forAllSystems` is the usual small helper; `nixpkgs.lib.genAttrs [ "a" "b" ] f` builds
  `{ a = f "a"; b = f "b"; }`. Libraries like `flake-utils` or `flake-parts` do the same
  with more features.

Keep build results out of Git:

```text file=.gitignore
result
result-*
```

## The Git-tracking rule

Make it a Git repository, but stage only `flake.nix`:

```bash
git init -q
git config user.name "Nix Learner"
git config user.email "learner@example.com"
git add flake.nix
```

```bash fails
nix build
```

```text expect
package.nix
```

`package.nix` is right there in the directory — but for a flake in a Git repository, Nix
copies only **tracked** files into the store as the flake's source. An untracked file does
not exist as far as the build is concerned. This keeps `result` links, secrets and editor
junk out of your builds; the price is remembering `git add`. Staging is enough: you do not
need to commit.

```bash
git add -A
git status --short
```

```bash
nix build
./result/bin/greet
nix run . -- Nix
nix run .#greet -- --version
```

```text expect
Hello, world!
Hello, Nix!
greet 1.0
```

`nix build` with no argument means `.#default`, which Nix looks up as
`packages.x86_64-linux.default`. `nix run` runs `meta.mainProgram` of the package.

## What the flake exposes

```bash
nix flake show
nix eval .#packages --apply builtins.attrNames
```

```text expect
greet
default
"aarch64-linux"
"x86_64-linux"
```

`nix flake show` lists outputs; for systems other than yours it prints "omitted" unless
you pass `--all-systems`. Nothing is built for `aarch64-linux` until someone asks — outputs
are lazy like everything else in Nix.

## The lock file

The first `nix build` created `flake.lock`, and Git should track it (we staged it with
`git add -A`). It is JSON:

```bash
cat flake.lock
```

```text expect
"rev": "fa1373130d5a21c040a47c5dbe1913d59ed91808"
"narHash": "sha256-
"lastModified":
"root": "root"
```

Its parts:

- **`nodes`** — one entry per input, transitively. `root` is your flake; its `inputs` map
  input names to node names.
- **`original`** — what `flake.nix` asked for (`github:NixOS/nixpkgs/<rev>`).
- **`locked`** — what that resolved to: owner/repo, `rev`, `lastModified` (commit time),
  and **`narHash`**, the hash of the fetched source tree. Even if GitHub served different
  bytes for that commit tomorrow, Nix would refuse them.
- **`version`** — the lock file format version.

With a commit in the URL, `original` and `locked` name the same commit. With a branch
(lesson 2) they differ: `original` says `nixos-26.05`, `locked` says which commit that was.

## Inputs of inputs, and `follows`

Flakes compose: an input can be another flake with inputs of its own. Here is a helper
flake (in a subdirectory, as monorepos often do) that pins *its own* nixpkgs — 25.11 — and
exports which release it got:

```nix file=tools/flake.nix
{
  description = "A helper flake that brings its own nixpkgs";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/b6018f87da91d19d0ab4cf979885689b469cdd41";

  outputs =
    { self, nixpkgs }:
    {
      lib.nixpkgsRelease = nixpkgs.lib.trivial.release;
    };
}
```

Use it from the main flake. `path:./tools` is a path relative to this flake:

```nix file=flake.nix
{
  description = "greet: a tiny C program, packaged as a flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";
    tools.url = "path:./tools";
  };

  outputs =
    { self, nixpkgs, tools }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAllSystems (
        pkgs:
        let
          greet = pkgs.callPackage ./package.nix { };
        in
        {
          inherit greet;
          default = greet;
        }
      );

      lib.toolsNixpkgsRelease = tools.lib.nixpkgsRelease;
    };
}
```

```bash timeout=1800
git add -A
nix flake lock
nix run github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808#jq -- -r '.nodes | keys | join(" ")' flake.lock
nix eval --raw .#lib.toolsNixpkgsRelease; echo
```

```text expect
nixpkgs nixpkgs_2 root tools
25.11
```

(`nix run <flake>#jq -- ARGS` runs jq from the pinned nixpkgs without installing it.)

Two nixpkgs now: yours (`nixpkgs`) and the helper's (`nixpkgs_2`). Each costs a download
and an evaluation, and anything the helper builds uses a different compiler and glibc than
your packages — two copies of everything in the closure. Usually you want one. `follows`
says "for this input of my input, use my input instead":

```nix file=flake.nix
{
  description = "greet: a tiny C program, packaged as a flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";
    tools = {
      url = "path:./tools";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    { self, nixpkgs, tools }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAllSystems (
        pkgs:
        let
          greet = pkgs.callPackage ./package.nix { };
        in
        {
          inherit greet;
          default = greet;
        }
      );

      lib.toolsNixpkgsRelease = tools.lib.nixpkgsRelease;
    };
}
```

```bash
nix flake lock
nix run github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808#jq -- -r '.nodes | keys | join(" ")' flake.lock
nix run github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808#jq -- -c '.nodes.tools.inputs' flake.lock
nix eval --raw .#lib.toolsNixpkgsRelease; echo
```

```text expect
nixpkgs root tools
{"nixpkgs":["nixpkgs"]}
26.05
```

In the lock, a follows is a **path** of input names (`["nixpkgs"]` = root's `nixpkgs`)
instead of a node name. The helper now evaluates against 26.05. That is also the risk of
`follows`: the helper was written and tested against 25.11. For a mature library flake it
is the right default; for a flake that needs a specific nixpkgs, leave it alone.

## Exercise: a package for one system only

Add a package `greet-v2` that exists **only** for `x86_64-linux`: the same program compiled
with `-march=x86-64-v2` (an x86-specific optimisation level, meaningless on ARM). `nix
eval` should list it under `x86_64-linux` and not under `aarch64-linux`.

<details><summary>Hint</summary>

Outputs are plain attribute sets: build the per-system sets first, then extend one with
`//`. Don't extend `self.packages.x86_64-linux` inside the definition of `packages` — an
output that reads itself while it is being defined is infinite recursion.

</details>

<details><summary>Solution</summary>

```nix file=flake.nix
{
  description = "greet: a tiny C program, packaged as a flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";
    tools = {
      url = "path:./tools";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    { self, nixpkgs, tools }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      common = forAllSystems (
        pkgs:
        let
          greet = pkgs.callPackage ./package.nix { };
        in
        {
          inherit greet;
          default = greet;
        }
      );
    in
    {
      packages = common // {
        x86_64-linux = common.x86_64-linux // {
          greet-v2 = common.x86_64-linux.greet.overrideAttrs (prevAttrs: {
            pname = "greet-v2";
            env = (prevAttrs.env or { }) // {
              NIX_CFLAGS_COMPILE = "-march=x86-64-v2";
            };
          });
        };
      };

      lib.toolsNixpkgsRelease = tools.lib.nixpkgsRelease;
    };
}
```

```bash
nix eval .#packages.x86_64-linux --apply builtins.attrNames
if nix eval .#packages.aarch64-linux --apply builtins.attrNames | grep -q greet-v2; then
  echo "greet-v2 leaked into aarch64-linux"; false
fi
nix build .#greet-v2
./result/bin/greet v2
```

```text expect
"greet-v2"
Hello, v2!
```

`env.NIX_CFLAGS_COMPILE` reaches the compiler wrapper, which adds the flag to every
compiler call. With `__structuredAttrs`, only attributes under `env` are exported to the
build as environment variables.

</details>

## Check yourself

<details><summary>Why does <code>outputs</code> have to be a function?</summary>

Its arguments are the inputs, which Nix fetches and locks first. The function form lets Nix
read `inputs` without evaluating `outputs`, lock everything, and only then call `outputs`
with the fetched flakes. It also makes outputs lazy: `nix build .#greet` evaluates only
what that package needs.

</details>

<details><summary>What would happen if you deleted <code>flake.lock</code> and ran <code>nix build</code>?</summary>

Nix would re-lock every input from `flake.nix`. With commit URLs you would get the same
lock back. With branch URLs (`nixos-26.05`) you would get whatever the branches point to
today — a silent update of everything. Never delete the lock to "fix" something.

</details>

<details><summary>In the lock file, what is the difference between <code>"nixpkgs": "nixpkgs_2"</code> and <code>"nixpkgs": ["nixpkgs"]</code> under an input's <code>inputs</code>?</summary>

A string names a node of its own: a separately fetched and locked copy. A list is a
`follows` path, starting from the root: "use whatever the root's `nixpkgs` input is".

</details>
