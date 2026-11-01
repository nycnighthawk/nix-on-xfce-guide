# Lesson 01.4 — Purity: the daemon, build users and the sandbox

**You will:** find out who actually runs your builds, look around inside the sandbox from a
builder, watch a network request fail, and see why fixed-output derivations may use the
network.

## Why purity matters

Input addressing (lesson 01.2) promises that the same derivation gives the same result. That
only holds if a builder can see nothing *except* its declared inputs. If it could read
`/usr/lib`, your home directory or the internet, two machines could build the "same" path
differently, and the cache, sharing and rollbacks would all break. Nix enforces purity at
two levels:

- **Evaluation** (pure eval mode, the default for `nix eval`/flakes): no reading the
  environment, the clock or unpinned files.
- **Build** (the sandbox): a builder runs in an empty, isolated root with only its input
  closure.

## Who builds: the daemon and the build users

On a multi-user install, your `nix` commands don't touch `/nix/store` themselves. They ask
the **nix-daemon** (running as root) over a Unix socket:

```bash
nix store info
```

```text expect
Store URL: daemon
```

The daemon runs each build as one of the unprivileged **build users** in the
`build-users-group`. Those users own nothing, can't read your files, and two builds never
share one at the same time:

```bash
nix config show build-users-group
getent group nixbld
nix config show trusted-users
```

```text expect
nixbld
nixbld1
root
```

You're not in `trusted-users`, so the daemon ignores options that would weaken it, such as
turning off the sandbox or adding unsigned substituters (Nix manual, *nix.conf →
trusted-users*).

## Evaluation purity

`nix eval` defaults to pure mode, where there's no access to environment variables, the
clock or arbitrary files. `--impure` (implied by `--file`) lifts that:

```bash
nix eval --expr 'builtins.getEnv "HOME"'
test "$(nix eval --impure --raw --expr 'builtins.getEnv "HOME"')" = "$HOME"
echo "impure eval sees HOME"
```

```text expect
""
impure eval sees HOME
```

```bash fails
nix eval --expr 'builtins.currentTime'
```

```text expect
currentTime
```

The classic tools (`nix-build`, `nix-instantiate`) evaluate impurely. Pinning (a hash in
`fetchTarball`, a `flake.lock`) is how you get reproducible evaluation with them.

## Build purity: look inside the sandbox

`sandbox = true` is the default on Linux:

```bash
nix config show sandbox
```

```text expect
true
```

This builder writes a report about its surroundings to `$out`. It doesn't set `PATH`, so
it calls tools through absolute store paths:

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

```bash file=probe.sh
# Runs inside the build sandbox. $cu is coreutils (an input); PATH is deliberately unset.
{
  echo "HOME=$HOME"
  echo "PATH=$PATH"
  echo "NIX_STORE=$NIX_STORE"
  echo "TMPDIR=$TMPDIR"
  echo "pwd=$PWD"
  echo "user=$("$cu/bin/id" -un 2>/dev/null) uid=$("$cu/bin/id" -u)"
  if [ -e /home ]; then echo "home: visible"; else echo "home: hidden"; fi
  echo "root dir: $("$cu/bin/ls" / | "$cu/bin/tr" '\n' ' ')"
  echo "store entries visible: $("$cu/bin/ls" /nix/store | "$cu/bin/wc" -l)"
} > "$out"
```

```nix file=probe.nix
let
  pkgs = import ./nixpkgs.nix { };
in
derivation {
  name = "sandbox-probe";
  system = "x86_64-linux";
  builder = "${pkgs.bash}/bin/bash";
  args = [ ./probe.sh ];
  cu = pkgs.coreutils;
}
```

```bash
nix-build probe.nix
cat result
```

```text expect
HOME=/homeless-shelter
PATH=/path-not-set
NIX_STORE=/nix/store
home: hidden
```

What the report shows:

- The builder runs as `nixbld` (uid 1000) *inside* the sandbox. That's a user namespace
  mapping of whichever `nixbld*` build user the daemon picked on the host.
- `HOME` points to a directory that doesn't exist, and `PATH` to nothing. Tools that read
  `~/.config` or search `PATH` can't pick up anything from your machine by accident.
- `/home` isn't there. The root contains only what Nix puts in: `/build` (the working
  directory), `/nix/store`, a minimal `/dev`, `/proc`, `/etc` (with a fake `passwd` that
  has a `nixbld` user), `/tmp` and `/bin/sh` (from the `sandbox-paths` setting).
- The builder sees only its input closure, not your whole store:

```bash
inside=$(sed -n 's/^store entries visible: //p' result)
host=$(ls /nix/store | wc -l)
echo "inside the sandbox: $inside paths; on the host: $host paths"
test "$inside" -lt "$host"
echo "the sandbox hides the rest of the store"
```

```text expect
the sandbox hides the rest of the store
```

The sandbox is built from Linux namespaces: mount (its own root), PID, IPC, UTS (hostname
`localhost`), user, and **network**. The network namespace has only a loopback interface.
See the manual's *nix.conf → sandbox* and the Nix source `src/libstore/unix/build/`.

## No network for normal builds

A builder that tries to download something fails:

```nix file=net.nix
let
  pkgs = import ./nixpkgs.nix { };
in
derivation {
  name = "try-network";
  system = "x86_64-linux";
  builder = "${pkgs.bash}/bin/bash";
  args = [
    "-c"
    "${pkgs.curl}/bin/curl -sS --max-time 20 https://cache.nixos.org/nix-cache-info > $out"
  ];
}
```

```bash fails
nix-build net.nix
```

```text expect
Could not resolve host
```

There's no `/etc/resolv.conf` and no route out. That isn't a bug to work around. Any data
a build needs has to come in as an input, and the next section shows how.

## Fixed-output derivations: the one exception

A **fixed-output derivation** (FOD) declares the hash of its output in advance with
`outputHash` (plus `outputHashAlgo` and `outputHashMode`). Nix checks the result against it,
so whatever happens during the build, only the expected bytes can reach the store. That's
why FODs get network access (and `/etc/resolv.conf`): every fetcher in nixpkgs is one.

Their output path is computed from **only** the name, the hash and the hashing mode, and
not from the builder, the URL or any input. So the path *is* the content. Look at
nixpkgs' own `fetchurl` and a hand-written FOD side by side:

```nix file=fod.nix
let
  pkgs = import ./nixpkgs.nix { };
  hash = "sha256-DV9gFUOC/uELEUocNOeF2LH0kgc64tOm97FHaHs2aqA="; # GNU hello 2.12.3
  byHand =
    name:
    derivation {
      inherit name;
      system = "x86_64-linux";
      builder = "${pkgs.bash}/bin/bash";
      args = [
        "-c"
        # --insecure: no certificate check. The hash below is the check (see the note after the build).
        "${pkgs.curl}/bin/curl -sSfL --retry 5 --insecure -o $out https://ftp.gnu.org/gnu/hello/hello-2.12.3.tar.gz"
      ];
      outputHashMode = "flat"; # hash the file itself (not a NAR of a directory)
      outputHashAlgo = "sha256";
      outputHash = hash;
    };
in
{
  viaMirror = pkgs.fetchurl {
    url = "mirror://gnu/hello/hello-2.12.3.tar.gz";
    inherit hash;
  };
  viaFtp = pkgs.fetchurl {
    url = "https://ftp.gnu.org/gnu/hello/hello-2.12.3.tar.gz";
    inherit hash;
  };
  sameNameAsNixpkgs = byHand "hello-2.12.3.tar.gz";
  ownName = byHand "hello-2.12.3-by-curl.tar.gz";
}
```

Compare paths by evaluating them. Nothing gets downloaded:

```bash
nix eval --impure --json --expr '
  let f = import ./fod.nix; in {
    differentRecipes = f.viaMirror.drvPath != f.viaFtp.drvPath;
    sameOutput = f.viaMirror.outPath == f.viaFtp.outPath;
    curlByHandSameOutput = f.sameNameAsNixpkgs.outPath == f.viaMirror.outPath;
  }'
```

```text expect
"curlByHandSameOutput":true
"differentRecipes":true
"sameOutput":true
```

Two different URLs and a completely different builder give one output path. That's
**content addressing**. It's also why changing a URL without changing the hash does
nothing if the old file is already in your store (or in a cache), a classic trap from course 03.

Now build the hand-written one under its own name, so there's no copy anywhere to
substitute. Its builder really runs `curl` inside the sandbox, with network:

```bash timeout=900
nix-build fod.nix -A ownName
nix hash file "$(readlink result)"
nix derivation show "$(nix-instantiate fod.nix -A ownName)" | grep -c outputHash
```

```text expect
sha256-DV9gFUOC/uELEUocNOeF2LH0kgc64tOm97FHaHs2aqA=
```

The builder ran curl with `--insecure`, and that was deliberate. nixpkgs' `fetchurl` also
turns TLS verification *off* when a hash is given: it sets
`SSL_CERT_FILE = "/no-cert-file.crt"` (see `pkgs/build-support/fetchurl/default.nix`). The
hash is a stronger check than a certificate. If the bytes don't match, the build fails
with a hash mismatch, whoever served them. Course 03 does this on purpose. It also means
fetches keep working behind TLS-intercepting proxies, which the sandbox's empty certificate
store would otherwise reject.

FOD outputs may not refer to other store paths. A fetch result has to be plain data, so
network access can't be used to sneak a dependency into the build.

## Check yourself

<details><summary>Name three things a sandboxed, non-fixed-output builder can't do.</summary>

Reach the network (there's only loopback and no DNS), see files outside its input closure
(your home, `/usr`, the rest of `/nix/store`), and see the host's processes. It also can't
run as root or as you: it's a `nixbld` build user mapped into a user namespace.
</details>

<details><summary>Why is it safe to give fixed-output derivations network access?</summary>

Because the output is checked against a hash fixed before the build. A different response
(a compromised mirror, a re-released tarball) fails the build instead of entering the store.
Their output path depends only on name, hash and mode, and they can't have references, so
the network can't change what they produce.
</details>

<details><summary>Your build works with `sandbox = false` but fails in the sandbox. What does that tell you?</summary>

It depends on something undeclared: a tool from `/usr/bin`, a file in your home, network
access. The fix is to add the dependency as an input, or for downloads to make it a
fixed-output fetch. Never turn the sandbox off to make it work: the result would only build
on your machine.
</details>
