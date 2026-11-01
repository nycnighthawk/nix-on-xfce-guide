# Lesson 01.2 — Derivations: instantiate, then realise

**You will:** write the smallest useful derivation, turn it into a `.drv` file, read that
file two ways, build it, and see that the output path was fixed before the build started.

## Two steps, two kinds of file

A **derivation** is a build recipe: run *this builder* with *these arguments* and *this
environment*, on *this system*, after *these inputs* exist, and expect *these outputs*.
Building one always takes two steps:

1. **Instantiation** (evaluation). Nix evaluates your `.nix` code. Calling the `derivation`
   builtin writes the recipe to the store as a **store derivation**, a `/nix/store/…drv`
   file, and returns its paths. Nothing gets built.
2. **Realisation** (building). Nix makes the derivation's outputs valid. It either downloads
   them from a binary cache (**substitution**) or runs the builder.

The split is deliberate. `.drv` files contain no Nix language, so the build side (the
daemon, a remote builder, a cache) never has to evaluate anything (Nix manual, *Store →
Store Derivation and Deriving Path*; *Language → Derivations*).

## The pin

Every file in this path imports the same nixpkgs commit (see
[CONVENTIONS.md](../../CONVENTIONS.md)). Here it only gives us a `bash` to use as the builder:

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

## The smallest derivation

`derivation` needs three attributes: `name`, `system` and `builder`. Everything else is
optional, and **every attribute becomes an environment variable for the builder**. Nix adds
`$out`, the output path.

```nix file=simple.nix
let
  pkgs = import ./nixpkgs.nix { };
in
derivation {
  name = "simple";
  system = "x86_64-linux";
  builder = "${pkgs.bash}/bin/bash";
  args = [
    "-c"
    "echo building $name; echo hi > $out"
  ];
}
```

`"${pkgs.bash}/bin/bash"` puts the store path of nixpkgs' bash into a string. The string
remembers that it came from a derivation (its *string context*, course 02). That's how
bash becomes an input of `simple`. `$name` and `$out` have no braces, so Nix leaves them
alone and bash expands them at build time.

### What `derivation` returns

The result is an attribute set with `type = "derivation"` and, among other things, the two
paths:

```bash
nix eval --impure --json --expr 'builtins.attrNames (import ./simple.nix)'
nix eval --raw -f simple.nix type; echo
```

```text expect
"drvPath"
"outPath"
derivation
```

## Step 1: instantiate

`nix-instantiate` evaluates the file and writes the `.drv`. (It warns that the `.drv` isn't
protected from garbage collection. That's fine here.)

```bash
drv=$(nix-instantiate simple.nix)
echo "$drv"
```

```text expect
-simple.drv
```

### Read the `.drv` file

On disk, a store derivation is an "ATerm", a simple term syntax. It lists the outputs,
input derivations, input sources, system, builder, arguments and environment:

```bash
cat "$drv"; echo
```

```text expect
Derive([("out",
```

`nix derivation show` prints the same thing as JSON, which is easier to read:

```bash
nix derivation show "$drv"
```

```text expect
simple
x86_64-linux
echo building $name; echo hi > $out
```

It's printed on one line. Pipe it through `jq` (taken from the pinned nixpkgs, so you don't
need to install it) to read it:

```bash
nix derivation show "$drv" | nix shell -f nixpkgs.nix jq -c jq .
```

```text expect
"inputs"
"outputs"
```

The current format (version 4) maps each `.drv` to its `name`, `system`, `builder`, `args`,
`env` (every attribute you passed, plus `out`), `outputs` (with the precomputed `path`) and
`inputs`. `inputs.drvs` lists the derivations whose outputs must be built first (bash) and
`inputs.srcs` lists plain store paths (sources).

Find the bash derivation among the inputs. Its *output* will be needed to run the builder.
The `.drv` file's own references are its inputs:

```bash
nix-store --query --references "$drv"
```

```text expect
bash
```

### The output path already exists (as a name)

Look at `outPath`. You haven't built anything, but the output path is already fixed:

```bash
out=$(nix eval --raw -f simple.nix outPath)
echo "$out"
test "$out" = "$(nix-store --query --outputs "$drv")"
echo "output path known before building"
```

```text expect
-simple
output path known before building
```

This is **input addressing**. The output path is a hash of the derivation (builder,
arguments, environment and its inputs' paths), not of the result. Change any of them and the
path changes; project 01a proves it. For the exact rules (how input derivations are hashed
"modulo" fixed outputs) see the manual's *Store → Store Derivation and Deriving Path →
Input-addressing derivation outputs*.

## Step 2: realise

`nix-store --realise` builds a `.drv` and prints its output paths:

```bash
nix-store --realise "$drv"
cat "$out"
```

```text expect
hi
```

Nix stores the builder's log. `nix log` shows it for any derivation that was built locally:

```bash
nix log "$drv"
```

```text expect
building simple
```

### The everyday shortcuts

`nix-build` does both steps and leaves a `result` symlink. The new CLI accepts a `.drv`
path with `^out` (or `^*` for all outputs), meaning "the outputs of this derivation":

```bash
nix-build simple.nix
test "$(readlink result)" = "$out"
nix build "$drv^out" --no-link --print-out-paths
```

```text expect
-simple
```

## Several outputs

`outputs` lists the outputs. Each one gets its own store path and environment variable,
and the builder has to create them all:

```nix file=two.nix
let
  pkgs = import ./nixpkgs.nix { };
in
derivation {
  name = "two";
  system = "x86_64-linux";
  builder = "${pkgs.bash}/bin/bash";
  outputs = [
    "out"
    "doc"
  ];
  args = [
    "-c"
    "echo program > $out; echo manual > $doc"
  ];
}
```

`nix-build two.nix` would build only `out`, the derivation's default output. Ask for all
of them with `^*`. Each output gets its own link, `result` and `result-doc`:

```bash
nix build -f two.nix '^*' --print-out-paths
ls -1 | grep result
cat result result-doc
```

```text expect
-two-doc
result-doc
program
manual
```

nixpkgs uses this (`out`, `dev`, `man`, `doc`, …) so that installing a program doesn't pull
in its headers and manuals.

## A real package's derivation

nixpkgs' `hello` is a derivation like yours, only with more inputs: `stdenv`, its source
tarball (itself a derivation, a *fetch*), and the generic builder script:

```bash
hdrv=$(nix-instantiate nixpkgs.nix -A hello)
echo "$hdrv"
nix-store --query --references "$hdrv" | grep -E 'hello-2\.12\.3\.tar\.gz\.drv|stdenv'
```

```text expect
hello-2.12.3.drv
hello-2.12.3.tar.gz.drv
stdenv
```

`stdenv.mkDerivation` (course 03) is a function that fills in `builder`, `args` and a
lot of environment, then calls the same `derivation` builtin.

## Check yourself

<details><summary>What is the difference between `drvPath` and `outPath`?</summary>

`drvPath` is the store path of the recipe (the `.drv` file), written during instantiation.
`outPath` is where the result will go. It's computed from the recipe at the same time, but
it only exists after realisation.
</details>

<details><summary>Why are `.drv` files written in a format with no Nix language in it?</summary>

So that building never needs an evaluator. The daemon, a remote builder or a CI machine can
take a `.drv` closure and build it with nothing else. It also gives a stable,
language-independent identity to hash.
</details>

<details><summary>`nix-build` printed a path without running your builder. How?</summary>

That output path was already valid in the store (you built it before), or a substituter had
it. Nix checks for valid outputs, then substitutes, and only then builds.
</details>
