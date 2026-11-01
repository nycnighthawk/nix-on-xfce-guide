# Lesson 04.4 — `checks`, `formatter`, and a classic `default.nix`

**You will:** give a flake `checks` and run them with `nix flake check`, let a formatting
check fail and fix it with `nix fmt`, and add a `default.nix` that builds the same thing —
the same store path — for people who use `nix-build` without flakes.

## The project

The package from lesson 1, written carelessly (all on a few long lines). It is valid Nix;
it is just not formatted the way nixpkgs and most projects require.

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

```nix file=package.nix
{lib,stdenv}: stdenv.mkDerivation (finalAttrs: { pname = "greet"; version = "1.0"; src = ./src; __structuredAttrs = true; strictDeps = true;
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
  meta = { description = "Prints a friendly greeting"; license = lib.licenses.mit; mainProgram = "greet"; }; })
```

## `checks` and `formatter`

```nix file=flake.nix
{
  description = "greet, with checks, a formatter and a classic default.nix";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      greet = self.packages.${system}.default;
    in
    {
      packages.${system}.default = pkgs.callPackage ./package.nix { };

      # Every attribute is a derivation; `nix flake check` builds them all.
      checks.${system} = {
        # Building the package is itself a check.
        package = greet;

        # The installed binary reports the package's version.
        version = pkgs.testers.testVersion { package = greet; };

        # All Nix files are formatted. `self` is this flake's source in the store.
        formatting = pkgs.runCommand "check-formatting" { nativeBuildInputs = [ pkgs.nixfmt ]; } ''
          cd ${self}
          nixfmt --check $(find . -name '*.nix')
          touch $out
        '';
      };

      # `nix fmt` runs this. nixfmt-tree is treefmt preconfigured with nixfmt.
      formatter.${system} = pkgs.nixfmt-tree;
    };
}
```

- `checks.<system>.<name>` must be derivations. Use them for anything that should gate a
  merge: package builds, `passthru.tests`, linters, NixOS VM tests (course 06).
- `formatter.<system>` is a package whose main program `nix fmt` runs.
  `pkgs.nixfmt-tree` (`pkgs/by-name/ni/nixfmt-tree/package.nix`) is the zero-setup choice:
  [treefmt](https://treefmt.com) with the official Nix formatter, formatting every tracked
  `*.nix` file in the repository. nixpkgs itself is formatted with nixfmt and checks it in CI.

## The classic entry point

Not everyone uses flakes: older tooling, `nix-build`-based CI, colleagues with the
experimental features off. A `default.nix` can build the same package from **the same lock
file** — no second pin to keep in sync:

```nix file=default.nix
# Classic entry point: `nix-build` works without flakes, pinned by flake.lock.
let
  lock = builtins.fromJSON (builtins.readFile ./flake.lock);
  # The lock node that the root's `nixpkgs` input points to.
  locked = lock.nodes.${lock.nodes.root.inputs.nixpkgs}.locked;
  nixpkgs = builtins.fetchTarball {
    url = "https://github.com/${locked.owner}/${locked.repo}/archive/${locked.rev}.tar.gz";
    # A GitHub input's narHash is the NAR hash of the unpacked tree — exactly what
    # fetchTarball's sha256 checks.
    sha256 = locked.narHash;
  };
  pkgs = import nixpkgs {
    system = "x86_64-linux";
    config = { };
    overlays = [ ];
  };
in
{
  default = pkgs.callPackage ./package.nix { };
}
```

This is the core of what the community `flake-compat` project does generally (for every
input type, and for whole flakes). Another option is
`(builtins.getFlake (toString ./.)).packages.x86_64-linux.default`, but that needs the
`flakes` feature, which is what you were avoiding.

```text file=.gitignore
result
result-*
```

```bash timeout=1800
git init -q
git config user.name "Nix Learner"
git config user.email "learner@example.com"
git add -A
nix flake lock
git add flake.lock
nix flake show
```

```text expect
checks
formatter
```

## `nix flake check`: a failing check

`nix flake check` evaluates every output (are packages derivations? are overlays
functions?) and **builds every check** for your system:

```bash fails
nix flake check
```

```text expect
check-formatting
```

The formatting check failed — `nixfmt --check` named the files it would change, and the
build of `check-formatting` failed. By default Nix stops at the first failing build; add
`--keep-going` to see every failing check in one run.

## `nix fmt`

```bash
nix fmt
git diff --stat
```

```text expect
package.nix
```

nixfmt rewrote `package.nix` into the standard layout, and possibly touched other files.
Look at it:

```bash
cat package.nix
```

```text expect
stdenv.mkDerivation (finalAttrs: {
pname = "greet";
```

Formatting never changes meaning — the derivation is the same, so nothing rebuilds:

```bash
nix flake check
echo "all checks passed"
```

```text expect
all checks passed
```

Build one check on its own when you are iterating on it:

```bash
nix build .#checks.x86_64-linux.version --print-build-logs
```

Make it a habit: `nix fmt` before every commit, `nix flake check` in CI. `nix flake check
--all-systems` also evaluates other systems' checks (without building them if you cannot).

## The classic `default.nix` at work

Build with the classic command — with flakes **switched off** for this one invocation —
and with the flake command, and compare:

```bash timeout=1800
classic=$(nix-build --option experimental-features '' -A default --no-out-link)
flake=$(nix build --no-link --print-out-paths .#default)
echo "classic: $classic"
echo "flake:   $flake"
[ "$classic" = "$flake" ] && echo "same store path"
"$classic/bin/greet" classic
```

```text expect
same store path
Hello, classic!
```

The same nixpkgs (from the lock), the same `package.nix`, the same source: the same
derivation, so the same output path. Nothing was built twice. Keep `default.nix` boring:
read the lock, import nixpkgs with an explicit `config` and `overlays`, `callPackage` the
same files the flake uses.

## Exercise: a behaviour check

Add a check `greets` that runs `greet Nix` and fails unless it prints exactly
`Hello, Nix!`. Run all checks.

<details><summary>Hint</summary>

The formatting check covers `flake.nix` too. What should you run before `nix flake check`?

</details>

<details><summary>Solution</summary>

```nix file=flake.nix
{
  description = "greet, with checks, a formatter and a classic default.nix";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      greet = self.packages.${system}.default;
    in
    {
      packages.${system}.default = pkgs.callPackage ./package.nix { };

      checks.${system} = {
        package = greet;
        version = pkgs.testers.testVersion { package = greet; };
        greets = pkgs.runCommand "check-greets" { nativeBuildInputs = [ greet ]; } ''
          [ "$(greet Nix)" = "Hello, Nix!" ]
          touch $out
        '';
        formatting = pkgs.runCommand "check-formatting" { nativeBuildInputs = [ pkgs.nixfmt ]; } ''
          cd ${self}
          nixfmt --check $(find . -name '*.nix')
          touch $out
        '';
      };

      formatter.${system} = pkgs.nixfmt-tree;
    };
}
```

Format first, then check. Whatever layout you typed, `nix fmt` makes the formatting check
pass:

```bash
nix fmt
nix flake check
nix build .#checks.x86_64-linux.greets
echo "greets passed"
```

```text expect
greets passed
```

</details>

## Check yourself

<details><summary>What does <code>nix flake check</code> do besides building <code>checks</code>?</summary>

It evaluates all outputs and checks their shape: `packages` and `checks` must be
derivations, `overlays` must be `final: prev:` functions, `nixosModules` must be modules,
`apps` must point at programs, and so on. Outputs for other systems are evaluated only with
`--all-systems`.

</details>

<details><summary>Why does reformatting not rebuild <code>greet</code>?</summary>

The derivation is built from the *evaluated* expression, not its text. Whitespace and layout
do not change any attribute value, so the `.drv` and the output path stay the same. (The
`formatting` check does rerun: it depends on the source text through `${self}`.)

</details>

<details><summary>Why does the classic <code>default.nix</code> read <code>flake.lock</code> instead of having its own pin?</summary>

One source of truth. With two pins, `nix build` and `nix-build` drift apart after the first
update that touches only one of them. Reading the lock makes `nix flake update` update both.

</details>
