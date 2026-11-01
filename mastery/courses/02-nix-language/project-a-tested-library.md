# Project 02a — A tested mini library

**Goal:** write a small library of string and list functions the way nixpkgs writes `lib`,
as a function of its dependencies, with unit tests run by `lib.debug.runTests`. Wire it up
so that a failing test makes the command fail, then watch a test catch a real bug.

**You'll practise:** the *function-of-attrset interface* (`{ lib }: { … }`), *tests as
data* (`runTests` returns the list of failures), forcing evaluation with `--strict`, and
`tryEval` for testing errors.

## How nixpkgs tests `lib`

nixpkgs' own `lib/tests/misc.nix` is one big call to `lib.debug.runTests`. Its header says
how to run it:

```
nix-instantiate --eval --strict lib/tests/misc.nix
If the resulting list is empty, all tests passed.
```

`runTests` takes an attribute set of tests. Each `test*` attribute is `{ expr; expected; }`,
and it returns a list with one `{ name; expected; result; }` per test whose `expr` doesn't
equal `expected` (`lib/debug.nix`). The list is *data*, so evaluating it succeeds even when
tests fail. nixpkgs' CI therefore compares the output with `[ ]` (see
`lib/tests/test-with-nix.nix`). You'll do both that and something stricter.

## 1. The pin

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

## 2. Tests first

Write down what the library should do before writing it:

```nix file=tests.nix
let
  lib = (import ./nixpkgs.nix { }).lib;
  my = import ./lib.nix { inherit lib; };
in
lib.debug.runTests {
  testWordsSimple = {
    expr = my.words "hello world";
    expected = [
      "hello"
      "world"
    ];
  };
  testWordsExtraSpaces = {
    expr = my.words "  hello   world ";
    expected = [
      "hello"
      "world"
    ];
  };
  testCapitalize = {
    expr = my.capitalize "nix";
    expected = "Nix";
  };
  testCapitalizeEmpty = {
    expr = my.capitalize "";
    expected = "";
  };
  testTitleCase = {
    expr = my.titleCase "the  nix language";
    expected = "The Nix Language";
  };
  testSlugify = {
    expr = my.slugify "Hello, World! 2026";
    expected = "hello-world-2026";
  };
  testChunksOf = {
    expr = my.chunksOf 2 [
      1
      2
      3
      4
      5
    ];
    expected = [
      [
        1
        2
      ]
      [
        3
        4
      ]
      [ 5 ]
    ];
  };
  # Errors can be tested too: tryEval catches `throw` and `assert`.
  testChunksOfRejectsZero = {
    expr = (builtins.tryEval (my.chunksOf 0 [ 1 ])).success;
    expected = false;
  };
  testSum = {
    expr = my.sum [
      1
      2
      3
      4
    ];
    expected = 10;
  };
  testFrequencies = {
    expr = my.frequencies [
      "a"
      "b"
      "a"
    ];
    expected = {
      a = 2;
      b = 1;
    };
  };
}
```

And a check that **fails** when any test fails. `lib.debug.throwTestFailures` returns `null`
for an empty list and otherwise prints each failure and throws:

```nix file=check.nix
let
  lib = (import ./nixpkgs.nix { }).lib;
  failures = import ./tests.nix;
in
builtins.seq (lib.debug.throwTestFailures { inherit failures; }) "all tests passed"
```

## 3. A first implementation (with a bug)

```nix file=lib.nix
# A small string and list library, nixpkgs style: a function of its dependencies.
{ lib }:
let
  inherit (lib) strings lists;
in
rec {
  # Split a string into words on spaces.
  words = s: strings.splitString " " s;

  # Upper-case the first character.
  capitalize =
    s: strings.toUpper (builtins.substring 0 1 s) + builtins.substring 1 (builtins.stringLength s) s;

  titleCase = s: strings.concatStringsSep " " (map capitalize (words s));

  # Lower-case, keep only [a-z0-9] and spaces, join the words with "-".
  slugify =
    s:
    let
      keep = c: builtins.match "[a-z0-9 ]" c != null;
      cleaned = strings.concatStrings (
        builtins.filter keep (strings.stringToCharacters (strings.toLower s))
      );
    in
    strings.concatStringsSep "-" (words cleaned);

  # Split a list into chunks of n elements.
  chunksOf =
    n: xs:
    assert lib.assertMsg (n > 0) "chunksOf: n must be positive, got ${toString n}";
    if xs == [ ] then [ ] else [ (lists.take n xs) ] ++ chunksOf n (lists.drop n xs);

  sum = builtins.foldl' (acc: x: acc + x) 0;

  # Count how often each string occurs.
  frequencies = builtins.foldl' (acc: x: acc // { ${x} = (acc.${x} or 0) + 1; }) { };
}
```

## 4. Run the tests and see them fail

The raw test result is a list of failures. Evaluating it *succeeds*, so look at what's in
it:

```bash
nix-instantiate --eval --strict tests.nix
```

```text expect
testTitleCase
testWordsExtraSpaces
```

`splitString " "` keeps the empty strings between consecutive spaces
(`"a  b"` → `[ "a" "" "b" ]`), and `titleCase` inherits the bug. That's two failures from
one cause. The check turns them into an error, with a readable report:

```bash fails
nix-instantiate --eval check.nix
```

```text expect
2 tests failed
- testTitleCase
- testWordsExtraSpaces
```

A command that fails is what you want in CI or a pre-commit hook. A command that prints
something that only *looks* like a failure isn't.

## 5. Fix the bug

Filter out the empty words:

```nix file=lib.nix
# A small string and list library, nixpkgs style: a function of its dependencies.
{ lib }:
let
  inherit (lib) strings lists;
in
rec {
  # Split a string into words on spaces, dropping empty words.
  words = s: builtins.filter (w: w != "") (strings.splitString " " s);

  # Upper-case the first character.
  capitalize =
    s: strings.toUpper (builtins.substring 0 1 s) + builtins.substring 1 (builtins.stringLength s) s;

  titleCase = s: strings.concatStringsSep " " (map capitalize (words s));

  # Lower-case, keep only [a-z0-9] and spaces, join the words with "-".
  slugify =
    s:
    let
      keep = c: builtins.match "[a-z0-9 ]" c != null;
      cleaned = strings.concatStrings (
        builtins.filter keep (strings.stringToCharacters (strings.toLower s))
      );
    in
    strings.concatStringsSep "-" (words cleaned);

  # Split a list into chunks of n elements.
  chunksOf =
    n: xs:
    assert lib.assertMsg (n > 0) "chunksOf: n must be positive, got ${toString n}";
    if xs == [ ] then [ ] else [ (lists.take n xs) ] ++ chunksOf n (lists.drop n xs);

  sum = builtins.foldl' (acc: x: acc + x) 0;

  # Count how often each string occurs.
  frequencies = builtins.foldl' (acc: x: acc // { ${x} = (acc.${x} or 0) + 1; }) { };
}
```

## Verification

All three ways of running the tests agree. The empty list, the way nixpkgs' CI checks
`lib`:

```bash
nix-instantiate --eval --strict tests.nix
test "$(nix-instantiate --eval --strict tests.nix)" = "[ ]"
```

```text expect
[ ]
```

The same as JSON, through the new CLI:

```bash
test "$(nix eval --json -f tests.nix)" = "[]"
echo "nix eval agrees: no failures"
```

```text expect
nix eval agrees: no failures
```

And the strict check, which now succeeds:

```bash
nix eval --raw -f check.nix; echo
```

```text expect
all tests passed
```

## Stretch goals

1. **More functions, tests first.** Add `padLeft n char s` and `intersperse sep xs`. Write
   the tests, see them fail with "attribute missing", then implement. (`lib.strings` and
   `lib.lists` have versions of both; compare yours against them in a test.)
2. **Test the error message.** `tryEval` only tells you *that* something failed. nixpkgs
   tests error messages from shell scripts (`lib/tests/modules.sh`). Write a `bash fails`
   style check that greps for `n must be positive` in the output of
   `nix-instantiate --eval --expr '(import ./lib.nix { lib = …; }).chunksOf 0 [ 1 ]'`.
3. **Run tests as a build.** Make a derivation that only builds if the tests pass, for
   example `pkgs.runCommand "lib-tests" { } (builtins.seq (lib.debug.throwTestFailures
   { failures = import ./tests.nix; }) "touch $out")`, so `nix-build` (and later
   `nix flake check`, course 04) runs them.
4. **Property-style tests.** Use `builtins.genList` to generate 100 inputs and check
   that, for every list, `builtins.concatLists (chunksOf n xs) == xs`.
