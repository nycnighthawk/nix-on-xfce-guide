# Project 02b — Build your own overlay system

**Goal:** implement `fix`, `extends`, `composeExtensions` and `makeExtensible` yourself,
in about ten lines. Use them to layer overlays over a small attribute set, then show that
nixpkgs' `lib` functions, `pkgs.extend`, `pkgs.appendOverlays` and
`import nixpkgs { overlays = …; }` all give the same results.

**You'll practise:** *fixed-point extension* (`final`/`prev`), *late binding* (later
layers change what earlier ones see), *composition order*, and reading nixpkgs'
`lib/fixed-points.nix` and `pkgs/top-level/stage.nix` with confidence.

## 1. Your implementation

Write it without looking at `lib`. You know all of it from lesson 02.5:

```nix file=myfix.nix
rec {
  # The fixed point of f: an x with x == f x. Laziness lets x refer to itself.
  fix =
    f:
    let
      x = f x;
    in
    x;

  # Put one overlay (final: prev: { … }) on top of a function of final.
  extends =
    overlay: f: final:
    let
      prev = f final;
    in
    prev // overlay final prev;

  # One overlay that applies f, then g (g sees f's result as part of prev).
  composeExtensions =
    f: g: final: prev:
    let
      fApplied = f final prev;
    in
    fApplied // g final (prev // fApplied);

  composeManyExtensions = builtins.foldl' composeExtensions (final: prev: { });

  # A fixed point that can be extended later: `.extend overlay` returns a new one.
  makeExtensible =
    rattrs:
    fix (final: rattrs final // { extend = overlay: makeExtensible (extends overlay rattrs); });
}
```

`composeManyExtensions` uses a *left* fold, and nixpkgs uses a right fold
(`lib.foldr`). They give the same result because composing overlays is associative, with
`final: prev: { }` as the identity. Step 4 tests that claim.

## 2. A base set and three overlays

```nix file=overlays.nix
{
  # The base: a function of the final set. Every reference goes through `final`.
  base = final: {
    demoWho = "world";
    demoGreeting = "Hello, ${final.demoWho}!";
    demoSummary = "${final.demoGreeting} (${toString (builtins.stringLength final.demoGreeting)} chars)";
  };

  # Changes data that others depend on: everything reading final.demoWho follows.
  rename = final: prev: { demoWho = "Nix"; };

  # Two overlays that change the same attribute, starting from prev.
  excite = final: prev: { demoGreeting = prev.demoGreeting + "!!"; };
  bracket = final: prev: { demoGreeting = "<" + prev.demoGreeting + ">"; };
}
```

(The `demo` prefix keeps the names from clashing with real packages when you apply these
to nixpkgs in step 5.)

## 3. Use your system

```nix file=try.nix
let
  my = import ./myfix.nix;
  o = import ./overlays.nix;
  apply = overlays: my.fix (my.extends (my.composeManyExtensions overlays) o.base);
in
{
  plain = my.fix o.base;
  renamed = apply [ o.rename ];
  exciteThenBracket = apply [
    o.rename
    o.excite
    o.bracket
  ];
  bracketThenExcite = apply [
    o.rename
    o.bracket
    o.excite
  ];
}
```

```bash
nix eval --json -f try.nix
```

```text expect
"plain":{"demoGreeting":"Hello, world!","demoSummary":"Hello, world! (13 chars)","demoWho":"world"}
"renamed":{"demoGreeting":"Hello, Nix!","demoSummary":"Hello, Nix! (11 chars)","demoWho":"Nix"}
"exciteThenBracket":{"demoGreeting":"<Hello, Nix!!!>","demoSummary":"<Hello, Nix!!!> (15 chars)","demoWho":"Nix"}
"bracketThenExcite":{"demoGreeting":"<Hello, Nix!>!!","demoSummary":"<Hello, Nix!>!! (15 chars)","demoWho":"Nix"}
```

Read the results against the code:

- **Late binding.** `rename` sets only `demoWho`, yet `demoGreeting` and `demoSummary`
  change, because the base reads `final.demoWho`.
- **Order.** `excite` and `bracket` both build on `prev.demoGreeting`, so the later one
  wraps the earlier one.
- **`demoSummary` sees the end result** of all layers (`final.demoGreeting`), even though
  it's defined in the base, before any overlay existed.

The classic mistake, and the error it gives: an overlay that defines an attribute from
`final` of *itself*:

```nix file=bad.nix
let
  my = import ./myfix.nix;
  o = import ./overlays.nix;
  loud = final: prev: { demoWho = final.demoWho + "!"; }; # should be prev.demoWho
in
(my.fix (my.extends loud o.base)).demoGreeting
```

```bash fails
nix eval -f bad.nix
```

```text expect
infinite recursion encountered
```

## 4. Same results as nixpkgs

Now compare against the real thing: `lib.fix`/`lib.extends`/`lib.composeManyExtensions`,
`lib.makeExtensible`, and three ways of putting overlays on the full nixpkgs package set.
For nixpkgs the base also has to be an overlay, so it's wrapped as `final: prev: base final`.

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

```nix file=compare.nix
let
  my = import ./myfix.nix;
  o = import ./overlays.nix;
  pkgs = import ./nixpkgs.nix { };
  inherit (pkgs) lib;

  overlays = [
    o.rename
    o.excite
    o.bracket
  ];
  pick = s: { inherit (s) demoWho demoGreeting demoSummary; };

  ours = my.fix (my.extends (my.composeManyExtensions overlays) o.base);

  # nixpkgs' lib, same structure
  libFix = lib.fix (lib.extends (lib.composeManyExtensions overlays) o.base);

  # extensible objects, one layer at a time
  ourObject = pick ((((my.makeExtensible o.base).extend o.rename).extend o.excite).extend o.bracket);
  libObject = pick ((((lib.makeExtensible o.base).extend o.rename).extend o.excite).extend o.bracket);

  # the real package set
  baseOverlay = final: prev: o.base final;
  viaExtend = pick ((((pkgs.extend baseOverlay).extend o.rename).extend o.excite).extend o.bracket);
  viaAppend = pick (pkgs.appendOverlays ([ baseOverlay ] ++ overlays));
  viaImport = pick (import ./nixpkgs.nix { overlays = [ baseOverlay ] ++ overlays; });

  # left fold vs right fold (associativity)
  rightFold = my.fix (
    my.extends (lib.foldr my.composeExtensions (final: prev: { }) overlays) o.base
  );
in
{
  inherit ours;
  libAgrees = libFix == ours;
  ourObjectAgrees = ourObject == ours;
  libObjectAgrees = libObject == ours;
  extendAgrees = viaExtend == ours;
  appendOverlaysAgrees = viaAppend == ours;
  importOverlaysAgrees = viaImport == ours;
  foldDirectionIrrelevant = rightFold == ours;
}
```

```bash
nix eval --json -f compare.nix
```

```text expect
"appendOverlaysAgrees":true
"extendAgrees":true
"foldDirectionIrrelevant":true
"importOverlaysAgrees":true
"libAgrees":true
"libObjectAgrees":true
"ourObjectAgrees":true
"ours":{"demoGreeting":"<Hello, Nix!!!>","demoSummary":"<Hello, Nix!!!> (15 chars)","demoWho":"Nix"}
```

It takes nixpkgs only a moment to evaluate this, even though the package set is huge:
laziness again. Only the three `demo*` attributes (and the machinery around them) are
ever forced.

Then compare your definitions with nixpkgs' own. `lib/fixed-points.nix` defines
`fix`, `extends` and `composeExtensions` almost character for character like yours, and
`pkgs/top-level/stage.nix` ends with `lib.fix toFix`, where `toFix` folds nixpkgs' internal
layers and your `overlays` with `lib.extends`. `pkgs.extend` (also in `stage.nix`) is just
`appendOverlays [ f ]`, which re-imports nixpkgs with one more overlay. That's why its
comment warns that each call re-evaluates the whole package set.

## 5. An overlay on a real package

The same mechanism changes real packages. Overlays use `prev` for the package they change,
and everything that depends on it through `final` picks up the change:

```nix file=hello-overlay.nix
let
  pkgs = import ./nixpkgs.nix {
    overlays = [
      (final: prev: { hello = prev.hello.overrideAttrs { pname = "hello-overlaid"; }; })
      (final: prev: {
        # depends on hello through final, so it sees the overlaid one
        hello-wrapper = final.writeShellScriptBin "greet" ''exec ${final.hello}/bin/hello "$@"'';
      })
    ];
  };
in
{
  helloName = pkgs.hello.name;
  wrapperRefersToOverlaidHello = pkgs.lib.hasInfix "-hello-overlaid-" pkgs.hello-wrapper.text;
}
```

```bash
nix eval --json -f hello-overlay.nix
```

```text expect
"helloName":"hello-overlaid-2.12.3"
"wrapperRefersToOverlaidHello":true
```

## Verification

- `try.nix` shows late binding (renaming changes the greeting) and order dependence
  (`exciteThenBracket` ≠ `bracketThenExcite`).
- `bad.nix` fails with infinite recursion, and you can explain why `prev.demoWho` fixes it.
- Every comparison in `compare.nix` is `true`: your `fix`/`extends`/`makeExtensible`
  behave exactly like nixpkgs' `lib`, `pkgs.extend`, `appendOverlays` and
  `import nixpkgs { overlays }`.

## Stretch goals

1. **`fix'` and `__unfix__`.** nixpkgs' `makeExtensible` stores the original function as
   `__unfix__`. Add that to yours and use it to re-run the fixed point with a different base.
2. **Nested sets.** Add `demoConfig = { port = 80; host = "localhost"; };` to the base and
   write an overlay that changes only `port`. First try `{ demoConfig.port = 8080; }` and
   see `host` disappear (`//` is shallow), then fix it with `prev.demoConfig // { … }`.
3. **`toExtension`.** nixpkgs' `lib.toExtension` accepts an attribute set, a
   `prev: { … }` function or a full `final: prev: { … }` overlay. Implement it and make
   your `extend` accept all three.
4. **Read the warning.** Find the comment above `extend` in `pkgs/top-level/stage.nix`.
   Measure it: time `nix eval` of `(pkgs.extend (_: _: { })).hello.name` with five chained
   `extend`s versus one `appendOverlays` with five overlays.
