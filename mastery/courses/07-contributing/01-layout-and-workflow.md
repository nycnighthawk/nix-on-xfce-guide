# Lesson 07.1 — nixpkgs layout and workflow

**You will:** find any package's source file, reproduce `pkgs/by-name` auto-wiring with the
exact overlay nixpkgs uses, and learn which branch a change belongs on and how it reaches
users.

nixpkgs is one Git repository with ~120 000 packages, NixOS, the library and two manuals, and
a few thousand people committing to it. It stays workable because of a handful of
conventions. This lesson is the map; the rest of the course is the rules.

## A pinned copy to explore

You'll read the same nixpkgs every other lesson uses — 26.05 at a fixed commit:

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

`pkgs.path` is the source tree itself (a store path). Keep it in a variable:

```bash
NIXPKGS=$(nix-instantiate --eval --expr 'toString (import ./nixpkgs.nix { }).path' | tr -d '"')
echo "$NIXPKGS"
ls "$NIXPKGS"
```

```text expect
/nix/store/
CONTRIBUTING.md
pkgs
nixos
lib
maintainers
```

| Directory | What lives there | Its README |
|---|---|---|
| `pkgs/by-name/` | almost every top-level package, one directory each | `pkgs/by-name/README.md` |
| `pkgs/top-level/` | entry points: `default.nix`, `stage.nix`, `all-packages.nix`, `*-packages.nix` sets | `pkgs/README.md` |
| `pkgs/development/` | language package sets (`python-modules`, `haskell-modules`, …), older categorised packages | |
| `pkgs/build-support/` | builders and fetchers (`fetchFromGitHub`, `dockerTools`, `testers`, …) | |
| `pkgs/stdenv/` | the standard environment (`setup.sh`, `make-derivation.nix`, `check-meta.nix`) | |
| `nixos/` | NixOS: `modules/`, `tests/`, `lib/`, the NixOS manual | `nixos/README.md` |
| `lib/` | the Nix library (`lib.*`) and its tests | `lib/README.md` |
| `doc/` | the nixpkgs manual sources | `doc/README.md` |
| `maintainers/` | `maintainer-list.nix`, `team-list.nix`, maintainer scripts | `maintainers/README.md` |
| `ci/` | everything GitHub Actions runs (`nix-build ci -A …`) | `ci/README.md` |

## Find any package's file

Every derivation records where it was defined in `meta.position`. That's the fastest way from
an attribute name to the file you would edit:

```bash
nix-instantiate --eval --expr '(import ./nixpkgs.nix { }).hello.meta.position'
ls "$NIXPKGS/pkgs/by-name/he/hello"
```

```text expect
pkgs/by-name/he/hello/package.nix
package.nix
test.nix
```

(Interactive equivalent: `nix edit -f ./nixpkgs.nix hello` opens it in `$EDITOR`.)

## How a directory becomes an attribute

There is no list of by-name packages anywhere. `pkgs/top-level/stage.nix` builds the package
set as a chain of overlays, and one of them is generated from the directory tree:

```bash
grep -n 'autoCalledPackages' "$NIXPKGS/pkgs/top-level/stage.nix"
sed -n '/^self: super:/,$p' "$NIXPKGS/pkgs/top-level/by-name-overlay.nix"
```

```text expect
autoCalledPackages = import ./by-name-overlay.nix ../by-name;
_internalCallByNamePackageFile = file: self.callPackage file { };
mapAttrs (name: self._internalCallByNamePackageFile) packageFiles
```

Read it as: for every `pkgs/by-name/<shard>/<name>/package.nix`, define
`pkgs.<name> = callPackage <that file> { }`. Two consequences:

1. **The directory name is the attribute name.** The shard (`he`) is just the lowercased first
   two letters, so no directory has 100 000 entries.
2. **`callPackage` with `{ }` means the file's arguments are its whole interface.** Each argument
   name is looked up in `pkgs` — `fetchurl` gets `pkgs.fetchurl`, `gettext` gets
   `pkgs.gettext`. That's *auto-wiring by name*. It's also why `.override { gettext = …; }`
   works on every package for free.

The overlay is an ordinary function `baseDirectory -> overlay`, so you can point it at your own
directory and get exactly nixpkgs' behaviour. Make two packages, one depending on the other
**by name only**:

```nix file=pkgs/by-name/gr/greeting-text/package.nix
{ writeText }:

writeText "greeting.txt" ''
  Hello from a by-name package
''
```

```nix file=pkgs/by-name/sa/say-greeting/package.nix
{
  writeShellApplication,
  greeting-text,
}:

writeShellApplication {
  name = "say-greeting";
  text = ''
    cat ${greeting-text}
  '';
  meta.description = "Print the text of the greeting-text package";
}
```

`say-greeting` asks for an argument called `greeting-text`; nothing else connects them. Now a
`default.nix` that applies nixpkgs' own `by-name-overlay.nix` to `./pkgs/by-name`:

```nix file=default.nix
# A function, like nixpkgs' own default.nix: `import ./. { }` and `nix-build -A` both work
{ overlays ? [ ] }:
let
  nixpkgs = import ./nixpkgs.nix;
  # nixpkgs' own by-name overlay, pointed at our directory instead of theirs
  byName = import ((nixpkgs { }).path + "/pkgs/top-level/by-name-overlay.nix") ./pkgs/by-name;
in
nixpkgs { overlays = [ byName ] ++ overlays; }
```

```bash
nix-build -A say-greeting
./result/bin/say-greeting
```

```text expect
Hello from a by-name package
```

This is the same command shape you use in a nixpkgs checkout (`nix-build -A some-package`
from the root, because the root `default.nix` is the package set). And `.override` already
works, because `callPackage` added it:

```bash
nix-build --no-out-link -E 'with import ./. { };
  say-greeting.override { greeting-text = writeText "x" "Overridden by name\n"; }' > out-path
"$(cat out-path)/bin/say-greeting"
```

```text expect
Overridden by name
```

### What the overlay does *not* check

The overlay's own comment says "No validity checks are done here … validity checks are done by
CI". Put a package in the wrong shard and it still evaluates locally:

```nix file=pkgs/by-name/zz/misplaced/package.nix
{ writeText }:

writeText "misplaced" "I am in the wrong shard\n"
```

```bash
nix-build --no-out-link -A misplaced
```

In nixpkgs this would fail the `nixpkgs-vet` CI job (lesson 2 lists its rules), which is why
you run it before pushing. Remove it:

```bash
rm -r pkgs/by-name/zz
```

### When `all-packages.nix` still matters

Only to change an argument's default. If a package needs `libbar_2` instead of `libbar`,
`pkgs/by-name/README.md` ("Changing implicit attribute defaults") says: prefer renaming the
*argument* to `libbar_2` so the requirement is visible in `package.nix` itself. If you really
must pass something else, the definition goes in `all-packages.nix`
(`foo = callPackage ../by-name/fo/foo/package.nix { libbar = libbar_2; };`) and the file
stays in `pkgs/by-name`. Packages for nested sets (`python3Packages.*`) can't be by-name at all;
they live in `pkgs/development/python-modules/` and are listed in
`pkgs/top-level/python-packages.nix`.

## Branches, channels, and where your change goes

From `CONTRIBUTING.md` ("Flow of merged pull requests", "Branch conventions"):

| Branch | Used for | Built by Hydra? |
|---|---|---|
| `master` | almost all changes; feeds `nixos-unstable`, `nixpkgs-unstable` | yes |
| `staging` | **mass rebuilds** (≥ 500 rebuilds: consider; ≥ 1000: required) | no |
| `staging-next` | `staging` being stabilised before it merges into `master`; only fixes | yes |
| `staging-nixos` | changes that rebuild all NixOS tests, Linux kernel updates | no |
| `release-26.05` | the stable release; feeds `nixos-26.05`, `nixos-26.05-small` | yes |
| `staging-26.05` … | the same staging pattern for the release | |

The **channel branches** (`nixos-unstable`, `nixos-26.05`, `nixpkgs-unstable`) are not for
development. Hydra moves them forward to a commit once its tests pass — that's why your flake
inputs point at them (or at a commit on them, like this path's pin), and why
`CONTRIBUTING.md` warns: never use `nixos-YY.MM` as the base of a backport.

The decision procedure:

1. Base on `master` (or `staging` if it's a mass rebuild). CI labels each PR with its rebuild
   count (the `10.rebuild-*` labels), so you'll be told if you guessed wrong.
2. Is the change *acceptable for a release* — a new package, a security fix, a patch or minor
   version bump without breakage? Then, after it is merged, **backport** it:
   - maintainers add the label `backport release-26.05` and a bot opens the PR;
   - anyone can do it by hand: branch from `release-26.05`, `git cherry-pick -x <commit>`
     (the `-x` records the original commit; lesson 4 shows it), title the PR
     `[26.05] greet: init at 1.0.0`, and link the original PR.
3. Breaking changes and major versions stay on `master` (with a release-note entry).

Which release are you looking at, and which is the oldest still supported?

```bash
nix-instantiate --eval --strict --expr 'let lib = (import ./nixpkgs.nix { }).lib; in
  { inherit (lib.trivial) release codeName oldestSupportedRelease; }'
```

```text expect
release = "26.05"
codeName = "Yarara"
```

`oldestSupportedRelease` is what lets `lib` emit deprecation warnings only once every
supported release has the replacement (see `lib/trivial.nix`).

## From merge to your machine

```text
your PR ──merge──► master ──Hydra evaluates and builds──► tests pass ──► nixos-unstable moves
                                                                          (status.nixos.org)
```

A merged change is in `nixpkgs-unstable` / `nixos-unstable` after the next successful Hydra
evaluation (hours to days), and binary-cached at the same time. A backport follows the same
path through `release-26.05` to `nixos-26.05`.

## Your turn

Add a third by-name package, `shout`, that runs `say-greeting` and upper-cases its output with
`tr`. Depend on `say-greeting` only through `package.nix`'s arguments. Build it and run it.

<details><summary>Solution</summary>

`writeShellApplication`'s `runtimeInputs` puts packages on `PATH`, and `coreutils` provides `tr`:

```nix file=pkgs/by-name/sh/shout/package.nix
{
  writeShellApplication,
  coreutils,
  say-greeting,
}:

writeShellApplication {
  name = "shout";
  runtimeInputs = [
    coreutils
    say-greeting
  ];
  text = ''
    say-greeting | tr '[:lower:]' '[:upper:]'
  '';
  meta.description = "Print the greeting in upper case";
}
```

```bash
nix-build -A shout
./result/bin/shout
```

```text expect
HELLO FROM A BY-NAME PACKAGE
```

</details>

## Check yourself

<details><summary>You see <code>pkgs.foo</code> but <code>pkgs/by-name/fo/foo</code> doesn't exist. Where else can it be?</summary>

In `all-packages.nix` (often pointing into the old category tree, `pkgs/tools/…`), in
`aliases.nix` (a rename or a removed package that throws), or produced by another overlay in
`stage.nix`. `meta.position` tells you the file in one command.
</details>

<details><summary>Why does nixpkgs prefer renaming an argument to <code>libbar_2</code> over overriding it in <code>all-packages.nix</code>?</summary>

The argument list is the package's interface. With `libbar_2` in `package.nix`, readers see the
requirement where the package is defined, and a user's `.override { libbar = …; }` fails loudly
instead of being silently ignored (`pkgs/by-name/README.md`).
</details>

<details><summary>A security fix for a package that's the same on master and 26.05. How many PRs, against what?</summary>

One PR against `master`; once merged, a backport to `release-26.05` (label or
`git cherry-pick -x`). Two separate PRs only if the fix differs between the branches.
</details>

<details><summary>Why isn't <code>nixos-26.05</code> a valid base for a backport?</summary>

It's a channel branch: Hydra moves it to tested commits of `release-26.05`. It lags behind the
development branch, and nobody merges into it.
</details>
