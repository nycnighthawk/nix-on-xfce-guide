# Lesson 04.2 — Pinning strategies

**You will:** compare branch, tag and commit pins; inspect a lock with `nix flake metadata`;
see what `nix flake update <input>` does and does not do; move a pin deliberately; try a
version temporarily with `--override-input`; and see why `nixpkgs#…` on the command line is
not pinned.

## Ways to name nixpkgs

| `inputs.nixpkgs.url` | Pins | Moves when |
|---|---|---|
| `github:NixOS/nixpkgs/nixos-26.05` | a **branch** (channel) | you run `nix flake update nixpkgs` |
| `github:NixOS/nixpkgs/nixos-unstable` | a fast-moving branch | same — and much more changes each time |
| `github:NixOS/nixpkgs/26.05` | a **tag** (the release branch-off point) | never (tags can in principle be moved upstream) |
| `github:NixOS/nixpkgs/fa1373130d5a…` | a **commit** | only when you edit the URL |
| `nixpkgs` (no URL) | whatever the **registry** says | every time the registry changes — avoid in `flake.nix` |

In every case except the last, the **lock file** holds the exact commit you get. The URL
only decides what "update" means.

- **Branch pins** (`nixos-26.05`) are the common choice for applications and systems: you
  get security fixes when *you* decide to update, and the lock says exactly what you have.
  Use the `nixos-*` / `nixpkgs-*` channel branches, not `release-26.05`: channel branches only
  advance after Hydra has built and tested a commit, so everything is in the cache.
- **Commit pins** make the URL itself exact. This path uses them so that every learner's
  lock file is identical. The cost: updating means editing `flake.nix`.

Source: Nix manual, *Flake references* (`nix3-flake`), and the nixpkgs README on channel
branches.

## Set up a flake

```nix file=flake.nix
{
  description = "Which nixpkgs am I using?";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { self, nixpkgs }:
    {
      packages.x86_64-linux.hello = nixpkgs.legacyPackages.x86_64-linux.hello;

      # Inputs carry metadata about what was fetched.
      lib = {
        release = nixpkgs.lib.trivial.release;
        rev = nixpkgs.rev;
        lastModifiedDate = nixpkgs.lastModifiedDate;
      };
    };
}
```

```text file=.gitignore
result
result-*
```

```bash
git init -q
git config user.name "Nix Learner"
git config user.email "learner@example.com"
git add -A
nix flake lock
git add flake.lock
git commit -qm "Pin nixpkgs 26.05"
nix eval --raw .#lib.release; echo
```

```text expect
26.05
```

## Inspect the lock

`nix flake metadata` prints what a flake *resolved* to: its own revision (or "dirty"), and
the tree of locked inputs.

```bash
nix flake metadata
```

```text expect
fa1373130d5a21c040a47c5dbe1913d59ed91808
```

For scripts, ask for JSON. The `locks` field is the lock file; `jq` (run from the pinned
nixpkgs, without installing it) picks fields out:

```bash
jq() { nix run github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808#jq -- "$@"; }
nix flake metadata --json | jq -r '.locks.nodes.nixpkgs.locked.rev'
ts=$(jq -r '.nodes.nixpkgs.locked.lastModified' flake.lock)
echo "nixpkgs commit date: $(date -u -d "@$ts" +%Y-%m-%d)"
nix eval --raw .#lib.lastModifiedDate; echo
```

```text expect
fa1373130d5a21c040a47c5dbe1913d59ed91808
nixpkgs commit date:
```

`jq` is a shell function now, for the rest of this lesson. `lastModified` is the commit
time; `lastModifiedDate` is the same as `YYYYMMDDHHMMSS`, which nixpkgs uses for its version
suffix (`26.05.20261020.fa13731`).

## `nix flake update` on a commit pin

`nix flake update <input>` re-resolves the *URL* of that input and writes the result to the
lock. Without an argument it updates every input — rarely what you want in one commit.

```bash
nix flake update nixpkgs
git diff --exit-code flake.lock && echo "lock unchanged"
```

```text expect
lock unchanged
```

Nothing to do: the URL names a commit, and it still resolves to that commit. With a branch
URL, the same command would move the lock to the branch's current tip. (Older Nix had
`nix flake lock --update-input nixpkgs`; current Nix uses `nix flake update nixpkgs`.)

## Moving a commit pin

To update a commit pin, edit the URL, then let Nix lock it. Here we "update" to 25.11 —
any commit works the same way:

```bash
sed -i 's/fa1373130d5a21c040a47c5dbe1913d59ed91808/b6018f87da91d19d0ab4cf979885689b469cdd41/' flake.nix
nix flake lock
```

```text expect
Updated input 'nixpkgs'
```

```bash
jq -r '.nodes.nixpkgs.locked.rev' flake.lock
nix eval --raw .#lib.release; echo
git diff --stat
```

```text expect
b6018f87da91d19d0ab4cf979885689b469cdd41
25.11
flake.lock
flake.nix
```

`flake.nix` and `flake.lock` change together, in one commit, with a message that says what
moved:

```bash
git commit -qam "nixpkgs: 26.05 -> 25.11 (b6018f87)"
git log --oneline
```

## Trying a version without committing to it

`--override-input` swaps an input for one command. Nix computes the changed lock, uses it,
and does not write it ("not writing modified lock file"). Handy for "does my project build
against unstable?":

```bash
nix eval --raw --override-input nixpkgs github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808 .#lib.release; echo
git diff --quiet flake.lock && echo "lock unchanged"
```

```text expect
26.05
lock unchanged
```

`nix flake lock --override-input nixpkgs <ref>`, by contrast, writes the override into the
lock — a way to pin an input without editing `flake.nix`, at the price of the lock and the
URL disagreeing.

## The registry: why `nixpkgs#hello` is not pinned

On the command line, `nixpkgs#hello` (as in course 00) uses an **indirect** flake
reference: Nix looks up `nixpkgs` in the *flake registry* — a user registry, a system one,
and a global list downloaded from `channels.nixos.org`:

```bash
nix registry list | grep 'flake:nixpkgs '
```

```text expect
flake:nixpkgs
```

The global entry points at `nixpkgs-unstable`, so `nix run nixpkgs#hello` today and next
month can give different hellos. That is fine for trying things, never for a project. In a
`flake.nix`, always write the full URL. To make the command line follow your project, you
can pin the registry entry — this edits `~/.config/nix/registry.json`, so it is shown, not
run:

```console
$ nix registry pin nixpkgs github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808
$ nix registry remove nixpkgs     # undo
```

Or use your project's pin directly: `nix shell --inputs-from . nixpkgs#jq` resolves
`nixpkgs` from the current flake's lock file.

```bash
nix shell --inputs-from . nixpkgs#hello -c hello --version | head -n 1
```

```text expect
hello (GNU Hello)
```

(That is 25.11's hello — the lock now pins 25.11.)

## Exercise: what am I running?

Write a small script `pins.sh` that prints, for **every** input in `flake.lock` (not only
nixpkgs), one line: the input name, the locked revision, and the commit date as
`YYYY-MM-DD`. Use `jq` on `flake.lock`.

<details><summary>Solution</summary>

Every node except `root` is an input; `locked.rev` and `locked.lastModified` exist for
GitHub inputs. `todate` turns a Unix time into ISO 8601.

```bash file=pins.sh
#!/usr/bin/env bash
set -euo pipefail
nix run github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808#jq -- -r '
  .nodes | to_entries[] | select(.key != "root")
  | "\(.key) \(.value.locked.rev // "-") \(.value.locked.lastModified | todate | .[0:10])"
' flake.lock
```

```bash
bash pins.sh
```

```text expect
nixpkgs b6018f87da91d19d0ab4cf979885689b469cdd41 20
```

</details>

## Check yourself

<details><summary>Your <code>flake.nix</code> uses <code>nixos-26.05</code>. A colleague clones the repo a month later and runs <code>nix build</code>. Do you build the same thing?</summary>

Yes, as long as `flake.lock` is committed: the lock pins the exact commit and `narHash`,
and `nix build` uses it without updating. Only `nix flake update` (or a missing lock) moves
it.

</details>

<details><summary>Why does nixpkgs recommend the <code>nixos-*</code> branches over <code>release-*</code> for pins?</summary>

`nixos-26.05` only advances to a commit after Hydra has built and tested it, so its
packages are in the binary cache and its tests passed. `release-26.05` is where changes
land first; a pin there may need large local builds or hit breakage.

</details>

<details><summary>What is the difference between <code>nix flake update nixpkgs</code> and editing the commit in the URL?</summary>

`nix flake update` re-resolves the URL that is already there; it can only move a *branch*
(or tag) pin. A commit URL always resolves to itself, so to change it you edit the URL and
run `nix flake lock`, which locks inputs whose URL changed and leaves the others alone.

</details>
