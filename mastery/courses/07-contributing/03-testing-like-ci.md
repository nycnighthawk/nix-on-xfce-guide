# Lesson 07.3 — Testing like CI

**You will:** learn what nixpkgs' CI runs on every pull request, run the same kinds of checks
yourself — build in the sandbox, rebuild to check determinism, `passthru.tests`, evaluation for
another platform — and see how `nixpkgs-review` builds everything your change affects.

A reviewer's first question is "does it build, and how do you know it works?". Answer it before
they ask: the PR template has a checkbox for each of these.

## What CI runs on a PR

nixpkgs' CI is GitHub Actions (`.github/workflows/`, entry point `pull-request-target.yml`)
plus the ofborg build bot. Almost every job is a `nix-build ci -A <something>`, which means you
can run it locally from a checkout:

| Job | What it checks | Local equivalent (from a checkout) |
|---|---|---|
| Lint › treefmt | every file formatted (nixfmt, keep-sorted, editorconfig, …) | `nix-build ci -A fmt.check` (or `nix fmt` to fix) |
| Lint › parse | every `.nix` file parses with several Nix versions | `nix-build ci -A parse` |
| Lint › nixpkgs-vet | `pkgs/by-name` rules, base vs head | `./ci/nixpkgs-vet.sh master` |
| Lint › commits | commit titles and author fields | (lesson 4 writes a local version) |
| Eval | evaluates all packages on four platforms with `checkMeta`; diffs output paths against the base → rebuild labels, reviewer requests | `nixpkgs-review` (below) does the same diff |
| Build | manuals, `lib` tests, the dev shell | `nix-build ci -A manual-nixpkgs`, `-A lib-tests` |
| ofborg | builds the attributes named in commit titles (`greet: …`) and their `passthru.tests` | `nix-build -A greet -A greet.tests` |

The project at the end of this course runs the build, test, treefmt and nixpkgs-vet checks for
real in a nixpkgs checkout. This lesson works with the pinned tarball, which behaves the same:
`nix-build nixpkgs.nix -A hello` here is `nix-build -A hello` at the root of a checkout.

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

## Build in the sandbox

Hydra builds with the sandbox on, so the PR template asks whether you did too. On Linux it's the
default; confirm:

```bash
nix config show sandbox
```

```text expect
true
```

`nix-build -A` builds the attribute and leaves `./result`. If a build fails, `-K` (`--keep-failed`)
keeps the build directory under `/tmp` so you can look inside; `nix log <path or drv>` replays
the log of anything built on this machine.

## Rebuild to check determinism

`--check` builds an attribute *again* — even though it's already in the store — and fails if the
new output differs bit for bit. Non-determinism (timestamps, build paths, random ordering)
breaks binary caching and reproducibility, so reviewers like seeing this:

```bash timeout=1800
nix-build nixpkgs.nix -A hello --no-out-link
nix-build nixpkgs.nix -A hello --check --no-out-link
```

The first command substitutes hello from the cache; the second downloads the source and builds
it locally once more, then compares. If outputs differed you'd get `error: derivation '…' may not be deterministic`, and
`--keep-failed` would keep both versions (`…-check`) for `diffoscope`.

## `passthru.tests`: tests that travel with the package

`passthru` attributes are available on the package but don't change its derivation, so adding
tests causes no rebuilds. `pkgs/README.md` ("Package tests") describes three kinds of test:
upstream's suite in `checkPhase`, **package tests** in `passthru.tests`, and **NixOS VM tests**
for services. GNU hello has two package tests:

```bash
nix-build nixpkgs.nix -A hello.tests --no-out-link
```

```text expect
hello-2.12.3-test-version
hello-test-run
```

Building an attribute set builds every derivation in it — that's how ofborg (and you) run all
of a package's tests with one command.

### Write your own

A package with two tests, written the way `pkgs/README.md` ("Writing larger package tests")
recommends: the tests live in `tests.nix` next to `package.nix` and receive the package as an
argument, set to `finalAttrs.finalPackage`.

```bash file=pkgs/by-name/ro/rot13/rot13.sh
#!/usr/bin/env bash
# rot13: rotate letters by 13 places
if [[ ${1-} == --version ]]; then
  echo "rot13 @version@"
  exit 0
fi
exec @tr@ 'A-Za-z' 'N-ZA-Mn-za-m'
```

```nix file=pkgs/by-name/ro/rot13/package.nix
{
  lib,
  stdenvNoCC,
  bash,
  coreutils,
  callPackage,
  testers,
}:

stdenvNoCC.mkDerivation (finalAttrs: {
  pname = "rot13";
  version = "1.0.0";

  __structuredAttrs = true;
  strictDeps = true;

  dontUnpack = true;

  # bash runs on the *target* machine (the script's interpreter), so it is a buildInput;
  # patchShebangs rewrites `#!/usr/bin/env bash` to it.
  buildInputs = [ bash ];

  installPhase = ''
    runHook preInstall
    install -Dm755 ${./rot13.sh} $out/bin/rot13
    substituteInPlace $out/bin/rot13 \
      --replace-fail @version@ ${finalAttrs.version} \
      --replace-fail @tr@ ${lib.getExe' coreutils "tr"}
    runHook postInstall
  '';

  passthru.tests = {
    version = testers.testVersion { package = finalAttrs.finalPackage; };
    roundtrip = callPackage ./tests.nix { rot13 = finalAttrs.finalPackage; };
  };

  meta = {
    description = "Rotate letters of standard input by 13 places";
    license = lib.licenses.mit;
    maintainers = [ ];
    mainProgram = "rot13";
    platforms = lib.platforms.all;
  };
})
```

```nix file=pkgs/by-name/ro/rot13/tests.nix
{ runCommand, rot13 }:

runCommand "rot13-test-roundtrip"
  {
    nativeBuildInputs = [ rot13 ];
  }
  ''
    [[ "$(echo 'Hello, Nix!' | rot13)" == 'Uryyb, Avk!' ]]
    [[ "$(echo 'Hello, Nix!' | rot13 | rot13)" == 'Hello, Nix!' ]]
    touch $out
  ''
```

The test runs `rot13`, so inside the test it is a `nativeBuildInputs` entry (lesson 2's rule).
Wire the directory up with nixpkgs' by-name overlay, exactly as a checkout does:

```nix file=default.nix
# A function, like nixpkgs' own default.nix: `import ./. { }` and `nix-build -A` both work
{ overlays ? [ ] }:
let
  nixpkgs = import ./nixpkgs.nix;
  byName = import ((nixpkgs { }).path + "/pkgs/top-level/by-name-overlay.nix") ./pkgs/by-name;
in
nixpkgs { overlays = [ byName ] ++ overlays; }
```

```bash
nix-build -A rot13
echo 'Hello, Nix!' | ./result/bin/rot13
head -n 1 result/bin/rot13
nix-build -A rot13.tests --no-out-link
```

```text expect
Uryyb, Avk!
#!/nix/store/
rot13-1.0.0-test-version
rot13-test-roundtrip
```

Now introduce a regression the way a careless update would, and watch the test catch it.
Because the test is bound to `finalAttrs.finalPackage`, it tests the *modified* package:

```nix file=broken.nix
with import ./. { };
(rot13.overrideAttrs {
  # a "regression": rotate by 1 instead of 13
  postInstall = ''
    substituteInPlace $out/bin/rot13 --replace-fail N-ZA-Mn-za-m B-ZAb-za
  '';
}).tests.roundtrip
```

```bash fails
nix-build --no-out-link broken.nix
```

```text expect
rot13-test-roundtrip
```

### `versionCheckHook` or `testers.testVersion`?

Both run the main program with `--version` (or `--help`) and look for `version`.
`versionCheckHook` (`doc/hooks/versionCheckHook.section.md`) runs during the package's own
install-check phase in an empty environment, so a failure fails the package build;
`testers.testVersion` (`doc/build-helpers/testers.chapter.md`) is a separate derivation in
`passthru.tests` — "a softer option" that also works for programs needing `HOME` or `PATH`.
Many packages use the hook; GNU hello has both.

### NixOS tests for services

A package that's mostly used through a NixOS module links that module's VM test, so changing
the package re-runs it:

```nix
{ nixosTests, ... }:
{
  passthru.tests = {
    inherit (nixosTests) nginx;
  };
}
```

In a checkout you run one with `nix-build -A nixosTests.nginx` (tests are listed in
`nixos/tests/all-tests.nix`). Course 06 and the capstone write one.

## Evaluate for other platforms

CI evaluates your package for x86_64-linux, aarch64-linux, x86_64-darwin and aarch64-darwin,
even if nobody builds it on all four. An evaluation error on any of them blocks the PR. You can
evaluate for another platform without building anything:

```bash
nix-instantiate nixpkgs.nix -A pkgsCross.aarch64-multiplatform.hello
nix-instantiate -A pkgsCross.aarch64-multiplatform.rot13
```

```text expect
hello-aarch64-unknown-linux-gnu-2.12.3.drv
rot13
```

(Your by-name overlay applies to the cross package set too — overlays are part of the package
set's definition, not of `x86_64-linux`.) If a dependency doesn't exist on a platform,
restrict `meta.platforms` instead of letting evaluation fail.

## `nixpkgs-review`: build everything you affect

Changing a library can break its dependents. `nixpkgs-review` (by Mic92; in nixpkgs as
`nixpkgs-review`) does locally what CI's eval and ofborg do together:

1. evaluates nixpkgs before and after your change (with `nix-eval-jobs`) and diffs the output
   paths, giving the list of rebuilt attributes;
2. builds all of them, plus their `passthru.tests`;
3. drops you into a `nix-shell` with every successful result on `PATH` and a report of what
   failed, so you can try the binaries.

The three ways you'll use it, from a nixpkgs checkout:

```console
$ nixpkgs-review wip            # uncommitted changes in the working tree
$ nixpkgs-review wip --staged   # only what's in the index
$ nixpkgs-review rev HEAD       # the last commit
$ nixpkgs-review pr 123456      # someone's open PR: fetches its head and the base, merges, builds
```

`pr` needs no GitHub token to fetch and build a public PR (it uses `git fetch` of
`refs/pull/<n>/head`); a token (`GITHUB_TOKEN`, or the `gh` CLI's login) is only needed for
`--post-result`, which posts the report as a PR comment, and it helps with API rate limits.
`--print-result` prints the report instead. Reviewing other people's PRs this way is one of the
most useful things a new contributor can do — and the report is what the template's
"Ran `nixpkgs-review` on this PR" checkbox refers to.

It's a big job for a change with many dependents (it really builds them), so it isn't run here.
Its CLI is:

```bash
REVIEW=$(nix-build nixpkgs.nix -A nixpkgs-review --no-out-link)
"$REVIEW/bin/nixpkgs-review" --help
```

```text expect
wip
pr
rev
```

## Your turn

Add a third test, `emptyInput`, inline in `package.nix` (no extra file): `rot13` with no input
must print nothing. Rebuild `rot13.tests` and see three results.

<details><summary>Solution</summary>

`runCommand` is enough for a one-liner; it needs the package on `PATH`, so `nativeBuildInputs`
again. Here is the whole `package.nix` with the new test:

```nix file=pkgs/by-name/ro/rot13/package.nix
{
  lib,
  stdenvNoCC,
  bash,
  coreutils,
  callPackage,
  runCommand,
  testers,
}:

stdenvNoCC.mkDerivation (finalAttrs: {
  pname = "rot13";
  version = "1.0.0";

  __structuredAttrs = true;
  strictDeps = true;

  dontUnpack = true;

  buildInputs = [ bash ];

  installPhase = ''
    runHook preInstall
    install -Dm755 ${./rot13.sh} $out/bin/rot13
    substituteInPlace $out/bin/rot13 \
      --replace-fail @version@ ${finalAttrs.version} \
      --replace-fail @tr@ ${lib.getExe' coreutils "tr"}
    runHook postInstall
  '';

  passthru.tests = {
    version = testers.testVersion { package = finalAttrs.finalPackage; };
    roundtrip = callPackage ./tests.nix { rot13 = finalAttrs.finalPackage; };
    emptyInput = runCommand "rot13-test-empty-input" {
      nativeBuildInputs = [ finalAttrs.finalPackage ];
    } ''[[ -z "$(rot13 < /dev/null)" ]] && touch $out'';
  };

  meta = {
    description = "Rotate letters of standard input by 13 places";
    license = lib.licenses.mit;
    maintainers = [ ];
    mainProgram = "rot13";
    platforms = lib.platforms.all;
  };
})
```

```bash
nix-build -A rot13.tests --no-out-link
```

```text expect
rot13-test-empty-input
rot13-test-roundtrip
rot13-1.0.0-test-version
```

</details>

## Check yourself

<details><summary>You added <code>passthru.tests</code> to a library with 3 000 dependents. Does your PR need to go to <code>staging</code>?</summary>

No. `passthru` isn't part of the derivation, so no output path changes and nothing rebuilds.
(Changing `doCheck` or the build itself would.)
</details>

<details><summary>Why bind tests to <code>finalAttrs.finalPackage</code> rather than taking the package from <code>pkgs</code>?</summary>

So that the tests of an overridden package test the override. With the `pkgs` version,
`(rot13.overrideAttrs …).tests` would still test the original and miss the regression you saw.
</details>

<details><summary><code>nix-build -A foo --check</code> fails with "may not be deterministic". What now?</summary>

Rebuild with `--keep-failed` to keep both outputs, compare them with `diffoscope`, and remove the
source of variation (embedded timestamps, build paths, unsorted file lists). `SOURCE_DATE_EPOCH`
is already set by stdenv; many tools have a flag to honour it.
</details>

## Stretch goals

- In a nixpkgs checkout (the project gives you one), change `pkgs/by-name/he/hello/package.nix`
  trivially and run `nixpkgs-review wip --print-result`. Look at how many attributes it builds.
- Run `nix-build ci -A lib-tests` in a checkout and read `lib/tests/release.nix` to see what it runs.
- Find a package whose `passthru.tests` includes a NixOS test (`grep -rl 'nixosTests\.' pkgs/by-name | head`).
