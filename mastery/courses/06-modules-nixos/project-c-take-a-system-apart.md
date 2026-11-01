# Project 06c — Take a system apart

**Goal:** treat a built NixOS system as an object you can measure and question. How big is it,
and what is the biggest part? Why does it contain a given package? Which module, and which of
your options, produced a given file in `/etc`? What changed between two generations? You answer
each question with a command, and each answer is checked.

**You will practise:**

- **derived files**: following symlinks from the system back to store paths, and from store
  paths back to options and modules;
- **closures as data**: `nix path-info -rS`, `nix why-depends`, `nix-store --query --roots`;
- **generations are closures**: `nix store diff-closures` and `nix profile diff-closures`;
- **asking the module system** (`options.<path>.definitionsWithLocations`) instead of grepping
  nixpkgs.

## 1. Two generations of a small machine

```bash
git init -q
```

```nix file=configuration.nix
{
  nixpkgs.hostPlatform = "x86_64-linux";
  boot.loader.grub.enable = false;
  fileSystems."/" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "ext4";
  };
  networking.hostName = "box";
  environment.etc."greeting.txt".text = "hello from box\n";
  documentation.nixos.enable = false;
  system.stateVersion = "26.05";
}
```

Generation 2 adds a package and replaces the greeting:

```nix file=gen2.nix
{ lib, pkgs, ... }:
{
  environment.systemPackages = [ pkgs.hello ];
  environment.etc."greeting.txt".text = lib.mkForce "hello from generation 2\n";
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
      nixosConfigurations.box2 = self.nixosConfigurations.box.extendModules {
        modules = [ ./gen2.nix ];
      };
    };
}
```

```bash timeout=3600
git add configuration.nix gen2.nix flake.nix
nix build .#nixosConfigurations.box.config.system.build.toplevel -o gen1
nix build .#nixosConfigurations.box2.config.system.build.toplevel -o gen2
readlink gen1 gen2
```

```text expect
-nixos-system-box-26.05
```

## 2. How big is it, and what is big?

`-S` is the closure size: the path plus everything it references, recursively. `-s` is the
size of one path alone (its NAR size). `-r` lists the whole closure.

```bash
echo "store paths in the closure: $(nix path-info -r ./gen1 | wc -l)"
nix path-info -Sh ./gen1
bytes=$(nix path-info -S ./gen1 | awk '{print $2}')
[ "$bytes" -gt $((100 * 1024 * 1024)) ] && echo "closure is larger than 100 MiB"
echo "five largest paths:"
nix path-info -rs ./gen1 | sort -k2 -n | tail -n 5 | awk '{printf "%8.1f MiB  %s\n", $2/1048576, $1}'
```

```text expect
store paths in the closure:
closure is larger than 100 MiB
five largest paths:
MiB  /nix/store/
```

Typical winners are the kernel modules, systemd, glibc and its locales, and the initrd. To shrink
a system, start at the top of this list and ask the next question about each entry.

## 3. Why is this in my system?

`nix why-depends A B` prints the chain of references from A to B. This is how you find out
which part of the system pulled in a package:

```bash
hello=$(nix eval --raw .#nixosConfigurations.box2.pkgs.hello.outPath)
nix why-depends ./gen2 "$hello"
```

```text expect
-nixos-system-box-26.05
-system-path
-hello-2.12.3
```

`environment.systemPackages` → `system.path` (`sw`) → hello. Generation 1 has no such chain:

```bash
nix why-depends ./gen1 "$hello" 2>&1 || true
```

```text expect
does not depend on
```

And what keeps a system alive? Its GC roots. Here these are the `gen1` symlink (an indirect root
under `/nix/var/nix/gcroots/auto`). On NixOS they would be the
`/nix/var/nix/profiles/system-*-link` generations:

```bash
nix-store --query --roots "$(readlink -f gen1)"
```

```text expect
/gen1 -> /nix/store/
```

## 4. Which option produced this file?

Start from a file, as you would on a running machine where you find `/etc/hostname` and wonder
where it came from. In the built system, it is a link into the store:

```bash
readlink gen1/etc/hostname
cat gen1/etc/hostname
```

```text expect
-etc-hostname
box
```

`trace.nix` asks the module system three things about any `environment.etc` entry: its store
path, the modules that define it, and the files that set the options those modules used. Paths
inside nixpkgs are shown relative to nixpkgs:

```nix file=trace.nix
# Usage: nix-instantiate --eval --strict --json trace.nix --argstr host box --argstr name hostname
{ host, name }:
let
  flake = builtins.getFlake (toString ./.);
  inherit (flake.inputs.nixpkgs) lib;
  nixpkgsDir = toString flake.inputs.nixpkgs.outPath;
  sys = flake.nixosConfigurations.${host};

  show =
    file:
    let
      f = toString file;
    in
    if lib.hasPrefix "${nixpkgsDir}/" f then lib.removePrefix "${nixpkgsDir}/" f else baseNameOf f;

  definedBy =
    option: attr:
    map (d: show d.file) (lib.filter (d: d.value ? ${attr}) option.definitionsWithLocations);
in
{
  source = toString sys.config.environment.etc.${name}.source;
  definedBy = definedBy sys.options.environment.etc name;
}
```

```bash
nix-instantiate --eval --strict --json trace.nix --argstr host box --argstr name hostname
```

```text expect
"definedBy":["nixos/modules/tasks/network-interfaces.nix"]
-etc-hostname"
```

Read the module the answer names. In `nixos/modules/tasks/network-interfaces.nix`:

```nix
environment.etc.hostname = mkIf (cfg.hostName != "") {
  text = cfg.hostName + "\n";
};
```

So the file comes from the option `networking.hostName`. Who set that?

```bash
nix eval --json .#nixosConfigurations.box.options.networking.hostName.files --apply 'map baseNameOf'
```

```text expect
["configuration.nix"]
```

The full chain is: your `configuration.nix` sets `networking.hostName` →
`network-interfaces.nix` defines `environment.etc.hostname.text` → `etc.nix` derives `source`
with `writeText "etc-hostname"` → the `etc` derivation links it → `gen1/etc/hostname`.

Your own file traces to your own module:

```bash
nix-instantiate --eval --strict --json trace.nix --argstr host box --argstr name greeting.txt
```

```text expect
"definedBy":["configuration.nix"]
```

The same technique works for any option. A systemd unit you didn't write:

```bash
ls gen1/etc/systemd/system/ | grep -c '\.service$'
nix eval --json .#nixosConfigurations.box.options.systemd.services.definitionsWithLocations \
  --apply 'defs: map (d: baseNameOf d.file) (builtins.filter (d: d.value ? nscd) defs)'
```

```text expect
["nscd.nix"]
```

## 5. What changed between generations?

`nix store diff-closures` compares two closures by package name and version, and reports size
changes larger than 8 KiB:

```bash
nix store diff-closures ./gen1 ./gen2
```

```text expect
hello: ∅ → 2.12.3
```

The greeting changed too, but `etc-greeting.txt` has no version and almost no size, so it isn't
listed. Compare the files directly:

```bash
diff <(cat gen1/etc/greeting.txt) <(cat gen2/etc/greeting.txt) || true
```

```text expect
< hello from box
> hello from generation 2
```

On NixOS you compare *generations*, which are numbered links in a profile. Make a profile here
the way `nixos-rebuild` does (lesson 06.2), and use `nix profile diff-closures`, which walks
all generations in order:

```bash
mkdir -p profiles
nix-env -p "$PWD/profiles/box" --set "$(readlink -f gen1)"
nix-env -p "$PWD/profiles/box" --set "$(readlink -f gen2)"
nix profile diff-closures --profile "$PWD/profiles/box"
```

```text expect
Version 1 -> 2:
hello: ∅ → 2.12.3
```

On a NixOS machine the same command is
`nix profile diff-closures --profile /nix/var/nix/profiles/system`. It shows what every
`nixos-rebuild switch` changed.

## 6. Verify

One script, answering every question of this project, failing if any answer is wrong:

```bash
set -e
[ "$(cat gen1/etc/hostname)" = "box" ]
nix why-depends ./gen2 "$hello" > /dev/null
nix why-depends ./gen1 "$hello" 2>&1 | grep -q "does not depend on"
nix-instantiate --eval --strict --json trace.nix --argstr host box --argstr name hostname | grep -q network-interfaces.nix
nix-instantiate --eval --strict --json trace.nix --argstr host box2 --argstr name greeting.txt | grep -q gen2.nix
nix store diff-closures ./gen1 ./gen2 | grep -q 'hello: ∅ → 2.12.3'
echo "PROJECT 06c OK"
```

```text expect
PROJECT 06c OK
```

Look at the fifth check more closely:

```bash
nix-instantiate --eval --strict --json trace.nix --argstr host box2 --argstr name greeting.txt
```

```text expect
"configuration.nix"
"gen2.nix"
```

Both modules are listed, although `gen2.nix` won with `mkForce`. Priorities are resolved per
*option*, and the option here is `environment.etc."greeting.txt".text`, one level further down,
inside the submodule. At the level of `environment.etc` both modules contribute a
`greeting.txt` entry. Look at the raw definitions and you can see the priority wrapper, still
unresolved:

```bash
nix eval --json --impure --expr '
  let sys = (builtins.getFlake (toString ./.)).nixosConfigurations.box2;
      def = sys.options.environment.etc.definitionsWithLocations;
      kind = t: if builtins.isAttrs t then t._type else "plain";
  in map (d: { file = baseNameOf d.file; prio = kind d.value."greeting.txt".text; })
       (builtins.filter (d: d.value ? "greeting.txt") def)'
```

```text expect
{"file":"configuration.nix","prio":"plain"}
{"file":"gen2.nix","prio":"override"}
```

`gen2.nix`'s value is still wrapped in `mkForce` (`_type = "override"`, priority 50) at this
level. The submodule unwraps and compares it when it merges `text`.

## Stretch goals

1. **Shrink it.** Set `documentation.enable = false;`, `environment.defaultPackages = [ ];` and
   `i18n.supportedLocales = [ "en_US.UTF-8/UTF-8" ];` in a generation 3. How much smaller is
   the closure? Which entries left the top-5 list? Look at `nixos/modules/profiles/minimal.nix`
   for more.
2. **Trace a unit.** Extend `trace.nix` with a `service` mode that reports
   `systemd.services.<name>` definitions and the unit file's store path
   (`config.systemd.units."<name>.service".unit`).
3. **Find the option for any `/etc` file.** Write an expression that takes a store path (from
   `readlink`) and returns every `environment.etc` entry whose `source` is that path, without
   knowing the name.
4. **Closure diff in CI.** Add a GitHub Actions step that builds the system before and after a
   PR and posts `nix store diff-closures` as a comment. (Course 08 builds a workflow.)
5. **Remote machines.** `nix path-info --store ssh://host -rSh /run/current-system` measures
   the system a real NixOS machine is running, without logging in.
