# Lesson 02.5 — Fixed points and overlays

**You will:** define an attribute set as a function of its own final value, take its fixed
point with `lib.fix`, layer changes over it with `lib.extends`, and see that nixpkgs
overlays are exactly that.

## The problem `rec` can't solve

Lesson 02.3 ended with a limit of `rec`: once the set is built, its internal references
are frozen. Override `version` from outside, and `name`, which was computed from it,
doesn't follow:

```bash
nix eval --json --expr '(rec { version = "1.0"; name = "demo-${version}"; }) // { version = "2.0"; }'
```

```text expect
{"name":"demo-1.0","version":"2.0"}
```

That's a stale `name`. To fix it, the references inside the set must point at the
**final** set, after all changes, not at the original.

## Sets as functions of themselves

Instead of `rec`, write a function that receives the final set and returns the set:

```nix
final: { version = "1.0"; name = "demo-${final.version}"; }
```

To get the set you need `x` such that `x = f x`, a **fixed point** of `f`. Laziness makes
that a single line. Bind `x` to `f x` and let `f` look into `x` only when an attribute is
needed. This is nixpkgs' `lib.fix`, verbatim from `lib/fixed-points.nix`:

```nix
fix = f: let x = f x; in x;
```

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

```nix file=fixed.nix
let
  lib = (import ./nixpkgs.nix { }).lib;

  base = final: {
    version = "1.0";
    name = "demo-${final.version}";
  };

  # An overlay: a function of the final set and the previous layer.
  bump = final: prev: { version = "2.0"; };
  suffix = final: prev: { name = prev.name + "-patched"; };
in
{
  plain = lib.fix base;
  bumped = lib.fix (lib.extends bump base);
  both = lib.fix (lib.extends suffix (lib.extends bump base));
  composed = lib.fix (lib.extends (lib.composeManyExtensions [ bump suffix ]) base);
}
```

```bash
nix eval --json -f fixed.nix
```

```text expect
"plain":{"name":"demo-1.0","version":"1.0"}
"bumped":{"name":"demo-2.0","version":"2.0"}
"both":{"name":"demo-2.0-patched","version":"2.0"}
"composed":{"name":"demo-2.0-patched","version":"2.0"}
```

`bumped` is what `//` couldn't do: changing `version` changed `name`, because `name` reads
`final.version`.

## `extends`: one layer on top

An **overlay** (nixpkgs' name; `lib` calls it an *extension*) is `final: prev: { … }`:

- `prev` is the set **before** this layer: what you're changing.
- `final` is the set **after all layers**: what you depend on.

`lib.extends overlay f` makes a new "function of final" by applying `f`, then merging the
overlay's result over it:

```nix
extends = overlay: f: final: let prev = f final; in prev // overlay final prev;
```

Every layer gets the *same* `final`, the one fixed point at the very end. That's why
`suffix` above sees `version = "2.0"` even though it doesn't know `bump` exists.

### Rules that follow

- **Change `x` → read `prev.x`.** Writing `version = final.version + "-rc";` defines
  `version` in terms of itself, a real cycle:

```bash fails
nix eval --expr '
  let lib = (import ./nixpkgs.nix { }).lib; in
  (lib.fix (lib.extends (final: prev: { version = final.version + "-rc"; }) (final: { version = "1.0"; }))).version' --impure
```

```text expect
infinite recursion encountered
```

- **Depend on `y` → read `final.y`**, so later layers can still change it.
- **Order matters** when two layers change the same attribute. Here `suffix` runs after
  `bump` (`composeManyExtensions [ bump suffix ]`): the later layer sees the earlier one
  as `prev`.
- `//` is shallow, so an overlay that changes one attribute inside a nested set
  must rebuild that set: `python3Packages = prev.python3Packages // { … }` loses
  nothing only if you start from `prev`. (nixpkgs has `overrideScope` / `pythonPackagesExtensions`
  for nested package sets.)

## nixpkgs is a fixed point

`pkgs/top-level/stage.nix` builds the package set the same way. At the end of the file,
`toFix = lib.foldl' (lib.flip lib.extends) (self: { }) [ … ]` folds a list of layers
(trivial builders, the `pkgs/by-name` packages, `all-packages.nix`, aliases, config
overrides, then **your overlays**, then the stdenv overrides) and the result is
`lib.fix toFix`. That's why an overlay that changes `openssl`
changes every package that takes `openssl` as an argument: they all get it from `final`.

`makeExtensible` packages the pattern as a value. The set carries an `extend` function that
returns a new fixed point with one more layer. nixpkgs' `pkgs.extend` (stage.nix) and `lib`
itself (`lib.extend`) are built this way:

```bash
nix eval --json --impure --expr '
  let
    lib = (import ./nixpkgs.nix { }).lib;
    obj = lib.makeExtensible (final: { version = "1.0"; name = "demo-${final.version}"; });
    obj2 = obj.extend (final: prev: { version = "2.0"; });
  in { inherit (obj) name; newName = obj2.name; }'
```

```text expect
{"name":"demo-1.0","newName":"demo-2.0"}
```

Applied to real packages, with `prev` used for the package you change:

```bash
nix eval --raw --impure --expr '
  let
    pkgs = import ./nixpkgs.nix { };
    pkgs2 = pkgs.extend (final: prev: {
      hello = prev.hello.overrideAttrs { pname = "hello-renamed"; };
      helloName = final.hello.name; # sees the new hello
    });
  in pkgs2.helloName'
```

```text expect
hello-renamed-2.12.3
```

The same *final/prev* idea, one level down, is behind `stdenv.mkDerivation (finalAttrs:
{ … })`. `overrideAttrs` is `extends` for one package's attributes: in
`pkgs/stdenv/generic/make-derivation.nix` it computes `prev = rattrs final` and merges your
overlay over it. So overriding `version` also updates a `src` that reads
`finalAttrs.version` (course 03). The NixOS module system
(course 06) is a fixed point too: `config` is the final value every module reads.

## Check yourself

<details><summary>Why does <code>let x = f x; in x</code> terminate?</summary>

Because of laziness. `x` is bound to a thunk for `f x`. Calling `f` doesn't force `x`. It
returns a set whose attribute values *refer* to `x` (still thunks). Only when you select an
attribute does `x` get forced, and by then it's the already-built set. It loops only if an
attribute's value really needs itself.
</details>

<details><summary>In an overlay, what goes wrong with <code>hello = final.hello.overrideAttrs …</code>?</summary>

`final.hello` *is* the attribute being defined (after all overlays, including this one),
so `hello` depends on itself: infinite recursion. To modify a package, start from
`prev.hello`.
</details>

<details><summary>Two overlays both set <code>version</code>. Which wins?</summary>

The one applied later (later in the `overlays` list, or the outer `extends`). Its result is
merged over the earlier one with `//`. If it reads `prev.version`, it sees the earlier
overlay's value.
</details>
