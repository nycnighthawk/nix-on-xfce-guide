# Course 06 · The module system and NixOS

**You will:** learn the module system on its own, as a typed configuration language. Then you
read how NixOS uses it to turn a few lines of configuration into a bootable system. You build,
boot and test NixOS machines from Xubuntu, without installing NixOS anywhere.

NixOS is not a separate program on top of nixpkgs. It is about 2,000 `.nix` files in
`nixpkgs/nixos/modules`, evaluated by one function, `lib.evalModules`. The result is one
derivation, `config.system.build.toplevel`. Once you understand `evalModules`, NixOS is just a
large example of it.

## Goals

After this course you can:

- declare options with types, defaults and documentation; combine modules with `imports`;
  control merging with `mkDefault`/`mkForce`/`mkOverride`, `mkIf` and `mkMerge`; and add
  assertions, all with `lib.evalModules` and no NixOS involved;
- explain the path from `nixosSystem { modules = …; }` through `nixos/lib/eval-config.nix` to
  `system.build.toplevel`, and find in the built system the file that any option produced;
- define `nixosConfigurations` in a flake, build them on Xubuntu, and boot one in QEMU;
- write a NixOS service module with an interface of typed options, and test it with a
  multi-machine `runNixOSTest`.

## Prerequisites

- Course 02 (functions, attribute sets, laziness, fixed points). The module system is a fixed
  point: `config` is passed to the modules that define it.
- Course 04 (flakes). Course 05.1 helps for reading `systemd` service definitions.
- 4 GB of free RAM and ~10 GB of disk for the system closures and VM tests.
- Hardware virtualisation (KVM) makes the VM lessons fast. Without it, QEMU falls back to
  emulation, which works but takes several minutes per boot. Check:

```bash
ls -l /dev/kvm 2>/dev/null || echo "no /dev/kvm: VM tests will run, slowly, without KVM"
nix config show system-features
```

```text expect
nixos-test
```

`nixos-test` must be in `system-features` for `runNixOSTest` to build. Nix adds it by default
on Linux, together with `kvm` when `/dev/kvm` is usable.

## Structure

| File | What you do |
|---|---|
| `01-module-system.md` | `lib.evalModules` from scratch: options, types, merging, priorities, `mkIf`/`mkMerge`, `imports`, assertions, type errors |
| `02-how-nixos-is-built.md` | read `eval-config.nix`, `top-level.nix`, `etc.nix`; build a `toplevel`; trace options to `/etc` files and systemd units; generations |
| `03-nixos-configurations-and-vms.md` | `nixosConfigurations`, `vmVariant`, `system.build.vm`; boot a VM headless from Xubuntu |
| `04-service-modules-and-tests.md` | a `services.hello-web` module; evaluate it; a `runNixOSTest` that boots it |
| `project-a-config-generator.md` | **06a** a typed config generator: evalModules + `pkgs.formats.toml` + freeform settings + validation |
| `project-b-service-vm-test.md` | **06b** service module + two-machine VM test (server, client, firewall) |
| `project-c-take-a-system-apart.md` | **06c** closure size, `why-depends`, which module wrote a file, `diff-closures` between generations |

Every file stands alone and starts in an empty directory. The NixOS lessons are flakes pinned to
nixpkgs 26.05 with `system.stateVersion = "26.05"`.

## Patterns this course drills

- **Options are an interface.** A module declares what can be configured (typed, documented)
  separately from how it is implemented. Users depend on the options, not on the implementation.
- **Config is a fixed point.** Every module receives the *final* `config` and contributes
  definitions to it. Laziness makes this work, and `mkIf` rather than `if` keeps it from
  recursing forever.
- **Priorities, not order.** Modules don't override each other by position. Definitions merge
  by type, and conflicts are resolved by priority (`mkDefault` 1000, plain 100, `mkForce` 50).
- **Derived files.** Options become store paths (`environment.etc.*.source`, unit files), and
  the system is a tree of symlinks to them. To debug, follow the links back to the options.
- **Tests boot real machines.** `runNixOSTest` builds whole NixOS VMs from the same modules and
  drives them from Python, inside the Nix sandbox.

## Primary sources

- NixOS manual 26.05: *Writing NixOS Modules* (option declarations, types, definitions,
  freeform modules), *NixOS Tests*.
- nixpkgs 26.05: `lib/modules.nix`, `lib/types.nix`, `lib/options.nix`, `nixos/lib/eval-config.nix`,
  `nixos/modules/module-list.nix`, `nixos/modules/system/activation/top-level.nix`,
  `nixos/modules/system/etc/etc.nix`, `nixos/lib/systemd-lib.nix`,
  `nixos/modules/virtualisation/qemu-vm.nix`, `nixos/modules/virtualisation/build-vm.nix`,
  `pkgs/build-support/testers/default.nix` (`runNixOSTest`), `pkgs/pkgs-lib/formats.nix`.
- nix.dev: *Module system deep dive*, *Integration testing with NixOS virtual machines*.

## Check yourself (before you start)

<details><summary>What does "a fixed point" mean for configuration, in one sentence?</summary>

The final configuration is the value that every module's function produces when that same final
configuration is passed in as `config`. Lazy evaluation lets Nix compute it as long as no
value depends on itself.
</details>

<details><summary>What do you get from <code>nixpkgs.lib.nixosSystem { modules = [ ./configuration.nix ]; }</code>?</summary>

The result of `lib.evalModules` over all NixOS modules plus yours: an attribute set with
`config`, `options`, `pkgs`, `extendModules` and a few more. `config.system.build.toplevel` is
the derivation that *is* the system. `nixos-rebuild` builds it and switches to it.
</details>
