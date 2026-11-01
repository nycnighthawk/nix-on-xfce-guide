# Lesson 07.2 — The new-package checklist

**You will:** build a package that follows every nixpkgs convention, prove to yourself *why*
`finalAttrs`, `__structuredAttrs` and `strictDeps` are required, check `meta` the way CI does,
format with nixfmt, and learn what `nixpkgs-vet` enforces.

Reviewers in nixpkgs see hundreds of new packages. Most review comments are the same dozen
points. Get them right before you push and your PR is a quick "LGTM".

## 0. Should it be in nixpkgs at all?

`pkgs/README.md` ("Quick Start to Adding a Package") asks you to answer these first; if any
answer is "no", publish it in your own flake or the NUR instead:

- Is it ready for general use, and maintained upstream?
- Does it have a clear licence? (No licence means *all rights reserved* — unfree.)
- Will other people use it? A library needs at least one dependent, ideally in the same PR.
- Will **you** maintain it for at least one release cycle?
- Security-sensitive software (web-facing services, auth, crypto) needs a responsive upstream.

## 1. Name, place and version

| Rule (`pkgs/README.md`, "Package naming", "Versioning") | Example |
|---|---|
| `pname` = upstream name, **no upper case** | `"mplayer"`, not `"MPlayer"` |
| attribute = `pname`; keep dashes (no camelCase) | `pkgs.some-package` |
| starts with a digit? prefix the attribute with `_` | `_0ad` |
| directory: `pkgs/by-name/<first two letters, lowercase>/<attr>/package.nix` | `pkgs/by-name/up/upcase/package.nix` |
| `version` starts with a digit | `"1.0.0"`, `"0.3.1rc2"` |
| untagged commit: last release + `-unstable-YYYY-MM-DD` | `"2.2-unstable-2022-03-15"`, or `"0-unstable-…"` with no release |

## 2. A package.nix that passes review

Here is a complete package, annotated. It's a tiny C filter called `upcase`. In nixpkgs `src`
would be a fetcher; here the source sits *inside* the package directory, which also shows the
by-name rule that a package may only refer to files in its own directory.

```c file=pkgs/by-name/up/upcase/src/upcase.c
#include <ctype.h>
#include <stdio.h>
#include <string.h>

#ifndef VERSION
#define VERSION "unknown"
#endif

int main(int argc, char **argv)
{
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        printf("upcase %s\n", VERSION);
        return 0;
    }
    int c;
    while ((c = getchar()) != EOF)
        putchar(toupper(c));
    return 0;
}
```

```make file=pkgs/by-name/up/upcase/src/Makefile
VERSION ?= 0.0.0
PREFIX ?= /usr/local

upcase: upcase.c
	$(CC) $(CFLAGS) -DVERSION='"$(VERSION)"' -o $@ upcase.c

install: upcase
	mkdir -p $(DESTDIR)$(PREFIX)/bin
	install -m 755 upcase $(DESTDIR)$(PREFIX)/bin/upcase

.PHONY: install
```

```nix file=pkgs/by-name/up/upcase/package.nix
# 1. A function of exactly the dependencies it uses. No `...`, no `with pkgs;`.
{
  lib,
  stdenv,
  testers,
}:

# 2. finalAttrs, not `rec`: references see the *final* attributes, after overrides.
stdenv.mkDerivation (finalAttrs: {
  pname = "upcase";
  version = "1.0.0";

  # 3. Required for all new top-level packages (doc/stdenv/stdenv.chapter.md).
  __structuredAttrs = true;
  # 4. Build tools must be in nativeBuildInputs; keeps cross-compilation honest.
  strictDeps = true;

  # In nixpkgs: fetchFromGitHub { owner; repo; tag = "v${finalAttrs.version}"; hash = "sha256-…"; }
  src = ./src;

  makeFlags = [
    "CC=${stdenv.cc.targetPrefix}cc"
    "PREFIX=${placeholder "out"}"
    "VERSION=${finalAttrs.version}"
  ];

  # 5. Tests travel with the package; finalPackage makes them follow overrides.
  passthru.tests.version = testers.testVersion { package = finalAttrs.finalPackage; };

  # 6. meta last, after passthru.
  meta = {
    description = "Convert standard input to upper case";
    homepage = "https://example.org/upcase";
    license = lib.licenses.mit;
    # In nixpkgs: `with lib.maintainers; [ your-handle ]` (lesson 4 adds the handle).
    maintainers = [
      {
        name = "Nix Mastery Learner";
        github = "nix-mastery-learner";
        githubId = 4000000001;
      }
    ];
    mainProgram = "upcase";
    platforms = lib.platforms.unix;
  };
})
```

Build it through nixpkgs' own by-name overlay (as in lesson 1), so this directory behaves
exactly like `pkgs/by-name` in a checkout:

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

```nix file=default.nix
let
  nixpkgs = import ./nixpkgs.nix;
  byName = import ((nixpkgs { }).path + "/pkgs/top-level/by-name-overlay.nix") ./pkgs/by-name;
in
nixpkgs { overlays = [ byName ]; }
```

```bash
nix-build -A upcase
echo 'shout it' | ./result/bin/upcase
./result/bin/upcase --version
nix-build -A upcase.tests --no-out-link
```

```text expect
SHOUT IT
upcase 1.0.0
upcase-1.0.0-test-version
```

Now the three rules people most often ask "why?" about.

### Why `finalAttrs` and not `rec`

`rec { version = "1.0.0"; makeFlags = [ "VERSION=${version}" ]; }` binds `version` when the
file is evaluated. A later `overrideAttrs { version = "9.9.9"; }` changes the attribute but not
the strings that already used it. `finalAttrs` is the *result after all overrides* — a fixed
point (course 02, lesson 5) — so everything that refers to it follows. Compare with the same
package written with `rec`:

```nix file=rec-variant.nix
# The same idea written the old way, for comparison only.
{ stdenv }:

stdenv.mkDerivation rec {
  pname = "upcase-rec";
  version = "1.0.0";
  src = ./pkgs/by-name/up/upcase/src;
  makeFlags = [ "VERSION=${version}" ];
}
```

```bash
nix-instantiate --eval --strict --expr 'with import ./. { }; {
  withFinalAttrs = (upcase.overrideAttrs { version = "9.9.9"; }).makeFlags;
  withRec = ((callPackage ./rec-variant.nix { }).overrideAttrs { version = "9.9.9"; }).makeFlags;
}'
```

```text expect
"VERSION=9.9.9"
withRec = [ "VERSION=1.0.0" ]
```

The `rec` version silently builds 1.0.0 labelled 9.9.9. And because the test uses
`finalAttrs.finalPackage`, the overridden package's test checks the *new* version:

```bash
nix-build --no-out-link -E 'with import ./. { }; (upcase.overrideAttrs { version = "9.9.9"; }).tests.version'
```

```text expect
upcase-9.9.9-test-version
```

### Why `__structuredAttrs = true`

Without it, every attribute reaches the builder as an environment variable — a single string.
A list like `makeFlags = [ "GREETING=Hello there" ]` is joined with spaces and split again on
spaces, so an element containing a space breaks in two. With structured attributes, lists
arrive as real Bash arrays (via `$NIX_ATTRS_SH_FILE`), and only what you put in `env` is
exported. See it:

```nix file=structured-demo.nix
let
  pkgs = import ./nixpkgs.nix { };
  countFlags =
    structured:
    pkgs.stdenvNoCC.mkDerivation {
      name = "count-flags-${if structured then "structured" else "plain"}";
      __structuredAttrs = structured;
      dontUnpack = true;
      makeFlags = [
        "GREETING=Hello there"
        "PREFIX=/opt/x"
      ];
      installPhase = ''
        flags=()
        concatTo flags makeFlags
        echo "makeFlags has ''${#flags[@]} elements:" > $out
        printf '  <%s>\n' "''${flags[@]}" >> $out
      '';
    };
in
{
  plain = countFlags false;
  structured = countFlags true;
}
```

```bash
cat "$(nix-build --no-out-link structured-demo.nix -A plain)"
```

```text expect
makeFlags has 3 elements:
<GREETING=Hello>
<there>
```

```bash
cat "$(nix-build --no-out-link structured-demo.nix -A structured)"
```

```text expect
makeFlags has 2 elements:
<GREETING=Hello there>
```

`concatTo` is the stdenv helper that phases use to read such variables either way. The stdenv
chapter is explicit: "All new top level packages must enable `__structuredAttrs`."

### Why `strictDeps = true`

stdenv sorts dependencies by *where they run*: `nativeBuildInputs` run on the build machine
during the build (compilers, `pkg-config`, `makeWrapper`, test tools); `buildInputs` are for the
machine the package will run on (libraries to link). For historical reasons, stdenv also puts
`buildInputs`' programs on `PATH` — which works until you cross-compile and that program is
for the wrong CPU. `strictDeps = true` turns off the fallback, so mistakes fail now instead of
in someone's cross build:

```nix file=strictdeps-demo.nix
let
  pkgs = import ./nixpkgs.nix { };
  useHello =
    { where, strict }:
    pkgs.stdenvNoCC.mkDerivation (
      {
        name = "uses-hello-${where}${if strict then "-strict" else ""}";
        __structuredAttrs = true;
        strictDeps = strict;
        dontUnpack = true;
        installPhase = ''
          hello > $out
        '';
      }
      // {
        ${where} = [ pkgs.hello ];
      }
    );
in
{
  loose = useHello {
    where = "buildInputs";
    strict = false;
  };
  strict-wrong = useHello {
    where = "buildInputs";
    strict = true;
  };
  strict-right = useHello {
    where = "nativeBuildInputs";
    strict = true;
  };
}
```

```bash
nix-build --no-out-link strictdeps-demo.nix -A loose
```

```bash fails
nix-build --no-out-link strictdeps-demo.nix -A strict-wrong
```

```text expect
hello: command not found
```

```bash
nix-build --no-out-link strictdeps-demo.nix -A strict-right
```

Rule of thumb: if the build *runs* it, it goes in `nativeBuildInputs`.

## 3. `meta`, the way reviewers read it

From `pkgs/README.md` ("Meta attributes") and the nixpkgs manual's meta chapter
(`doc/stdenv/meta.chapter.md`):

- `description` — one sentence; capitalised; **no** leading article ("A", "An", "The"); does not
  start with or mention the package name; **no** trailing period; factual, not "blazing fast".
- `license` — must be set and match upstream; no licence statement → `lib.licenses.unfree`.
- `sourceProvenance` — required if you repackage binaries (`lib.sourceTypes.binaryNativeCode`).
- `mainProgram` — set when there is one obvious executable in `bin/` (as a literal string,
  not `pname`); it's what `nix run` and `lib.getExe` use.
- `maintainers` — must be set for new packages.
- `platforms` — where it can build; `lib.platforms.unix`, `.linux`, `.all`.
- `homepage`, `changelog` — strongly encouraged; `changelog` often interpolates the version.

CI evaluates every package with `config.checkMeta = true` (`ci/eval/outpaths.nix`), which
type-checks `meta` against `pkgs/stdenv/generic/check-meta.nix`. A typo that a normal
evaluation ignores becomes an error there:

```nix file=meta-typo.nix
{
  checkMeta ? false,
}:

let
  pkgs = import ./nixpkgs.nix { config = { inherit checkMeta; }; };
in
pkgs.stdenvNoCC.mkDerivation {
  name = "meta-typo";
  dontUnpack = true;
  installPhase = "touch $out";
  meta = {
    description = "Package with a typo in its meta";
    mainprogram = "meta-typo";
  };
}
```

```bash
nix-instantiate meta-typo.nix
```

```bash fails
nix-instantiate meta-typo.nix --arg checkMeta true
```

```text expect
key 'mainprogram' is unrecognized
```

`checkMeta` checks *types*. The style rules (articles, periods) are checked by reviewers — and,
next, by you.

### Your turn: a `meta` linter

Write `lint-meta.nix`: a function `lib: pkg: [ problems ]` that returns a list of strings, one
per broken rule from the list above (description present, capitalised, no leading article, no
trailing punctuation, doesn't mention `pname`; `license` set; `maintainers` non-empty;
`mainProgram` set). It should return `[ ]` for `upcase` and find six problems in:

```nix
{ pname = "frob"; meta = { description = "The frob tool."; }; }
```

<details><summary>Solution</summary>

```nix file=lint-meta.nix
lib: pkg:
let
  meta = pkg.meta or { };
  description = meta.description or "";
  matches = regex: builtins.match regex description != null;
in
lib.optional (description == "") "meta.description is missing"
++ lib.optional (description != "" && !matches "[A-Z0-9].*") "meta.description is not capitalised"
++ lib.optional (matches "(A|An|The) .*") "meta.description starts with an article"
++ lib.optional (matches ".*[.!?,;:]") "meta.description ends with punctuation"
++ lib.optional (lib.hasInfix (lib.toLower pkg.pname) (lib.toLower description)) "meta.description mentions the package name"
++ lib.optional (!(meta ? license)) "meta.license is missing"
++ lib.optional ((meta.maintainers or [ ]) == [ ]) "meta.maintainers is empty"
++ lib.optional (!(meta ? mainProgram)) "meta.mainProgram is missing"
```

```bash
nix-instantiate --eval --strict --expr 'with import ./. { }; import ./lint-meta.nix lib upcase'
```

```text expect
[ ]
```

```bash
nix-instantiate --eval --strict --expr 'with import ./. { };
  import ./lint-meta.nix lib { pname = "frob"; meta = { description = "The frob tool."; }; }'
```

```text expect
meta.description starts with an article
meta.description ends with punctuation
meta.description mentions the package name
meta.license is missing
meta.maintainers is empty
meta.mainProgram is missing
```

</details>

## 4. Format with nixfmt

CI rejects any `.nix` file that isn't formatted by the official formatter, nixfmt (the style
was fixed by RFC 166). In a checkout you'd run `nix fmt` or `treefmt` (lesson 3 and the project
run the exact CI check). Here, take nixfmt from the pinned nixpkgs:

```bash
NIXFMT=$(nix-build nixpkgs.nix -A nixfmt --no-out-link)/bin/nixfmt
"$NIXFMT" --version
```

```nix file=ugly.nix
{lib,stdenv}: stdenv.mkDerivation {pname="ugly";version="1.0";
    meta={license=lib.licenses.mit;};}
```

`--check` exits non-zero and changes nothing when a file isn't formatted:

```bash fails
"$NIXFMT" --check ugly.nix
```

Format every Nix file you wrote, then check again — this pair (format, then `--check`) is the
whole workflow:

```bash
"$NIXFMT" ugly.nix pkgs/by-name/up/upcase/package.nix
"$NIXFMT" --check ugly.nix pkgs/by-name/up/upcase/package.nix
cat ugly.nix
```

```text expect
pname = "ugly";
license = lib.licenses.mit;
```

## 5. What `nixpkgs-vet` enforces

`nixpkgs-vet` (`pkgs/by-name/ni/nixpkgs-vet`, run by the `nixpkgs-vet` job in
`.github/workflows/lint.yml` via `ci/nixpkgs-vet.nix`) checks the `pkgs/by-name` structure by
comparing your branch (*head*) with the branch you target (*base*). Among its rules
(`pkgs/by-name/README.md`, "Validation"; the full list is in the nixpkgs-vet README):

- every entry is `pkgs/by-name/<shard>/<name>/package.nix`, with `<shard>` the lowercased first
  two characters of `<name>`, and `<name>` a valid attribute name;
- `pkgs.<name>` evaluates to a derivation, defined by `callPackage` of that file;
- files in a package directory don't refer to paths outside it;
- **ratchets**: a *new* top-level package defined with `callPackage` must be in `pkgs/by-name`;
  an attribute already in by-name can't move back.

`ci/nixpkgs-vet.nix` adds two checks of its own: no `<nixpkgs/…>` lookups inside `pkgs/`, and
no two paths that differ only in case.

The real tool needs a full nixpkgs tree for base and head, so the project runs it there. For
quick feedback while you work, a few of its rules fit in a short script:

```bash file=by-name-check.sh
#!/usr/bin/env bash
# by-name-check.sh ROOT ATTR... — a quick, partial re-implementation of some
# nixpkgs-vet rules for pkgs/by-name. The real check is nixpkgs-vet.
set -uo pipefail
root=$1
shift
status=0
fail() {
  echo "by-name-check: $*"
  status=1
}
for attr in "$@"; do
  [[ $attr =~ ^[a-zA-Z_][a-zA-Z0-9_-]*$ ]] || fail "$attr: not a valid attribute name"
  shard=$(printf '%s' "${attr:0:2}" | tr '[:upper:]' '[:lower:]')
  dir=$root/pkgs/by-name/$shard/$attr
  if [[ ! -f $dir/package.nix ]]; then
    fail "$attr: expected pkgs/by-name/$shard/$attr/package.nix"
    continue
  fi
  if grep -rnE --include='*.nix' '(^|[^.])\.\./' "$dir"; then
    fail "$attr: refers to a path outside its directory"
  fi
  if grep -rn --include='*.nix' '<nixpkgs' "$dir"; then
    fail "$attr: uses <nixpkgs>"
  fi
  all=$root/pkgs/top-level/all-packages.nix
  if [[ -f $all ]] && grep -nE "^  $attr = callPackage .*\{ \};" "$all"; then
    fail "$attr: also defined in all-packages.nix with no arguments"
  fi
done
[[ $status == 0 ]] && echo "by-name-check: ok ($*)"
exit $status
```

```bash
chmod +x by-name-check.sh
./by-name-check.sh . upcase
```

```text expect
by-name-check: ok (upcase)
```

A package in the wrong shard that reaches into another package's directory fails twice:

```nix file=pkgs/by-name/xx/oops/package.nix
{ runCommand }:

runCommand "oops" { } ''
  cp -r ${../../up/upcase/src} $out
''
```

```bash fails
./by-name-check.sh . oops
```

```text expect
expected pkgs/by-name/oo/oops/package.nix
```

```bash
mkdir -p pkgs/by-name/oo && mv pkgs/by-name/xx/oops pkgs/by-name/oo/ && rmdir pkgs/by-name/xx
```

```bash fails
./by-name-check.sh . oops
```

```text expect
refers to a path outside its directory
```

```bash
rm -r pkgs/by-name/oo
```

## 6. The rest of the list

- **Sources.** Always a fetcher; prefer `fetchFromGitHub`/`fetchurl` (archives, cacheable,
  proxy-friendly) over `fetchgit`; `tag = …` for releases, a *full* 40-character commit hash for
  `rev`; SRI `hash = "sha256-…"` (course 03 L2 covers `lib.fakeHash`).
- **Patches.** Name them for what they fix or add a comment; prefer `fetchpatch` from an
  upstream commit to vendoring a file.
- **No `overrideAttrs` inside nixpkgs** — change the other package properly instead
  (`pkgs/README.md`, "`overrideAttrs` and `overridePythonAttrs`").
- **No import-from-derivation.** Hydra evaluates the whole set; IFD would serialise builds into
  evaluation.
- **Tests.** Run upstream's test suite (`doCheck = true`), add `versionCheckHook` and/or
  `passthru.tests` (lesson 3).
- **Updates.** Add `passthru.updateScript` so the update bot can bump it (lesson 4).

## Check yourself

<details><summary>Your package puts <code>python3</code> in <code>buildInputs</code> to run a build script, and it builds fine. What will a reviewer say, and why?</summary>

Move it to `nativeBuildInputs` and add `strictDeps = true`. It only works because of the
non-strict `PATH` fallback; when cross-compiling, `buildInputs` are for the target CPU, so the
script would get the wrong interpreter (or none).
</details>

<details><summary>Why does <code>passthru.tests.version</code> use <code>finalAttrs.finalPackage</code> instead of the package's own name (<code>upcase</code>)?</summary>

Referring to `upcase` from the argument list tests the *unmodified* package from `pkgs`. With
`finalPackage` the test belongs to whatever derivation it's attached to, so
`(upcase.overrideAttrs …).tests` tests the overridden build, as you saw with 9.9.9.
</details>

<details><summary>Fix this description: <code>"upcase: A fast tool to uppercase text."</code></summary>

`"Convert standard input to upper case"` — no package name, no article, no subjective "fast",
capitalised, no trailing period.
</details>

<details><summary>Does <code>checkMeta</code> catch a description that ends with a period?</summary>

No. It checks that `meta` has known keys with the right types. Style rules are enforced in
review (and by tools like the `lint-meta.nix` you wrote).
</details>

## Stretch goals

- Run `nix-instantiate --eval --strict -E 'with import ./. { }; upcase.meta.position'` and see
  where `meta` positions point. Why does nixpkgs store positions at all?
- Add a `doCheck = true` `make check` target to the Makefile and wire it up.
- Read `pkgs/stdenv/generic/check-meta.nix` and find which check turns `meta.broken = true` into
  an evaluation error, and how `config.allowBroken` relaxes it.
