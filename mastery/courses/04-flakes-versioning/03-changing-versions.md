# Lesson 04.3 — Changing versions

**You will:** get a different version of GNU hello in four ways — the pinned nixpkgs, a
second nixpkgs, `overrideAttrs` with `finalAttrs.version`, and an overlay — and learn which
one to reach for.

## Four tools for one job

| Strategy | What changes | Rebuilds | Use when |
|---|---|---|---|
| Move the nixpkgs pin (lesson 2) | everything | nothing (cache) | you want a whole newer/older package set |
| A **second nixpkgs input** | one package comes from another set | nothing (cache) | the version you need exists in another release |
| **`overrideAttrs`** with `finalAttrs.version` + new `src` | one package, under a new name | that package | no nixpkgs has the version, and only *you* need it |
| An **overlay** | one package, for the whole package set | it and everything depending on it | every dependent must use your version (a patched library, a policy) |

Pattern to remember: **overlays for policy, `overrideAttrs` for one package.**

## The flake

The override is a function in its own file, so the flake can use it twice — once alone,
once inside an overlay:

```nix file=hello-2.12.1.nix
# An overrideAttrs function for GNU hello: a different release, from its own tarball.
{ fetchurl }:
finalAttrs: prevAttrs: {
  version = "2.12.1";
  src = fetchurl {
    url = "mirror://gnu/hello/hello-${finalAttrs.version}.tar.gz";
    hash = "sha256-jZkUKv2SV28wsM18tCqNxoCZmLxdYH2Idh9RLibH2yA=";
  };
  # Older releases may not compile as C23, the default standard of GCC 15 in nixpkgs 26.05.
  # Pinning the language standard is the usual remedy for old C code.
  env = (prevAttrs.env or { }) // {
    NIX_CFLAGS_COMPILE = "-std=gnu17";
  };
}
```

A tiny program that depends on hello, to see who gets which hello:

```nix file=greeter.nix
{
  lib,
  writeShellScriptBin,
  gnused,
  hello,
}:

writeShellScriptBin "greeter" ''
  echo "greeter uses: $(${lib.getExe hello} --version | ${lib.getExe gnused} -n 1p)"
''
```

```nix file=flake.nix
{
  description = "Four ways to get a different version of a package";

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
      pkgs = nixpkgs.legacyPackages.${system};
      pkgs-2511 = nixpkgs-2511.legacyPackages.${system};

      # The same nixpkgs, instantiated again with our overlay applied to the whole set.
      pkgsWithOverlay = import nixpkgs {
        inherit system;
        overlays = [ self.overlays.default ];
      };
    in
    {
      # final = the package set after all overlays; prev = the set before this one.
      overlays.default = final: prev: {
        hello = prev.hello.overrideAttrs (import ./hello-2.12.1.nix { inherit (final) fetchurl; });
      };

      packages.${system} = {
        # 1. Whatever the pinned nixpkgs has.
        hello = pkgs.hello;

        # 2. A second nixpkgs, side by side.
        hello-from-2511 = pkgs-2511.hello;

        # 3. overrideAttrs. First the classic mistake: change only the version...
        hello-version-only = pkgs.hello.overrideAttrs { version = "2.12.1"; };
        # ...then properly: new version *and* new source hash.
        hello-2_12_1 = pkgs.hello.overrideAttrs (import ./hello-2.12.1.nix { inherit (pkgs) fetchurl; });

        # 4. An overlay: everything in pkgsWithOverlay sees the new hello.
        greeter = pkgs.callPackage ./greeter.nix { };
        greeter-overlaid = pkgsWithOverlay.callPackage ./greeter.nix { };
      };
    };
}
```

```text file=.gitignore
result
result-*
```

```bash timeout=1800
git init -q
git add -A
nix flake lock
git add flake.lock
nix flake show
```

```text expect
hello-from-2511
hello-2_12_1
greeter-overlaid
```

## 1 and 2: from a package set

Both come from the binary cache; nothing compiles.

```bash timeout=1800
for p in hello hello-from-2511; do
  out=$(nix build --no-link --print-out-paths .#$p)
  echo "$p: $($out/bin/hello --version | head -n 1)"
done
```

```text expect
hello: hello (GNU Hello) 2.12.3
hello-from-2511: hello (GNU Hello)
```

Two nixpkgs means two complete package sets: hello from 25.11 comes with 25.11's glibc.
That is fine for a tool you run; it is a problem when you *link* things from both sets
together. And each extra nixpkgs input costs evaluation time and disk.

## 3: `overrideAttrs` with `finalAttrs.version`

nixpkgs' hello writes its URL as `hello-${finalAttrs.version}.tar.gz`. So overriding the
version moves the URL too — but not the hash:

```bash fails
nix build .#hello-version-only
```

```text expect
hash mismatch in fixed-output derivation
sha256-jZkUKv2SV28wsM18tCqNxoCZmLxdYH2Idh9RLibH2yA=
```

This is the fixed-point argument working as designed (course 03 lesson 3): the URL followed
the version, Nix fetched 2.12.1, and the hash still claimed 2.12.3. A loud failure, which is
what you want. `hello-2.12.1.nix` replaces `src` with the right hash — the `got:` value from
this very error, after you have checked it against upstream:

```bash timeout=1800
nix build .#hello-2_12_1
./result/bin/hello --version | head -n 1
nix eval --raw .#hello-2_12_1.name; echo
```

```text expect
hello (GNU Hello) 2.12.1
hello-2.12.1
```

nixpkgs' `versionCheckHook` in hello's install check verified, during the build, that the
binary reports the version you set.

Three things to note about the override function:

- `finalAttrs.version` in the URL, not a literal: whoever overrides *your* override's
  version gets a consistent URL again.
- `prevAttrs.env or { }`: extend what was there instead of replacing it.
- It takes `fetchurl` as an argument, like a `package.nix` takes its dependencies, so it can
  be applied to any package set.

## 4: an overlay

An overlay is a function `final: prev: { … }` that nixpkgs folds into its package set
(Nixpkgs manual, *Overlays*). Here it replaces `hello`. Every package in that set that takes
`hello` as an argument now gets 2.12.1:

```bash timeout=1800
nix run .#greeter
nix run .#greeter-overlaid
```

```text expect
greeter uses: hello (GNU Hello) 2.12.3
greeter uses: hello (GNU Hello) 2.12.1
```

Same `greeter.nix`, different package set. In a real system, the overlay would rebuild every
dependent of the replaced package — for `openssl` or `glibc`, that is most of nixpkgs.

Why `prev.hello` but `final.fetchurl`?

- `prev.hello` — the hello *before* this overlay. Using `final.hello` here would refer to
  the result of this very definition: infinite recursion.
- `final.fetchurl` — the final version of everything else, so a later overlay that changes
  `fetchurl` is respected. Rule: take the thing you are replacing from `prev`, everything
  else from `final`.

Why `import nixpkgs { overlays = …; }` and not `nixpkgs.legacyPackages`? `legacyPackages` is
already instantiated, with no overlays. Applying an overlay means instantiating nixpkgs again
— which also costs another evaluation of the package set, so do it once and reuse it.

## Exercise: add, don't replace

Change the overlay so that it **adds** `hello_2_12_1` to the package set instead of
replacing `hello`. Expose it as `packages.x86_64-linux.hello-from-overlay`. Which hello does
`greeter-overlaid` use now?

<details><summary>Solution</summary>

A new attribute name affects nothing that already exists; only code that asks for
`hello_2_12_1` sees it. That is how nixpkgs itself ships several versions of one program
(`python312`, `python313`, …).

```nix file=flake.nix
{
  description = "Four ways to get a different version of a package";

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
      pkgs = nixpkgs.legacyPackages.${system};
      pkgsWithOverlay = import nixpkgs {
        inherit system;
        overlays = [ self.overlays.default ];
      };
    in
    {
      overlays.default = final: prev: {
        hello_2_12_1 = prev.hello.overrideAttrs (
          import ./hello-2.12.1.nix { inherit (final) fetchurl; }
        );
      };

      packages.${system} = {
        hello-from-overlay = pkgsWithOverlay.hello_2_12_1;
        greeter-overlaid = pkgsWithOverlay.callPackage ./greeter.nix { };
      };
    };
}
```

```bash timeout=1800
nix build .#hello-from-overlay
./result/bin/hello --version | head -n 1
nix run .#greeter-overlaid
```

```text expect
hello (GNU Hello) 2.12.1
greeter uses: hello (GNU Hello) 2.12.3
```

`greeter-overlaid` is back to 2.12.3: its `hello` argument still means nixpkgs' hello.
(`nixpkgs-2511` is now an unused input. `nix flake check` does not mind, but a reviewer
would ask you to remove it — and its lock entry with it.)

</details>

## Check yourself

<details><summary>You override <code>version</code> with <code>overrideAttrs</code> and the build succeeds, but the binary reports the old version. What happened?</summary>

The package uses `rec` or a literal URL instead of `finalAttrs.version`, so the source did not
change — and if you also kept the old hash, Nix reused the old source silently. Override
`src` explicitly, reset its hash to `lib.fakeHash`, and add a version check
(`versionCheckHook` or `testers.testVersion`) so this cannot pass unnoticed.

</details>

<details><summary>Why is the overlay's override written with <code>final.fetchurl</code> and <code>prev.hello</code>?</summary>

`prev.hello` is the package being replaced; `final.hello` would be the replacement itself
(infinite recursion). `final.fetchurl` picks up any later overlay's changes to `fetchurl`.

</details>

<details><summary>When is a second nixpkgs input the wrong tool?</summary>

When the package must link against or be loaded by things from your main package set —
plugins, libraries, Python modules. Two sets mean two glibcs and two Pythons, which do not
mix. Then you backport the version with `overrideAttrs` (or an overlay) on your main set.

</details>
