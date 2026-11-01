# Lesson 03.2 — Fetchers and hashes

**You will:** fetch a release tarball with `fetchurl`, get its hash by trust-on-first-use,
see the difference between flat and recursive hashes, fall into the stale-hash trap on
purpose, and keep local sources minimal with `lib.fileset`.

## Two kinds of fetchers

| | `builtins.fetchTarball`, `builtins.fetchGit`, … | `pkgs.fetchurl`, `pkgs.fetchFromGitHub`, … |
|---|---|---|
| Runs at | evaluation time | build time (it is a derivation) |
| Uses the binary cache | no | yes |
| Allowed in nixpkgs packages | no | yes |

You already use a built-in fetcher: `nixpkgs.nix` fetches nixpkgs itself while Nix
evaluates. Packages use the nixpkgs fetchers. Each one is a **fixed-output derivation**
(FOD): a derivation that may access the network, but whose output must match a hash you
declare in advance. Because the output is known in advance, its store path depends only on
the hash and the name — not on the URL, not on curl's version. Source: Nixpkgs manual,
*Fetchers* (`doc/build-helpers/fetchers.chapter.md`).

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

## What gets hashed: flat vs recursive

A hash in Nix is written in **SRI** form: `sha256-<base64>`. What it covers depends on the
fetcher:

- **flat** — the bytes of one file. `fetchurl` uses this: the hash of the tarball as
  downloaded.
- **recursive** — the NAR serialisation of a file tree (names, contents, executable bits,
  symlinks). `fetchzip` and `fetchFromGitHub` use this: the hash of the *unpacked* directory.

See both with local files, no network:

```bash
mkdir -p tree
printf 'hello\n' > tree/greeting.txt
nix hash file tree/greeting.txt
nix hash path tree
chmod +x tree/greeting.txt
nix hash file tree/greeting.txt
nix hash path tree
```

The flat hash of the file is the same both times. The recursive hash of the directory
changes when you set the executable bit, because the NAR records it. That is why you must
never copy a `sha256sum` of an upstream `.tar.gz` into `fetchzip`: it hashes something
else.

## Trust on first use

You do not know the hash of a file you have not downloaded. Nixpkgs' answer (manual,
*Updating source hashes*, "the fake hash method"): write a **fake** hash, build, and read
the real one from the error.

```nix file=sources.nix
{ lib, fetchurl }:
{
  hello-src = fetchurl {
    url = "mirror://gnu/hello/hello-2.12.3.tar.gz";
    hash = lib.fakeHash;
  };
}
```

`mirror://gnu/` expands to a list of GNU mirrors (`pkgs/build-support/fetchurl/mirrors.nix`);
the fetcher tries them in order.

```nix file=default.nix
let
  pkgs = import ./nixpkgs.nix {
    config = { };
    overlays = [ ];
  };
in
pkgs.callPackage ./sources.nix { }
```

```bash fails
nix-build -A hello-src
```

```text expect
hash mismatch in fixed-output derivation
sha256-DV9gFUOC/uELEUocNOeF2LH0kgc64tOm97FHaHs2aqA=
```

Nix downloaded the tarball, hashed it, and refused the result: `specified:` is the fake
hash (`sha256-AAAA…`), `got:` is the real one. Before you trust it, compare it with
something upstream signs or publishes over HTTPS — for GNU that is the `.sig` file next to
the tarball. Then paste it in:

```nix file=sources.nix
{ lib, fetchurl }:
{
  hello-src = fetchurl {
    url = "mirror://gnu/hello/hello-2.12.3.tar.gz";
    hash = "sha256-DV9gFUOC/uELEUocNOeF2LH0kgc64tOm97FHaHs2aqA=";
  };
}
```

```bash
nix-build -A hello-src
nix hash file "$(readlink result)"
```

```text expect
sha256-DV9gFUOC/uELEUocNOeF2LH0kgc64tOm97FHaHs2aqA=
```

Two details from the fetcher's source (`pkgs/build-support/fetchurl/default.nix`) worth
knowing:

- Use exactly `lib.fakeHash` (or `""`) as the placeholder. With a fake hash, `fetchurl`
  verifies TLS certificates. With a real hash it does not need to — the hash already
  protects you — so an arbitrary made-up hash would download *unverified* (manual,
  *Obtaining hashes securely*).
- The hash is the identity. Nix computes the output path from hash + name before it
  downloads anything. If that path already exists, nothing is downloaded at all.

## Prefetching instead

If you prefer to get the hash before writing the expression, prefetch the file. This
downloads it into the store and prints its hash:

```bash
nix store prefetch-file https://ftp.gnu.org/gnu/hello/hello-2.12.3.tar.gz
```

```text expect
sha256-DV9gFUOC/uELEUocNOeF2LH0kgc64tOm97FHaHs2aqA=
```

For a whole Git repository at a revision, the `nurl` tool (in nixpkgs) prints a complete
`fetchFromGitHub { … }` call including the hash.

## The stale-hash trap

The flip side of "the hash is the identity": if you change a fetcher's URL but not its
hash, and the old output still exists in your store, **Nix silently reuses the old
output.** It never looks at the new URL. The manual warns about exactly this (*Fetchers*,
*Caveats*).

`fetchurl` names its output after the file, so a new version usually gets a new name and
you get an error instead. Fetchers whose name does not change — `fetchFromGitHub` always
names its output `source` — fall straight into the trap. Recreate that with an explicit
`name`:

```nix file=sources.nix
{ lib, fetchurl }:
{
  # what you had
  current = fetchurl {
    name = "hello-src.tar.gz";
    url = "mirror://gnu/hello/hello-2.12.3.tar.gz";
    hash = "sha256-DV9gFUOC/uELEUocNOeF2LH0kgc64tOm97FHaHs2aqA=";
  };

  # "downgrade to 2.12.1": URL edited, hash forgotten
  stale = fetchurl {
    name = "hello-src.tar.gz";
    url = "mirror://gnu/hello/hello-2.12.1.tar.gz";
    hash = "sha256-DV9gFUOC/uELEUocNOeF2LH0kgc64tOm97FHaHs2aqA=";
  };
}
```

```bash
a=$(nix-build -A current --no-out-link)
b=$(nix-build -A stale --no-out-link)
[ "$a" = "$b" ] && echo "same store path"
tar -tzf "$b" > list.txt
head -n 1 list.txt
```

```text expect
same store path
hello-2.12.3/
```

The "2.12.1" source contains 2.12.3. No error, no download. The rule: **whenever you change
any fetcher argument, reset the hash to `lib.fakeHash` and build again.**

## Fetching from GitHub

The same workflow, for a Git forge. You will see this shape in most nixpkgs packages
(shown, not run — it needs a hash for a real repository):

```nix
{ fetchFromGitHub }:
fetchFromGitHub {
  owner = "BurntSushi";
  repo = "ripgrep";
  tag = "14.1.1"; # prefer `tag` over `rev` for releases
  hash = "sha256-gyWnahj1A+iXUQlQ1O1H1u7K5euYQOld9qWm99Vjaeg=";
}
```

It downloads GitHub's archive for that tag and unpacks it, so `hash` is a **recursive**
hash of the directory. Use `tag` for release tags and `rev` for a commit; with a `rev` set
to a branch name, the hash breaks as soon as the branch moves. Source: *Fetchers*, section
`fetchFromGitHub`.

## Local sources: `lib.fileset`

For your own code the source is a directory next to the expression. `src = ./.` copies
*everything*: build results, editor backups, notes, `.git`. Any change to any of them
changes the source hash and forces a rebuild. `lib.fileset` selects exactly the files a
build needs (Nixpkgs manual, *File sets*, `lib/fileset/default.nix`).

```c file=project/main.c
int main(void) { return 0; }
```

```markdown file=project/NOTES.md
Things to do some day.
```

```nix file=filesets.nix
{ lib, runCommand }:
{
  whole = runCommand "whole-dir" { src = ./project; } ''
    ls $src > $out
  '';

  filtered = runCommand "only-sources" {
    src = lib.fileset.toSource {
      root = ./project;
      fileset = lib.fileset.unions [ ./project/main.c ];
    };
  } ''
    ls $src > $out
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
pkgs.callPackage ./filesets.nix { }
```

Record both derivation paths, edit the notes, and compare:

```bash
whole1=$(nix-instantiate -A whole)
filtered1=$(nix-instantiate -A filtered)
echo "More things to do." >> project/NOTES.md
whole2=$(nix-instantiate -A whole)
filtered2=$(nix-instantiate -A filtered)
[ "$whole1" != "$whole2" ] && echo "whole: changed"
[ "$filtered1" = "$filtered2" ] && echo "filtered: unchanged"
```

```text expect
whole: changed
filtered: unchanged
```

In a Git repository, `lib.fileset.gitTracked ./.` is a convenient starting set; intersect or
subtract from it as needed.

## Exercise: fix the stale source

Make `stale` really fetch hello 2.12.1, using the fake-hash workflow. Prove it by listing the
tarball.

<details><summary>Solution</summary>

Reset the hash to the fake one and build to get the real hash:

```nix file=sources.nix
{ lib, fetchurl }:
{
  stale = fetchurl {
    name = "hello-src.tar.gz";
    url = "mirror://gnu/hello/hello-2.12.1.tar.gz";
    hash = lib.fakeHash;
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
pkgs.callPackage ./sources.nix { }
```

```bash fails
nix-build -A stale
```

```text expect
hash mismatch in fixed-output derivation
sha256-jZkUKv2SV28wsM18tCqNxoCZmLxdYH2Idh9RLibH2yA=
```

Copy the `got:` hash in:

```nix file=sources.nix
{ lib, fetchurl }:
{
  stale = fetchurl {
    name = "hello-src.tar.gz";
    url = "mirror://gnu/hello/hello-2.12.1.tar.gz";
    hash = "sha256-jZkUKv2SV28wsM18tCqNxoCZmLxdYH2Idh9RLibH2yA=";
  };
}
```

```bash
tar -tzf "$(nix-build -A stale --no-out-link)" > list.txt
head -n 1 list.txt
```

```text expect
hello-2.12.1/
```

Better still, drop the explicit `name` so the file name carries the version, and a
forgotten hash becomes an error rather than a silent reuse.

</details>

## Check yourself

<details><summary>Why can a fetcher access the network when normal builds cannot?</summary>

It is a fixed-output derivation: its output hash is declared up front, so whatever happens
during the download, the result is either exactly that content or an error. The network
cannot make the build non-reproducible, so the sandbox allows it.

</details>

<details><summary>You switch a package from <code>fetchurl</code> of a <code>.tar.gz</code> to <code>fetchzip</code> of the same URL. Can you keep the hash?</summary>

No. `fetchurl` hashes the tarball's bytes (flat); `fetchzip` hashes the unpacked tree
(recursive NAR). Reset to `lib.fakeHash` and rebuild.

</details>

<details><summary>What makes the stale-hash trap possible, and what is the habit that avoids it?</summary>

The output path depends only on the hash, the name and the hashing mode. If a path with
that identity exists, Nix uses it without fetching. The habit: whenever a fetcher argument
changes, reset the hash to `lib.fakeHash` and let Nix compute it again.

</details>
