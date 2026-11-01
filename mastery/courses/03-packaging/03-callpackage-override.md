# Lesson 03.3 — `callPackage`, overriding, `meta` and `passthru.tests`

**You will:** package GNU hello as a function of its dependencies, customise it with
`override` and `overrideAttrs`, see why `finalAttrs` beats `rec`, read its `meta`, and run
the tests that travel with it.

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

## The package

This is close to nixpkgs' own `pkgs/by-name/he/hello/package.nix`, plus one feature flag.

```nix file=package.nix
{
  lib,
  stdenv,
  fetchurl,
  runCommand,
  testers,
  versionCheckHook,

  # A feature flag: an ordinary argument with a default. callPackage leaves it alone
  # (nixpkgs has no attribute called withNls); `override` can change it.
  withNls ? true,
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

  # NLS = native language support: the translated messages under share/locale.
  configureFlags = lib.optionals (!withNls) [ "--disable-nls" ];

  # Upstream's test suite, inside the build.
  doCheck = true;

  # After installing, run $out/bin/hello --version and look for the version string.
  doInstallCheck = true;
  nativeInstallCheckInputs = [ versionCheckHook ];

  # Tests that are *separate* derivations: built on demand, by CI, by reviewers.
  passthru.tests = {
    version = testers.testVersion { package = finalAttrs.finalPackage; };
    greets = runCommand "hello-greets" { nativeBuildInputs = [ finalAttrs.finalPackage ]; } ''
      [ "$(hello)" = "Hello, world!" ]
      [ "$(hello --greeting=Hi)" = "Hi" ]
      touch $out
    '';
  };

  meta = {
    description = "Program that produces a familiar, friendly greeting";
    homepage = "https://www.gnu.org/software/hello/manual/";
    changelog = "https://git.savannah.gnu.org/cgit/hello.git/plain/NEWS?h=v${finalAttrs.version}";
    license = lib.licenses.gpl3Plus;
    mainProgram = "hello";
    platforms = lib.platforms.all;
  };
})
```

## `callPackage`: the caller supplies the dependencies

`pkgs.callPackage ./package.nix { }` does three things (Nixpkgs manual, *Overriding*;
implementation `lib.customisation.callPackageWith`):

1. imports the file, getting a function;
2. reads its argument names with `builtins.functionArgs` and passes each one that exists in
   `pkgs` (`lib`, `stdenv`, `fetchurl`, …), plus whatever you give in `{ }`, which wins;
3. wraps the result with `lib.makeOverridable`, which adds `.override`.

Arguments with a default that `pkgs` does not have (`withNls`) keep their default. An
argument with no default that nobody supplies is an error, with a hint naming it.

```nix file=default.nix
let
  pkgs = import ./nixpkgs.nix {
    config = { };
    overlays = [ ];
  };
in
rec {
  hello = pkgs.callPackage ./package.nix { };

  # override: call package.nix again with different *arguments*.
  hello-no-nls = hello.override { withNls = false; };

  # overrideAttrs: change the *attributes* given to mkDerivation.
  hello-quick = hello.overrideAttrs (finalAttrs: prevAttrs: {
    pname = "hello-quick";
    doCheck = false;
    postInstall = (prevAttrs.postInstall or "") + ''
      ln -s hello $out/bin/hi
    '';
  });
}
```

Build all three. hello compiles from source here (about a minute each): your derivation is
not byte-identical to nixpkgs', so there is nothing to substitute.

```bash timeout=3600
nix-build -A hello -A hello-no-nls -A hello-quick
./result/bin/hello
./result-3/bin/hi --version | head -n 1
echo "translations with NLS:    $(find -L result -name '*.mo' | wc -l)"
echo "translations without NLS: $(find -L result-2 -name '*.mo' | wc -l)"
[ "$(find -L result-2 -name '*.mo' | wc -l)" -eq 0 ]
```

```text expect
Hello, world!
hello (GNU Hello) 2.12.3
translations without NLS: 0
```

`nix-build` with several `-A` creates `result`, `result-2`, `result-3`, in order.

## `override` vs `overrideAttrs`

| | `pkg.override { … }` | `pkg.overrideAttrs (finalAttrs: prevAttrs: { … })` |
|---|---|---|
| Changes | the arguments of `package.nix` | the attribute set given to `mkDerivation` |
| Typical use | feature flags, swapping a dependency (`openssl = libressl;`), another `stdenv` | version and `src`, patches, flags, phases, `doCheck`, `meta` |
| Comes from | `lib.makeOverridable` (added by `callPackage`) | `mkDerivation` itself |

Rule of thumb: if the thing you want to change is a **name in the argument list**, use
`override`. Otherwise use `overrideAttrs`. They compose:
`(hello.override { withNls = false; }).overrideAttrs { doCheck = false; }`. The older
`overrideDerivation` works below `mkDerivation` and loses hooks; avoid it (manual,
*Overriding*, `<pkg>.overrideDerivation`).

## Why `finalAttrs` and not `rec`

Older nixpkgs code writes `stdenv.mkDerivation rec { … }` and refers to `version` directly.
`rec` is resolved when the file is *read*, so an override later cannot reach inside it.
`finalAttrs` is resolved after all overrides. See the difference without building anything:

```nix file=rec-style.nix
{ stdenv, fetchurl }:

stdenv.mkDerivation rec {
  pname = "hello";
  version = "2.12.3";
  src = fetchurl {
    url = "mirror://gnu/hello/hello-${version}.tar.gz";
    hash = "sha256-DV9gFUOC/uELEUocNOeF2LH0kgc64tOm97FHaHs2aqA=";
  };
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
  hello = pkgs.callPackage ./package.nix { };
  hello-rec = pkgs.callPackage ./rec-style.nix { };

  # Evaluation only — these would fail to build (there is no hello 9.9).
  hello-9-9 = hello.overrideAttrs { version = "9.9"; };
  hello-rec-9-9 = hello-rec.overrideAttrs { version = "9.9"; };

  hello-exe = pkgs.lib.getExe hello;
}
```

```bash
echo "finalAttrs: $(nix eval --raw --file default.nix hello-9-9.name) from $(nix eval --raw --file default.nix hello-9-9.src.url)"
echo "rec:        $(nix eval --raw --file default.nix hello-rec-9-9.name) from $(nix eval --raw --file default.nix hello-rec-9-9.src.url)"
```

```text expect
finalAttrs: hello-9.9 from mirror://gnu/hello/hello-9.9.tar.gz
rec:        hello-9.9 from mirror://gnu/hello/hello-2.12.3.tar.gz
```

The `rec` package now *claims* to be 9.9 and builds 2.12.3. With `finalAttrs`, the URL
follows the version (and the stale hash would fail loudly — course 04 overrides a version
properly). This is why the nixpkgs manual recommends the fixed-point form (*Fixed-point
arguments of mkDerivation*) and new packages use it.

## `meta`: facts about the package, not the build

`meta` does not affect the derivation or its hash. Tools read it: `nix search`, `nix run`
(`mainProgram`), the license and platform checks that refuse to evaluate unfree or
unsupported packages, and the nixpkgs CI (Nixpkgs manual, *Meta-attributes*,
`doc/stdenv/meta.chapter.md`).

```bash
nix eval --raw --file default.nix hello.meta.license.spdxId; echo
nix eval --raw --file default.nix hello.meta.mainProgram; echo
nix eval --raw --file default.nix hello-exe; echo
```

```text expect
GPL-3.0-or-later
hello
/bin/hello
```

`lib.getExe pkg` is `"${pkg}/bin/${pkg.meta.mainProgram}"`. Use it instead of spelling out
`bin/…` paths.

## Tests that travel with the package

Two layers, both in `package.nix`:

- **In the build:** `doCheck` runs upstream's tests; `doInstallCheck` with `versionCheckHook`
  runs the *installed* binary. A failure here fails the package itself.
- **Beside the build:** `passthru.tests` is an attribute set of derivations that test the
  finished package. They do not run when you build `hello`, so they can be slow or need
  extra tools. nixpkgs CI and `nixpkgs-review` build them for every change (manual,
  *Passthru-attributes*, `passthru.tests`).

`passthru` attributes are added to the derivation without becoming build inputs, so the
tests are reachable as `hello.tests`. Note that they use `finalAttrs.finalPackage`, so they
test the package *after* any override — `hello-quick.tests` tests `hello-quick`.

```bash
nix-build -A hello.tests --no-out-link
nix-store --read-log "$(nix-instantiate -A hello)" | grep 'find version'
```

```text expect
Successfully managed to find version 2.12.3
```

## Exercise: `ghello`

GNU's `configure` accepts `--program-prefix=g`, which installs the binary as `ghello`.
Add a `ghello` attribute to `default.nix` that builds hello this way, without editing
`package.nix`. Both the install check and `passthru.tests.version` must still pass.

<details><summary>Hint</summary>

Both tests find the binary through `meta.mainProgram`.

</details>

<details><summary>Solution</summary>

`overrideAttrs` can change `meta` too. Append to the previous flags instead of replacing
them, so `withNls = false` keeps working through `override`.

```nix file=default.nix
let
  pkgs = import ./nixpkgs.nix {
    config = { };
    overlays = [ ];
  };
in
rec {
  hello = pkgs.callPackage ./package.nix { };

  ghello = hello.overrideAttrs (finalAttrs: prevAttrs: {
    pname = "ghello";
    configureFlags = prevAttrs.configureFlags ++ [ "--program-prefix=g" ];
    # hello's own test suite runs the program as `hello`, so it can't pass once the binary is
    # renamed; the version checks below still test the renamed program.
    doCheck = false;
    meta = prevAttrs.meta // { mainProgram = "ghello"; };
  });
}
```

```bash timeout=1800
nix-build -A ghello
nix-build -A ghello.tests.version --no-out-link
./result/bin/ghello
ls result/bin
```

```text expect
Hello, world!
ghello
```

`versionCheckHook` reads `NIX_MAIN_PROGRAM`, which `mkDerivation` sets from the *final*
`meta.mainProgram`; `testers.testVersion` reads `package.meta.mainProgram` of the final
package. Both follow the override.

</details>

## Check yourself

<details><summary>You want hello built with clang. <code>override</code> or <code>overrideAttrs</code>?</summary>

`override { stdenv = pkgs.clangStdenv; }`: `stdenv` is an argument of `package.nix`. With
`overrideAttrs` you can only change what is passed *to* `stdenv.mkDerivation`, by which time
the stdenv has been chosen.

</details>

<details><summary>Why do the <code>passthru.tests</code> use <code>finalAttrs.finalPackage</code> instead of the <code>hello</code> argument?</summary>

`finalAttrs.finalPackage` is the package after all overrides. A test written against a
`hello` argument (as the real nixpkgs file does for one of its tests) tests the *unmodified*
package from the package set, even when you build the tests of an overridden one.

</details>

<details><summary>Does changing <code>meta.description</code> rebuild the package?</summary>

No. `meta` is not passed to the builder, so it is not part of the derivation and does not
change the store path. Changing `doCheck`, `configureFlags` or `postInstall` does.

</details>
