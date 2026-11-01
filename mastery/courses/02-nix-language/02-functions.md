# Lesson 02.2 — Functions

**You will:** write curried functions, destructure attribute-set arguments with defaults
and `@`-patterns, read the errors you get when a call doesn't match, and build a small
`callPackage` to see why every nixpkgs package is a function of an attribute set.

## One argument, always

A function is `pattern: body`. Every function takes **exactly one** argument. "Several
arguments" is either currying (a function that returns a function) or one attribute set
that gets destructured.

```nix file=functions.nix
let
  add = a: b: a + b; # curried: `add 1` is a function waiting for b
  inc = add 1;
  compose = f: g: x: f (g x);

  greet =
    {
      name,
      greeting ? "Hello",
      ...
    }@args:
    "${greeting}, ${name}! (${toString (builtins.length (builtins.attrNames args))} args passed)";
in
{
  three = add 1 2;
  incremented = map inc [
    1
    2
    3
  ];
  composed = (compose inc (x: x * 10)) 4;
  named = greet { name = "Ada"; };
  custom = greet {
    name = "Ada";
    greeting = "Hi";
    extra = true;
  };
  argsOf = builtins.functionArgs greet;
  isFunction = builtins.isFunction inc;
}
```

```bash
nix eval --json -f functions.nix
```

```text expect
"argsOf":{"greeting":true,"name":false}
"composed":41
"custom":"Hi, Ada! (3 args passed)"
"incremented":[2,3,4]
"isFunction":true
"named":"Hello, Ada! (1 args passed)"
"three":3
```

Read `greet`'s pattern piece by piece:

- `{ name, greeting ? "Hello", ... }`: the argument must be an attribute set with `name`.
  `greeting` is optional and defaults to `"Hello"`, and `...` allows more attributes.
- `@args` binds the **whole argument** as passed. Look at `named`: `args` has one
  attribute. **Defaults aren't in `args`.** That catches people when they forward `args`
  to another function.
- `builtins.functionArgs` exposes the pattern: each name maps to whether it has a default.
  This is what `callPackage` reads.

Application is left-associative and binds tighter than any operator: `f a b` is
`(f a) b`, and `f a + 1` is `(f a) + 1`.

## When a call doesn't match

Patterns are checked when the function is called. These two errors show up in real
nixpkgs work all the time:

```bash fails
nix eval --expr '({ name }: name) { }'
```

```text expect
called without required argument 'name'
```

```bash fails
nix eval --expr '({ name }: name) { name = "a"; colour = "red"; }'
```

```text expect
called with unexpected argument 'colour'
```

The second is why most package functions end in `...` (or don't, on purpose, to catch
typos in overrides).

## Higher-order functions

Builtins and `lib` lean on functions that take functions:

```nix file=hof.nix
let
  xs = [
    3
    1
    2
  ];
in
{
  sorted = builtins.sort builtins.lessThan xs;
  total = builtins.foldl' (acc: x: acc + x) 0 xs;
  squares = builtins.genList (i: i * i) 4;
  byParity = builtins.groupBy (x: if builtins.bitAnd x 1 == 0 then "even" else "odd") xs;
}
```

```bash
nix eval --json -f hof.nix
```

```text expect
"byParity":{"even":[2],"odd":[3,1]}
"sorted":[1,2,3]
"squares":[0,1,4,9]
"total":6
```

`foldl'` (the apostrophe is part of the name) is the *strict* left fold. It forces the
accumulator at each step, so long lists don't build up a chain of unevaluated additions.
`builtins.groupBy` needs a function that returns a string (the group's name), and it keeps
the original order inside each group.

**Your turn:** write `countBy`, a function that takes a classifier and a list and returns
how many elements fall in each group. For example, `countBy f [ 3 1 2 ]` with the parity
classifier above should give `{ even = 1; odd = 2; }`. Use `groupBy` and
`builtins.mapAttrs`.

<details><summary>Solution</summary>

`builtins.mapAttrs` calls its function with the name *and* the value:

```nix file=countby.nix
let
  countBy = f: xs: builtins.mapAttrs (_name: group: builtins.length group) (builtins.groupBy f xs);
  parity = x: if builtins.bitAnd x 1 == 0 then "even" else "odd";
in
countBy parity [
  3
  1
  2
]
```

```bash
nix eval --json -f countby.nix
```

```text expect
{"even":1,"odd":2}
```
</details>

## The function-of-attrset interface: `callPackage`

Every package in nixpkgs is a file like this:

```nix
{ lib, stdenv, fetchurl }:
stdenv.mkDerivation { … }
```

It doesn't import its dependencies. It **declares** them as arguments, and whoever calls it
supplies them. `callPackage` does that automatically: it reads the argument names with
`functionArgs`, takes exactly those from the package set, and lets you override any of them.
Here's a one-line version of it:

```nix file=callpackage.nix
let
  pool = {
    name = "demo";
    version = "1.0";
    compiler = "gcc";
    unrelated = "never passed";
  };

  callPackage = f: overrides: f (builtins.intersectAttrs (builtins.functionArgs f) pool // overrides);

  package =
    {
      name,
      version,
      compiler,
      debug ? false,
    }:
    "${name}-${version} built with ${compiler}${if debug then " (debug)" else ""}";
in
{
  plain = callPackage package { };
  overridden = callPackage package {
    compiler = "clang";
    debug = true;
  };
}
```

```bash
nix eval --json -f callpackage.nix
```

```text expect
{"overridden":"demo-1.0 built with clang (debug)","plain":"demo-1.0 built with gcc"}
```

`package` has no `...`, yet passing it from a pool with an extra attribute works, because
`intersectAttrs` passes only what it asks for. The real one,
`lib.callPackageWith` in `lib/customisation.nix`, has the same core line
(`allArgs = intersectAttrs fargs autoArgs // args;`). It adds an error for missing
arguments ("did you mean…?") and makes the result overridable with `lib.makeOverridable`
(`.override`). Check that it agrees with yours:

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

```bash
nix eval --impure --raw --expr '
  let
    lib = (import ./nixpkgs.nix { }).lib;
    pool = { name = "demo"; version = "1.0"; compiler = "gcc"; };
    package = { name, version, compiler, debug ? false }:
      "${name}-${version} built with ${compiler}${if debug then " (debug)" else ""}";
  in
  lib.callPackageWith pool package { debug = true; }'
```

```text expect
demo-1.0 built with gcc (debug)
```

## Check yourself

<details><summary>What does <code>({ a, b ? 2 }@args: args) { a = 1; }</code> return?</summary>

`{ a = 1; }`. `@args` is the argument exactly as passed, and defaults aren't added to it.
Use the bound names (`a`, `b`) when you need the defaults.
</details>

<details><summary>Why are nixpkgs packages functions of their dependencies instead of files that import them?</summary>

So the caller decides which dependencies to use. The same file can be built against a
different compiler, a patched library or another platform's package set. `override` (which
calls the function again with changed arguments) and cross-compilation both depend on it.
</details>

<details><summary>Is <code>map f xs ++ ys</code> the same as <code>map f (xs ++ ys)</code>?</summary>

No. Function application binds tighter than `++`, so it's `(map f xs) ++ ys`, and `f`
isn't applied to `ys`.
</details>
