# Lesson 06.3 — `nixosConfigurations`, `build-vm`, and booting NixOS from Xubuntu

**You will:** keep a NixOS machine in a flake, see how `vmVariant` derives a VM from it with
`extendModules`, build the VM on Xubuntu without `nixos-rebuild`, and boot it headless until it
prints its greeting and powers itself off.

## `nixosConfigurations` is a convention

A flake output `nixosConfigurations.<host>` is just a `nixpkgs.lib.nixosSystem { … }` result.
Tools look for it there. `nixos-rebuild switch --flake .#box` builds
`nixosConfigurations.box.config.system.build.toplevel` and switches to it. `nix flake check`
evaluates it. `nix flake show` lists it.

On Xubuntu there is no `nixos-rebuild` (it is a NixOS tool), and you don't need it. Every
`nixos-rebuild` action is "build an attribute of `config.system.build`", followed by something
that only makes sense on the target machine:

| `nixos-rebuild …` | builds | then |
|---|---|---|
| `build` | `config.system.build.toplevel` | nothing |
| `switch` / `boot` / `test` | `config.system.build.toplevel` | set profile, run `switch-to-configuration` |
| `build-vm` | `config.system.build.vm` | nothing; you run `./result/bin/run-<host>-vm` |
| `build-vm-with-bootloader` | `config.system.build.vmWithBootLoader` | same, but boots through a real boot loader |

(See `pkgs/by-name/ni/nixos-rebuild-ng/src/nixos_rebuild/` for the actual code.)

## The VM is the same machine, extended

`nixos/modules/virtualisation/build-vm.nix` declares:

```nix
vmVariant = extendModules { modules = [ ./qemu-vm.nix ]; };
…
options.virtualisation.vmVariant = mkOption { inherit (vmVariant) type; default = { }; … };
config.system.build.vm = lib.mkDefault config.virtualisation.vmVariant.system.build.vm;
```

So `system.build.vm` comes from a **second evaluation** of your configuration, with
`qemu-vm.nix` added. That module overrides `fileSystems`, the boot loader and the kernel command
line with `mkVMOverride` (priority 10). It shares the host's `/nix/store` with the guest over 9p,
so nothing is copied into a disk image. It also writes the `run-<host>-vm` script. Anything you
put in `virtualisation.vmVariant = { … }` applies **only** to the VM. This is the module system's
fixed point used twice: `extendModules` re-runs the same fixed point with more modules.

## The machine

```bash
git init -q
```

```nix file=configuration.nix
{ pkgs, ... }:
{
  nixpkgs.hostPlatform = "x86_64-linux";
  boot.loader.grub.enable = false;
  fileSystems."/" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "ext4";
  };
  networking.hostName = "box";
  environment.etc."greeting.txt".text = "hello from box\n";
  environment.systemPackages = [ pkgs.hello ];
  documentation.nixos.enable = false;
  system.stateVersion = "26.05";
}
```

`vm.nix` holds the VM-only settings. A one-shot service prints the greeting to the console. If
the kernel command line contains `box.poweroff`, it then shuts the VM down. That keeps the VM
usable interactively, and lets a script boot it and wait for it to finish.

```nix file=vm.nix
{ pkgs, ... }:
{
  virtualisation.vmVariant = {
    virtualisation = {
      graphics = false; # serial console on your terminal, no window
      memorySize = 1024; # MiB
      cores = 2;
    };

    # Convenience for interactive use of the throwaway VM only. Never on a real machine.
    services.getty.autologinUser = "root";

    systemd.services.announce = {
      description = "Announce that the VM has booted";
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        Type = "oneshot";
        StandardOutput = "journal+console";
      };
      script = ''
        echo "BOX-VM: $(cat /etc/greeting.txt) ($(${pkgs.hello}/bin/hello))"
        if grep -qw box.poweroff /proc/cmdline; then
          systemctl --no-block poweroff
        fi
      '';
    };
  };
}
```

```nix file=flake.nix
{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { nixpkgs, ... }:
    {
      nixosConfigurations.box = nixpkgs.lib.nixosSystem {
        modules = [
          ./configuration.nix
          ./vm.nix
        ];
      };
    };
}
```

```bash
git add configuration.nix vm.nix flake.nix
nix flake show 2>/dev/null
```

```text expect
nixosConfigurations
box: NixOS configuration
```

## Two evaluations, one configuration

The base system has no `virtualisation.memorySize` option at all, because `qemu-vm.nix` isn't
one of its modules. The VM variant has it:

```bash
nix eval .#nixosConfigurations.box.config.virtualisation --apply 'v: v ? memorySize'
nix eval .#nixosConfigurations.box.config.virtualisation.vmVariant.virtualisation.memorySize
nix eval .#nixosConfigurations.box.config.fileSystems --apply builtins.attrNames
nix eval .#nixosConfigurations.box.config.virtualisation.vmVariant.fileSystems --apply builtins.attrNames
```

```text expect
false
1024
[ "/" ]
"/tmp/xchg"
```

The VM gets extra file systems, set by `qemu-vm.nix` with `mkVMOverride`: the host's store
over 9p (`/nix/.ro-store`, bind-mounted on `/nix/store`) and a directory shared with the host
(`/tmp/xchg`). The `announce` service exists only in the VM:

```bash
nix eval .#nixosConfigurations.box.config.systemd.services --apply 's: s ? announce'
nix eval .#nixosConfigurations.box.config.virtualisation.vmVariant.systemd.services --apply 's: s ? announce'
```

```text expect
false
true
```

## Build the VM

```bash timeout=3600
nix build .#nixosConfigurations.box.config.system.build.vm
ls result/bin
grep -o 'qemu-system-x86_64 -machine accel=kvm:tcg' result/bin/run-box-vm | head -n1
```

```text expect
run-box-vm
qemu-system-x86_64 -machine accel=kvm:tcg
```

`accel=kvm:tcg` means "use KVM if you can, otherwise emulate". The same script works on a laptop
with KVM (boots in seconds) and in a CI runner without it (boots in minutes).

### Running it interactively

This is how you would use it on your desktop. It is not run by this lesson, because it waits for
you:

```console
$ ./result/bin/run-box-vm
<<< NixOS Stage 1 >>>
…
<<< Welcome to NixOS 26.05 (x86_64) - ttyS0 >>>
box login: root (automatic login)
BOX-VM: hello from box (Hello, world!)
[root@box:~]# systemctl status announce
[root@box:~]# poweroff
```

The VM keeps its state in `./box.qcow2` (created on first run; delete it to start fresh) and
shares `/nix/store` read-only with your machine. With `graphics = true` (the default) you get a
QEMU window instead. Press `Ctrl-a x` to kill QEMU in `-nographic` mode.

### Running it headless, from a script

Pass `box.poweroff` on the kernel command line (`$QEMU_KERNEL_PARAMS` is appended by the run
script), give QEMU no terminal input, and wait. `timeout` turns a hung boot into a failure:

```bash timeout=3600
export QEMU_KERNEL_PARAMS="box.poweroff"
timeout 3000 ./result/bin/run-box-vm < /dev/null > boot.log 2>&1
unset QEMU_KERNEL_PARAMS
grep -a "BOX-VM:" boot.log
grep -a -m1 "Welcome to NixOS" boot.log || true
```

```text expect
BOX-VM: hello from box (Hello, world!)
```

That was a full boot: initrd, systemd, your service, and a clean shutdown. For anything more,
such as waiting for a port, running commands in the guest or several machines, use
`runNixOSTest` (lesson 06.4). It does all of this inside the Nix sandbox and drives the VMs
from Python.

## From Xubuntu to real NixOS machines

The same flake deploys to real hardware. These are shown, not run:

```console
# Build here, copy the closure over SSH, activate there:
$ nix run nixpkgs#nixos-rebuild -- switch --flake .#box --target-host root@box.example.org

# Or by hand, which is exactly what that does:
$ nix build .#nixosConfigurations.box.config.system.build.toplevel
$ nix copy --to ssh://root@box.example.org ./result
$ ssh root@box.example.org nix-env -p /nix/var/nix/profiles/system --set "$(readlink -f result)"
$ ssh root@box.example.org "$(readlink -f result)"/bin/switch-to-configuration switch
```

A real machine also needs a real `hardware-configuration.nix` (from `nixos-generate-config` on
it) and a boot loader, for example `boot.loader.systemd-boot.enable = true;`.

## Your turn

Add a second machine, `nixosConfigurations.box2`, that *reuses* `box` through `extendModules`
and only changes the host name to `box2` and the greeting to `hello from box2`. Show that its VM
script is called `run-box2-vm` (the VM package's `meta.mainProgram`) without building it, and that the greeting file has the new text,
by building just `config.environment.etc."greeting.txt".source`.

<details><summary>Solution</summary>

`networking.hostName` is a `str`, so a second plain definition would conflict. Use `mkForce`.
The greeting is `lines`, so `mkForce` is needed there too, to *replace* the text rather than
add a line (see lesson 06.2).

```nix file=box2.nix
{ lib, ... }:
{
  networking.hostName = lib.mkForce "box2";
  environment.etc."greeting.txt".text = lib.mkForce "hello from box2\n";
}
```

```nix file=flake.nix
{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { self, nixpkgs }:
    {
      nixosConfigurations.box = nixpkgs.lib.nixosSystem {
        modules = [
          ./configuration.nix
          ./vm.nix
        ];
      };
      nixosConfigurations.box2 = self.nixosConfigurations.box.extendModules {
        modules = [ ./box2.nix ];
      };
    };
}
```

```bash
git add box2.nix flake.nix
nix eval --raw .#nixosConfigurations.box2.config.system.build.vm.meta.mainProgram; echo
nix build '.#nixosConfigurations.box2.config.environment.etc."greeting.txt".source' -o greeting2
cat greeting2
```

```text expect
run-box2-vm
hello from box2
```
</details>

## Check yourself

<details><summary>Why doesn't the VM need a disk image containing NixOS?</summary>

`qemu-vm.nix` boots the kernel and initrd directly (`-kernel`, `-initrd`, `init=` on the command
line) and mounts the host's `/nix/store` into the guest over 9p (or virtiofs). The system's
closure is already in your store. The `box.qcow2` image only holds the guest's mutable state:
`/var`, `/home`, `/etc` files made at activation.
</details>

<details><summary>What does <code>virtualisation.vmVariant = { … }</code> change in the system you deploy with <code>nixos-rebuild switch</code>?</summary>

Nothing. `vmVariant` is evaluated separately with `extendModules`, and only
`system.build.vm` uses it. `config.system.build.toplevel` of the base configuration never sees
those definitions. That is why it is a safe place for autologin and test-only services.
</details>

<details><summary>Why is <code>mkVMOverride</code> priority 10, lower (stronger) than <code>mkForce</code>'s 50?</summary>

The VM must replace the real machine's file systems and boot settings even when the user's
configuration uses `mkForce` for them. Otherwise `build-vm` would try to mount your real disks.
</details>
