# Lesson 03.4 — Fixing builds: patches, substitutions, wrappers, outputs

**You will:** apply a patch, rewrite strings in sources with `substituteInPlace`, give a
program its runtime dependencies with `wrapProgram`, and split a library into `out` and
`dev` outputs.

Most software assumes a conventional Linux: tools in `/usr/bin`, data in `/usr/share`,
everything on `$PATH`. In a Nix build none of that exists, and at runtime only what the
package declares is guaranteed. Each technique in this lesson closes one of those gaps.

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

## 1. Patches

Use a patch when the change is a real code change: a bug fix, a build fix, a backport. In
nixpkgs, patches either come from upstream (`fetchpatch` with a URL and hash) or live next
to `package.nix` with a comment saying why and whether it was sent upstream (`pkgs/README.md`,
*Patches*).

Here is a program with a typo:

```c file=greet/greet.c
#include <stdio.h>

int main(void) {
  puts("Helo, world!");
  return 0;
}
```

Make the patch the usual way: copy, edit, `diff -u`. (`diff` exits with 1 when the files
differ, which is what we want.)

```bash
cp -r greet greet-fixed
sed -i 's/Helo/Hello/' greet-fixed/greet.c
diff -u greet/greet.c greet-fixed/greet.c > fix-typo.patch || [ $? -eq 1 ]
cat fix-typo.patch
```

```text expect
-  puts("Helo, world!");
+  puts("Hello, world!");
```

The patch phase runs `patch -p1` for each entry in `patches`, from inside the source
directory. `-p1` strips the first path component (`greet/`, `greet-fixed/`), leaving
`greet.c`.

```nix file=patched.nix
{ stdenv }:

stdenv.mkDerivation {
  pname = "greet";
  version = "1.0";
  src = ./greet;

  __structuredAttrs = true;
  strictDeps = true;

  patches = [ ./fix-typo.patch ];

  # No Makefile upstream, so we write the two phases ourselves (with their hooks).
  buildPhase = ''
    runHook preBuild
    $CC -O2 -o greet greet.c
    runHook postBuild
  '';
  installPhase = ''
    runHook preInstall
    install -Dm755 greet $out/bin/greet
    runHook postInstall
  '';

  meta.mainProgram = "greet";
}
```

## 2. `substituteInPlace`: rewrite strings

For small, mechanical changes — a hard-coded path, a tool name, a version string — a patch is
overkill and breaks on every upstream release. `substituteInPlace FILE --replace-fail OLD NEW`
edits the file in place during the build (Nixpkgs manual, *The Standard Environment*,
`substitute` and `substituteInPlace`).

The flags:

| Flag | If `OLD` is not found |
|---|---|
| `--replace-fail OLD NEW` | the build **fails** — use this by default |
| `--replace-warn OLD NEW` | prints a warning |
| `--replace-quiet OLD NEW` | does nothing |
| `--subst-var NAME` / `--subst-var-by NAME VALUE` | replaces `@NAME@` placeholders |

`--replace-fail` matters: when upstream changes the line you were rewriting, you want to
hear about it, not ship an unpatched program. (The old `--replace` flag is deprecated.)

A script that calls GNU hello by name:

```bash file=scripts/greet-twice
#!/usr/bin/env bash
# Greets twice, using GNU hello.
set -eu
name=${1:-${GREET_NAME:-world}}
hello --greeting="Hello, $name!"
hello --greeting="Hello again, $name!"
```

Hard-wire hello's store path into it, in `postPatch` (after patches, before the build):

```nix file=hardwired.nix
{
  lib,
  stdenvNoCC,
  bash,
  hello,
  pattern ? "hello --greeting",
}:

stdenvNoCC.mkDerivation {
  pname = "greet-twice-hardwired";
  version = "1.0";
  src = ./scripts;

  __structuredAttrs = true;
  strictDeps = true;

  # The interpreter in the #! line runs on the *host*, so it is a buildInput. With
  # strictDeps, patchShebangs only looks for interpreters there.
  buildInputs = [ bash ];

  postPatch = ''
    substituteInPlace greet-twice \
      --replace-fail '${pattern}' '${lib.getExe hello} --greeting'
  '';

  dontBuild = true;
  installPhase = ''
    runHook preInstall
    install -Dm755 greet-twice $out/bin/greet-twice
    runHook postInstall
  '';

  meta.mainProgram = "greet-twice";
}
```

The `pattern` argument exists only so we can break the build on purpose in a moment.

## 3. `makeWrapper` and `wrapProgram`: set the environment

Hard-wiring is precise, but you have to find every call. The alternative is to leave the
program alone and **wrap** it: `wrapProgram $out/bin/prog ARGS` renames the program to
`.prog-wrapped` and puts a small script in its place that sets up the environment and
`exec`s the original. `makeWrapper` (in `nativeBuildInputs`) provides the function. Its
arguments are documented in `pkgs/build-support/setup-hooks/make-wrapper.sh`:

| Argument | Effect |
|---|---|
| `--prefix PATH : DIRS` | put `DIRS` in front of `$PATH` |
| `--suffix PATH : DIRS` | append, as a fallback the user can override |
| `--set VAR VALUE` | always set `VAR` |
| `--set-default VAR VALUE` | set `VAR` only if the caller has not |
| `--add-flags "…"` | add arguments before the user's |

```nix file=wrapped.nix
{
  lib,
  stdenvNoCC,
  makeWrapper,
  bash,
  hello,
  withWrapper ? true,
}:

stdenvNoCC.mkDerivation {
  pname = "greet-twice";
  version = "1.0";
  src = ./scripts;

  __structuredAttrs = true;
  strictDeps = true;

  nativeBuildInputs = [ makeWrapper ];
  buildInputs = [ bash ];

  dontBuild = true;
  installPhase = ''
    runHook preInstall
    install -Dm755 greet-twice $out/bin/greet-twice
    runHook postInstall
  '';

  postInstall = lib.optionalString withWrapper ''
    wrapProgram $out/bin/greet-twice --prefix PATH : ${lib.makeBinPath [ hello ]}
  '';

  meta.mainProgram = "greet-twice";
}
```

```nix file=default.nix
let
  pkgs = import ./nixpkgs.nix {
    config = { };
    overlays = [ ];
  };
in
rec {
  patched = pkgs.callPackage ./patched.nix { };
  hardwired = pkgs.callPackage ./hardwired.nix { };
  broken-substitution = hardwired.override { pattern = "hullo --greeting"; };
  wrapped = pkgs.callPackage ./wrapped.nix { };
  unwrapped = wrapped.override { withWrapper = false; };
}
```

> **Name optional arguments `withX`/`enableX`.** `callPackage` fills *every* argument whose name
> matches an attribute of `pkgs` — defaults are only used when nothing matches. Name the flag
> `wrap` and you get nixpkgs' `wrap` package (a Go program) instead of `true`, and evaluation
> fails with `expected a Boolean but found a set`. (This lesson hit exactly that in CI.) nixpkgs
> avoids it by convention: `withWrapper`, `enableTests`, `withNls`.

### The patch

```bash
nix-build -A patched
./result/bin/greet
```

```text expect
Hello, world!
```

### The substitution, and how it fails

```bash
nix-build -A hardwired
grep -- '--greeting' result/bin/greet-twice
env -i ./result/bin/greet-twice Nix
```

```text expect
/bin/hello --greeting
Hello, Nix!
Hello again, Nix!
```

`env -i` runs the program with an **empty environment**: no `PATH`, no `HOME`. That is the
honest test of whether a package declares its dependencies. It passes because the script
now names hello by its store path.

If upstream renames the call, `--replace-fail` catches it:

```bash fails
nix-build -A broken-substitution
```

```text expect
doesn't match anything
```

### The wrapper

First the unwrapped script, in an empty environment:

```bash
nix-build -A unwrapped -o result-unwrapped
head -n 1 result-unwrapped/bin/greet-twice
```

```text expect
#!/nix/store/
```

The fixup phase's `patchShebangs` rewrote `#!/usr/bin/env bash` to a store path — because
`bash` is in `buildInputs`. The interpreter is fine; `hello` is not:

```bash fails
env -i ./result-unwrapped/bin/greet-twice Nix
```

```text expect
hello: command not found
```

Now the wrapped one:

```bash
nix-build -A wrapped
env -i ./result/bin/greet-twice Nix
cat result/bin/greet-twice
```

```text expect
Hello, Nix!
Hello again, Nix!
.greet-twice-wrapped
PATH=
```

Either way, the store path of hello is written into a file in the output, so Nix's
reference scanner records it as a **runtime dependency**. Copy this package to another
machine and hello comes along:

```bash
nix-store --query --references "$(readlink result)" | grep -c hello
```

### Which one to use

- **Hard-wire** (`substituteInPlace`) when the program calls a handful of known tools: it is
  exact, it costs nothing at runtime, and nothing in the user's environment can interfere.
- **Wrap** (`wrapProgram`) when the program calls tools you cannot easily enumerate, needs
  environment variables (`PYTHONPATH`, `GIO_MODULE_DIR`, …), or is an interpreted script you
  would rather not edit. `--prefix` fixes the dependency; `--suffix` only offers a fallback.
- Prefer `makeBinaryWrapper` over `makeWrapper` when you do not need shell features in the
  wrapper: it produces a tiny compiled wrapper that also works as a `#!` interpreter
  (manual, `makeWrapper`).

## 4. Multiple outputs

Headers, static libraries, `pkg-config` files and documentation are only needed when
*building against* a package. Splitting them into separate outputs keeps the runtime
closure small. You declare `outputs`; the fixup phase's `multiple-outputs.sh` hook moves
standard directories (`include/` to `dev`, `share/man` to `man`, `share/doc` to `doc`, …)
for you. Source: Nixpkgs manual, *Multiple-output packages*
(`doc/stdenv/multiple-output.chapter.md`).

```c file=libgreet/greet.h
#ifndef GREET_H
#define GREET_H
const char *greeting(void);
#endif
```

```c file=libgreet/greet.c
#include "greet.h"

const char *greeting(void) { return "Hello from libgreet!"; }
```

```c file=libgreet/demo.c
#include <stdio.h>
#include "greet.h"

int main(void) {
  puts(greeting());
  return 0;
}
```

```make file=libgreet/Makefile
PREFIX ?= /usr/local

all: libgreet.a greet-demo

greet.o: greet.c greet.h
	$(CC) $(CFLAGS) -c -o greet.o greet.c

libgreet.a: greet.o
	$(AR) rcs libgreet.a greet.o

greet-demo: demo.c libgreet.a
	$(CC) $(CFLAGS) -o greet-demo demo.c libgreet.a

install: all
	install -Dm644 greet.h $(PREFIX)/include/greet.h
	install -Dm644 libgreet.a $(PREFIX)/lib/libgreet.a
	install -Dm755 greet-demo $(PREFIX)/bin/greet-demo

.PHONY: all install
```

```nix file=libgreet.nix
{ stdenv }:

stdenv.mkDerivation {
  pname = "libgreet";
  version = "1.0";
  src = ./libgreet;

  __structuredAttrs = true;
  strictDeps = true;

  # The first output is the default one: what `${libgreet}` and `result` refer to.
  outputs = [
    "out"
    "dev"
  ];

  makeFlags = [ "PREFIX=${placeholder "out"}" ];

  meta.mainProgram = "greet-demo";
}
```

A consumer only names `libgreet`. stdenv picks the `dev` output for `buildInputs`, and the
`dev` output propagates `out`, so the compiler finds both the header and the library:

```c file=consumer/consumer.c
#include <stdio.h>
#include <greet.h>

int main(void) {
  printf("consumer says: %s\n", greeting());
  return 0;
}
```

```nix file=consumer.nix
{ stdenv, libgreet }:

stdenv.mkDerivation {
  pname = "greet-consumer";
  version = "1.0";
  src = ./consumer;

  __structuredAttrs = true;
  strictDeps = true;

  buildInputs = [ libgreet ];

  buildPhase = ''
    runHook preBuild
    $CC -o consumer consumer.c -lgreet
    runHook postBuild
  '';
  installPhase = ''
    runHook preInstall
    install -Dm755 consumer $out/bin/consumer
    runHook postInstall
  '';
}
```

```nix file=default.nix
let
  pkgs = import ./nixpkgs.nix {
    config = { };
    overlays = [ ];
  };
in
rec {
  libgreet = pkgs.callPackage ./libgreet.nix { };
  consumer = pkgs.callPackage ./consumer.nix { inherit libgreet; };
}
```

```bash
out=$(nix-build -A libgreet.out --no-out-link)
dev=$(nix-build -A libgreet.dev --no-out-link)
echo "out: $(cd $out && find . -type f | sort | tr '\n' ' ')"
echo "dev: $(cd $dev && find . -type f | sort | tr '\n' ' ')"
[ ! -e "$out/include" ]
nix-build -A consumer
./result/bin/consumer
```

```text expect
./bin/greet-demo
./lib/libgreet.a
./include/greet.h
./nix-support/propagated-build-inputs
consumer says: Hello from libgreet!
```

`include/` moved to `dev` by itself. `dev/nix-support/propagated-build-inputs` names the
`out` path, which is how depending on `dev` brings in `out`. In nixpkgs you would also add
`"man"`, `"doc"` or `"bin"` outputs where they exist, and `separateDebugInfo = true` for
a `debug` output.

## Exercise: a default that callers can override

`greet-twice` greets `$GREET_NAME` when given no argument. Make the wrapped package default
to the name `Nixer`, while still letting a caller's `GREET_NAME` win. Check both in `env -i`.

<details><summary>Solution</summary>

`--set-default` sets the variable only if the caller has not; `--set` would always win.

```nix file=wrapped.nix
{
  lib,
  stdenvNoCC,
  makeWrapper,
  bash,
  hello,
  withWrapper ? true,
}:

stdenvNoCC.mkDerivation {
  pname = "greet-twice";
  version = "1.0";
  src = ./scripts;

  __structuredAttrs = true;
  strictDeps = true;

  nativeBuildInputs = [ makeWrapper ];
  buildInputs = [ bash ];

  dontBuild = true;
  installPhase = ''
    runHook preInstall
    install -Dm755 greet-twice $out/bin/greet-twice
    runHook postInstall
  '';

  postInstall = lib.optionalString withWrapper ''
    wrapProgram $out/bin/greet-twice \
      --prefix PATH : ${lib.makeBinPath [ hello ]} \
      --set-default GREET_NAME Nixer
  '';

  meta.mainProgram = "greet-twice";
}
```

```nix file=default.nix
let
  pkgs = import ./nixpkgs.nix {
    config = { };
    overlays = [ ];
  };
in
{
  wrapped = pkgs.callPackage ./wrapped.nix { };
}
```

```bash
nix-build -A wrapped
env -i ./result/bin/greet-twice
env -i GREET_NAME=Ada ./result/bin/greet-twice
```

```text expect
Hello, Nixer!
Hello again, Ada!
```

</details>

## Check yourself

<details><summary>Why is <code>bash</code> in <code>buildInputs</code> and not <code>nativeBuildInputs</code>?</summary>

The `#!` interpreter runs when the *installed* program runs, on the host platform, so it is
a host dependency. With `strictDeps`, `patchShebangs` only resolves interpreters from host
dependencies (`buildInputs`); a `bash` in `nativeBuildInputs` is the build machine's bash,
which is wrong when cross-compiling.

</details>

<details><summary>When should a <code>substituteInPlace</code> use <code>--replace-warn</code> instead of <code>--replace-fail</code>?</summary>

Rarely: when the pattern is genuinely optional, e.g. one substitution shared by several
versions where only some contain the string. By default use `--replace-fail`, so a changed
upstream file breaks the build instead of producing a silently unpatched program.

</details>

<details><summary>How did hello become a runtime dependency of <code>greet-twice</code>, when nothing declared it as one?</summary>

After the build, Nix scans the output for the hash parts of store paths that were inputs to
the build. The wrapper (or the substituted script) contains hello's path, so hello is
recorded as a reference and becomes part of the closure. Runtime dependencies are
discovered, not declared.

</details>

<details><summary>What does <code>outputs = [ "out" "dev" ]</code> do if you never move anything yourself?</summary>

The `multiple-outputs.sh` setup hook moves standard paths in the fixup phase: `include/`,
`lib/pkgconfig`, `lib/cmake`, `share/aclocal` to `dev`, documentation and man pages to their
outputs, and writes `dev/nix-support/propagated-build-inputs` so that `dev` pulls in `out`.
For autoconf packages it also passes `--includedir=$dev/include` and friends to `configure`.

</details>
