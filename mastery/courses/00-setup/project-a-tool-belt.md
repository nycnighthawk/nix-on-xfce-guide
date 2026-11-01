# Project 00 — Throwaway tool belt

**Goal:** write a script that brings its own tools, pinned to an exact nixpkgs commit, so it
runs the same on any machine with Nix, with nothing installed beforehand.

**You'll practise:** ad-hoc environments; reproducible interpreted scripts (the `nix-shell`
shebang); pinning.

## 1. A report script that needs tools you don't have

The script below uses `jq` and `figlet`. Neither is installed on Xubuntu by default:

```bash
command -v jq figlet || echo "not installed"
```

```text expect
not installed
```

The first line runs the script with `nix-shell`. The second line tells `nix-shell` which
interpreter to use and which packages to provide, from an **exact nixpkgs commit**.
(`nix-shell` reads extra `#! nix-shell` lines as its arguments; see the Nix manual,
"nix-shell → Use as a #!-interpreter".)

```bash file=report.sh
#! /usr/bin/env nix-shell
#! nix-shell -i bash --pure -p jq figlet coreutils
#! nix-shell -I nixpkgs=https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz

# Inside, jq and figlet exist. --pure also removes everything else from PATH,
# so the script can't accidentally depend on tools from the host.
figlet -f small "report"
echo '{"tool":"jq","ok":true,"items":[3,1,2]}' | jq -c '{tool, sorted: (.items | sort)}'
command -v curl >/dev/null && echo "curl visible" || echo "host tools hidden by --pure"
```

```bash timeout=1200
chmod +x report.sh
./report.sh
```

```text expect
{"tool":"jq","sorted":[1,2,3]}
host tools hidden by --pure
```

Run it again. The second run is instant because everything is already in the store:

```bash
time ./report.sh > /dev/null
```

## 2. The same with the new CLI

The `nix` command has its own shebang support (`nix shell` reads `#! nix` lines). Flakes are
pinned by commit in the reference itself:

```bash file=report2.sh
#! /usr/bin/env nix
#! nix shell github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808#jq github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808#bash --command bash

echo '[5,4,6]' | jq -c 'sort'
```

```bash
chmod +x report2.sh
./report2.sh
```

```text expect
[4,5,6]
```

## 3. Verify: nothing was installed

```bash
command -v jq figlet || echo "still not installed"
ls ~/.nix-profile/bin 2>/dev/null | grep -E '^(jq|figlet)$' || echo "profile untouched"
```

```text expect
still not installed
profile untouched
```

## Stretch goals

- Write a Python script with a `nix-shell` shebang that uses `python3.withPackages (ps: [ ps.requests ])`.
  Hint: `#! nix-shell -i python3 -p "python3.withPackages (ps: [ ps.requests ])"`.
- Remove `--pure` and use `curl` without listing it. Why does that make the script less
  reproducible?
- Swap the pinned commit for `nixos-26.05` (a branch). What can change between two runs a month
  apart?
