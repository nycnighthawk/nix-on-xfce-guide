# Lesson 00.2 — First commands and the store

**You will:** run software without installing it, find packages, and learn to read
`/nix/store` paths, using both the classic CLI and the newer `nix` command.

## Two command-line interfaces

Nix has two CLIs that talk to the same store:

| Classic (stable) | New `nix` command (experimental, enabled in 00.1) |
|---|---|
| `nix-shell -p hello` | `nix shell nixpkgs#hello` |
| `nix-build` | `nix build` |
| `nix-instantiate --eval` | `nix eval` |
| `nix-store -q …` | `nix path-info`, `nix-store` still used |

You'll see both in documentation and in nixpkgs. This path uses whichever is clearer and names
the other.

The `nixpkgs` in `nixpkgs#hello` is a **flake reference** looked up in the *flake registry*,
which by default points at the moving `nixpkgs-unstable` branch. Course 04 replaces it with
exact pins; for now, just look:

```bash
nix registry list | grep -m1 'flake:nixpkgs'
```

```text expect
github:NixOS/nixpkgs
```

## Run without installing

`nix shell` puts packages on `PATH` for one command (or a subshell when you leave out
`--command`):

```bash
nix shell nixpkgs#cowsay nixpkgs#lolcat --command bash -c 'cowsay "no install needed" | lolcat -f | head -3'
command -v cowsay || echo "cowsay is not installed"
```

```text expect
no install needed
cowsay is not installed
```

`nix run` runs a package's main program directly:

```bash
nix run nixpkgs#figlet -- Nix
```

## Finding packages

`nix search` evaluates all of nixpkgs, so the first search takes a while:

```bash timeout=1200
nix search nixpkgs '^ripgrep$'
```

```text expect
legacyPackages.x86_64-linux.ripgrep
```

The web search at `search.nixos.org` gives the same answers faster.

## Reading a store path

Ask where `hello` lives:

```bash
p=$(nix build nixpkgs#hello --no-link --print-out-paths)
echo "$p"
ls "$p/bin"
```

```text expect
-hello-2.12
hello
```

A store path looks like `/nix/store/<hash>-<name>-<version>`:

- the **hash** (32 characters, base32) is derived from *everything that went into the build*:
  sources, dependencies, build script, compiler flags. Change any input and you get a different
  path. Course 01 proves this.
- the store is **read-only** and paths never change once built, so many versions can live side
  by side.

Every store path's dependencies are recorded. `hello` needs glibc at runtime:

```bash
nix path-info --recursive "$p"
```

```text expect
glibc
hello
```

## Two versions side by side

Nothing stops you from using an old and a new version at once. They're just different paths.
Here's `hello` from nixpkgs 26.05 and from 25.11 (the two exact commits this path pins):

```bash timeout=1200
new=$(nix build github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808#hello --no-link --print-out-paths)
old=$(nix build github:NixOS/nixpkgs/b6018f87da91d19d0ab4cf979885689b469cdd41#hello --no-link --print-out-paths)
"$new/bin/hello" --version | head -1
"$old/bin/hello" --version | head -1
[ "$new" != "$old" ] && echo "different store paths"
```

```text expect
hello (GNU Hello)
different store paths
```

## Check yourself

<details><summary>What does the hash in a store path depend on?</summary>
All the inputs of the build (sources, dependencies, builder, arguments, environment), not the
output bytes. That's called <em>input addressing</em>. Course 01 covers the exception
(fixed-output and content-addressed paths).
</details>
<details><summary>After <code>nix shell nixpkgs#cowsay</code>, how would you remove cowsay?</summary>
There's nothing to uninstall. Its store paths are garbage once nothing refers to them, and
<code>nix-collect-garbage</code> deletes unreferenced paths (lesson 01.5).
</details>
<details><summary>Why can't two versions of a library conflict?</summary>
Each is in its own store path, and each program is built against the exact paths it depends on.
There's no shared <code>/usr/lib</code> to fight over.
</details>
