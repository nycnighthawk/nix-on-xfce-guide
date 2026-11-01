# Project 03b — Repair a broken build

**Goal:** package `motd`, a tiny C tool written for a conventional Linux. Its Makefile calls
`/usr/bin/gcc` and installs into `/usr`; the program reads its data from `/usr/share` and
pipes it through `cowsay`, which it expects on `$PATH`. Make it build, make it run, and
prove it runs in an **empty environment** (`env -i`) on a machine where neither `/usr/share/motd`
nor `cowsay` exists.

**You will practise:**

- **Reading failures** — each fix is driven by the error in front of you, one at a time.
- **Build-time path fixes** — `makeFlags` and `substituteInPlace --replace-fail`.
- **Runtime path fixes** — patching the store path into the program.
- **Runtime dependencies** — `wrapProgram --prefix PATH`, and how Nix discovers the
  dependency by scanning.
- **Tests travel with the package** — a `passthru.tests` that runs the tool with `env -i`
  inside the sandbox.

## The upstream source

Treat these files as upstream's: you do not edit them, you fix them from `package.nix`.

```c file=motd/motd.c
/* motd: print the first quote of the day, as said by a cow. */
#include <signal.h>
#include <stdio.h>
#include <string.h>

#define QUOTES "/usr/share/motd/quotes.txt"

int main(void) {
  char line[256];
  FILE *in = fopen(QUOTES, "r");
  if (!in) {
    perror("motd: cannot open " QUOTES);
    return 1;
  }
  if (!fgets(line, sizeof line, in)) {
    fprintf(stderr, "motd: %s is empty\n", QUOTES);
    return 1;
  }
  fclose(in);
  line[strcspn(line, "\n")] = '\0';

  signal(SIGPIPE, SIG_IGN);
  FILE *cow = popen("cowsay", "w");
  if (!cow) {
    perror("motd: popen");
    return 1;
  }
  fprintf(cow, "%s\n", line);
  if (pclose(cow) != 0) {
    fprintf(stderr, "motd: cowsay failed (is it on your PATH?)\n");
    return 1;
  }
  return 0;
}
```

```text file=motd/quotes.txt
Nix builds are pure functions
Pin your inputs
```

```make file=motd/Makefile
PREFIX = /usr

motd: motd.c
	/usr/bin/gcc -O2 -Wall -o motd motd.c

install: motd
	install -Dm755 motd $(PREFIX)/bin/motd
	install -Dm644 quotes.txt $(PREFIX)/share/motd/quotes.txt

.PHONY: install
```

On a typical Ubuntu machine with `gcc` and `cowsay` installed, `make && sudo make install`
works. Nix has neither `/usr/bin/gcc` nor a writable `/usr`, and the result must not depend
on what happens to be installed.

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

```nix file=default.nix
let
  pkgs = import ./nixpkgs.nix {
    config = { };
    overlays = [ ];
  };
in
{
  motd = pkgs.callPackage ./package.nix { };
}
```

## Step 1 — the naive package

```nix file=package.nix
{ lib, stdenv }:

stdenv.mkDerivation {
  pname = "motd";
  version = "1.0";
  src = ./motd;

  __structuredAttrs = true;
  strictDeps = true;

  meta = {
    description = "Prints the quote of the day, as said by a cow";
    license = lib.licenses.mit;
    mainProgram = "motd";
  };
}
```

```bash fails
nix-build -A motd
```

```text expect
/usr/bin/gcc
```

The build phase ran `make`, and make ran `/usr/bin/gcc`: no such file in the sandbox. The
compiler in a Nix build is the wrapped one named by `$CC`.

## Step 2 — fix the build-time paths

Two problems, two tools:

- The compiler path is **inside a recipe**, so no make variable can override it. Rewrite it
  with `substituteInPlace` in `postPatch`. Use `'$(CC)'` in single quotes so the shell leaves
  it alone and make expands it.
- `PREFIX = /usr` is a make variable. Variables given on make's command line override
  assignments in the Makefile, so `makeFlags` is enough — no patching.

```nix file=package.nix
{ lib, stdenv }:

stdenv.mkDerivation {
  pname = "motd";
  version = "1.0";
  src = ./motd;

  __structuredAttrs = true;
  strictDeps = true;

  postPatch = ''
    substituteInPlace Makefile --replace-fail /usr/bin/gcc '$(CC)'
  '';

  makeFlags = [ "PREFIX=${placeholder "out"}" ];

  meta = {
    description = "Prints the quote of the day, as said by a cow";
    license = lib.licenses.mit;
    mainProgram = "motd";
  };
}
```

```bash
nix-build -A motd
ls -R result/
```

```text expect
motd
quotes.txt
```

It builds and installs. Now run it the honest way, in an empty environment:

```bash fails
env -i ./result/bin/motd
```

```text expect
/usr/share/motd/quotes.txt
```

## Step 3 — fix the runtime data path

The quotes are installed in `$out/share/motd`, but the program looks in `/usr/share/motd`.
This is a hard-coded path in the *source*. Point it at the package's own output. In a phase,
`$out` is the output path:

```nix file=package.nix
{ lib, stdenv }:

stdenv.mkDerivation {
  pname = "motd";
  version = "1.0";
  src = ./motd;

  __structuredAttrs = true;
  strictDeps = true;

  postPatch = ''
    substituteInPlace Makefile --replace-fail /usr/bin/gcc '$(CC)'
    substituteInPlace motd.c --replace-fail /usr/share/motd "$out/share/motd"
  '';

  makeFlags = [ "PREFIX=${placeholder "out"}" ];

  meta = {
    description = "Prints the quote of the day, as said by a cow";
    license = lib.licenses.mit;
    mainProgram = "motd";
  };
}
```

```bash
nix-build -A motd
```

```bash fails
env -i ./result/bin/motd
```

```text expect
cowsay
```

The quote file is found. Now `popen("cowsay")` asks `/bin/sh` to find `cowsay` on `$PATH`;
there is no `PATH` and no cowsay. (It would fail in your normal terminal too, unless you
happen to have cowsay installed — and then it would use *your* cowsay, whatever version that
is.)

## Step 4 — declare the runtime dependency

`cowsay` is a runtime dependency. Wrap the program so its `PATH` starts with cowsay's
`bin/`. `makeWrapper` runs during the build, so it is a `nativeBuildInput`; `cowsay` is only
named in the wrapper, so it needs no input list at all — the string `${cowsay}` is enough.

```nix file=package.nix
{
  lib,
  stdenv,
  makeWrapper,
  cowsay,
  runCommand,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "motd";
  version = "1.0";
  src = ./motd;

  __structuredAttrs = true;
  strictDeps = true;

  nativeBuildInputs = [ makeWrapper ];

  postPatch = ''
    substituteInPlace Makefile --replace-fail /usr/bin/gcc '$(CC)'
    substituteInPlace motd.c --replace-fail /usr/share/motd "$out/share/motd"
  '';

  makeFlags = [ "PREFIX=${placeholder "out"}" ];

  postInstall = ''
    wrapProgram $out/bin/motd --prefix PATH : ${lib.makeBinPath [ cowsay ]}
  '';

  # Run the finished tool with an empty environment, inside the build sandbox.
  passthru.tests.clean-env = runCommand "motd-clean-env" { } ''
    env -i ${lib.getExe finalAttrs.finalPackage} > $out
    grep -q "Nix builds are pure functions" $out
  '';

  meta = {
    description = "Prints the quote of the day, as said by a cow";
    license = lib.licenses.mit;
    mainProgram = "motd";
  };
})
```

```bash
nix-build -A motd
env -i ./result/bin/motd
```

```text expect
Nix builds are pure functions
```

## Verification

**It runs with no environment at all** (above) **and inside the sandbox**, where there is
no `/usr` of any kind:

```bash
nix-build -A motd.tests.clean-env
cat result
```

```text expect
Nix builds are pure functions
```

**Nix knows about cowsay.** The wrapper contains cowsay's store path, so the reference
scanner recorded it. It is in the closure, and it will be copied wherever `motd` is copied:

```bash
motd=$(nix-build -A motd --no-out-link)
nix-store --query --references "$motd"
nix-store --query --requisites "$motd" | grep -c cowsay
```

```text expect
cowsay
```

**No host paths remain.** Search the output for `/usr/`:

```bash
if grep -r /usr/ "$motd"; then echo "found a /usr path"; false; else echo "no /usr paths"; fi
```

```text expect
no /usr paths
```

## What you fixed, and with what

| Problem | Where | Fix |
|---|---|---|
| `/usr/bin/gcc` in a recipe | build time | `substituteInPlace Makefile --replace-fail … '$(CC)'` |
| `PREFIX = /usr` | install time | `makeFlags = [ "PREFIX=${placeholder "out"}" ]` |
| `/usr/share/motd` in the source | runtime data | `substituteInPlace motd.c --replace-fail … "$out/share/motd"` |
| `cowsay` from `$PATH` | runtime program | `wrapProgram … --prefix PATH : ${lib.makeBinPath [ cowsay ]}` |

`--replace-fail` everywhere: if upstream changes any of those lines, the build stops and
tells you, instead of shipping a half-patched tool.

## Stretch goals

1. **Hard-wire instead of wrap.** Replace the wrapper with a third substitution that turns
   `popen("cowsay"` into `popen("${lib.getExe cowsay}"`. Compare the two outputs: what is in
   `bin/` now, and is cowsay still in the closure? When would you prefer each?
2. **One impurity is left.** `popen` runs `/bin/sh`, which is *not* a store path — it works
   because every Linux (and the build sandbox) provides one. Remove it: patch the program to
   use `posix_spawnp`, or substitute the call to run `${runtimeShell}`. Then check with
   `strings $motd/bin/.motd-wrapped | grep /bin/sh`.
3. **Binary wrapper.** Switch `makeWrapper` to `makeBinaryWrapper`. What does `file
   result/bin/motd` say before and after? Why does nixpkgs prefer the binary wrapper on
   macOS?
4. **Make it upstreamable.** Write a patch for the Makefile that uses `CC ?= cc` and
   `PREFIX ?= /usr/local`, and a `-DQUOTES=…` define for the data path, so the next packager
   needs no substitutions at all.

## Check yourself

<details><summary>Why could <code>makeFlags</code> fix <code>PREFIX</code> but not <code>/usr/bin/gcc</code>?</summary>

`PREFIX` is a make variable, and variables set on make's command line override assignments
in the Makefile. `/usr/bin/gcc` is literal text in a recipe; no variable controls it, so the
text itself has to change.

</details>

<details><summary>In step 3, why <code>"$out/share/motd"</code> and not <code>${placeholder "out"}</code>?</summary>

Both work. `postPatch` is shell code that runs during the build, when `$out` is set.
`placeholder "out"` is the Nix-level way to say the same thing in an attribute that is not
shell (such as an element of `makeFlags`); Nix replaces the placeholder with the real path
when it creates the derivation's environment.

</details>

<details><summary>cowsay is in neither <code>buildInputs</code> nor <code>nativeBuildInputs</code>. How does it get into the closure?</summary>

Interpolating `${cowsay}` into the build script makes cowsay an input of the derivation, so
it is built and available. After the build, Nix scans the output for store paths of inputs;
the wrapper script contains cowsay's path, so it is recorded as a runtime reference.
Listing a package in an input list is about the *build* environment; what the output
*refers to* is what makes a runtime dependency.

</details>
