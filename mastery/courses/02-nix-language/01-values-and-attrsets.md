# Lesson 02.1 — Values, attribute sets, `let`, `inherit` and `with`

**You will:** meet every Nix data type, write strings with interpolation and indentation
stripping, use lists, and build attribute sets with all the shorthand nixpkgs uses.

## Expressions, not statements

A Nix file is **one expression**. There are no statements, no assignments and no
mutation. Evaluating it gives a value. `nix eval --expr` evaluates the expression you give
it and prints the result:

```bash
nix eval --expr '1 + 2 * 3'
```

```text expect
7
```

To get output you can compare reliably, ask for JSON. Attribute names come out sorted:

```bash
nix eval --json --expr '{ sum = 1 + 2 * 3; intDiv = 7 / 2; floatDiv = 7.0 / 2; }'
```

```text expect
{"floatDiv":3.5,"intDiv":3,"sum":7}
```

Watch the spaces in `7 / 2`: `7/2` without spaces is a **path** literal, not a division.

## The types

```bash
nix eval --json --expr 'map builtins.typeOf [ 1 1.0 "s" true null [ ] { } (x: x) ]'
nix eval --impure --expr 'builtins.typeOf ./.'
```

```text expect
["int","float","string","bool","null","list","set","lambda"]
"path"
```

That's all of them: integers, floats, strings, booleans, `null`, lists, attribute sets,
functions (`lambda`) and paths. Paths are a separate type from strings, and lesson 02.4
covers why. Derivations aren't a type of their own: a derivation is an attribute set with
`type = "derivation"`.

The language is **dynamically typed** and has no implicit conversions between strings and
numbers:

```bash fails
nix eval --expr '"version " + 2'
```

```text expect
cannot coerce an integer to a string
```

```bash
nix eval --expr '"version " + toString 2'
```

```text expect
"version 2"
```

## Strings

Double-quoted strings support `\n`, `\t`, `\"` and **interpolation** with `${ … }`. The
interpolated value has to be a string, a path or something with an `outPath` (a derivation):

```bash
nix eval --expr 'let name = "Nix"; in "Hello, ${name}! ${toString (40 + 2)}"'
```

```text expect
"Hello, Nix! 42"
```

**Indented strings** `'' … ''` are for multi-line text such as scripts and config files.
They remove the common leading indentation. Inside them, `''${` escapes interpolation
and `'''` produces `''`:

```nix file=strings.nix
let
  name = "Nix";
in
''
  Hello, ${name}!
    this line keeps two extra spaces
  Literal: ''${name} and '''quotes'''
''
```

```bash
nix eval --raw -f strings.nix
```

```text expect
Hello, Nix!
  this line keeps two extra spaces
Literal: ${name} and ''quotes''
```

Bash scripts in nixpkgs are almost always indented strings, so learn to see `''${var}`
(bash's own `${var}`) versus `${var}` (Nix interpolation).

## Lists

Lists are written with spaces, not commas. They're immutable, and the elements can be of
different types:

```bash
nix eval --json --expr '
  let xs = [ 1 2 3 ]; in {
    all = xs ++ [ 4 ];
    second = builtins.elemAt xs 1;
    len = builtins.length xs;
    doubled = map (x: x * 2) xs;
    evens = builtins.filter (x: builtins.bitAnd x 1 == 0) xs;
  }'
```

```text expect
{"all":[1,2,3,4],"doubled":[2,4,6],"evens":[2],"len":3,"second":2}
```

The classic list trap: inside `[ ]`, spaces separate *elements*, so a function call needs
parentheses:

```bash
nix eval --json --expr '[ (builtins.length [ toString 1 ]) (builtins.length [ (toString 1) ]) ]'
```

```text expect
[2,1]
```

`[ toString 1 ]` is a two-element list: a function and a number.

## Attribute sets

Attribute sets (`{ name = value; … }`) are what everything else is built from: packages,
configurations, the whole of nixpkgs. This file uses every piece of shorthand you'll meet:

```nix file=attrs.nix
let
  version = "1.0";
  meta = {
    license = "MIT";
    homepage = "https://example.org";
  };
  defaults = {
    color = "blue";
    size = 1;
  };
  key = "dynamic";
in
{
  inherit version; # same as: version = version;
  inherit (meta) license; # same as: license = meta.license;
  server.port = 8080; # nested: server = { port = 8080; };
  server.host = "localhost"; # merged with the line above
  ${key} = true; # attribute name computed from a string
  settings = defaults // { size = 2; }; # update: right-hand side wins
  hasColor = defaults ? color; # does the attribute exist?
  shape = defaults.shape or "square"; # default when it doesn't
  colors = with defaults; [
    color
    "red"
  ]; # `with` brings an attrset's names into scope
}
```

```bash
nix eval --json -f attrs.nix
```

```text expect
"colors":["blue","red"]
"dynamic":true
"hasColor":true
"license":"MIT"
"server":{"host":"localhost","port":8080}
"settings":{"color":"blue","size":2}
"shape":"square"
"version":"1.0"
```

Things to remember:

- `//` is **shallow**: `{ a.x = 1; } // { a.y = 2; }` gives `{ a.y = 2; }`, because the
  whole `a` gets replaced. `lib.recursiveUpdate` merges deeply. (Overlays use `//`,
  which is why nested package sets need care.)
- Selecting a missing attribute is an error. Use `or` or `?` when it may be missing:

```bash fails
nix eval --expr '{ a = 1; }.b'
```

```text expect
attribute 'b' missing
```

## `let`, scoping and `with`

`let … in` binds names for one expression. Bindings can refer to each other in any order
(lesson 02.3 explains why that works). Scoping is **lexical**, with one exception: `with`
brings in names *weakly*. A name that's already bound by `let` or a function argument
always wins over one from `with`:

```bash
nix eval --expr 'let color = "green"; in with { color = "blue"; }; color'
```

```text expect
"green"
```

That's why nixpkgs style avoids `with` beyond small scopes like `meta = with lib; { … }`,
and is moving away from even that. With several nested `with`s you can't tell where a name
comes from without evaluating. Prefer `inherit (lib) foo bar;` or `lib.foo`.

## Interactive: `nix repl`

For exploring, the REPL is faster than `nix eval`. It's interactive, so here it's shown
only. Type `:?` for help, `:p` to print a value completely, `:q` to quit:

```console
$ nix repl
nix-repl> x = { a = 1; b.c = [ 1 2 ]; }
nix-repl> x.b
{ c = [ ... ]; }
nix-repl> :p x
{
  a = 1;
  b = { c = [ 1 2 ]; };
}
nix-repl> builtins.attrNames x
[ "a" "b" ]
```

The non-interactive equivalent of the last line:

```bash
nix eval --json --expr 'builtins.attrNames { a = 1; b.c = [ 1 2 ]; }'
```

```text expect
["a","b"]
```

## Check yourself

<details><summary>What is <code>{ a = { x = 1; y = 2; }; } // { a = { x = 3; }; }</code>?</summary>

`{ a = { x = 3; }; }`. `//` replaces top-level attributes entirely, so `y` is gone. Use
`lib.recursiveUpdate` if you want `{ a = { x = 3; y = 2; }; }`.
</details>

<details><summary>Why does <code>let x = 1; in with { x = 2; }; x</code> give 1?</summary>

Names from `with` have the lowest priority. Any lexical binding (`let`, function
arguments, `rec`) shadows them, wherever it is. This keeps `with` from silently changing
the meaning of names that are already bound.
</details>

<details><summary>What's the difference between <code>"${x}"</code> and <code>''${x}</code> inside an indented string?</summary>

`${x}` is Nix interpolation: it's replaced during evaluation. `''${x}` is an escaped,
literal `${x}`, which survives into the text (typically for bash to expand at build time).
</details>
