# Lesson 00.1 — Install Nix on Xubuntu and verify it

**You will:** install Nix in multi-user (daemon) mode, check you have a safe version, and turn
on the two experimental features the rest of the path uses.

> Every grey `bash` block in this path is executed by CI on a fresh Xubuntu 26.04 machine, in
> order, in one terminal. If you type them in order, you will get the same results.

## Prerequisites

Nix's installer needs `curl` and `xz`; later courses use `git`.

```bash
sudo apt-get update -qq
sudo apt-get install -y -qq curl xz-utils git
```

## Install

The official installer sets up `/nix`, a `nix-daemon` systemd service and a group of build
users (`nixbld1…32`) so builds never run as you. `--yes` accepts its prompts; leave it off to
review each one.

```bash timeout=1800
curl --proto '=https' --tlsv1.2 -sSfL https://nixos.org/nix/install -o nix-install.sh
sh nix-install.sh --daemon --yes
```

The installer hooks Nix into new shells via `/etc/bash.bashrc` and `/etc/profile.d/nix.sh`.
**Open a new terminal** — or load it into this one:

```bash
. /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh
nix --version
```

```text expect
nix (Nix) 2.35
```

## Check the version is safe

Nix releases before **2.35.3** contain security bugs fixed in October 2026. This expression asks
Nix to compare its own version:

```bash
nix-instantiate --eval --expr 'builtins.compareVersions builtins.nixVersion "2.35.3" >= 0'
```

```text expect
true
```

## Turn on flakes and the `nix` command

Both are still officially *experimental* (so they can still change), but they are used almost
universally. This path uses them from course 04 on, and the `nix` command from the start.

```bash
sudo tee -a /etc/nix/nix.conf > /dev/null <<'EOF'
experimental-features = nix-command flakes
max-jobs = auto
EOF
sudo systemctl restart nix-daemon
nix config show experimental-features
```

```text expect
flakes
nix-command
```

## Smoke test

Fetch and run a program without installing it. It comes pre-built from `cache.nixos.org`:

```bash
nix run nixpkgs#hello
```

```text expect
Hello, world!
```

**Check yourself:** where did `hello` come from, and where is it now? (Answer: downloaded
into `/nix/store`; nothing outside `/nix` changed. Lesson 00.2 shows how to see it.)
