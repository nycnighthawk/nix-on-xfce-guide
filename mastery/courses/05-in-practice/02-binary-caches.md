# Lesson 05.2 — Binary caches: signatures, `nix copy`, a file cache, trust settings

**You will:** read what `cache.nixos.org` actually serves, check signatures yourself, create a
signing key, push a path into a binary cache in a directory, and find out who decides whether a
cache is trusted.

## A binary cache is a directory of files

Course 01 showed that a substituter lets Nix download a store path instead of building it. Here
is what that looks like from the other side. A binary cache (Nix manual: *Store Types → HTTP
Binary Cache Store* and *Local Binary Cache Store*) holds three kinds of file:

| File | Contents |
|---|---|
| `nix-cache-info` | the cache's `StoreDir` (must be `/nix/store`) and `Priority` |
| `<hash>.narinfo` | metadata for one store path: its NAR's URL, compression, `NarHash`, `NarSize`, `References`, `Deriver`, and one or more `Sig:` lines |
| `nar/<filehash>.nar.xz` | the store path's contents, serialised as a NAR (*Nix ARchive*) and compressed |

Nothing in this layout says whether the cache is honest. Anyone who can write files can make a
cache. Trust comes from the `Sig:` lines. Each is an Ed25519 signature, by a named key, over the
store path, its `NarHash`, `NarSize` and `References`. The receiving store accepts the path only
if at least one signature verifies with a key it trusts.

## Who trusts what: the daemon's settings

On a multi-user install the **daemon** (running as root) owns `/nix/store`. Your `nix` commands
are clients that ask it to add paths. So the settings that matter are the daemon's, from
`/etc/nix/nix.conf`:

```bash
nix config show substituters
nix config show trusted-public-keys
nix config show require-sigs
nix config show trusted-users
nix store info
```

```text expect
https://cache.nixos.org
cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY=
true
root
Trusted:
```

- `substituters`: caches the daemon asks, in priority order.
- `trusted-public-keys`: keys whose signatures the daemon accepts. The default is only
  `cache.nixos.org-1`.
- `require-sigs = true`: a path copied into the store needs a trusted signature. (There are two
  exceptions: content-addressed paths, which can be verified from their contents, and paths the
  daemon built itself.)
- `trusted-users`: who may change the daemon's restricted settings. The default is `root` only.
  `nix store info` prints `Trusted: 0` for a normal user and `Trusted: 1` for a trusted one.

## Look at a real signed path

Fetch GNU hello from nixpkgs 26.05. It comes from `cache.nixos.org`, so it carries that cache's
signature:

```bash
P=github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808
H=$(nix build "$P#hello" --no-link --print-out-paths)
echo "$H"
nix path-info --sigs "$H"
```

```text expect
hello-2.12.3
cache.nixos.org-1:
```

The narinfo is a plain text file at `https://cache.nixos.org/<hash part>.narinfo`. The hash part
is the 32 characters after `/nix/store/`:

```bash
hashpart=$(basename "$H" | cut -c1-32)
curl -fsS "https://cache.nixos.org/$hashpart.narinfo"
echo ---
curl -fsS https://cache.nixos.org/nix-cache-info
```

```text expect
StorePath: /nix/store/
URL: nar/
NarHash: sha256:
References:
Sig: cache.nixos.org-1:
StoreDir: /nix/store
Priority: 40
```

`nix store verify` checks a path's contents against its `NarHash`, and its signatures against
your `trusted-public-keys`. `--sigs-needed 1` asks for at least one valid signature:

```bash
nix store verify --sigs-needed 1 "$H" && echo "hello: contents and signature OK"
```

```text expect
hello: contents and signature OK
```

## A path you built has no signature, and doesn't need one

Build something that no cache has:

```bash
git init -q
```

```nix file=flake.nix
{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { nixpkgs, ... }:
    let
      pkgs = nixpkgs.legacyPackages.x86_64-linux;
    in
    {
      packages.x86_64-linux.default = pkgs.runCommand "cache-lesson-note" { } ''
        echo "built on this machine, for lesson 05.2" > $out
      '';
    };
}
```

```bash
git add flake.nix
L=$(nix build --no-link --print-out-paths)
nix path-info --sigs "$L"
nix store verify "$L" && echo "local build: trusted because the daemon built it"
```

```text expect
cache-lesson-note
local build: trusted because the daemon built it
```

The daemon marks paths it builds as *ultimately trusted*, so they need no signature. Ask for a
signature anyway and verification fails:

```bash fails
nix store verify --sigs-needed 1 "$L"
```

```text expect
is untrusted
```

## Your own key and your own cache

A key pair is two short text files. The name before the colon identifies the key in `Sig:`
lines. Convention: `<host or org>-<number>`, so you can rotate to `-2` later.

```bash
nix key generate-secret --key-name lesson-cache-1 > key.sec
nix key convert-secret-to-public < key.sec > key.pub
cat key.pub
```

```text expect
lesson-cache-1:
```

`key.sec` can sign anything as `lesson-cache-1`. Treat it like an SSH private key: mode 600, never
in git, and in CI keep it in a secret store.

Now copy the path to a binary cache in a directory. `file://` makes it a *binary cache*. A bare
path would mean a chroot store, a different thing. The store URL parameter `secret-key` makes the
cache sign each path as it is uploaded (Nix manual: *Local Binary Cache Store* → `secret-key`):

```bash
chmod 600 key.sec
nix copy --to "file://$PWD/cache?secret-key=$PWD/key.sec" "$L"
ls cache
cat cache/nix-cache-info
cat "cache/$(basename "$L" | cut -c1-32).narinfo"
```

```text expect
nar
nix-cache-info
StoreDir: /nix/store
StorePath: /nix/store/
Compression: xz
Sig: lesson-cache-1:
```

That is a complete binary cache. Serve the directory over HTTP (any static web server, or an S3
bucket) and other machines can substitute from it.

## Trust is checked by whoever writes the store

`nix store verify --store file://…` opens the cache *in your own process*. Your own
settings apply, so you can pass the key on the command line:

```bash
nix store verify --store "file://$PWD/cache" --trusted-public-keys "$(cat key.pub)" "$L" \
  && echo "cache copy verified with lesson-cache-1"
```

```text expect
cache copy verified with lesson-cache-1
```

Without the key, the same cache entry is untrusted:

```bash fails
nix store verify --store "file://$PWD/cache" "$L"
```

```text expect
is untrusted
```

The daemon is different. It runs as root and protects a store that every user shares. If any
user could add a trusted key, any user could put a fake `bash` into `/nix/store` for everyone.
So the daemon ignores restricted settings sent by clients that aren't in `trusted-users`. It
also says so:

```bash
nix store info --trusted-public-keys "$(cat key.pub)" 2>&1
```

```text expect
ignoring the client-specified setting 'trusted-public-keys'
```

(If you have put yourself in `trusted-users`, you won't see this warning. That is exactly the
point: a trusted user can make the daemon accept any key.)

To make the daemon trust a cache there are three tools, from narrowest to broadest:

| Setting in `/etc/nix/nix.conf` | Effect |
|---|---|
| `extra-trusted-public-keys = name:KEY` | The daemon accepts paths signed by this key, from any source. |
| `extra-trusted-substituters = URL` | Normal users may *enable* this cache per command (`--extra-substituters URL`). It is not used otherwise. |
| `trusted-users = root @wheel you` | These users can set *any* setting through the daemon, including keys, substituters and `require-sigs = false`. This is root-equivalent: such a user can put arbitrary contents into store paths that root's programs will run. |

Flakes can carry `nixConfig.extra-substituters` and `extra-trusted-public-keys`. Nix asks before
applying them (unless `accept-flake-config = true`), and even then they are only client-side
settings: the daemon still ignores the restricted ones from users who aren't trusted.

Project 05a uses the first two rows to substitute from your own cache, and shows unsigned and
forged paths being rejected.

## Your turn

Sign a second, different path with a **second** key, `lesson-cache-2`, push it to the same cache,
and show that `nix store verify` on the cache accepts it when you trust both keys
(`--trusted-public-keys` takes a space-separated list), but rejects it when you trust only
`lesson-cache-1`.

<details><summary>Solution</summary>

`runCommand` in an inline expression gives a second, different path without editing the flake.
`--impure` relaxes pure evaluation for the `--expr`.

```bash
nix key generate-secret --key-name lesson-cache-2 > key2.sec
chmod 600 key2.sec
nix key convert-secret-to-public < key2.sec > key2.pub
L2=$(nix build --impure --no-link --print-out-paths --expr '
  (builtins.getFlake "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808")
    .legacyPackages.x86_64-linux.runCommand "cache-lesson-note-2" { } "echo two > $out"')
nix copy --to "file://$PWD/cache?secret-key=$PWD/key2.sec" "$L2"
nix store verify --store "file://$PWD/cache" \
  --trusted-public-keys "$(cat key.pub) $(cat key2.pub)" "$L" "$L2" && echo "both verified"
```

```text expect
both verified
```

```bash fails
nix store verify --store "file://$PWD/cache" --trusted-public-keys "$(cat key.pub)" "$L2"
```

```text expect
is untrusted
```
</details>

## Check yourself

<details><summary>A narinfo's <code>Sig:</code> covers which fields, and why not the NAR file itself?</summary>

The store path, `NarHash`, `NarSize` and `References` (the "fingerprint", see
`ValidPathInfo::fingerprint` in Nix's `libstore`). The NAR is covered indirectly: after
downloading, Nix hashes the NAR and compares it with the signed `NarHash`. This is why the
compressed file's name and compression can change without re-signing.
</details>

<details><summary>Why are paths built by the daemon trusted without a signature, but paths you <code>nix copy</code> in are not?</summary>

The daemon ran the build itself, so it knows the output came from the derivation (it marks
the path *ultimate*). A copied path's contents came from somewhere else. Only a trusted
signature, or content addressing, links those contents to the store path's name.
</details>

<details><summary>Your colleague suggests "just add me to <code>trusted-users</code> so I can use our cache". What do you suggest instead, and why?</summary>

Add the cache's public key to `trusted-public-keys` (and the URL to `substituters`, or to
`trusted-substituters` so people opt in). That trusts one key for one purpose. `trusted-users`
lets that person disable signature checks or add any key, which is effectively root on the
machine.
</details>
