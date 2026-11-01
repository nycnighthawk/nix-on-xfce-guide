# Project 01b — Prove reproducibility

**Goal:** stop *assuming* builds are reproducible and check it. Rebuild a package you
downloaded from cache.nixos.org and compare it bit for bit. Then write a build that isn't
reproducible, catch it, fix it, and finally compare two closures to see exactly what differs.

**You'll practise:** *rebuild-and-compare* (`nix-build --check`, `nix build --rebuild`),
*removing sources of non-determinism* (clocks, randomness), and *closure comparison*
(`nix store diff-closures`).

## Background: what "reproducible" means here

Input addressing (lesson 01.2) guarantees that the same recipe gives the same *path*. It
doesn't guarantee the same *bytes*. A builder can still read the clock, use random numbers,
depend on thread timing or embed the build directory. The sandbox removes most outside
influences, and nixpkgs' `stdenv` sets `SOURCE_DATE_EPOCH` and fixes the build directory
(`/build`). The rest is up to the package.

**Bit-for-bit reproducibility** means anyone can rebuild a path and get an identical NAR,
so a binary cache can be checked independently instead of trusted (see
reproducible-builds.org and the nixpkgs manual, *Reproducible builds*). Nix's tool for this
is the `--check` build mode: build the derivation *again*, even though its output is valid,
and compare the new result with the existing one.

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

## 1. Check the cache: rebuild GNU hello yourself

Fetch hello from the cache (instant), then rebuild it from source locally with `--check`.
This downloads the compiler toolchain once and compiles hello in about a minute. If the
result differs in any byte from what cache.nixos.org served, the command fails.

```bash timeout=2400
nix-build nixpkgs.nix -A hello -o hello
nix-build nixpkgs.nix -A hello --check --no-out-link
echo "hello rebuilt locally: identical to the cache's copy"
```

```text expect
hello rebuilt locally: identical to the cache's copy
```

That's an independent check of the cache's signature: you didn't have to trust Hydra
for this path.

## 2. A build that isn't reproducible

This derivation stamps its output with the build time and a random number, two classic
sources of non-determinism:

```nix file=stamp.nix
let
  pkgs = import ./nixpkgs.nix { };
in
derivation {
  name = "build-stamp";
  system = "x86_64-linux";
  builder = "${pkgs.bash}/bin/bash";
  PATH = "${pkgs.coreutils}/bin";
  args = [
    "-c"
    ''
      echo "built at: $(date +%s.%N)" > $out
      echo "lucky number: $RANDOM" >> $out
    ''
  ];
}
```

Build it once. It works, and nothing seems wrong:

```bash
nix-build stamp.nix
cat result
```

```text expect
built at:
lucky number:
```

Now rebuild and compare. The second build gets another time and another number, so the
check fails:

```bash fails
nix-build stamp.nix --check
```

```text expect
may not be deterministic
```

The new CLI has the same check under a different name:

```bash fails
nix build -f stamp.nix --rebuild
```

```text expect
may not be deterministic
```

To *see* the difference, add `--keep-failed`. Nix then keeps the second result next to the
first as `<path>.check`, and you can `diff` the two (or use `diffoscope` for binaries):

```console
$ nix-build stamp.nix --check --keep-failed
error: derivation '/nix/store/…-build-stamp.drv' may not be deterministic: output "/nix/store/…-build-stamp" differs from "/nix/store/…-build-stamp.check"
$ diff /nix/store/…-build-stamp /nix/store/…-build-stamp.check
```

## 3. Fix it

Don't remove the information. Make it come from the *inputs*:

- **Time:** use a fixed timestamp that's part of the recipe. The convention is the
  `SOURCE_DATE_EPOCH` variable (nixpkgs' stdenv sets it for you; here you set it yourself).
- **Randomness:** seed the generator from the recipe. In bash, assigning to `RANDOM` seeds
  it, so the sequence is the same every time.

```nix file=stamp.nix
let
  pkgs = import ./nixpkgs.nix { };
in
derivation {
  name = "build-stamp";
  system = "x86_64-linux";
  builder = "${pkgs.bash}/bin/bash";
  PATH = "${pkgs.coreutils}/bin";
  SOURCE_DATE_EPOCH = "1700000000";
  args = [
    "-c"
    ''
      echo "built at: $(date -u -d "@$SOURCE_DATE_EPOCH" +%F)" > $out
      RANDOM=42
      echo "lucky number: $RANDOM" >> $out
    ''
  ];
}
```

The recipe changed, so this is a new derivation with a new output path. Build it, then
check it with both tools:

```bash
nix-build stamp.nix
cat result
nix-build stamp.nix --check
nix build -f stamp.nix --rebuild --no-link
echo "fixed: two builds, identical output"
```

```text expect
built at: 2023-11-14
fixed: two builds, identical output
```

## 4. Compare closures

Reproducibility is about *bytes*. Often you also want to know *what changed* between two
builds: which dependencies came or went, and how big they are. Build the same tiny script
twice, once with nixpkgs' interactive `bash` and once with `bashNonInteractive`, the one
`stdenv` uses for scripts:

```nix file=closures.nix
let
  pkgs = import ./nixpkgs.nix { };
  script =
    name: shell:
    derivation {
      inherit name shell;
      system = "x86_64-linux";
      builder = "${shell}/bin/bash";
      args = [
        "-c"
        ''echo "#!$shell/bin/bash" > $out; echo 'echo hi' >> $out''
      ];
    };
in
{
  big = script "hi-interactive" pkgs.bash;
  small = script "hi-noninteractive" pkgs.bashNonInteractive;
}
```

```bash
nix-build closures.nix -A big -o big
nix-build closures.nix -A small -o small
nix path-info --closure-size --human-readable ./small ./big
names() { nix-store --query --requisites "$1" | sed 's|^/nix/store/[a-z0-9]*-||' | sort; }
diff <(names ./small) <(names ./big) || true
```

```text expect
readline
```

The interactive bash brings in `readline` (and its terminal library). Nix can summarise a
diff like this per package, with versions and size changes. It's the same command NixOS
users run between two system generations:

```bash
nix store diff-closures ./small ./big
```

```text expect
readline:
```

Each line is a package name, its version before → after (`∅` = absent), and the size
change.

## Verification

- `nix-build nixpkgs.nix -A hello --check` passes: your build of hello equals the cache's.
- The first `stamp.nix` fails `--check` / `--rebuild` with "may not be deterministic".
- The fixed `stamp.nix` passes both, and prints the date taken from `SOURCE_DATE_EPOCH`.
- You can name the packages that differ between two closures.

## Stretch goals

1. **Hidden non-determinism.** Write a builder that lists a directory with `ls -U` (directory
   order), or writes files from several background jobs, and catch it with `--check`.
   Which of these does the sandbox *not* protect you from?
2. **Use diffoscope.** `nix shell -f nixpkgs.nix diffoscope -c diffoscope A B` on the kept
   `.check` output of a non-deterministic build.
3. **Check something bigger.** Run `--check` on a package with a compiled binary, such as
   `nix-build nixpkgs.nix -A jq --check`. Is it reproducible?
4. **Content addressing.** Read the manual's *Store → Content-Addressing Store Objects* and
   the `ca-derivations` experimental feature. With CA derivations, the output path comes
   from the result. Why does that let Nix stop rebuilding dependents when a change doesn't
   affect a build's output ("early cutoff")?
