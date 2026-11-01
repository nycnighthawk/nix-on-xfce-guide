# Lesson 01.3 — References, closures and the binary cache

**You will:** see how Nix finds runtime dependencies by scanning, walk a closure as a list, a
tree and a size report, ask why one path depends on another, and check where a substitute
comes from and who signed it.

## References are found, not declared

A derivation's *inputs* are everything it might need to build. Its output's
**references** are the store paths it still needs at run time. You never list those
yourself. When the build finishes, Nix scans every byte of the output for the hash part
of each input path, and each hash it finds becomes a reference (Dolstra 2006, chapter 3,
"pointer discovery"; Nix manual, *Store → Store Object*: references).

Three derivations make the point. All three have coreutils as an input:

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

```nix file=refs.nix
let
  pkgs = import ./nixpkgs.nix { };
  mk =
    name: script:
    derivation {
      inherit name;
      system = "x86_64-linux";
      builder = "${pkgs.bash}/bin/bash";
      args = [
        "-c"
        script
      ];
      cu = pkgs.coreutils; # an input, available to the script as $cu
    };
in
{
  # writes the path of `ls` into its output
  keeps = mk "keeps-ref" "echo $cu/bin/ls > $out";
  # runs coreutils' `date`, but writes only its result
  uses = mk "uses-only" "$cu/bin/date -u -d @0 +%F > $out";
  # writes the path, but upper-cased, so the hash can't be found
  hides = mk "hides-ref" ''echo "''${cu^^}" > $out'';
}
```

(In a `''…''` string, `''${` is a literal `${`, so bash gets `${cu^^}` and upper-cases the
variable.)

```bash
nix-build refs.nix -A keeps -o keeps
nix-build refs.nix -A uses -o uses
nix-build refs.nix -A hides -o hides
echo "keeps:"; nix-store --query --references ./keeps
echo "uses:";  nix-store --query --references ./uses
echo "hides:"; nix-store --query --references ./hides
```

```text expect
-coreutils-
```

Only `keeps` refers to coreutils. Assert the other two have no references at all:

```bash
test -z "$(nix-store --query --references ./uses)"
test -z "$(nix-store --query --references ./hides)"
cat uses hides
```

```text expect
1970-01-01
/NIX/STORE/
```

So scanning is precise in one direction and blind in the other:

- **No false negatives for plain text.** If the path is written into the output anywhere
  (a shebang, an RPATH, a config file), Nix records it.
- **Nothing it can't see.** Compressed, encoded or transformed paths aren't found. Here,
  `hides` would break at run time on a machine without coreutils. In practice this almost
  never happens, but it's why nixpkgs avoids compressing files that contain store paths.

## Closures

A path's **closure** is the path plus everything it references, recursively. A closure is
what you have to copy to another machine for the path to work there. That's what `nix copy`,
binary caches and container images all ship.

```bash
nix-store --query --requisites ./keeps
```

```text expect
-glibc-
-coreutils-
```

The same closure as a tree. Each path appears once, and repeats show as `[...]`:

```bash
nix-store --query --tree ./keeps
```

```text expect
-keeps-ref
└───/nix/store/
```

And with sizes. `-s` is the path's own NAR size, `-S` its closure size, `-h` makes them
readable:

```bash
nix path-info --recursive -sSh ./keeps
```

```text expect
-keeps-ref
```

### Why does X depend on Y?

`nix why-depends` finds a chain of references, and shows where in each file the hash
appears:

```bash
glibc=$(nix-store --query --requisites ./keeps | grep -E -- '-glibc-[0-9][^/]*$' | head -n 1)
echo "$glibc"
nix why-depends ./keeps "$glibc"
```

```text expect
coreutils
```

The reverse direction: `--referrers` lists paths in *your* store that refer to a path. You'll
use it with the garbage collector in lesson 01.5:

```bash
nix-store --query --referrers "$(nix-store --query --references ./keeps)" | grep keeps-ref
```

## Binary caches: realisation without building

Input addressing means the output path is known before the build. So before building, Nix
asks its **substituters** whether they already have that exact path. On a standard install
that's `cache.nixos.org`, and only signatures from its key are trusted:

```bash
nix config show substituters
nix config show trusted-public-keys
```

```text expect
https://cache.nixos.org
cache.nixos.org-1:
```

Hydra, nixpkgs' CI, builds every package on the release branches and uploads the results,
signed. Take pinned `hello`: its output path comes from evaluation alone, and you can ask
the cache about it without having it locally. A cache is just files over HTTP, and each path
has a `.narinfo` named after its hash part:

```bash
hello=$(nix eval --raw -f nixpkgs.nix hello.outPath)
echo "$hello"
curl -sSf "https://cache.nixos.org/$(basename "$hello" | cut -d- -f1).narinfo"
```

```text expect
-hello-2.12.3
StorePath: /nix/store/
NarHash: sha256:
References:
Sig: cache.nixos.org-1:
```

The narinfo lists the path's references, its NAR hash (what you'll get after unpacking),
where the compressed NAR lives (`URL:`), and a signature over the path, hash and references.
`nix path-info` can read the same data from any store:

```bash
nix path-info --store https://cache.nixos.org --sigs "$hello"
```

```text expect
cache.nixos.org-1:
```

Now realise it. Nix finds it in the cache and downloads it instead of compiling. The
signature is checked and kept:

```bash
nix-build nixpkgs.nix -A hello --no-out-link
"$hello/bin/hello"
nix path-info --sigs "$hello"
nix store verify --sigs-needed 1 "$hello"
echo "verified: contents match the NAR hash and a trusted key signed it"
```

```text expect
Hello, world!
cache.nixos.org-1:
verified:
```

### Why this is safe

- The client checks the signature against `trusted-public-keys` *before* it accepts a
  path. An unsigned or wrongly signed path is rejected (course 05 shows this with your own
  cache).
- It checks the downloaded NAR against the signed `NarHash`.
- What it can't check is that the cache built the *right thing* for that derivation. That
  is the trust you place in the key. Project 01b shows how to check it yourself
  (`--check`). Content-addressed derivations (the `ca-derivations` experimental feature)
  are the long-term answer.

## Check yourself

<details><summary>Your program loads a plugin at run time from a path built from two strings: `"/nix/store/" + hash + "-plugin"`. Will the plugin be in the program's closure?</summary>

Only if the complete hash part appears somewhere in the output bytes. If the hash is stored
as one string, it's found, even without the `/nix/store/` prefix: Nix scans for hash
parts. If it's assembled from pieces or encoded, it isn't, and the plugin will be missing
on another machine.
</details>

<details><summary>What's the difference between `--references` and `--requisites`?</summary>

`--references` gives the direct references (one level). `--requisites` (`-R`) gives the
whole closure, the references taken recursively, including the path itself.
</details>

<details><summary>A cache has a path you want, signed by a key not in `trusted-public-keys`. What happens?</summary>

Nix refuses to substitute it and builds locally instead (or fails if it can't). Adding a
substituter without its key doesn't make its paths trusted. As an untrusted user you also
can't add keys yourself; `trusted-public-keys` belongs to root (or `trusted-users`).
</details>
