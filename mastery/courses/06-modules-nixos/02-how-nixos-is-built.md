# Lesson 06.2 — How NixOS is built: from `nixosSystem` to `system.build.toplevel`

**You will:** read the few files that turn a NixOS configuration into a system, build the system
for a tiny machine on Xubuntu, take the result apart (`activate`, `etc/`, `sw/`, `init`), trace
two options to the files they produce, and make and roll back generations the way
`nixos-rebuild` does.

## The path through nixpkgs

Read these files alongside the lesson. All paths are in nixpkgs 26.05.

**1. `flake.nix` → `lib.nixosSystem`.** A thin wrapper. It calls `nixos/lib/eval-config.nix`
with your `modules`, sets `system = null` (so the platform must come from
`nixpkgs.hostPlatform`), and adds a module that records the flake's revision in the system label.

**2. `nixos/lib/eval-config.nix`.** Its own header comment says it should be "an extremely thin
wrapper around lib.evalModules", and it is. The interesting lines:

```nix
baseModules ? import ../modules/module-list.nix,   # ~2,000 NixOS modules
…
noUserModules = evalModulesMinimal {
  inherit prefix specialArgs;
  modules = baseModules ++ extraModules ++ [ pkgsModule modulesModule ];
};
nixosWithUserModules = noUserModules.extendModules { modules = allUserModules; };
```

So NixOS is *every* module in `module-list.nix` (each declares options and sets
`config = mkIf cfg.enable …`), plus `pkgsModule` (which sets `nixpkgs.system`), plus your
modules. It is evaluated with the same `evalModules` you used in lesson 06.1. `pkgs`, the
package set your modules receive, is itself built *inside* the module system, from the
`nixpkgs.*` options (`nixos/modules/misc/nixpkgs.nix`).

**3. `nixos/modules/system/activation/top-level.nix`.** Declares `system.build.toplevel`, the
derivation that *is* the system. Its builder is a short shell script, `systemBuilder`:

```nix
ln -s ${config.system.build.etc}/etc $out/etc
ln -s ${config.system.path} $out/sw
ln -s "$systemd" $out/systemd
echo -n "$nixosLabel" > $out/nixos-version
${config.system.systemBuilderCommands}     # other modules add their parts here
```

Then it checks `config.assertions` and `config.warnings` with `lib.asserts.checkAssertWarn`,
which is the mechanism you rebuilt in lesson 06.1. Other modules contribute through
`system.systemBuilderCommands`. For example `activatable-system.nix` copies in the `activate`
script, `switchable-system.nix` adds `bin/switch-to-configuration`, and the boot modules add
`kernel`, `initrd` and `init`.

**4. `nixos/modules/system/etc/etc.nix`.** Turns the option `environment.etc` (an `attrsOf`
submodule) into one derivation `etc` of symlinks, `system.build.etc`. For each entry with a
`text`, the `source` is derived: `source = mkDerivedConfig options.text (pkgs.writeText "etc-<name>")`.

**5. `nixos/modules/system/boot/systemd.nix` and `nixos/lib/systemd-lib.nix`.** Turn
`systemd.services.<name>` into unit files. They are linked in as
`environment.etc."systemd/system".source`, so units are just more `/etc` files.

Options go in. Store paths come out. The toplevel is a tree of symlinks to them.

## A tiny machine

```bash
git init -q
```

```nix file=configuration.nix
{ pkgs, ... }:
{
  nixpkgs.hostPlatform = "x86_64-linux";

  # What any NixOS system must decide: how it boots and what "/" is. This
  # machine is never installed on a disk, so: no boot loader, and a root file
  # system that only has to be described, not to exist.
  boot.loader.grub.enable = false;
  fileSystems."/" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "ext4";
  };

  networking.hostName = "box";

  # Two options whose results you will find in the built system.
  environment.etc."greeting.txt".text = "hello from box\n";

  systemd.services.greeter = {
    description = "Print the greeting once at boot";
    wantedBy = [ "multi-user.target" ];
    serviceConfig.Type = "oneshot";
    script = "cat /etc/greeting.txt";
  };

  # Don't build the NixOS manual for this demo; it is big and slow to build.
  documentation.nixos.enable = false;

  system.stateVersion = "26.05";
}
```

A second *generation* of the same machine adds one line to the greeting. Instead of copying
the configuration, the flake extends it. `extendModules` re-runs the same evaluation with one
more module (it is part of every `evalModules` result, see `lib/modules.nix`):

```nix file=v2.nix
{
  # environment.etc.<name>.text has type `nullOr lines`: definitions from
  # several modules are concatenated, not in conflict.
  environment.etc."greeting.txt".text = "second line, added in generation 2\n";
}
```

```nix file=flake.nix
{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { self, nixpkgs }:
    {
      nixosConfigurations.box = nixpkgs.lib.nixosSystem {
        modules = [ ./configuration.nix ];
      };

      nixosConfigurations.box-v2 = self.nixosConfigurations.box.extendModules {
        modules = [ ./v2.nix ];
      };
    };
}
```

```bash
git add configuration.nix v2.nix flake.nix
```

Before building, look at what you are about to build. It is an ordinary derivation, and NixOS is
an ordinary module evaluation:

```bash
nix eval --raw .#nixosConfigurations.box.config.system.build.toplevel.name; echo
n=$(nix eval .#nixosConfigurations.box._module.args.baseModules --apply builtins.length)
echo "NixOS base modules: $n"
[ "$n" -gt 1500 ] && echo "more than 1500 modules, all evaluated with lib.evalModules"
```

```text expect
nixos-system-box-26.05
more than 1500 modules, all evaluated with lib.evalModules
```

## Build it

This downloads a kernel, systemd and the rest of a minimal system from the cache, and builds the
small machine-specific parts locally (initrd, `/etc`, the system path):

```bash timeout=3600
nix build .#nixosConfigurations.box.config.system.build.toplevel
ls result/
```

```text expect
activate
etc
init
initrd
kernel
nixos-version
sw
systemd
```

What the entries are:

| Entry | What it is | Made by |
|---|---|---|
| `activate` | shell script that makes a running machine match this system | `activatable-system.nix`, `activation-script.nix` |
| `bin/switch-to-configuration` | runs `activate`, restarts changed units, updates the boot loader | `switchable-system.nix` |
| `etc` | link to the `etc` derivation: every `environment.etc` entry | `etc.nix` |
| `sw` | link to `system.path`: `environment.systemPackages` merged with `buildEnv` | `system-path.nix` |
| `kernel`, `initrd`, `kernel-params` | what the boot loader loads | `boot/kernel.nix`, `boot/systemd/initrd.nix` |
| `init` | the first program the initrd starts in the real root (stage 2) | `top-level.nix` |
| `systemd` | link to the systemd package used | `top-level.nix` |
| `nixos-version`, `system` | the label and the platform | `top-level.nix` |

```bash
cat result/nixos-version; echo
cat result/system; echo
readlink result/sw
test -x result/sw/bin/bash && echo "sw/bin has bash, systemctl, ..."
grep -m1 "^systemConfig=" result/activate
```

```text expect
26.05
x86_64-linux
-system-path
sw/bin has bash, systemctl, ...
systemConfig='/nix/store/
nixos-system-box-26.05
```

`activate` begins by setting `systemConfig` to the toplevel's own store path. The `@out@`
placeholder was substituted by `sed` while building, see `activatable-system.nix`. Look for where
it points `/run/current-system` at itself:

```bash
grep -n "current-system" result/activate | head -n 3
```

```text expect
/run/current-system
```

## Trace an option to its file: `environment.etc`

You set `environment.etc."greeting.txt".text`. The `etc` module derived a `source` from it, a
store path made by `pkgs.writeText "etc-greeting.txt"`. Ask the evaluator for that path, and
follow the symlinks in the built system to the same place:

```bash
src=$(nix eval --raw '.#nixosConfigurations.box.config.environment.etc."greeting.txt".source')
echo "option source: $src"
echo "built file:    $(readlink -f result/etc/greeting.txt)"
[ "$src" = "$(readlink -f result/etc/greeting.txt)" ] && echo "same store path"
cat result/etc/greeting.txt
```

```text expect
-etc-greeting.txt
same store path
hello from box
```

The chain is: `result/etc` → the `etc` derivation's `etc/` → `greeting.txt` → the
`writeText` output. On a running NixOS machine, activation makes `/etc/static` point at that
`etc` directory and links `/etc/greeting.txt` → `/etc/static/greeting.txt`
(`nixos/modules/system/etc/setup-etc.pl`).

Not everything in `/etc` comes from the store. Files that must be writable or that hold secrets,
such as `/etc/passwd` and `/etc/shadow`, are created by the activation script from
`users.users` (`nixos/modules/config/update-users-groups.pl`):

```bash
test -e result/etc/passwd || echo "no passwd in the system closure; activation writes it"
```

```text expect
no passwd in the system closure
```

## Trace an option to its file: a systemd unit

`systemd.services.greeter` became a unit file under `etc/systemd/system`. `script` became a small
script in the store, and `ExecStart` points to it (`nixos/lib/systemd-unit-options.nix` sets
`serviceConfig.ExecStart`; `nixos/lib/systemd-lib.nix` `makeJobScript` writes the script):

```bash
cat result/etc/systemd/system/greeter.service
ls result/etc/systemd/system/multi-user.target.wants/ | grep greeter
```

```text expect
[Unit]
Description=Print the greeting once at boot
[Service]
ExecStart=/nix/store/
-unit-script-greeter-start/bin/greeter-start
Type=oneshot
greeter.service
```

NixOS never runs `systemctl enable`. `wantedBy` becomes the `.wants/` symlink, built into the
same `etc` tree (the `[Install]` section written by `commonUnitText` in `systemd-lib.nix` is
informational). Now compare with the evaluated option:

```bash
exec_start=$(nix eval --raw .#nixosConfigurations.box.config.systemd.services.greeter.serviceConfig.ExecStart)
script=${exec_start%% *}
echo "ExecStart option: $script"
grep -qF "ExecStart=$script" result/etc/systemd/system/greeter.service && echo "unit file matches the option"
cat "$script"
```

```text expect
unit file matches the option
cat /etc/greeting.txt
```

## Generations, the way `nixos-rebuild` makes them

`nixos-rebuild switch` does three things after building (see
`pkgs/by-name/ni/nixos-rebuild-ng/src/nixos_rebuild/nix.py`, `set_profile`):

1. `nix-env -p /nix/var/nix/profiles/system --set <toplevel>`: a new numbered generation
   link, which is also a GC root;
2. `<toplevel>/bin/switch-to-configuration switch`: run `activate`, restart changed units,
   install boot loader entries for every generation.

You can't activate a NixOS system on Xubuntu, but step 1 works with any profile path. Make a
profile in this directory:

```bash timeout=3600
mkdir -p profiles
nix-env -p "$PWD/profiles/box" --set "$(readlink -f result)"
nix build .#nixosConfigurations.box-v2.config.system.build.toplevel -o result-v2
nix-env -p "$PWD/profiles/box" --set "$(readlink -f result-v2)"
nix-env -p "$PWD/profiles/box" --list-generations
ls -l profiles | grep -o 'box.*'
cat profiles/box/etc/greeting.txt
```

```text expect
(current)
box -> box-2-link
hello from box
second line, added in generation 2
```

Generation 2 only rebuilt what changed: the greeting file, the `etc` tree, the unit that
references it (none here) and the toplevel. Everything else is shared. Roll back:

```bash
nix-env -p "$PWD/profiles/box" --rollback
cat profiles/box/etc/greeting.txt
```

```text expect
switching profile from version 2 to 1
hello from box
```

On NixOS, `nixos-rebuild switch --rollback` does exactly this, then runs the old generation's
`switch-to-configuration`. The boot menu lists every generation that still has a link, which is
why old generations survive garbage collection until you delete them
(`nix-env -p /nix/var/nix/profiles/system --delete-generations old`, or `nix-collect-garbage -d`).

## Your turn

Find out, without building anything, (a) which store path `/etc/hostname` would come from and
(b) which `ExecStart` the `nscd` service has. Both come from NixOS modules, not from your
configuration. Then confirm both against `result/`.

<details><summary>Solution</summary>

`networking.hostName` feeds `environment.etc.hostname` (in `nixos/modules/tasks/network-interfaces.nix`).
`services.nscd` is enabled by default (`nixos/modules/services/system/nscd.nix`):

```bash
h=$(nix eval --raw .#nixosConfigurations.box.config.environment.etc.hostname.source)
[ "$h" = "$(readlink -f result/etc/hostname)" ] && echo "hostname file matches: $(cat "$h")"
e=$(nix eval --raw .#nixosConfigurations.box.config.systemd.services.nscd.serviceConfig.ExecStart)
grep -qF "ExecStart=$e" result/etc/systemd/system/nscd.service && echo "nscd unit matches: $e"
```

```text expect
hostname file matches: box
nscd unit matches: /nix/store/
```
</details>

## Check yourself

<details><summary>What is <code>config.system.build.toplevel</code>, in one sentence?</summary>

A derivation (built by `top-level.nix`'s `systemBuilder`) whose output is a directory of
symlinks to the parts of the system (`etc`, `sw`, `kernel`, `initrd`, `systemd`) plus the
`activate` and `switch-to-configuration` scripts. Its closure is the whole operating system.
</details>

<details><summary>Why can you build a NixOS system on Xubuntu, but not activate it there?</summary>

Building is just realising derivations, which any Nix installation can do for `x86_64-linux`.
Activating changes the running machine: `/etc`, users, systemd units and the boot loader. It
expects to be running *on* NixOS, as root, with NixOS's systemd as PID 1.
</details>

<details><summary>Why did <code>v2.nix</code> add a second line instead of failing with "conflicting definition values"?</summary>

`environment.etc.<name>.text` has type `nullOr lines`. `lines` merges several string definitions
by joining them with newlines. A `str` option would have conflicted. The type, not the module
order, decides.
</details>

<details><summary>Where in the built system would you look for the effect of <code>environment.systemPackages = [ pkgs.hello ];</code>?</summary>

`result/sw/bin/hello`. `sw` is `system.path`, a `buildEnv` of all `environment.systemPackages`
(`nixos/modules/config/system-path.nix`). On a running system it is `/run/current-system/sw`,
which is on everyone's `PATH`.
</details>
