# Lesson 01.5 — Garbage collection and GC roots

**You will:** see what keeps a store path alive, add and remove GC roots, watch the
collector refuse to delete a live path, and then delete it once it is dead. All on one path
you made, so nothing else in your store gets touched.

## The model

Nothing in `/nix/store` is ever overwritten, so the store only grows until you collect
garbage. The collector works like one in a programming language:

- **Roots** are the starting points: symlinks under `/nix/var/nix/gcroots` (directly, or
  through `gcroots/auto`, which points to symlinks elsewhere), profile generations
  (`/nix/var/nix/profiles`, `~/.local/state/nix/profiles`), and store paths open in
  running processes.
- A path is **alive** if a root reaches it through references (lesson 01.3).
- Everything else is **dead**. `nix-collect-garbage` deletes all of it.

Two settings extend "alive" (Nix manual, *nix.conf*): `keep-derivations` (default `true`)
keeps the `.drv` files of live outputs, and `keep-outputs` (default `false`) would keep the
outputs of live `.drv` files, which is handy for development machines.

```bash
echo "keep-derivations=$(nix config show keep-derivations)"
echo "keep-outputs=$(nix config show keep-outputs)"
```

```text expect
keep-derivations=true
keep-outputs=false
```

## A path to collect

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

```nix file=gcdemo.nix
let
  pkgs = import ./nixpkgs.nix { };
in
derivation {
  name = "gc-demo";
  system = "x86_64-linux";
  builder = "${pkgs.bash}/bin/bash";
  args = [
    "-c"
    "echo 'collect me' > $out"
  ];
}
```

```bash
nix-build gcdemo.nix
p=$(readlink result)
drv=$(nix-store --query --deriver "$p")
echo "$p"
```

```text expect
-gc-demo
```

## `result` is a root

`nix-build` made `./result` a symlink to the output. It also registered it as an
**indirect root**: a symlink in `/nix/var/nix/gcroots/auto/` that points at your `result`
link. That's how the collector finds roots that live in your directories:

```bash
ls -l /nix/var/nix/gcroots/auto/ | grep -F "$PWD/result"
nix-store --query --roots "$p"
```

```text expect
/result
```

`--print-roots` lists every root the collector would start from. Yours is there:

```bash
nix-store --gc --print-roots | grep -F "$PWD/result"
```

```text expect
-gc-demo
```

## A live path can't be deleted

`nix-store --delete` removes specific paths, but only dead ones:

```bash fails
nix-store --delete "$p"
```

```text expect
still alive
```

## More roots

`--add-root` creates a root wherever you want, usually next to the project that needs the
path. With `--realise`, it builds or substitutes the path first if needed:

```bash
nix-store --add-root "$PWD/keep-me" --realise "$p"
rm result
nix-store --query --roots "$p"
```

```text expect
/keep-me
```

Deleting `result` didn't free the path: `keep-me` still holds it. Other ways to make roots:
`nix build --out-link NAME`, `nix-instantiate --add-root NAME` (for `.drv` files), and
profiles (`nix profile install`, NixOS generations). Each profile generation is a root
until you delete the generation.

## Dead, then gone

Remove the last root. The path is now dead. `--print-dead` lists what a full collection
*would* delete without deleting anything:

```bash
rm keep-me
test -z "$(nix-store --query --roots "$p")"
nix-store --gc --print-dead | grep -F "$p"
```

```text expect
-gc-demo
```

Now it can be deleted, and so can its `.drv` (here with the new CLI):

```bash
nix-store --delete "$p"
test ! -e "$p"
nix store delete "$drv"
test ! -e "$drv"
echo "both gone"
```

```text expect
deleted
both gone
```

## Collecting everything

You've just done by hand, on one path, what these commands do to every dead path:

```console
$ nix-collect-garbage                         # delete all dead paths
$ nix-collect-garbage --delete-older-than 30d # also delete old profile generations first
$ nix-store --gc --max-freed 10G              # stop after freeing 10 GiB
$ nix store gc                                # new-CLI equivalent of nix-store --gc
```

They aren't run here on purpose. A full collection would also delete this course's pinned
nixpkgs source and every package you fetched (nothing roots them), and the next lesson
would download them again. On your own machine, run them whenever you like. Anything
still rooted survives, and anything deleted can be rebuilt or substituted from its
derivation. Deleting a path never loses information that Nix can't regenerate.

For unattended machines, `min-free` / `max-free` in `nix.conf` make Nix collect
automatically when the disk fills up, and NixOS has `nix.gc.automatic`.

## Check yourself

<details><summary>You `rm result` and run `nix-collect-garbage`, but the path survives. Name two possible reasons.</summary>

Another root still reaches it: a profile generation that installed it, another `result`
symlink, a root made with `--add-root`, or a path that references it (a reverse
dependency) is itself alive. Or a running process has it open. `nix-store --query --roots
PATH` tells you which.
</details>

<details><summary>Why does the collector need `gcroots/auto` instead of just following every symlink on disk?</summary>

It can't scan the whole filesystem for symlinks into the store. Indirect roots record
*where* the user's symlinks are. When one of those symlinks is deleted or changed, the auto
entry becomes stale and the collector ignores it, so `rm result` is enough to remove a root.
</details>

<details><summary>Is running the garbage collector ever dangerous?</summary>

It never deletes anything reachable from a root, so installed software and current
generations keep working. What you lose is cached work: unrooted build results and sources
that you might need again. That's why development machines often set `keep-outputs = true`
and root their dev shells (for example with nix-direnv).
</details>
