# Project 06b — Service module + two-machine VM test

**Goal:** ship `services.hello-web` the way a nixpkgs module is shipped: a module with a typed
interface, exported as `nixosModules.default`, a fast evaluation check, and a NixOS VM test with
**two machines**. The client fetches the page from the server over the test network, a port
the module didn't open is blocked by the firewall, and the service comes back after a crash.

**You will practise:**

- **options are an interface**: `enable`, `package`, `port`, `message`, `openFirewall`;
- **tests boot real machines**: `pkgs.testers.runNixOSTest` with `nodes.server` and
  `nodes.client`, `defaults`, and `subtest`;
- **fast checks first**: a check that builds only the generated unit file, before the slow VM
  test;
- **negative tests**: proving the firewall *blocks* something, not just that the happy path works.

## 1. The module

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
    <title>hello-web on ${config.networking.hostName}</title>
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
        DynamicUser = true;
        AmbientCapabilities = lib.optionals (cfg.port < 1024) [ "CAP_NET_BIND_SERVICE" ];
        Restart = "on-failure";
        RestartSec = 1;
      };
    };

    networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ cfg.port ];
  };
}
```

## 2. The test

The test is a module too. `defaults` is applied to every node. Each `nodes.<name>` is a full
NixOS configuration, and its name is also its host name on the test network (the framework
writes `/etc/hosts`, see `nixos/lib/testing/network.nix`).

```nix file=test.nix
{
  name = "hello-web-two-machines";

  defaults =
    { pkgs, ... }:
    {
      environment.systemPackages = [ pkgs.curl ];
    };

  nodes.server =
    { pkgs, ... }:
    {
      imports = [ ./hello-web.nix ];
      services.hello-web = {
        enable = true;
        port = 8080;
        message = "Hello across the network";
        openFirewall = true;
      };
      # Only for the firewall probe in the test script.
      environment.systemPackages = [ pkgs.python3 ];
    };

  nodes.client = { };

  testScript = ''
    start_all()

    server.wait_for_unit("hello-web.service")
    server.wait_for_open_port(8080, addr="127.0.0.1")
    client.wait_for_unit("multi-user.target")

    with subtest("client fetches the page through the opened port"):
        page = client.succeed("curl -sf --max-time 10 http://server:8080/")
        print(f"CLIENT GOT: {page.strip()}")
        assert "Hello across the network" in page, page
        assert "hello-web on server" in page, page

    with subtest("a port the module did not open is blocked"):
        server.succeed(
            "systemd-run --unit=probe $(command -v python3) -m http.server 9000 --bind 0.0.0.0"
        )
        server.wait_for_open_port(9000, addr="127.0.0.1")
        server.succeed("curl -sf --max-time 10 http://127.0.0.1:9000/ > /dev/null")
        client.fail("curl -sf --max-time 5 http://server:9000/")
        print("FIREWALL: port 9000 answers locally but not from the client")

    with subtest("the service comes back after a crash"):
        server.succeed("systemctl kill --signal=KILL hello-web.service")
        server.wait_until_succeeds(
            "test $(systemctl show -p NRestarts --value hello-web.service) -ge 1"
        )
        server.wait_for_open_port(8080, addr="127.0.0.1")
        client.wait_until_succeeds(
            "curl -sf --max-time 10 http://server:8080/ | grep -q 'Hello across the network'"
        )
        print("RESTART: hello-web restarted and serves again")
  '';
}
```

## 3. The flake

```nix file=flake.nix
{
  description = "services.hello-web: a NixOS module with tests";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};

      # A minimal machine using the module, for evaluation checks.
      demo = nixpkgs.lib.nixosSystem {
        modules = [
          self.nixosModules.default
          {
            nixpkgs.hostPlatform = system;
            boot.loader.grub.enable = false;
            fileSystems."/" = {
              device = "/dev/disk/by-label/nixos";
              fsType = "ext4";
            };
            documentation.nixos.enable = false;
            system.stateVersion = "26.05";
            services.hello-web = {
              enable = true;
              message = "demo";
            };
          }
        ];
      };
    in
    {
      nixosModules.default = ./hello-web.nix;
      nixosModules.hello-web = self.nixosModules.default;

      nixosConfigurations.demo = demo;

      checks.${system} = {
        # Seconds: build only the unit file and look at it.
        unit = pkgs.runCommand "hello-web-unit-check" { } ''
          unit=${demo.config.systemd.units."hello-web.service".unit}/hello-web.service
          grep -q 'http.server 8080' "$unit"
          grep -q '^DynamicUser=true' "$unit"
          if grep -q CAP_NET_BIND_SERVICE "$unit"; then
            echo "port 8080 must not get CAP_NET_BIND_SERVICE" >&2
            exit 1
          fi
          echo "unit file OK" > $out
        '';

        # Minutes: boot two machines.
        vm = pkgs.testers.runNixOSTest ./test.nix;
      };
    };
}
```

```bash
git add hello-web.nix test.nix flake.nix
nix flake show 2>/dev/null
```

```text expect
nixosModules
default: NixOS module
vm: derivation
```

## 4. Fast check first

```bash
nix build .#checks.x86_64-linux.unit -o unit-check && cat unit-check
```

```text expect
unit file OK
```

The firewall side is plain evaluation. `demo` doesn't set `openFirewall`, so no port is open,
but the firewall is on (the NixOS default):

```bash
nix eval .#nixosConfigurations.demo.config.networking.firewall.allowedTCPPorts
nix eval .#nixosConfigurations.demo.config.networking.firewall.enable
```

```text expect
[ ]
true
```

Extend `demo` with `openFirewall = true`, and ask the module system not only for the value but
for *who defined it*. When an option has a surprising value on a real machine, this is how you
find the module responsible, instead of grepping nixpkgs:

```bash
nix eval --json --impure --expr '
  let
    f = builtins.getFlake (toString ./.);
    open = f.nixosConfigurations.demo.extendModules {
      modules = [ { services.hello-web.openFirewall = true; } ];
    };
    opt = open.options.networking.firewall.allowedTCPPorts;
  in {
    ports = open.config.networking.firewall.allowedTCPPorts;
    definedIn = map (d: baseNameOf d.file) (builtins.filter (d: d.value != [ ]) opt.definitionsWithLocations);
  }'
```

```text expect
{"definedIn":["hello-web.nix"],"ports":[8080]}
```

## 5. Boot two machines

```bash timeout=3600
nix build .#checks.x86_64-linux.vm --no-link
nix log .#checks.x86_64-linux.vm | grep -a -E "CLIENT GOT:|FIREWALL:|RESTART:"
```

```text expect
CLIENT GOT: <!doctype html>
FIREWALL: port 9000 answers locally but not from the client
RESTART: hello-web restarted and serves again
```

## 6. Verify

`nix flake check` evaluates everything (including `nixosConfigurations.demo`) and builds every
check. Both are already built, so it only re-evaluates:

```bash timeout=3600
nix flake check && echo "PROJECT 06b OK"
```

```text expect
PROJECT 06b OK
```

## Stretch goals

1. **A failing test on purpose.** Set `openFirewall = false;` on the server and rebuild
   `.#checks.x86_64-linux.vm`. Read the failure: which subtest failed, and what did `curl` report?
2. **Interactive debugging.** `nix run .#checks.x86_64-linux.vm.driverInteractive`, then
   `start_all()`, `client.succeed("curl -s http://server:8080/")`, `server.shell_interact()`.
3. **Two instances.** Turn `services.hello-web` into `services.hello-web.instances.<name>`
   (`attrsOf (submodule …)`), each with its own port and message, generating
   `systemd.services."hello-web-${name}"`. Test two instances on one server.
4. **Hardening.** Add `ProtectHome`, `PrivateDevices`, `RestrictAddressFamilies` and
   `SystemCallFilter`, then run `systemd-analyze security hello-web` in the test and assert the
   exposure score is below 3.0.
5. **Upstream style.** Compare your module with `nixos/modules/services/web-servers/static-web-server.nix`
   and its test `nixos/tests/web-servers/static-web-server.nix`. What do they do that you don't?
