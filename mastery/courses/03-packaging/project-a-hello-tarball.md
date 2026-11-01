# Project 03a — GNU hello from a tarball

**Goal:** package GNU hello 2.12.3 from its release tarball, nixpkgs style, starting from
no hash at all. Hit the hash mismatch on purpose, fix it, run the upstream tests and your
own, and show that your source is the very same store object nixpkgs uses.

**You will practise:**

- **Trust on first use** — `lib.fakeHash`, read the mismatch, verify, commit the hash.
- **`package.nix` as a function of its dependencies**, called with `callPackage`.
- **Tests travel with the package** — `doCheck`, `versionCheckHook`, `passthru.tests`.
- **Content addressing of fixed outputs** — same hash and name, same store path.

## Setup

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
  hello = pkgs.callPackage ./package.nix { };

  # nixpkgs' own hello, for comparison
  upstream-hello = pkgs.hello;
}
```

## Step 1 — write the package without a hash

You know the URL. You do not know the hash, and you must not guess one.

```nix file=package.nix
{
  lib,
  stdenv,
  fetchurl,
  testers,
  versionCheckHook,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "hello";
  version = "2.12.3";

  src = fetchurl {
    url = "mirror://gnu/hello/hello-${finalAttrs.version}.tar.gz";
    hash = lib.fakeHash;
  };

  __structuredAttrs = true;
  strictDeps = true;

  doCheck = true;

  doInstallCheck = true;
  nativeInstallCheckInputs = [ versionCheckHook ];

  passthru.tests.version = testers.testVersion { package = finalAttrs.finalPackage; };

  meta = {
    description = "Program that produces a familiar, friendly greeting";
    homepage = "https://www.gnu.org/software/hello/manual/";
    license = lib.licenses.gpl3Plus;
    mainProgram = "hello";
    platforms = lib.platforms.all;
  };
})
```

## Step 2 — let it fail

```bash fails
nix-build -A hello
```

```text expect
hash mismatch in fixed-output derivation
specified: sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
sha256-DV9gFUOC/uELEUocNOeF2LH0kgc64tOm97FHaHs2aqA=
```

Read the error carefully. The failing derivation is the *source*
(`hello-2.12.3.tar.gz.drv`), not hello itself: Nix built the fetcher first, because hello
depends on it. `specified:` is your fake hash, `got:` is what the mirror served.

## Step 3 — verify before you trust

The `got:` value is only as trustworthy as the download. GNU signs its releases. A
learner-friendly check is to fetch the same file again over HTTPS from the primary site and
compare:

```bash
nix store prefetch-file --json https://ftp.gnu.org/gnu/hello/hello-2.12.3.tar.gz > prefetch.json
cat prefetch.json; echo
```

```text expect
sha256-DV9gFUOC/uELEUocNOeF2LH0kgc64tOm97FHaHs2aqA=
```

(For a real package, also check the GPG signature `hello-2.12.3.tar.gz.sig` against the
maintainer's key; the GNU keyring is at `https://ftp.gnu.org/gnu/gnu-keyring.gpg`.)

## Step 4 — commit the hash and build

```nix file=package.nix
{
  lib,
  stdenv,
  fetchurl,
  testers,
  versionCheckHook,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "hello";
  version = "2.12.3";

  src = fetchurl {
    url = "mirror://gnu/hello/hello-${finalAttrs.version}.tar.gz";
    hash = "sha256-DV9gFUOC/uELEUocNOeF2LH0kgc64tOm97FHaHs2aqA=";
  };

  __structuredAttrs = true;
  strictDeps = true;

  doCheck = true;

  doInstallCheck = true;
  nativeInstallCheckInputs = [ versionCheckHook ];

  passthru.tests.version = testers.testVersion { package = finalAttrs.finalPackage; };

  meta = {
    description = "Program that produces a familiar, friendly greeting";
    homepage = "https://www.gnu.org/software/hello/manual/";
    license = lib.licenses.gpl3Plus;
    mainProgram = "hello";
    platforms = lib.platforms.all;
  };
})
```

```bash timeout=1800
nix-build -A hello
./result/bin/hello
./result/bin/hello --version | head -n 1
```

```text expect
Hello, world!
hello (GNU Hello) 2.12.3
```

## Verification

**Upstream's test suite ran** (check phase), and **the installed binary reported the right
version** (installCheck phase):

```bash
nix-store --read-log "$(nix-instantiate -A hello)" > build.log
grep 'Running phase: checkPhase' build.log
grep -E '# (TOTAL|PASS|FAIL):' build.log || true
grep 'find version' build.log
```

```text expect
Running phase: checkPhase
Successfully managed to find version 2.12.3
```

The `# TOTAL / PASS / FAIL` lines are automake's test-suite summary.

**The separate test passes:**

```bash
nix-build -A hello.tests.version --no-out-link
```

**Your source is nixpkgs' source.** A fixed-output path depends only on the hash, the name
and the hashing mode, so your `src` and nixpkgs' `hello.src` are one and the same store
object — even though you wrote your own `fetchurl` call:

```bash
mine=$(nix eval --raw --file default.nix hello.src.outPath)
theirs=$(nix eval --raw --file default.nix upstream-hello.src.outPath)
echo "$mine"
[ "$mine" = "$theirs" ] && echo "same source store path"
```

```text expect
hello-2.12.3.tar.gz
same source store path
```

**Your package is not nixpkgs' package.** Its derivation differs (different attributes:
`strictDeps`, no `passthru.tests.run`, no `postInstallCheck`, …), so its output path differs
and it had to be built rather than downloaded:

```bash
nix eval --raw --file default.nix hello.outPath; echo
nix eval --raw --file default.nix upstream-hello.outPath; echo
```

**The runtime closure is small:** hello needs only the C library.

```bash
nix-store --query --references "$(readlink result)"
```

```text expect
glibc
```

## What you built, in nixpkgs terms

`package.nix` is ready for `pkgs/by-name/<prefix>/<name>/package.nix`: a function of its
dependencies, `finalAttrs`, structured attributes, an SRI hash from a verified first fetch,
upstream tests on, a version check, `meta` with a license and `mainProgram`. Course 07 puts
a package like this into a nixpkgs checkout and runs nixpkgs' CI checks on it.

## Stretch goals

1. **Automate the TOFU step.** Write a shell snippet that runs the build with `lib.fakeHash`,
   extracts the `got:` hash from the log with `grep -o 'sha256-[A-Za-z0-9+/=]*'`, and writes it
   into `package.nix` with `sed`. Then look at `nix-update` in nixpkgs, which does this (and
   more) for real packages.
2. **Become a cache hit.** Copy `pkgs/by-name/he/hello/package.nix` (and its `test.nix`) from
   the nixpkgs commit you pinned, call it with `callPackage`, and compare its `outPath` with
   `pkgs.hello.outPath`. They are equal — and `nix-build` downloads instead of compiling.
   Then change one character in `postInstallCheck` and watch it build again.
3. **A second version.** Add `hello-2-12-1 = hello.overrideAttrs (…)` to `default.nix` that
   builds 2.12.1, using the fake-hash workflow for the new `src`. Course 04 lesson 3 does
   this with flakes and explains a GCC 15 pitfall with older releases.

## Check yourself

<details><summary>The error in step 2 named <code>hello-2.12.3.tar.gz.drv</code>. Why not <code>hello-2.12.3.drv</code>?</summary>

The source is a separate derivation (a fixed-output one) and an input of hello. Nix builds
inputs first; the source failed, so hello was never attempted.

</details>

<details><summary>Why are your <code>src</code> store path and nixpkgs' identical, when the derivations that produce them may differ?</summary>

For a fixed-output derivation, the output path is computed from the declared hash, the
hashing mode (flat) and the name only. How the file is fetched — URL, mirror list, curl
version — does not enter into it. That is also why a fixed-output source on
`cache.nixos.org` can be substituted for anyone's `fetchurl` with the same hash.

</details>

<details><summary>Why did hello compile on your machine instead of being downloaded from the cache?</summary>

Its derivation is not identical to the one Hydra built (different attributes give a
different `.drv` and so a different output path), and nobody has built yours. Substitution
works by output path. Stretch goal 2 shows the converse.

</details>
