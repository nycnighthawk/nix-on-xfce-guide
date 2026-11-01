# Project 01a — A derivation by hand

**Goal:** package a small program with nothing but the `derivation` builtin, bash and
coreutils (no `stdenv`, no helpers), then use it to see every idea from this course at
work: the `.drv` file, input addressing, reference scanning and closures.

**You'll practise:** *input addressing* (any change to an input changes the output path),
*dependency discovery by scanning* (runtime references are found, not declared), and
*build-time vs run-time closures*.

This is the modern version of Nix Pills chapters 6–8. Those use the default `<nixpkgs>`
channel and `nix-store` only. Here everything comes from a pinned nixpkgs and you read
the result with the current tools.

## 1. Files

The pin:

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

The builder script. Bash runs it inside the sandbox, where every derivation attribute is an
environment variable. It makes a `greet` program and a data file:

```bash file=builder.sh
# builder.sh: produce $out/bin/greet and $out/share/message.txt
set -eu
mkdir -p "$out/bin" "$out/share"
printf '%s\n' "$message" > "$out/share/message.txt"

# The program uses only bash builtins at run time, so its one runtime
# dependency is the bash in its shebang line.
{
  echo "#!$bash/bin/bash"
  echo "while IFS= read -r line; do echo \"\$line\"; done < $out/share/message.txt"
} > "$out/bin/greet"
chmod +x "$out/bin/greet"
```

The derivation. It's a function with a default argument, so you can change an input from
the command line:

```nix file=default.nix
{
  message ? "Hello from a hand-written derivation",
}:
let
  pkgs = import ./nixpkgs.nix { };
in
derivation {
  name = "greeting";
  system = "x86_64-linux";
  builder = "${pkgs.bash}/bin/bash";
  args = [ ./builder.sh ]; # a path: copied to the store, becomes an input source
  bash = pkgs.bash; # $bash in the builder (for the shebang)
  PATH = "${pkgs.coreutils}/bin"; # mkdir, chmod at build time
  inherit message; # $message in the builder
}
```

## 2. Instantiate and read the `.drv`

```bash
drv=$(nix-instantiate default.nix)
echo "$drv"
nix derivation show "$drv"
```

```text expect
-greeting.drv
builder.sh
Hello from a hand-written derivation
x86_64-linux
```

Find in the JSON: the output `out` with its path already filled in, `builder.sh` as an
**input source** (a store path, copied from your directory), bash and coreutils as **input
derivations**, and `message`, `bash`, `PATH` in the environment.

## 3. Build and run

```bash
nix-build
./result/bin/greet
```

```text expect
Hello from a hand-written derivation
```

Building again does nothing: the output path is valid, so `nix-build` just prints it.

```bash
first=$(readlink result)
again=$(nix-build --no-out-link)
test "$first" = "$again"
echo "same inputs, same path: $first"
```

```text expect
same inputs, same path: /nix/store/
```

## 4. Change an input, watch the path change

Change the message. That's a different environment, so a different derivation and a
different output:

```bash
other=$(nix-build --no-out-link --argstr message "Bonjour")
echo "$first"
echo "$other"
test "$first" != "$other"
"$other/bin/greet"
```

```text expect
Bonjour
```

Change the builder script, even just a comment. `builder.sh` is copied by content, so its
store path changes, and with it the derivation and the output:

```bash
cp builder.sh builder.sh.orig
echo "# a harmless comment" >> builder.sh
edited=$(nix-build --no-out-link)
test "$edited" != "$first"
echo "edited script: new output path"
```

```text expect
edited script: new output path
```

Undo the edit, and also change the file's timestamp. Metadata isn't part of the hash, so
you're back to the original path, and Nix doesn't rebuild:

```bash
mv builder.sh.orig builder.sh
touch builder.sh
restored=$(nix-build --no-out-link)
test "$restored" = "$first"
echo "same content again: original path, nothing rebuilt"
```

```text expect
same content again: original path, nothing rebuilt
```

`make` decides what to rebuild from timestamps. Nix decides from content and recipes, so a
fresh checkout, a `touch` or a different machine never causes a rebuild.

## 5. References: what the output needs at run time

```bash
nix-store --query --references ./result
```

```text expect
-bash-
-greeting
```

Two references:

- **bash**, because its path is written in `greet`'s shebang line.
- **The output itself**, because `greet` mentions `$out/share/message.txt`. A
  self-reference is normal.

coreutils is missing, though it was an input and the build used `mkdir` and `chmod`.
Nothing in the output mentions its path, so the scan doesn't find it:

```bash
test -z "$(nix-store --query --references ./result | grep coreutils)"
echo "coreutils: build-time only"
```

```text expect
coreutils: build-time only
```

## 6. The closure

Everything `greet` needs at run time, as a tree and with sizes:

```bash
nix-store --query --tree ./result
nix path-info --recursive --closure-size --human-readable ./result
```

```text expect
-greeting
-bash-
glibc
```

Compare that with the **build-time** closure, everything needed to *produce* the output.
That's the `.drv` files and sources reachable from your derivation, all the way down to
nixpkgs' bootstrap tools:

```bash
runtime=$(nix-store --query --requisites ./result | wc -l)
buildtime=$(nix-store --query --requisites "$drv" | wc -l)
echo "runtime closure: $runtime paths; build-time closure: $buildtime paths"
test "$runtime" -lt "$buildtime"
```

```text expect
runtime closure:
```

The difference between those two numbers is why Nix-built containers and deployments can be
small: you ship the runtime closure only.

## Verification

You're done when all of these hold. The blocks above check each one:

- `nix derivation show` shows your attributes, and the output path is known before building.
- The same inputs give the same path; any content change gives a new one; `touch` doesn't.
- `nix-store --query --references ./result` lists bash and the output, but not coreutils.
- The runtime closure is much smaller than the build-time closure.

## Stretch goals

1. **Two outputs.** Add `outputs = [ "out" "doc" ];` and write a `README` to `$doc`. Which
   output does `./result` point to? What's in `result-doc`'s closure?
2. **Make coreutils a runtime dependency.** Make `greet` call `${coreutils}/bin/date`. Check
   that `--references` now includes coreutils and the closure grows.
3. **Structured attributes.** Add `__structuredAttrs = true;`. The environment variables
   disappear; read `$NIX_ATTRS_SH_FILE` (`source` it) instead. This is what nixpkgs
   requires for new packages (nixpkgs manual, *stdenv → Structured attributes*).
4. **Hide a reference.** Make the output contain bash's path in a way scanning can't
   detect (compress it with `gzip`, or reverse the string). The closure no longer includes
   bash. Why is that dangerous?
