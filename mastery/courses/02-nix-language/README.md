# Course 02 · The Nix language

Nix is a small, lazy, purely functional language for describing derivations. You could
learn its syntax in an afternoon. Reading nixpkgs takes more: you need its *idioms*, the
function-of-an-attribute-set interface, laziness used as configuration, and fixed points
that overlays extend. This course goes from values to fixed points, and you prove each step
with `nix eval`.

## Goals

After this course you can:

- read and write any Nix expression: values, attribute sets, `let`/`inherit`/`with`, lists,
  strings and interpolation, functions and their patterns;
- predict *when* something is evaluated, and use that: lazy attributes, `seq`/`deepSeq`,
  `tryEval`, and why `nix-instantiate --eval --strict` exists;
- say what happens when a path is put into a string (it's copied to the store and gets
  *string context*) and how that context turns into derivation inputs;
- define `fix` and `extends` from scratch and explain overlays (`final`/`prev`) in terms of
  them, well enough to read `lib/fixed-points.nix` and `pkgs/top-level/stage.nix`.

## Prerequisites

- Course 00 (Nix installed, `nix-command flakes` on) and course 01 (store paths,
  derivations), because course 02 refers back to `.drv` files and the store.
- No functional programming background needed. If you know any language with closures
  (JavaScript, Python), you have enough.

```bash
nix eval --expr '"Nix " + builtins.nixVersion'
```

```text expect
"Nix 2.35
```

## How to run Nix code in this course

| Command | Use it for |
|---|---|
| `nix eval --expr 'EXPR'` | quick expressions; pure mode (no files, no environment) |
| `nix eval --json …` | structured output that's easy to compare |
| `nix eval --raw …` | print a string without quotes |
| `nix eval -f file.nix [attr]` | evaluate a file (implies `--impure`) |
| `nix-instantiate --eval --strict file.nix` | the classic, stable equivalent; `--strict` forces the whole value |
| `nix repl` | interactive exploration (shown in `console` blocks only) |

## Structure

| File | What you do |
|---|---|
| [01-values-and-attrsets.md](01-values-and-attrsets.md) | Types, strings, lists, attribute sets, `let`, `inherit`, `with`, `//`, `?`, `or` |
| [02-functions.md](02-functions.md) | Currying, attribute-set patterns, defaults, `@`-patterns, a mini `callPackage` |
| [03-laziness-and-recursion.md](03-laziness-and-recursion.md) | Call-by-need, `seq`/`deepSeq`, `tryEval`, `rec`, infinite recursion |
| [04-paths-imports-context.md](04-paths-imports-context.md) | Paths vs strings, `import`, lookup paths, string context, `builtins.path` |
| [05-fixed-points-and-overlays.md](05-fixed-points-and-overlays.md) | `lib.fix`, `lib.extends`, overlays, `makeExtensible` |
| [project-a-tested-library.md](project-a-tested-library.md) | A small library with unit tests via `lib.debug.runTests` |
| [project-b-overlay-system.md](project-b-overlay-system.md) | Your own `fix`/`extends`, checked against nixpkgs' overlays |

## Patterns you will practise

- **Function-of-attrset interfaces.** `{ stdenv, fetchurl, lib }: …` is how every nixpkgs
  package declares its dependencies. `callPackage` fills them in by reading the
  function's argument names.
- **Laziness as configuration.** A huge attribute set (all of nixpkgs, a whole NixOS
  configuration) costs nothing until you look at one attribute. Values can refer to each
  other freely as long as there's no real cycle.
- **Fixed-point extension.** Define a set as a function of its own final value
  (`final: { … }`), and you can layer changes over it (`final: prev: { … }`). Every
  later reference then sees the change. Overlays, `overrideAttrs` with `finalAttrs`, and the
  module system all work like this.

## Primary sources

- Nix reference manual 2.35, *Language* (Data Types, Syntax and semantics, Scoping, String
  context, Lookup path, Built-in functions).
- nixpkgs 26.05: `lib/` (with `lib/fixed-points.nix`, `lib/customisation.nix`,
  `lib/debug.nix`), `doc/using/overlays.chapter.md`, `pkgs/top-level/stage.nix`.
- nix.dev, *Nix language basics* and *Working with local files*. Lessons 01 and 04 follow
  a similar order.

## Check yourself (after the course)

<details><summary>What does `{ lib, stdenv, ... }:` at the top of a file tell you?</summary>

The file is a function that takes one attribute set and needs at least `lib` and `stdenv`
from it. `...` lets the caller pass more. `callPackage` uses `builtins.functionArgs` to see
the names and passes exactly those from the package set.
</details>

<details><summary>Why can nixpkgs be a single attribute set with 100,000+ packages without being slow?</summary>

Laziness. An attribute's value is a thunk (deferred computation) until something needs it.
`pkgs.hello` evaluates hello and its dependencies, not the other 100,000. Selecting
attributes is cheap; forcing all of them (`--strict` on `pkgs`) would never finish.
</details>

<details><summary>In an overlay `final: prev: { … }`, when do you use `final` and when `prev`?</summary>

Use `prev` for the value you're replacing (`hello = prev.hello.overrideAttrs …`), otherwise
you'd define it in terms of itself. Use `final` for everything you depend on, so that later
overlays' changes reach you too.
</details>
