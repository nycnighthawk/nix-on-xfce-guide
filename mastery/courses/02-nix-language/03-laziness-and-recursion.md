# Lesson 02.3 — Laziness, recursion and `rec`

**You will:** see that values are computed only when needed and at most once, control
evaluation with `seq`, `deepSeq` and `tryEval`, use recursion and self-reference safely,
and find out why `nix-instantiate --eval` needs `--strict`.

## Call-by-need

Nix is **lazy**. An expression isn't evaluated when it's bound, only when its value is
needed. Until then it's a **thunk**, a suspended computation. A value that's never needed
is never computed, even if it would fail:

```bash
nix eval --expr 'let unused = throw "never evaluated"; in 42'
nix eval --expr '{ broken = throw "boom"; fine = 1; }.fine'
nix eval --expr 'builtins.length [ (throw "a") (throw "b") ]'
nix eval --json --expr 'builtins.attrNames { a = throw "x"; b = throw "y"; }'
```

```text expect
42
1
2
["a","b"]
```

The list has two elements, and counting them doesn't touch them. The attribute names are
known, so listing them doesn't evaluate the values.

### At most once

When a thunk is forced, its result **replaces** it, so a shared value is computed once
however many times it's used. `builtins.trace` prints to stderr when it's evaluated, which
lets you count:

```bash
nix-instantiate --eval --strict --expr '
  let x = builtins.trace "computing x" (6 * 7); in [ x x x ]' 2> trace.log
grep -c "computing x" trace.log
```

```text expect
[ 42 42 42 ]
1
```

A *function call*, on the other hand, gets evaluated every time it happens:

```bash
nix-instantiate --eval --strict --expr '
  let f = n: builtins.trace "calling f" (n * 2); in [ (f 1) (f 1) (f 1) ]' 2> trace.log
grep -c "calling f" trace.log
```

```text expect
3
```

This is why nixpkgs is cheap to use: `import <nixpkgs> {}` builds a set of 100,000+
thunks, and `pkgs.hello` forces only hello and the things hello needs.

## Forcing evaluation

Laziness has a cost: an error can hide in an unevaluated value, and you only find it when
something forces it. These tools control that:

- **Weak head normal form (WHNF):** forcing a value evaluates it only until its outermost
  shape is known. For an attribute set that means "it's a set with these names", not the
  values.
- `builtins.seq a b` forces `a` to WHNF, then returns `b`.
- `builtins.deepSeq a b` forces `a` completely, then returns `b`.

```bash
nix eval --expr 'builtins.seq { a = throw "inside"; } "the set itself is fine"'
```

```text expect
"the set itself is fine"
```

```bash fails
nix eval --expr 'builtins.deepSeq { a = throw "inside"; } "never returned"'
```

```text expect
inside
```

`builtins.tryEval` catches `throw` and failing `assert`s (only those: real bugs such as a
type error or a missing attribute aren't caught). It forces to WHNF, so it doesn't see
errors nested deeper:

```bash
nix eval --json --expr '
  {
    caught = builtins.tryEval (throw "boom");
    assertion = builtins.tryEval (assert 1 == 2; "unreachable");
    ok = builtins.tryEval 42;
    shallow = (builtins.tryEval { a = throw "deep"; }).success;
  }'
```

```text expect
"assertion":{"success":false,"value":false}
"caught":{"success":false,"value":false}
"ok":{"success":true,"value":42}
"shallow":true
```

nixpkgs uses `tryEval` to skip packages that `throw` (for example, packages that are
broken or not available on your platform) when listing everything, as `nix search` and
Hydra do.

## Why `--strict`?

`nix-instantiate --eval` prints its result *without forcing anything that's still
unevaluated*, and that's the documented behaviour (Nix manual, *nix-instantiate*,
`--strict`). The values show up as placeholders. `--strict` forces the whole value first:

```bash
nix-instantiate --eval --expr '{ a = 1 + 1; b = [ (2 + 2) ]; }'
nix-instantiate --eval --strict --expr '{ a = 1 + 1; b = [ (2 + 2) ]; }'
```

```text expect
{ a = 2; b = [ 4 ]; }
```

The first line prints `{ a = <CODE>; b = <CODE>; }`, where `<CODE>` means "not evaluated
yet". That's also why it can print a set containing an error:

```bash
nix-instantiate --eval --expr '{ fine = 1; broken = throw "boom"; }'
```

```bash fails
nix-instantiate --eval --strict --expr '{ fine = 1; broken = throw "boom"; }'
```

```text expect
boom
```

`nix eval` doesn't need the flag: it forces what it prints as it goes. One surprise:
when an *attribute* fails, `nix eval` shows it inline as `«error: …»` and still exits
successfully. Only an error in the top-level value (or anything under `--json`) fails the
command. So when a test should fail, select the attribute or use `--json`. Use `--strict`
with `nix-instantiate`, for example to run test suites (project 02a), which is exactly how
nixpkgs runs its own `lib` tests (`lib/tests/misc.nix`).

## Recursion

Functions can call themselves through a `let` binding. `let` is recursive: every name is in
scope in every binding, in any order:

```bash
nix eval --json --expr '
  let
    fib = n: if n < 2 then n else fib (n - 1) + fib (n - 2);
  in
  map fib [ 0 1 2 3 4 5 6 7 8 9 10 ]'
```

```text expect
[0,1,1,2,3,5,8,13,21,34,55]
```

Laziness also lets data refer to itself. Here's an infinite stream of natural numbers,
where only the cells you walk through are ever built:

```bash
nix eval --expr '
  let
    from = n: { head = n; tail = from (n + 1); };
    nats = from 0;
  in
  nats.tail.tail.tail.head'
```

```text expect
3
```

## `rec` attribute sets

`rec { … }` lets attributes refer to each other, like `let` does, but the result is the
set itself:

```bash
nix eval --json --expr 'rec { version = "1.0"; name = "demo-${version}"; }'
```

```text expect
{"name":"demo-1.0","version":"1.0"}
```

The catch: in a `rec` set, *every* attribute shadows the same name from outside. A
binding that looks harmless can turn into a self-reference:

```bash fails
nix eval --expr '(let version = "1.0"; in rec { version = version; }).version'
```

```text expect
infinite recursion encountered
```

With a plain set, `{ version = version; }` (that is, `{ inherit version; }`) would
have taken the outer `version`. A `rec` set also can't be extended later: once it's built,
the references inside are fixed. That's why nixpkgs moved from
`stdenv.mkDerivation rec { … }` to `stdenv.mkDerivation (finalAttrs: { … })`. The
`finalAttrs` form is a *fixed point* that `overrideAttrs` can extend, so overriding
`version` also changes `src`'s URL. Lesson 02.5 builds that idea from scratch.

### Real cycles

Laziness allows self-reference as long as each step makes progress. A value that needs
*itself* to be computed first is a real cycle, and Nix detects it:

```bash fails
nix eval --expr 'let x = x + 1; in x'
```

```text expect
infinite recursion encountered
```

## Check yourself

<details><summary>Does <code>builtins.length (map (x: throw "no") [ 1 2 3 ])</code> fail?</summary>

No, it returns 3. `map` creates a list of three thunks (`(x: throw "no") 1`, …) and `length`
doesn't force elements.
</details>

<details><summary>What's the difference between <code>seq</code> and <code>deepSeq</code>?</summary>

`seq` forces its first argument to weak head normal form (just enough to know its outer
shape: "a list of 3 elements", "a set with these names"). `deepSeq` forces it completely,
including every element and attribute value, recursively.
</details>

<details><summary>Why does <code>rec { a = 1; b = a; }</code> work but <code>rec { a = a; }</code> loop?</summary>

In the first, `b` refers to `a`, which is `1`: no cycle. In the second, `a` refers to the
`a` of the same `rec` set (itself), not to some outer `a`, so evaluating it needs its own
value first.
</details>
