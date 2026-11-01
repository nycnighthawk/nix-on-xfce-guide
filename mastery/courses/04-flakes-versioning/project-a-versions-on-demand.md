# Project 04a — Versions on demand

**Goal:** one flake that offers GNU hello in three versions — from nixpkgs 26.05, from
nixpkgs 25.11, and a release that neither ships (2.12.1), added through an overlay — all
buildable on their own and installable together, side by side, under distinct names.

**You will practise:**

- **Two nixpkgs inputs side by side** — one set for most things, a second one for one
  older package.
- **Overlays for policy, `overrideAttrs` for one package** — here an overlay that *adds* a
  versioned attribute rather than replacing `hello`, so nothing else changes.
- **`finalAttrs.version` + a new `src`** — the version override from lesson 3.
- **The lock file is the version** — which hello you get is decided by `flake.lock` and two
  lines of Nix, nothing else.
- **`checks`** — a version test per variant, run by `nix flake check`.

## The override

The same override function as in lesson 3: it takes its dependency (`fetchurl`) as an
argument and returns an `overrideAttrs` function.

```nix file=hello-2.12.1.nix
# overrideAttrs function: GNU hello 2.12.1 from its release tarball.
{ fetchurl }:
finalAttrs: prevAttrs: {
  version = "2.12.1";
  src = fetchurl {
    url = "mirror://gnu/hello/hello-${finalAttrs.version}.tar.gz";
    hash = "sha256-jZkUKv2SV28wsM18tCqNxoCZmLxdYH2Idh9RLibH2yA=";
  };
  # Older releases may not compile as C23, GCC 15's default; pin the C standard.
  env = (prevAttrs.env or { }) // {
    NIX_CFLAGS_COMPILE = "-std=gnu17";
  };
}
```

## The flake

```nix file=flake.nix
{
  description = "Versions on demand: GNU hello from 26.05, from 25.11, and 2.12.1";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";
    nixpkgs-2511.url = "github:NixOS/nixpkgs/b6018f87da91d19d0ab4cf979885689b469cdd41";
  };

  outputs =
    {
      self,
      nixpkgs,
      nixpkgs-2511,
    }:
    let
      system = "x86_64-linux";
      # Main package set: 26.05 plus our overlay.
      pkgs = import nixpkgs {
        inherit system;
        overlays = [ self.overlays.default ];
      };
      inherit (pkgs) lib;
      # Second package set, used for one package only.
      pkgs-2511 = nixpkgs-2511.legacyPackages.${system};

      versions = {
        "26.05" = pkgs.hello;
        "25.11" = pkgs-2511.hello;
        "2.12.1" = pkgs.hello_2_12_1;
      };
    in
    {
      # Adds a versioned attribute; `hello` itself is untouched, so no dependent rebuilds.
      overlays.default = final: prev: {
        hello_2_12_1 = prev.hello.overrideAttrs (import ./hello-2.12.1.nix { inherit (final) fetchurl; });
      };

      packages.${system} = {
        hello-26_05 = versions."26.05";
        hello-25_11 = versions."25.11";
        hello-2_12_1 = versions."2.12.1";

        # All three in one bin/, as hello-<label>.
        default = pkgs.runCommand "hello-versions" { } ''
          mkdir -p $out/bin
          ${lib.concatStrings (
            lib.mapAttrsToList (label: hello: ''
              ln -s ${lib.getExe hello} $out/bin/hello-${label}
            '') versions
          )}
        '';
      };

      checks.${system} = lib.mapAttrs' (
        label: hello:
        lib.nameValuePair "version-${lib.replaceStrings [ "." ] [ "_" ] label}" (
          pkgs.testers.testVersion { package = hello; }
        )
      ) versions;
    };
}
```

```text file=.gitignore
result
result-*
```

Read the design:

- `versions` is the single list of what the flake offers. The packages, the combined
  `default` and the checks are all derived from it, so adding a version is one line.
- The 25.11 hello comes from 25.11's package set *with its own glibc*. It is a separate
  program, so that is harmless. (It would not be harmless for a library you link into a
  26.05 program.)
- `hello_2_12_1` is built with 26.05's compiler and libraries. Its version is ours; its
  toolchain is the pinned one.

```bash timeout=1800
git init -q
git add -A
nix flake lock
git add flake.lock
nix flake show
```

```text expect
hello-26_05
hello-25_11
hello-2_12_1
version-2_12_1
```

## Build each version on demand

Each package builds on its own. The first two come from the binary cache; 2.12.1 compiles
(about a minute).

```bash timeout=3600
for p in hello-26_05 hello-25_11 hello-2_12_1; do
  out=$(nix build --no-link --print-out-paths .#$p)
  echo "$p -> $(basename "$out"): $("$out/bin/hello" --version | head -n 1)"
done
```

```text expect
hello-26_05 -> 
(GNU Hello) 2.12.3
(GNU Hello) 2.12.1
```

## All three, side by side

```bash timeout=1800
nix build .#default
ls result/bin
for v in 26.05 25.11 2.12.1; do
  printf '%-7s ' "$v"
  ./result/bin/hello-$v --version | head -n 1
done
```

```text expect
hello-2.12.1
hello-25.11
hello-26.05
(GNU Hello) 2.12.3
(GNU Hello) 2.12.1
```

## Verification

**Each binary is the version its package says it is.** For 25.11 we do not hard-code the
number — we ask that nixpkgs:

```bash
want=$(nix eval --raw .#hello-25_11.version)
got=$(./result/bin/hello-25.11 --version | head -n 1 | awk '{print $NF}')
echo "25.11 ships hello $want; the binary says $got"
[ "$want" = "$got" ]
```

```text expect
25.11 ships hello
```

**The checks pass**, one `testVersion` per variant:

```bash timeout=1800
nix flake check
echo "checks passed"
```

```text expect
checks passed
```

**The two package sets really are separate.** The combined package's closure contains two
different glibcs — one from each nixpkgs:

```bash
nix path-info --recursive .#default | grep -- '-glibc-' | sed 's|^/nix/store/[a-z0-9]*-||' | sort -u
[ "$(nix path-info --recursive .#default | grep -c -- '-glibc-')" -ge 2 ]
```

```text expect
glibc-
```

**Run a version without installing anything**, straight from the flake:

```bash
nix shell .#default -c hello-2.12.1 --greeting="on demand"
nix run .#hello-25_11 -- --greeting="from 25.11"
```

```text expect
on demand
from 25.11
```

## Stretch goals

1. **A fourth version.** Add hello 2.10 the same way (a `hello-2.10.nix` with
   `hash = lib.fakeHash;` first). Expect trouble: 2.10 is from 2014. Read the build log, decide
   whether a flag (`-std=gnu89`? `-Wno-error=…`?) or a patch fixes it, and add a comment saying
   why. Is it worth it? (In nixpkgs the answer for very old versions is usually "no — pin an
   old nixpkgs instead".)
2. **Consume the overlay from another flake.** In a second directory, write a flake with
   `inputs.versions.url = "path:../<this project>";` that applies `versions.overlays.default`
   to its own nixpkgs and builds `hello_2_12_1`. Make its `versions` input `follow` its
   `nixpkgs`. Does the 2.12.1 build get reused?
3. **Apps.** Add `apps.x86_64-linux.hello-25_11 = { type = "app"; program = …; }` entries,
   generated from `versions`, so `nix run .#hello-25_11` works even if the package had no
   `meta.mainProgram`.
4. **A policy overlay.** Write a second overlay that *replaces* `hello` with 2.12.1 for the
   whole set, apply it in a third package set, and show that a package depending on `hello`
   (lesson 3's `greeter`) changes while the `versions` packages do not.

## Check yourself

<details><summary>Why does the overlay add <code>hello_2_12_1</code> instead of replacing <code>hello</code>?</summary>

The goal is *on demand*: offer 2.12.1 next to the default without changing anything else. A
replacing overlay would make every package in the set that uses `hello` switch (and
rebuild), and `versions."26.05"` would no longer be 2.12.3.

</details>

<details><summary>Where exactly is it decided that "25.11's hello" is the version it is?</summary>

In `flake.lock`: the `nixpkgs-2511` node's `rev` and `narHash`. The URL in `flake.nix`
names the commit; the lock pins it with a content hash. Change either deliberately and the
version may change; leave them alone and it never does.

</details>

<details><summary>The 2.12.1 build compiled locally. When would it come from a cache instead?</summary>

When someone has already built the exact same derivation and pushed it to a cache you
trust — your own cache (course 05), or a colleague's. cache.nixos.org only has what Hydra
builds from nixpkgs itself, and nixpkgs has no hello 2.12.1.

</details>
