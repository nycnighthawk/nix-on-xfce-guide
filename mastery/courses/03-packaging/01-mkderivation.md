# Lesson 03.1 — `stdenv.mkDerivation`, phases and hooks

**You will:** package a small C program with `stdenv.mkDerivation (finalAttrs: …)`, read
the phases in its build log, hook into them, and see what `__structuredAttrs` and
`strictDeps` change.

## Why `mkDerivation` and not `derivation`

In course 01 you wrote a raw `derivation { … }`. You had to name a builder, put every tool
on `PATH` yourself, and write every step. `stdenv.mkDerivation` is the nixpkgs layer on top
of that. It gives you:

- a **standard environment**: a wrapped C compiler, binutils, coreutils, `make`, `sed`,
  `grep`, `tar`, `patch`, `patchelf` and friends;
- a **generic builder** (`pkgs/stdenv/generic/setup.sh`) that runs a fixed list of
  **phases**: unpack → patch → configure → build → check → install → fixup → installCheck
  → dist;
- **hooks** (`preBuild`, `postInstall`, …) so you can add a few lines to a phase without
  replacing it;
- **dependency wiring**: anything in `nativeBuildInputs` or `buildInputs` gets its `bin/` on
  `PATH`, its headers and libraries passed to the compiler, and its *setup hook* run.

Most packages need only a few attributes, because the defaults already do what
`./configure && make && make install` does. Source: Nixpkgs manual, *The Standard
Environment*, sections *Using stdenv* and *Phases* (`doc/stdenv/stdenv.chapter.md`).

## Pin nixpkgs

Every classic lesson in this path imports the same nixpkgs commit, so you get the same
compiler, the same library versions, and cache hits from `cache.nixos.org`:

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

## The program

A greeting program with a Makefile that follows the usual conventions: it respects `PREFIX`,
`CC` and `CFLAGS`, and has `check` and `install` targets. Upstream projects that do this
need almost no packaging work.

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

```make file=src/Makefile
PREFIX ?= /usr/local
VERSION ?= 0.0.0
CFLAGS ?= -O2

greet: greet.c
	$(CC) $(CFLAGS) -DVERSION='"$(VERSION)"' -o greet greet.c

check: greet
	test "$$(./greet)" = "Hello, world!"
	test "$$(./greet Nix)" = "Hello, Nix!"

install: greet
	install -Dm755 greet $(PREFIX)/bin/greet

.PHONY: check install
```

```markdown file=src/README.md
greet prints a greeting. `greet NAME` greets NAME. `greet --version` prints the version.
```

## The package

```nix file=package.nix
{ lib, stdenv }:

stdenv.mkDerivation (finalAttrs: {
  pname = "greet";
  version = "1.0";

  # A local directory. Nix copies it into the store; its hash becomes part of the
  # derivation, so editing a source file changes the output path.
  src = ./src;

  # Pass attributes to the builder as JSON + bash arrays, not as environment variables.
  __structuredAttrs = true;
  # Only nativeBuildInputs end up on PATH, only buildInputs are linked against.
  strictDeps = true;

  # make PREFIX=$out VERSION=1.0 — placeholder "out" becomes the real $out at build time.
  makeFlags = [
    "PREFIX=${placeholder "out"}"
    "VERSION=${finalAttrs.version}"
  ];

  # mkDerivation does not run tests unless asked to.
  doCheck = true;

  meta = {
    description = "Prints a friendly greeting";
    license = lib.licenses.mit;
    mainProgram = "greet";
    platforms = lib.platforms.unix;
  };
})
```

Read it line by line:

- **`(finalAttrs: { … })`** — you pass a *function* of the final attributes, not a plain set.
  `finalAttrs.version` is the version *after* any later `overrideAttrs`. Lesson 3 shows why
  that beats `rec { … }`.
- **`src = ./src`** — the unpack phase copies the directory and `cd`s into it.
- **No `configurePhase`** — there is no `configure` script, so the phase prints "no
  configure script, doing nothing".
- **`makeFlags`** — used by the default build, check *and* install phases.
- **`doCheck = true`** — the check phase runs `make check` (it looks for a `check` or `test`
  target).
- **`meta.mainProgram`** — tells `nix run`, `lib.getExe` and the testers which binary is
  the program.

`package.nix` is a function of its dependencies. Something has to call it. `callPackage`
does: it looks at the argument names (`lib`, `stdenv`) and passes those attributes from the
package set. Lesson 3 covers it in depth.

```nix file=default.nix
let
  # config = { } and overlays = [ ] stop nixpkgs reading ~/.config/nixpkgs — your build
  # should not depend on files outside this directory.
  pkgs = import ./nixpkgs.nix {
    config = { };
    overlays = [ ];
  };
in
{
  greet = pkgs.callPackage ./package.nix { };
}
```

## Build and run

The first command fetches the nixpkgs tarball (about 45 MB) and the standard environment
from the binary cache. Later lessons reuse both.

```bash timeout=1800
nix-build -A greet
./result/bin/greet
./result/bin/greet Nix
./result/bin/greet --version
```

```text expect
Hello, world!
Hello, Nix!
greet 1.0
```

## Read the phases in the build log

Nix keeps the log of every build. Ask for the log of the derivation (`.drv`) you just built
and pick out the phase headers:

```bash
drv=$(nix-instantiate -A greet)
nix-store --read-log "$drv" > build.log
grep 'Running phase' build.log
grep -E 'no configure script|build flags|check flags' build.log
```

```text expect
Running phase: unpackPhase
Running phase: patchPhase
Running phase: configurePhase
Running phase: buildPhase
Running phase: checkPhase
Running phase: installPhase
Running phase: fixupPhase
no configure script, doing nothing
```

What each phase did here:

| Phase | Default behaviour | Here |
|---|---|---|
| unpack | unpack `src` (tarball, zip, or copy a directory); `cd` into it | copied `src/` |
| patch | apply `patches`, then run `postPatch` | nothing to do |
| configure | run `./configure --prefix=$out` if it exists | skipped: no script |
| build | `make $makeFlags $buildFlags` | compiled `greet` |
| check | `make check` if `doCheck` | ran both tests |
| install | `make install $makeFlags $installFlags` | installed `bin/greet` |
| fixup | strip binaries, shrink RPATHs, patch `#!` lines, move docs and man pages | stripped `greet` |

The installCheck and dist phases did not run: they are off unless you set
`doInstallCheck` / `doDist`. Lesson 3 uses installCheck.

## Hooks: add, don't replace

Every phase calls `runHook pre<Phase>` at the start and `runHook post<Phase>` at the end.
Setting `preBuild`, `postInstall` and so on adds shell code there. That is almost always
better than replacing a whole phase, because you keep the default behaviour *and* the hooks
other people (and setup hooks of your dependencies) attach.

Add a `preBuild` that prints how `makeFlags` reaches the builder:

```nix file=package.nix
{ lib, stdenv }:

stdenv.mkDerivation (finalAttrs: {
  pname = "greet";
  version = "1.0";

  src = ./src;

  __structuredAttrs = true;
  strictDeps = true;

  makeFlags = [
    "PREFIX=${placeholder "out"}"
    "VERSION=${finalAttrs.version}"
  ];

  doCheck = true;

  # Runs at the start of buildPhase. `declare -p` shows the variable's type and value.
  preBuild = ''
    declare -p makeFlags
  '';

  meta = {
    description = "Prints a friendly greeting";
    license = lib.licenses.mit;
    mainProgram = "greet";
    platforms = lib.platforms.unix;
  };
})
```

Now build it twice: as written, and with `__structuredAttrs` switched off by
`overrideAttrs` (lesson 3 explains `overrideAttrs`; here it just flips one attribute):

```nix file=default.nix
let
  pkgs = import ./nixpkgs.nix {
    config = { };
    overlays = [ ];
  };
in
rec {
  greet = pkgs.callPackage ./package.nix { };
  greet-unstructured = greet.overrideAttrs { __structuredAttrs = false; };
}
```

```bash
nix-build -A greet -A greet-unstructured --no-out-link
nix-store --read-log "$(nix-instantiate -A greet)" | grep 'makeFlags='
nix-store --read-log "$(nix-instantiate -A greet-unstructured)" | grep 'makeFlags='
```

```text expect
declare -a makeFlags=
declare -x makeFlags=
```

With structured attributes, `makeFlags` is a real **bash array** (`declare -a`): each list
element stays one argument, even if it contains spaces. Without them, every attribute
becomes an exported **environment variable** (`declare -x`) and the list is flattened into
one space-separated string — a flag like `"CFLAGS=-O2 -g"` would be split in two. The
nixpkgs manual is blunt: "All new top level packages must enable `__structuredAttrs`"
(*The Standard Environment*, section `__structuredAttrs`). Attributes you really want as
environment variables go under `env = { … }`.

### `strictDeps`

Without `strictDeps`, stdenv is lenient: a tool you put in `buildInputs` still lands on
`PATH`, and a library in `nativeBuildInputs` still gets linked. That works on your machine
and breaks cross-compilation, where "the machine that builds" and "the machine that runs"
differ. With `strictDeps = true`:

- `nativeBuildInputs` — things that **run during the build** (compilers, `pkg-config`,
  `makeWrapper`, code generators). Built for the build machine.
- `buildInputs` — things the result **links against or runs with** (libraries, the
  interpreter in a `#!` line). Built for the host machine.

Source: *The Standard Environment*, sections *Specifying dependencies* and `strictDeps`.
Lesson 4 shows a case where `strictDeps` makes you put `bash` in `buildInputs`.

## Debugging a build interactively

When a phase fails, `nix-shell` drops you into the build environment of a derivation, with
the same variables and functions as the builder. You run phases one at a time:

```console
$ nix-shell -A greet
[nix-shell]$ cd "$(mktemp -d)"
[nix-shell]$ runPhase unpackPhase      # cd's into the source copy
[nix-shell]$ runPhase buildPhase
[nix-shell]$ ./greet
Hello, world!
```

`nix-build --keep-failed` keeps the build directory of a failed build (it prints the path)
so you can inspect what was there.

## Exercise: write an `installPhase` by hand

Some upstream Makefiles have no `install` target. Replace the install phase with your own
that installs `greet` to `$out/bin` **and** `README.md` to `$out/share/doc/greet/`. Keep
the hooks working: a `postInstall` you add must still run.

<details><summary>Solution</summary>

Start and end with `runHook`, or `preInstall`/`postInstall` silently stop running — for
you and for anyone who overrides your package later. The `postInstall` here proves the hook
still fires.

```nix file=package.nix
{ lib, stdenv }:

stdenv.mkDerivation (finalAttrs: {
  pname = "greet";
  version = "1.0";

  src = ./src;

  __structuredAttrs = true;
  strictDeps = true;

  makeFlags = [ "VERSION=${finalAttrs.version}" ];

  doCheck = true;

  installPhase = ''
    runHook preInstall
    install -Dm755 greet $out/bin/greet
    install -Dm644 README.md $out/share/doc/greet/README.md
    runHook postInstall
  '';

  postInstall = ''
    echo "postInstall ran" > $out/share/doc/greet/hook-proof
  '';

  meta = {
    description = "Prints a friendly greeting";
    license = lib.licenses.mit;
    mainProgram = "greet";
    platforms = lib.platforms.unix;
  };
})
```

```bash
nix-build -A greet
./result/bin/greet --version
cat result/share/doc/greet/hook-proof
ls result/share/doc/greet
```

```text expect
greet 1.0
postInstall ran
README.md
```

`PREFIX` is gone from `makeFlags` because `make install` no longer runs.

</details>

## Check yourself

<details><summary>Which phase would run <code>./configure</code>, and why did it do nothing here?</summary>

`configurePhase`. It runs `$configureScript` (default `./configure`) with `--prefix=$out`
and `configureFlags`. Our source has no `configure` script, so it printed "no configure
script, doing nothing". Set `dontConfigure = true` to skip the phase explicitly.

</details>

<details><summary>Why add a <code>postInstall</code> instead of overriding <code>installPhase</code>?</summary>

`postInstall` adds to the default phase; overriding replaces it. Replacing loses the default
behaviour (`make install` with your flags) and, if you forget `runHook preInstall` /
`runHook postInstall`, the hooks of everyone downstream. Replace a phase only when the
default cannot work.

</details>

<details><summary>With <code>__structuredAttrs = true</code>, how do you export an environment variable to the build, e.g. <code>NIX_CFLAGS_COMPILE</code>?</summary>

Put it under `env`: `env.NIX_CFLAGS_COMPILE = "-O3";`. Top-level attributes become bash
variables only (not exported), so compilers and other child processes would not see them.

</details>

<details><summary>You changed one line in <code>src/README.md</code>. Does <code>greet</code> rebuild?</summary>

Yes. `src = ./src` copies the whole directory into the store, so any change to it changes
the source's store path, the derivation, and the output path. Lesson 2 uses `lib.fileset`
to include only the files that matter.

</details>
