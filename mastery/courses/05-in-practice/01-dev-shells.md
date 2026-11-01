# Lesson 05.1 — Dev shells: `mkShell`, `inputsFrom`, `shellHook`, direnv

**You will:** give a small C project a dev shell, use it from scripts with
`nix develop --command`, see that it *is* the package's build environment, and make it load by
itself when you `cd` into the project, with direnv and nix-direnv.

## Why a dev shell is a derivation

When you build a package, the builder runs bash inside an environment made by `stdenv`. The
compiler wrapper is on `PATH`, `NIX_CFLAGS_COMPILE` points at the headers of every `buildInputs`
entry, the setup hooks (for example pkg-config's) have run, and so on. `nix develop` gives you the
**same environment** in an interactive shell. It evaluates the derivation, runs its setup up to the
point where the build would start, saves the resulting variables and functions, and opens bash
with them.

So a "dev shell" is simply a derivation that is meant to be entered, not built. `pkgs.mkShell` is
the helper for that. Read it, it is 60 lines
(`pkgs/build-support/mkshell/default.nix` in nixpkgs 26.05):

- it is `stdenv.mkDerivation` (through `lib.extendMkDerivation`);
- `packages` is appended to `nativeBuildInputs`, so these tools land on `PATH`;
- `inputsFrom = [ drv … ]` collects the `buildInputs`, `nativeBuildInputs` and the propagated
  variants **of those derivations**, minus the derivations themselves;
- `shellHook`s of the `inputsFrom` derivations and your own are concatenated;
- the build phase only writes a warning file. Building a `mkShell` is never the goal.

Any other attribute becomes an environment variable of the derivation, just as with
`mkDerivation`. The tidy way to set variables is `env = { NAME = "value"; }`.

## A project to work on

A tiny program that prints the zlib version it was linked against. It needs a compiler,
`pkg-config` (a build tool, so `nativeBuildInputs`) and zlib (a library, so `buildInputs`).

```bash
git init -q
mkdir -p src
```

```c file=src/zver.c
#include <stdio.h>
#include <zlib.h>

int main(void) {
    printf("built against zlib %s\n", zlibVersion());
    return 0;
}
```

```nix file=package.nix
{
  lib,
  stdenv,
  pkg-config,
  zlib,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "zver";
  version = "0.1";

  src = ./src;

  __structuredAttrs = true;
  strictDeps = true;

  nativeBuildInputs = [ pkg-config ];
  buildInputs = [ zlib ];

  buildPhase = ''
    runHook preBuild
    $CC zver.c -o zver $(pkg-config --cflags --libs zlib)
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    install -Dm755 zver $out/bin/zver
    runHook postInstall
  '';

  meta = {
    description = "Print the zlib version a program was built against";
    license = lib.licenses.mit;
    mainProgram = "zver";
    platforms = lib.platforms.unix;
  };
})
```

The flake exposes the package and a dev shell built **from** it:

```nix file=flake.nix
{
  description = "zver: a package and its dev shell";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      packages.${system}.default = pkgs.callPackage ./package.nix { };

      devShells.${system}.default = pkgs.mkShell {
        # Everything zver needs to build: stdenv's compiler, pkg-config, zlib.
        inputsFrom = [ self.packages.${system}.default ];

        # Extra tools you want while working, not needed to build.
        packages = [
          pkgs.jq
          pkgs.gdb
        ];

        # Environment variables, set the tidy way.
        env.GREETING = "hello from the dev shell";

        # Runs every time the shell starts (also for `nix develop --command`).
        shellHook = ''
          echo "zver dev shell: zlib $(pkg-config --modversion zlib), $(cc --version | head -n1)"
        '';
      };
    };
}
```

Flakes only see files that git tracks, so add them:

```bash
git add src/zver.c package.nix flake.nix
nix build
./result/bin/zver
```

```text expect
built against zlib
```

## Entering the shell, and using it from scripts

Interactively you would type `nix develop` and get a bash prompt with the shell hook printed:

```console
$ nix develop
zver dev shell: zlib 1.3.1, gcc (GCC) 15.2.0
$ cc src/zver.c -o zver $(pkg-config --cflags --libs zlib) && ./zver
built against zlib 1.3.1
$ exit
```

(The version numbers are whatever nixpkgs 26.05 ships; yours may differ.)

Scripts, Makefiles and CI should use `--command`. It runs one program inside the environment and
exits with that program's status. Here you compile by hand, exactly as the build phase does:

```bash
nix develop --command bash -c '
  cc src/zver.c -o zver-by-hand $(pkg-config --cflags --libs zlib)
  ./zver-by-hand
  echo "GREETING=$GREETING"
  echo "jq is $(command -v jq)"
'
```

```text expect
zver dev shell: zlib
built against zlib
GREETING=hello from the dev shell
jq is /nix/store/
```

The shell hook ran first (its line is at the top). The compiler, pkg-config and the zlib headers
came from `inputsFrom`. `jq` came from `packages`. `GREETING` came from `env`.

### The shell is the build environment

`inputsFrom` didn't copy a list by hand. It read the package's own inputs. You can see them,
because the dev shell's derivation attributes are environment variables in the shell:

```bash
nix develop --command bash -c 'echo "buildInputs: $buildInputs"; echo "nativeBuildInputs: $nativeBuildInputs"'
```

```text expect
buildInputs: /nix/store/
zlib
pkg-config
```

If you later add a library to `package.nix`, the dev shell gets it too. That is the main reason
to prefer `inputsFrom` over listing build dependencies twice.

### Pure shells

By default `nix develop` *adds* to your current environment: your own `PATH` comes after the
shell's. `--ignore-env` (`-i`) starts from an empty environment, which is how you check that a
build really doesn't use anything from Ubuntu:

```bash
nix develop --ignore-env --command bash -c 'type -P curl || echo "curl: not on PATH"; type -P cc'
```

```text expect
curl: not on PATH
/nix/store/
```

Ubuntu's `/usr/bin/curl` is gone. The compiler from the shell is still there.

### What `nix develop` actually computes

`nix print-dev-env` prints the environment as a bash script, or as JSON. This is what direnv will
use below:

```bash
nix print-dev-env --json > dev-env.json
nix run --inputs-from . nixpkgs#jq -- -r '.variables.GREETING.value' dev-env.json
```

```text expect
hello from the dev shell
```

`--inputs-from .` means "resolve `nixpkgs` using *this* flake's locked input". The jq you run is
the one your project pins, not whatever the global registry points at today.

### Keeping the shell from being garbage-collected

A dev shell's inputs are not GC roots. After `nix-collect-garbage` the next `nix develop`
downloads everything again. `--profile` keeps the environment as a profile, which is a GC root.
CI caches use this, and nix-direnv does it for you (see below):

```bash
nix develop --profile ./.dev-profile --command true
ls -l .dev-profile
```

```text expect
.dev-profile-1-link
```

## direnv: the shell loads when you `cd` in

[direnv](https://direnv.net) runs a project's `.envrc` when you enter the directory and undoes
it when you leave. Its standard library has `use flake`, which calls
`nix print-dev-env --profile .direnv/flake-profile` and loads the result. The project needs only
this:

```bash file=.envrc
use flake
```

direnv refuses to run an `.envrc` until you `direnv allow` it, because an `.envrc` is code. In
daily use you install direnv once and hook it into bash. You don't need either of these for the
rest of the lesson, so they are shown and not run:

```console
$ nix profile add nixpkgs#direnv          # older Nix: nix profile install
$ echo 'eval "$(direnv hook bash)"' >> ~/.bashrc
$ cd ~/src/zver
direnv: error /home/you/src/zver/.envrc is blocked. Run `direnv allow` to approve its content
$ direnv allow
direnv: loading ~/src/zver/.envrc
direnv: using flake
direnv: export +AR +AS +CC … +GREETING … ~PATH
```

Without the hook, `direnv exec DIR COMMAND` does the same thing for one command. That is how you
use direnv from scripts, and how this lesson tests it without touching your `~/.bashrc`. direnv
comes from the project's own pinned nixpkgs:

```bash
git add .envrc
nix shell --inputs-from . nixpkgs#direnv --command direnv allow .
nix shell --inputs-from . nixpkgs#direnv --command \
  direnv exec . bash -c 'echo "GREETING=$GREETING"; jq --version'
```

```text expect
GREETING=hello from the dev shell
jq-
```

### nix-direnv: cached and protected from GC

direnv's built-in `use flake` evaluates the flake every time you enter the directory, and nothing
stops the garbage collector from deleting the shell. [nix-direnv](https://github.com/nix-community/nix-direnv)
replaces `use flake` with a version that:

- caches the environment and only re-evaluates when `flake.nix`, `flake.lock` or files you
  `watch_file` change;
- keeps the shell's profile **and all flake inputs** as GC roots in `.direnv/`.

You enable it by sourcing its `direnvrc` from direnv's config directory. Normally that is
`~/.config/direnv/direnvrc`. Here the lesson points `DIRENV_CONFIG` at a local directory instead,
so your home directory isn't touched:

```bash
mkdir -p direnv-config
echo "source $(nix build --inputs-from . nixpkgs#nix-direnv --no-link --print-out-paths)/share/nix-direnv/direnvrc" \
  > direnv-config/direnvrc
rm -rf .direnv
export DIRENV_CONFIG=$PWD/direnv-config
nix shell --inputs-from . nixpkgs#direnv --command direnv exec . bash -c 'echo "GREETING=$GREETING"'
ls .direnv
```

```text expect
GREETING=hello from the dev shell
flake-inputs
flake-profile-
```

Run it again. This time nothing is evaluated: nix-direnv says it uses the cached shell.

```bash
nix shell --inputs-from . nixpkgs#direnv --command direnv exec . true
unset DIRENV_CONFIG
```

To set this up for real, add `nix-direnv` to your profile and put
`source $HOME/.nix-profile/share/nix-direnv/direnvrc` in `~/.config/direnv/direnvrc`. Home
Manager users set `programs.direnv.enable = true; programs.direnv.nix-direnv.enable = true;`.
Add `.direnv/` to the project's `.gitignore`.

## Classic `shell.nix`

Before flakes, `nix-shell` read `shell.nix`. The `mkShell` call is identical. Only the way you
get `pkgs` changes:

```nix
# shell.nix
let
  pkgs = import ./nixpkgs.nix { };   # a pinned nixpkgs, as in course 02
in
pkgs.mkShell {
  inputsFrom = [ (pkgs.callPackage ./package.nix { }) ];
  packages = [ pkgs.jq ];
}
```

`nix-shell --run 'make'` is the classic version of `nix develop --command make`. direnv's
`use nix` loads a `shell.nix`.

## Your turn

Add a second, minimal shell `devShells.x86_64-linux.ci` that contains **only** `jq` and the
variable `CI_MODE = "1"`. Don't use `inputsFrom`. Use `pkgs.mkShellNoCC`, the variant without a
C compiler (it is defined right after `mkShell` in `pkgs/top-level/all-packages.nix`). Prove it
with `nix develop .#ci --command …`, and prove that this shell has no `cc`.

<details><summary>Solution</summary>

```nix file=flake.nix
{
  description = "zver: a package and its dev shells";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      packages.${system}.default = pkgs.callPackage ./package.nix { };

      devShells.${system} = {
        default = pkgs.mkShell {
          inputsFrom = [ self.packages.${system}.default ];
          packages = [
            pkgs.jq
            pkgs.gdb
          ];
          env.GREETING = "hello from the dev shell";
          shellHook = ''
            echo "zver dev shell: zlib $(pkg-config --modversion zlib), $(cc --version | head -n1)"
          '';
        };

        ci = pkgs.mkShellNoCC {
          packages = [ pkgs.jq ];
          env.CI_MODE = "1";
        };
      };
    };
}
```

```bash
git add flake.nix
nix develop .#ci --ignore-env --command bash -c 'echo "CI_MODE=$CI_MODE"; jq --version; type -P cc || echo "no cc in the ci shell"'
```

```text expect
CI_MODE=1
jq-
no cc in the ci shell
```
</details>

## Check yourself

<details><summary>Why does a <code>mkShell</code> with <code>inputsFrom = [ pkg ]</code> not contain <code>pkg</code> itself?</summary>

`mkShell` subtracts the `inputsFrom` derivations from the merged input lists
(`lib.subtractLists inputsFrom …` in `mkshell/default.nix`). The shell is for *developing* the
package, so it gets the package's inputs. If you also want the built program, add it to
`packages`.
</details>

<details><summary>You add <code>pkgs.openssl</code> to <code>packages</code> and your C code can't find <code>openssl/ssl.h</code>. Why, and what is the fix?</summary>

`packages` goes into `nativeBuildInputs` (tools for the build platform). With `strictDeps` or
when cross-compiling, headers and libraries for the program are only set up for `buildInputs`.
Put libraries in the package's `buildInputs` and reach them with `inputsFrom`, or set
`buildInputs = [ pkgs.openssl ];` on the shell.
</details>

<details><summary>What does nix-direnv give you over direnv's own <code>use flake</code>?</summary>

A cache (the flake isn't evaluated on every `cd`, only when watched files change) and GC roots
for the dev environment *and* the flake inputs in `.direnv/`, so `nix-collect-garbage` doesn't
force a re-download. It also falls back to the last working environment when evaluation fails.
</details>

<details><summary>In CI, why prefer <code>nix develop --command make test</code> over installing tools on the runner?</summary>

The runner then uses exactly the tools pinned by `flake.lock`, the same ones developers use
locally. Updating a tool is a reviewed change to the lock file, not a change to the CI image.
</details>
