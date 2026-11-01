# Lesson 06.4 — Writing a service module; testing it with `runNixOSTest`

**You will:** write `services.hello-web`, a NixOS module with a typed interface (enable, package,
port, message, openFirewall) that runs a small web server under systemd. You check what it
generates without booting anything, then boot it in a NixOS VM test that fetches the page and
checks it.

## The shape of a service module

Open almost any file under `nixos/modules/services/` and you will find this shape:

```nix
{ config, lib, pkgs, ... }:
let
  cfg = config.services.NAME;            # 1. a short name for "my options"
in
{
  options.services.NAME = {              # 2. the interface: typed, documented
    enable = lib.mkEnableOption "NAME";
    package = lib.mkPackageOption pkgs "NAME" { };
    …
  };

  config = lib.mkIf cfg.enable {         # 3. the implementation, only when enabled
    systemd.services.NAME = { … };
    users.users / networking.firewall / environment.etc …
  };
}
```

The interface and the implementation are separate on purpose. Users write
`services.NAME.port = 9000;` and never touch `systemd.services.NAME`. Later the implementation can
change (another server, more hardening) without breaking their configurations. That is the
**options are an interface** pattern. The implementation only *sets other modules' options*. It
doesn't start anything itself. systemd, the firewall and `/etc` are produced by their own
modules from these definitions, as you traced in lesson 06.2.

## The module

The server is Python's built-in `http.server`, serving one generated page. Every part comes
from the binary cache. The page is built at evaluation time from the `message` option, so a
change of message is a new store path, and therefore a changed unit, and therefore a restart on
`nixos-rebuild switch`.

```bash
git init -q
```

```nix file=hello-web.nix
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.hello-web;

  site = pkgs.writeTextDir "index.html" ''
    <!doctype html>
    <title>hello-web</title>
    <h1>${lib.escapeXML cfg.message}</h1>
  '';
in
{
  options.services.hello-web = {
    enable = lib.mkEnableOption "hello-web, a tiny demo web server";

    package = lib.mkPackageOption pkgs "python3" { };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8080;
      description = "TCP port to listen on.";
    };

    message = lib.mkOption {
      type = lib.types.str;
      default = "Hello from NixOS";
      description = "Text shown on the page.";
    };

    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Open {option}`services.hello-web.port` in the firewall.";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.hello-web = {
      description = "hello-web demo server";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      serviceConfig = {
        ExecStart = lib.escapeShellArgs [
          (lib.getExe cfg.package)
          "-m"
          "http.server"
          (toString cfg.port)
          "--bind"
          "0.0.0.0"
          "--directory"
          "${site}"
        ];
        # A throwaway system user, created when the service starts
        # (systemd.exec(5), DynamicUser=). Implies ProtectSystem=strict etc.
        DynamicUser = true;
        # Ports below 1024 need this capability; only grant it when needed.
        AmbientCapabilities = lib.optionals (cfg.port < 1024) [ "CAP_NET_BIND_SERVICE" ];
        Restart = "on-failure";
      };
    };

    networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ cfg.port ];
  };
}
```

Points worth copying:

- `lib.mkPackageOption pkgs "python3" { }` declares `package`, defaulting to `pkgs.python3`. Users
  can swap in another build without touching the module.
- `lib.escapeShellArgs` builds `ExecStart` safely. systemd splits the command line with
  shell-like quoting.
- `networking.firewall.allowedTCPPorts` is a `listOf port`. Several modules add to it, and
  `mkIf` adds nothing when the user didn't ask.
- `DynamicUser = true` is the cheapest hardening there is. No `users.users` entry is needed.

## A machine that uses it

```nix file=web.nix
{
  nixpkgs.hostPlatform = "x86_64-linux";
  boot.loader.grub.enable = false;
  fileSystems."/" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "ext4";
  };
  documentation.nixos.enable = false;
  system.stateVersion = "26.05";

  services.hello-web = {
    enable = true;
    port = 80;
    message = "Hello from web";
    openFirewall = true;
  };
}
```

## The test

A NixOS test is itself a module (`nixos/lib/testing/`) with a `name`, `nodes` (each node is a
NixOS configuration) and a `testScript` in Python. `pkgs.testers.runNixOSTest` (see
`pkgs/build-support/testers/default.nix`) evaluates it and returns a derivation. Building that
derivation boots the VMs in the sandbox and runs the script. The script's API (`wait_for_unit`,
`succeed`, `wait_for_open_port`, …) is in `nixos/lib/test-driver/src/test_driver/machine/__init__.py`.

```nix file=test.nix
{
  name = "hello-web";

  nodes.machine =
    { pkgs, ... }:
    {
      imports = [ ./hello-web.nix ];
      services.hello-web = {
        enable = true;
        message = "Hello from a NixOS test";
      };
      environment.systemPackages = [ pkgs.curl ];
    };

  testScript = ''
    machine.wait_for_unit("hello-web.service")
    machine.wait_for_open_port(8080, addr="127.0.0.1")

    page = machine.succeed("curl -sf http://127.0.0.1:8080/")
    print(f"PAGE: {page.strip()}")
    assert "Hello from a NixOS test" in page, f"unexpected page: {page}"

    # DynamicUser: the server must not run as root.
    uid = machine.succeed(
        "stat -c %u /proc/$(systemctl show -p MainPID --value hello-web.service)"
    ).strip()
    print(f"server uid: {uid}")
    assert uid != "0", "hello-web runs as root"
  '';
}
```

```nix file=flake.nix
{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      nixosModules.hello-web = ./hello-web.nix;

      nixosConfigurations.web = nixpkgs.lib.nixosSystem {
        modules = [
          self.nixosModules.hello-web
          ./web.nix
        ];
      };

      checks.${system}.hello-web = pkgs.testers.runNixOSTest ./test.nix;
    };
}
```

```bash
git add hello-web.nix web.nix test.nix flake.nix
```

## First, test by evaluation

Booting takes seconds to minutes. Evaluating takes a moment. Check what the module generates for
`web` before you build anything:

```bash
c=.#nixosConfigurations.web.config
nix eval --raw $c.systemd.services.hello-web.serviceConfig.ExecStart; echo
nix eval $c.systemd.services.hello-web.serviceConfig.AmbientCapabilities
nix eval $c.networking.firewall.allowedTCPPorts
nix eval --raw .#nixosConfigurations.web.options.services.hello-web.port.description; echo
```

```text expect
-m http.server 80 --bind 0.0.0.0 --directory /nix/store/
[ "CAP_NET_BIND_SERVICE" ]
80
TCP port to listen on.
```

Port 80 got the capability and a firewall hole. You can also *build* single pieces of the
system without building all of it. The unit file is the derivation
`config.systemd.units."hello-web.service".unit`, and building it also builds the page it refers
to:

```bash
nix build '.#nixosConfigurations.web.config.systemd.units."hello-web.service".unit' -o unit
grep '^ExecStart=' unit/hello-web.service
dir=$(grep -o '/nix/store/[^ ]*-index.html' unit/hello-web.service)
grep -o '<h1>.*</h1>' "$dir/index.html"
```

```text expect
ExecStart=/nix/store/
<h1>Hello from web</h1>
```

## Then, boot it

```bash timeout=3600
nix build .#checks.x86_64-linux.hello-web --no-link
nix log .#checks.x86_64-linux.hello-web | grep -a -E "PAGE:|server uid:"
```

```text expect
PAGE: <!doctype html>
server uid:
```

The build succeeded, so every `assert` in the script held. If one fails, the build fails and
prints the end of the log. Re-running a passing test does nothing, because the result is in your
store, like any build. To run it again anyway, use `nix build --rebuild`.

To debug a test interactively, build its driver and get a Python prompt with the VMs under your
control (not run here):

```console
$ nix run .#checks.x86_64-linux.hello-web.driverInteractive
>>> machine.start()
>>> machine.succeed("systemctl status hello-web")
>>> machine.shell_interact()     # a root shell in the VM
```

## Your turn

Add an option `services.hello-web.title` (a `str`, default `"hello-web"`) that sets the page's `<title>`,
and extend the *evaluation* check: confirm, without booting, that `web`'s page has the default
title and that a machine setting `title = "Box"` gets `<title>Box</title>`. Use `extendModules`
on `nixosConfigurations.web` for the second machine.

<details><summary>Solution</summary>

```nix file=hello-web.nix
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.hello-web;

  site = pkgs.writeTextDir "index.html" ''
    <!doctype html>
    <title>${lib.escapeXML cfg.title}</title>
    <h1>${lib.escapeXML cfg.message}</h1>
  '';
in
{
  options.services.hello-web = {
    enable = lib.mkEnableOption "hello-web, a tiny demo web server";
    package = lib.mkPackageOption pkgs "python3" { };
    port = lib.mkOption {
      type = lib.types.port;
      default = 8080;
      description = "TCP port to listen on.";
    };
    message = lib.mkOption {
      type = lib.types.str;
      default = "Hello from NixOS";
      description = "Text shown on the page.";
    };
    title = lib.mkOption {
      type = lib.types.str;
      default = "hello-web";
      description = "Title of the page.";
    };
    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Open {option}`services.hello-web.port` in the firewall.";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.hello-web = {
      description = "hello-web demo server";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      serviceConfig = {
        ExecStart = lib.escapeShellArgs [
          (lib.getExe cfg.package)
          "-m"
          "http.server"
          (toString cfg.port)
          "--bind"
          "0.0.0.0"
          "--directory"
          "${site}"
        ];
        DynamicUser = true;
        AmbientCapabilities = lib.optionals (cfg.port < 1024) [ "CAP_NET_BIND_SERVICE" ];
        Restart = "on-failure";
      };
    };
    networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ cfg.port ];
  };
}
```

```nix file=flake.nix
{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      nixosModules.hello-web = ./hello-web.nix;

      nixosConfigurations.web = nixpkgs.lib.nixosSystem {
        modules = [
          self.nixosModules.hello-web
          ./web.nix
        ];
      };

      nixosConfigurations.web-titled = self.nixosConfigurations.web.extendModules {
        modules = [ { services.hello-web.title = "Box"; } ];
      };

      checks.${system}.hello-web = pkgs.testers.runNixOSTest ./test.nix;
    };
}
```

```bash
git add hello-web.nix flake.nix
for host in web web-titled; do
  nix build ".#nixosConfigurations.$host.config.systemd.units.\"hello-web.service\".unit" -o "unit-$host"
  dir=$(grep -o '/nix/store/[^ ]*-index.html' "unit-$host/hello-web.service")
  echo "$host: $(grep -o '<title>.*</title>' "$dir/index.html")"
done
```

```text expect
web: <title>hello-web</title>
web-titled: <title>Box</title>
```
</details>

## Check yourself

<details><summary>Why does the module set <code>systemd.services.hello-web</code> instead of writing a unit file into <code>environment.etc</code> itself?</summary>

Because the systemd module already turns `systemd.services.*` into unit files, `.wants` links,
restart triggers on change, and documentation. Setting its options composes with every other
module, for example one that adds `serviceConfig.MemoryMax` to your service from outside.
Writing files directly would bypass all of that.
</details>

<details><summary>A user sets <code>services.hello-web.port = 443;</code> on a machine where nginx also listens on 443. Which part of NixOS notices?</summary>

Nothing at evaluation time. Ports aren't a typed resource. The server fails at runtime
(`Address already in use`) and systemd restarts it. A module could add an assertion if it knew
about the other service. A VM test that enables both would catch it before deployment.
</details>

<details><summary>Why does <code>runNixOSTest</code> run inside the Nix sandbox, and what does that buy you?</summary>

It is a derivation: the VMs, the driver and the script are inputs, and success is "the build
produced an output". So tests are cached (a passing test isn't re-run until something it depends
on changes), reproducible (no network, fixed inputs), and they can run on any Nix builder, which
is exactly how nixpkgs' CI runs thousands of them.
</details>
