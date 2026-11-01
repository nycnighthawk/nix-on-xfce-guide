# Project 04b — Lock hygiene

**Goal:** take a flake with a duplicated nixpkgs, clean it up with `follows`, update one
input on its own, inspect exactly what the update changed, make CI refuse an un-locked
change, then roll the update back with Git and prove the old build comes back — the same
store path, without rebuilding.

**You will practise:**

- **The lock file is the version** — every step is a small, reviewable change to
  `flake.lock`, committed like code.
- **`follows`** — one nixpkgs for the whole dependency tree.
- **Update one thing at a time** — move one pin, `nix flake lock`, nothing else moves.
- **Inspect, don't guess** — `nix flake metadata`, `jq` on the lock, `git diff`.
- **Rollback is a revert** — the old lock gives the old derivations, which are still in the
  store.

## Setup: a project with a helper flake

A helper flake (a subdirectory, as in a monorepo) brings its own nixpkgs, 26.05, and builds
a tiny tool that reports which nixpkgs built it:

```nix file=tools/flake.nix
{
  description = "Helper tools, with their own nixpkgs pin";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { self, nixpkgs }:
    let
      pkgs = nixpkgs.legacyPackages.x86_64-linux;
    in
    {
      packages.x86_64-linux.default = pkgs.writeShellScriptBin "which-nixpkgs" ''
        echo "built with nixpkgs ${nixpkgs.lib.trivial.release}"
      '';
    };
}
```

The main project is pinned to the older 25.11 — the update you are about to make:

```nix file=flake.nix
{
  description = "Lock hygiene";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/b6018f87da91d19d0ab4cf979885689b469cdd41";
    tools.url = "path:./tools";
  };

  outputs =
    {
      self,
      nixpkgs,
      tools,
    }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      packages.${system} = {
        default = pkgs.hello;
        which-nixpkgs = tools.packages.${system}.default;
      };
    };
}
```

```text file=.gitignore
result
result-*
```

```bash timeout=1800
git init -q
git config user.name "Nix Learner"
git config user.email "learner@example.com"
git add -A
nix flake lock
git add flake.lock
git commit -qm "Initial project"
jq() { nix run github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808#jq -- "$@"; }
jq -r '.nodes | keys | join(" ")' flake.lock
nix run .#which-nixpkgs
```

```text expect
nixpkgs nixpkgs_2 root tools
built with nixpkgs 26.05
```

Two nixpkgs in the lock, and the tool is built from a different one than the project. `jq`
is a shell function (pinned, nothing installed) for the rest of this project.

## Step 1 — add `follows`

```nix file=flake.nix
{
  description = "Lock hygiene";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/b6018f87da91d19d0ab4cf979885689b469cdd41";
    tools = {
      url = "path:./tools";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      tools,
    }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      packages.${system} = {
        default = pkgs.hello;
        which-nixpkgs = tools.packages.${system}.default;
      };
    };
}
```

```bash
nix flake lock
jq -r '.nodes | keys | join(" ")' flake.lock
jq -c '.nodes.tools.inputs' flake.lock
nix run .#which-nixpkgs
```

```text expect
nixpkgs root tools
{"nixpkgs":["nixpkgs"]}
built with nixpkgs 25.11
```

`nixpkgs_2` is gone from the lock, and the tool is now built from the project's nixpkgs.
Commit it as its own change, and record what the project builds at this point:

```bash timeout=1800
git commit -qam "tools: follow nixpkgs"
before_hello=$(nix build --no-link --print-out-paths .#default)
before_tool=$(nix build --no-link --print-out-paths .#which-nixpkgs)
"$before_hello/bin/hello" --version | head -n 1
```

```text expect
hello (GNU Hello)
```

## Step 2 — update one input

Move the nixpkgs pin to 26.05 by editing its commit, and lock. Only inputs whose URL
changed are re-locked (`nix flake lock` never updates anything else):

```bash
sed -i 's/b6018f87da91d19d0ab4cf979885689b469cdd41/fa1373130d5a21c040a47c5dbe1913d59ed91808/' flake.nix
nix flake lock
```

```text expect
Updated input 'nixpkgs'
```

Inspect what changed — the lock diff is the review:

```bash
git diff --stat
git diff flake.lock
echo "old: $(git show HEAD:flake.lock | jq -r '.nodes.nixpkgs.locked.rev')"
echo "new: $(jq -r '.nodes.nixpkgs.locked.rev' flake.lock)"
nix flake metadata --json | jq '.locks.nodes.nixpkgs.locked | {rev, lastModified, narHash}'
```

```text expect
flake.lock
flake.nix
old: b6018f87da91d19d0ab4cf979885689b469cdd41
new: fa1373130d5a21c040a47c5dbe1913d59ed91808
"rev": "fa1373130d5a21c040a47c5dbe1913d59ed91808"
```

Only the `nixpkgs` node changed: `rev`, `lastModified`, `narHash`. The `tools` node is the
same; through `follows`, the tool now gets the new nixpkgs automatically. Build, check,
commit:

```bash timeout=1800
after_hello=$(nix build --no-link --print-out-paths .#default)
"$after_hello/bin/hello" --version | head -n 1
nix run .#which-nixpkgs
[ "$after_hello" != "$before_hello" ] && echo "hello changed"
git commit -qam "nixpkgs: 25.11 -> 26.05 (fa137313)"
git log --oneline
```

```text expect
hello (GNU Hello) 2.12.3
built with nixpkgs 26.05
hello changed
nixpkgs: 25.11 -> 26.05
tools: follow nixpkgs
Initial project
```

With a branch pin (`nixos-26.05`) step 2 would be one command, `nix flake update nixpkgs`,
and the same inspection.

## Step 3 — make CI refuse an unlocked change

Someone edits an input URL and forgets to commit the new lock. Locally, Nix would quietly
re-lock. In CI you want a hard failure: `--no-update-lock-file`.

```bash
sed -i 's/fa1373130d5a21c040a47c5dbe1913d59ed91808/b6018f87da91d19d0ab4cf979885689b469cdd41/' flake.nix
```

```bash fails
nix build --no-update-lock-file .#default
```

```text expect
--no-update-lock-file
```

```bash
git checkout -- flake.nix flake.lock
git status --short
```

Use `--no-update-lock-file` (or `nix flake lock --no-update-lock-file` as a pre-commit
check) wherever a build must match the committed lock exactly.

## Step 4 — roll back

The update broke something in production (pretend). Revert the commit:

```bash
git revert --no-edit HEAD
git log --oneline | head -n 1
jq -r '.nodes.nixpkgs.locked.rev' flake.lock
```

```text expect
Revert
b6018f87da91d19d0ab4cf979885689b469cdd41
```

## Verification

**The rollback rebuilds the old result exactly** — the same store paths as before the
update. Nothing compiles or downloads: those paths are still in the store (until garbage
collection — pin them with `--out-link` or a profile if they matter):

```bash
rolled_hello=$(nix build --no-link --print-out-paths .#default)
rolled_tool=$(nix build --no-link --print-out-paths .#which-nixpkgs)
echo "before:      $before_hello"
echo "rolled back: $rolled_hello"
[ "$rolled_hello" = "$before_hello" ] && echo "hello: identical"
[ "$rolled_tool" = "$before_tool" ] && echo "tool: identical"
nix run .#which-nixpkgs
```

```text expect
hello: identical
tool: identical
built with nixpkgs 25.11
```

**The history tells the whole story**, one reviewable change per commit:

```bash
git log --oneline --stat | grep -E 'flake\.(nix|lock)|^[0-9a-f]+ '
```

## Stretch goals

1. **Diff locks like a reviewer.** Write a script that compares `git show HEAD~1:flake.lock`
   with `flake.lock` and prints one line per changed input: name, old rev → new rev, old date →
   new date. (Tools such as `nvd` / `nix store diff-closures` go further and diff the
   *closures*: try `nix store diff-closures $before_hello $after_hello`.)
2. **Protect the rollback target.** Run `nix-collect-garbage` and repeat step 4. Is the old
   build still there? Fix it with `nix build .#default --out-link gcroots/before` *before*
   updating, and explain why that works (course 01, GC roots).
3. **A follows chain.** Give `tools` its own input that also has a `nixpkgs` input, and make
   it follow the root's with `inputs.tools.inputs.other.inputs.nixpkgs.follows = "nixpkgs";`.
   Read the resulting path in `flake.lock`.
4. **Automated updates.** Look at how projects automate step 2 in CI (for example the
   `DeterminateSystems/update-flake-lock` GitHub Action): what does it commit, and what do
   your checks have to cover so that you can merge its pull requests with confidence?

## Check yourself

<details><summary>After step 2, why did the <code>tools</code> node in <code>flake.lock</code> not change?</summary>

Its own entry did not change: its URL is the same path and its `nixpkgs` input is a
`follows` (`["nixpkgs"]`), a reference to the root's input rather than a pinned node. The
root's `nixpkgs` changed, and `tools` sees that through the reference.

</details>

<details><summary>Why are the store paths after the rollback identical to the ones before the update?</summary>

The reverted lock pins the same nixpkgs `rev` and `narHash`, so evaluation produces the
same derivations, which have the same output paths — input addressing (course 01). Those
outputs were still in the store, so `nix build` had nothing to do.

</details>

<details><summary>What does <code>--no-update-lock-file</code> protect against that a committed lock alone does not?</summary>

A `flake.nix` edited without re-locking. Normally Nix notices the mismatch and silently
writes a new lock (and builds against it). With `--no-update-lock-file` it fails instead, so
a CI run can never build something other than what the committed lock says.

</details>
