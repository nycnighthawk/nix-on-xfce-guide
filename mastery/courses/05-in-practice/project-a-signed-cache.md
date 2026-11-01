# Project 05a — Signed cache round trip

**Goal:** run your own binary cache end to end. Build three store paths, sign one properly,
leave one unsigned and sign one with a forged key. Push all three to a cache in a directory,
delete them from your store, and get them back. Your daemon must accept exactly the
properly signed one, both by `nix copy` and by ordinary substitution during `nix build`.

**You will practise:**

- **cache keys as trust**: a signature is only worth something if the *daemon* trusts the key;
- **trust-on-configuration**: `trusted-public-keys` and `trusted-substituters` as the narrow
  alternatives to `trusted-users`;
- **proving a negative**: `--max-jobs 0` to prove a path was substituted, not rebuilt.

> This project changes `/etc/nix/nix.conf` (two marked blocks) and restarts the daemon. The last
> step removes the blocks again. If you stop halfway, run the clean-up step yourself.

## 1. Three unique paths

Each path's contents include a random nonce, so the paths exist nowhere else. You are
going to delete them from your store, and the paths must not be in `cache.nixos.org` or in use
by anything else.

These are `runCommand` derivations on purpose. `writeText` and `runCommandLocal` set
`allowSubstitutes = false` (see `pkgs/build-support/trivial-builders/default.nix`), so Nix would
never substitute them, and step 7 needs substitution.

```bash
git init -q
printf '%s' "$(date +%s%N)-$RANDOM" > nonce.txt
```

```nix file=flake.nix
{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { nixpkgs, ... }:
    let
      pkgs = nixpkgs.legacyPackages.x86_64-linux;
      nonce = builtins.readFile ./nonce.txt;
      note =
        name: text:
        pkgs.runCommand name { } ''
          echo ${pkgs.lib.escapeShellArg "${text} (nonce ${nonce})"} > $out
        '';
    in
    {
      packages.x86_64-linux = {
        good = note "cache-demo-good" "signed with the real key";
        unsigned = note "cache-demo-unsigned" "never signed";
        forged = note "cache-demo-forged" "signed with an impostor key";
      };
    };
}
```

```bash
git add flake.nix nonce.txt
G=$(nix build .#good --no-link --print-out-paths)
U=$(nix build .#unsigned --no-link --print-out-paths)
F=$(nix build .#forged --no-link --print-out-paths)
printf '%s\n' "$G" "$U" "$F" | tee paths.txt
cat "$G"
```

```text expect
cache-demo-good
cache-demo-unsigned
cache-demo-forged
signed with the real key
```

`--no-link` matters. A `result` symlink would be a GC root, and step 4 has to delete these paths.

## 2. Keys: a real one and an impostor

The impostor uses the **same key name**. A signature only says which key name signed it.
Anyone can pick any name, so only the public key decides whether a signature is accepted.

```bash
nix key generate-secret --key-name demo-cache-1 > key.sec
nix key convert-secret-to-public < key.sec > key.pub
nix key generate-secret --key-name demo-cache-1 > evil.sec
chmod 600 key.sec evil.sec
cat key.pub
```

```text expect
demo-cache-1:
```

## 3. Sign, then push

`nix store sign` adds signatures to paths **in your store**. They are recorded in the daemon's
database next to the path, and `nix copy` carries them along.

```bash
nix store sign --key-file key.sec "$G"
nix store sign --key-file evil.sec "$F"
nix path-info --sigs "$G" "$U" "$F"
```

```text expect
added 1 signatures
demo-cache-1:
```

Push all three into a fresh binary cache (`file://` means binary cache, see lesson 05.2):

```bash
nix copy --to "file://$PWD/cache" "$G" "$U" "$F"
ls cache
for p in "$G" "$U" "$F"; do
  ni="cache/$(basename "$p" | cut -c1-32).narinfo"
  grep '^StorePath:' "$ni"
  grep '^Sig:' "$ni" || echo "(no Sig line)"
done
```

```text expect
nix-cache-info
Sig: demo-cache-1:
(no Sig line)
```

Before involving the daemon, check the cache with your own process (client-side settings apply
here). Only `good` verifies with the real public key:

```bash
nix store verify --store "file://$PWD/cache" --trusted-public-keys "$(cat key.pub)" "$G" \
  && echo "good: verified against key.pub"
```

```text expect
good: verified against key.pub
```

```bash fails
nix store verify --store "file://$PWD/cache" --trusted-public-keys "$(cat key.pub)" "$U" "$F"
```

```text expect
is untrusted
```

## 4. Delete the paths from your store

`nix store delete` only deletes paths that are not *alive*, which means not reachable from any GC
root. Nothing references these three:

```bash
nix store delete "$G" "$U" "$F"
```

```text expect
3 store paths deleted
```

```bash fails
nix path-info "$G"
```

```text expect
is not valid
```

## 5. The daemon refuses a key it doesn't trust

Copy `good` back from the cache. The daemon checks the signature against **its**
`trusted-public-keys`. `demo-cache-1` isn't one of them yet:

```bash fails
nix copy --from "file://$PWD/cache" "$G"
```

```text expect
lacks a signature by a trusted key
```

`nix copy` has `--no-check-sigs`. For a normal user the daemon ignores it. It turns
`dontCheckSigs` back off for untrusted clients (`src/libstore/daemon.cc` in Nix 2.35, operation
`AddToStoreNar`). Try it:

```bash fails
nix copy --no-check-sigs --from "file://$PWD/cache" "$G"
```

```text expect
lacks a signature by a trusted key
```

## 6. Trust the key, system-wide, and nothing more

Add the public key to the daemon's configuration and restart it. The `# BEGIN`/`# END` lines
let step 9 remove exactly this block.

```bash
sudo tee -a /etc/nix/nix.conf > /dev/null <<EOF
# BEGIN mastery-05a
extra-trusted-public-keys = $(cat key.pub)
# END mastery-05a
EOF
sudo systemctl restart nix-daemon
nix config show trusted-public-keys
```

```text expect
cache.nixos.org-1:
demo-cache-1:
```

Now the round trip works for `good`, and **only** for `good`:

```bash
nix copy --from "file://$PWD/cache" "$G"
cat "$G"
nix path-info --sigs "$G"
```

```text expect
signed with the real key
demo-cache-1:
```

```bash fails
nix copy --from "file://$PWD/cache" "$U"
```

```text expect
lacks a signature by a trusted key
```

The forged path has a `demo-cache-1:` signature, but it doesn't verify with the trusted key:

```bash fails
nix copy --from "file://$PWD/cache" "$F"
```

```text expect
lacks a signature by a trusted key
```

## 7. Substitution during a build

`nix copy` is explicit. In daily use, paths arrive by **substitution**: `nix build` asks the
daemon to realise a derivation, and the daemon looks in its `substituters` before building.
Delete `good` again and prove that, without your cache, it can only be *built*. `--max-jobs 0`
forbids local builds, so the command fails:

```bash
nix store delete "$G"
```

```bash fails
nix build .#good --no-link --max-jobs 0
```

```text expect
local builds are disabled (max-jobs = 0)
```

Normal users may pass `--extra-substituters`, but the daemon uses a URL from a normal user only
if the URL is listed in `trusted-substituters`. Otherwise it warns and ignores it:

```bash fails
nix build .#good --no-link --max-jobs 0 --extra-substituters "file://$PWD/cache"
```

```text expect
ignoring untrusted substituter 'file://
```

List the cache as a trusted substituter. This doesn't turn it on for anyone. It only allows users
to turn it on:

```bash
sudo tee -a /etc/nix/nix.conf > /dev/null <<EOF
# BEGIN mastery-05a
extra-trusted-substituters = file://$PWD/cache
# END mastery-05a
EOF
sudo systemctl restart nix-daemon
nix build .#good --no-link --print-out-paths --max-jobs 0 --extra-substituters "file://$PWD/cache"
cat "$G"
```

```text expect
from 'file://
signed with the real key
```

`--max-jobs 0` guarantees nothing was built. The "copying path … from 'file://…'" line shows
where it came from.

## 8. Verify

The whole round trip, as one check:

```bash
nix path-info --sigs "$G" | grep -q 'demo-cache-1:' && echo "good is back, with its signature"
nix path-info "$U" 2>/dev/null || echo "unsigned stayed out"
nix path-info "$F" 2>/dev/null || echo "forged stayed out"
```

```text expect
good is back, with its signature
unsigned stayed out
forged stayed out
```

## 9. Clean up

Remove both marked blocks and restart the daemon, so your machine trusts only
`cache.nixos.org` again:

```bash
sudo sed -i '/^# BEGIN mastery-05a$/,/^# END mastery-05a$/d' /etc/nix/nix.conf
sudo systemctl restart nix-daemon
nix config show trusted-public-keys
grep -c mastery-05a /etc/nix/nix.conf || echo "nix.conf is back to normal"
```

```text expect
cache.nixos.org-1:
nix.conf is back to normal
```

## What about `trusted-users`?

The other way to make step 5 work is `trusted-users = root tester` in `nix.conf`. Then the daemon
accepts *your* `--extra-trusted-public-keys`, `--extra-substituters`, `--no-check-sigs` and even
`--option require-sigs false`. That is convenient on a single-user laptop. On a shared machine it
means "this user can put anything into store paths that root and every other user will run",
which is root access. The Nix manual says so in the `trusted-users` entry. Prefer the narrow
settings you used here.

## Stretch goals

1. **Sign on upload instead.** Skip `nix store sign`, and push with
   `nix copy --to "file://$PWD/cache2?secret-key=$PWD/key.sec"` (lesson 05.2). When is each
   approach better? (Hint: who holds the key, the builder or the uploader?)
2. **Sign everything you build.** `secret-key-files = /etc/nix/key.sec` in `nix.conf` makes the
   daemon sign every path it builds. Why is this a setting for build *servers* and not laptops?
3. **Serve it over HTTP.** `python3 -m http.server -d cache 8080` and use
   `http://localhost:8080` as the substituter. Watch `nix build -v` query `nix-cache-info` and the
   narinfo.
4. **Rotate keys.** Generate `demo-cache-2`, re-sign `good` with it, trust both keys, then remove
   `demo-cache-1`. Which paths are still accepted?
5. **Read the code.** In Nix 2.35, follow `LocalStore::addToStore` → `pathInfoIsUntrusted` in
   `src/libstore/local-store.cc` and find the exact condition that rejected `unsigned`.
