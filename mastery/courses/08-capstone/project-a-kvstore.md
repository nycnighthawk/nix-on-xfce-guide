# Capstone — kvstore: from source to service, image and CI

**Goal:** build one repository that shows everything you've learnt: a small HTTP key-value
service, packaged the way nixpkgs packages software, wrapped in a flake with a dev shell,
formatter and checks, deployable as a hardened NixOS service proven by a two-machine VM test,
shipped as a container image and through a signed binary cache, and checked by CI on every push.

**You'll practise** (and the course that introduced each):

- `package.nix` as a function of its dependencies; `finalAttrs`; tests in the build (03, 07);
- flake outputs and overlays; lazy evaluation of outputs (04);
- dev shells, containers without a Dockerfile, signing keys as trust (05);
- typed module options, assertions, systemd sandboxing, `runNixOSTest` (06);
- "run CI before CI does" — the workflow is `nix flake check` (07).

Everything happens in one directory, which becomes a Git repository in stage 2. Run the stages
in order: each builds on the files of the one before.

## Stage 1 · The service, packaged nixpkgs-style

### The service

kvstore stores each value in its own file and speaks three requests. It uses only the Python
standard library, so the package has no dependencies to manage — the interesting part is the
Nix, not the Python.

```toml file=pyproject.toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "kvstore"
version = "1.0.0"
description = "Tiny HTTP key-value store built on the Python standard library"
requires-python = ">=3.10"

[project.scripts]
kvstore = "kvstore.server:main"
```

```python file=src/kvstore/__init__.py
"""kvstore: a tiny HTTP key-value store built on the Python standard library."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kvstore")
except PackageNotFoundError:  # running from a source checkout, not installed
    __version__ = "0+unknown"
```

```python file=src/kvstore/server.py
"""HTTP front end and on-disk store.

    GET /healthz      200 "ok"
    GET /kv/<key>     200 with the stored bytes, or 404
    PUT /kv/<key>     201 Created (new key) or 204 No Content (replaced)

Each value is one file under the data directory, written atomically
(temporary file + rename), so a crash never leaves a half-written value.
"""

import argparse
import os
import re
import signal
import sys
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__

# Keys can't start with "." (so they never collide with temporary files) or contain "/".
KEY_RE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}")
MAX_VALUE_BYTES = 1024 * 1024


class Store:
    """One file per key in a directory."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def _path(self, key):
        if not KEY_RE.fullmatch(key):
            raise ValueError(f"invalid key: {key!r}")
        return os.path.join(self.root, key)

    def get(self, key):
        try:
            with open(self._path(key), "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def put(self, key, value):
        """Store value; return True if the key is new."""
        path = self._path(key)
        existed = os.path.exists(path)
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(value)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return not existed


class Handler(BaseHTTPRequestHandler):
    server_version = f"kvstore/{__version__}"

    def _send(self, status, body=b"", content_type="text/plain; charset=utf-8"):
        self.send_response(status)
        if status != HTTPStatus.NO_CONTENT:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _key(self):
        prefix = "/kv/"
        return self.path[len(prefix) :] if self.path.startswith(prefix) else None

    def do_GET(self):
        if self.path == "/healthz":
            return self._send(HTTPStatus.OK, b"ok\n")
        key = self._key()
        if key is None:
            return self._send(HTTPStatus.NOT_FOUND, b"not found\n")
        try:
            value = self.server.store.get(key)
        except ValueError:
            return self._send(HTTPStatus.BAD_REQUEST, b"invalid key\n")
        if value is None:
            return self._send(HTTPStatus.NOT_FOUND, b"no such key\n")
        return self._send(HTTPStatus.OK, value, "application/octet-stream")

    def do_PUT(self):
        key = self._key()
        if key is None:
            return self._send(HTTPStatus.NOT_FOUND, b"not found\n")
        length = self.headers.get("Content-Length")
        if length is None:
            return self._send(HTTPStatus.LENGTH_REQUIRED, b"Content-Length required\n")
        try:
            size = int(length)
        except ValueError:
            return self._send(HTTPStatus.BAD_REQUEST, b"bad Content-Length\n")
        if size < 0:
            return self._send(HTTPStatus.BAD_REQUEST, b"bad Content-Length\n")
        if size > MAX_VALUE_BYTES:
            return self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, b"value too large\n")
        value = self.rfile.read(size)
        try:
            created = self.server.store.put(key, value)
        except ValueError:
            return self._send(HTTPStatus.BAD_REQUEST, b"invalid key\n")
        return self._send(HTTPStatus.CREATED if created else HTTPStatus.NO_CONTENT)


class KVServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store):
        super().__init__(address, Handler)
        self.store = store


def main(argv=None):
    parser = argparse.ArgumentParser(prog="kvstore", description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on")
    parser.add_argument("--port", type=int, default=8080, help="TCP port (0 = any free port)")
    parser.add_argument("--data-dir", default="data", help="directory holding the values")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    server = KVServer((args.host, args.port), Store(args.data_dir))

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)  # systemd and Docker stop services with SIGTERM
    print(
        f"kvstore {__version__} listening on {args.host}:{server.server_port},"
        f" data in {server.store.root}",
        file=sys.stderr,
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

The tests start a real server on a free port (`port 0`) in a thread and talk HTTP to it. The
Nix build sandbox has a loopback interface, so they run during the build:

```python file=tests/test_server.py
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from kvstore.server import KVServer, Store

# Never use a proxy from the environment for these local requests.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class StoreTest(unittest.TestCase):
    def test_put_reports_new_keys(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(d)
            self.assertTrue(store.put("a", b"1"))
            self.assertFalse(store.put("a", b"2"))
            self.assertEqual(store.get("a"), b"2")
            self.assertIsNone(store.get("missing"))

    def test_rejects_unsafe_keys(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(d)
            for key in ["", "../etc", ".hidden", "a/b", "x" * 200]:
                with self.assertRaises(ValueError, msg=key):
                    store.put(key, b"")


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = KVServer(("127.0.0.1", 0), Store(self.tmp.name))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, method, path, data=None):
        req = urllib.request.Request(self.base + path, data=data, method=method)
        try:
            with OPENER.open(req, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_put_then_get(self):
        self.assertEqual(self.request("PUT", "/kv/greeting", b"hello")[0], 201)
        self.assertEqual(self.request("GET", "/kv/greeting"), (200, b"hello"))

    def test_overwrite(self):
        self.request("PUT", "/kv/k", b"one")
        self.assertEqual(self.request("PUT", "/kv/k", b"two")[0], 204)
        self.assertEqual(self.request("GET", "/kv/k"), (200, b"two"))

    def test_missing_and_invalid(self):
        self.assertEqual(self.request("GET", "/kv/nope")[0], 404)
        self.assertEqual(self.request("GET", "/kv/..secret")[0], 400)
        self.assertEqual(self.request("GET", "/other")[0], 404)

    def test_values_survive_a_restart(self):
        self.request("PUT", "/kv/durable", b"still here")
        self.assertEqual(Store(self.tmp.name).get("durable"), b"still here")

    def test_healthz(self):
        self.assertEqual(self.request("GET", "/healthz"), (200, b"ok\n"))


if __name__ == "__main__":
    unittest.main()
```

### The package

Written exactly like a `pkgs/by-name/*/package.nix` (course 07): a function of its
dependencies, `finalAttrs`, `__structuredAttrs`, `meta` last. The Python specifics come from the
nixpkgs manual's Python section (`doc/languages-frameworks/python.section.md`):

- `pyproject = true` builds a wheel the PEP 517 way (`pypaBuildHook`) and installs it
  (`pypaInstallHook`); `build-system` lists what `[build-system] requires` needs.
- `buildPythonApplication`, not `buildPythonPackage`: an application's modules aren't meant to
  be imported by other packages, so it isn't prefixed with the Python version.
- Python packages have no `checkPhase` — tests run in `installCheckPhase`, *against the
  installed package*, which is why the tests import `kvstore` rather than `src.kvstore`.
  `unittestCheckHook` runs `python -m unittest discover`; `pythonImportsCheck` is a cheap
  "does it import" smoke test.

```nix file=nix/package.nix
{
  lib,
  python3Packages,
  testers,
}:

let
  # pyproject.toml is the one place the version is written down.
  pyprojectToml = lib.importTOML ../pyproject.toml;
in
python3Packages.buildPythonApplication (finalAttrs: {
  pname = "kvstore";
  inherit (pyprojectToml.project) version;
  pyproject = true;

  __structuredAttrs = true;

  # Only what the build needs: editing flake.nix or the README doesn't rebuild the package.
  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../pyproject.toml
      ../src
      ../tests
    ];
  };

  build-system = [ python3Packages.setuptools ];

  nativeCheckInputs = [ python3Packages.unittestCheckHook ];
  unittestFlags = [
    "-s"
    "tests"
    "-v"
  ];

  pythonImportsCheck = [ "kvstore" ];

  passthru.tests.version = testers.testVersion { package = finalAttrs.finalPackage; };

  meta = {
    description = "Tiny HTTP key-value store built on the Python standard library";
    license = lib.licenses.mit;
    mainProgram = "kvstore";
    platforms = lib.platforms.linux;
  };
})
```

Because it's a plain `callPackage` function, it builds without any flake — with the pinned
nixpkgs every lesson uses:

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

```bash timeout=1800
nix-build -E 'with import ./nixpkgs.nix { }; callPackage ./nix/package.nix { }'
./result/bin/kvstore --version
nix log ./result | grep -E '^Ran [0-9]+ tests|^OK$|pythonImportsCheckPhase'
```

```text expect
kvstore 1.0.0
Ran 7 tests
OK
pythonImportsCheckPhase
```

The version came from `pyproject.toml` twice: Nix read it with `importTOML`, and Python read
it from the installed package metadata. Now use it — start it in the background, store a value,
read it back, stop it:

```bash
./result/bin/kvstore --port 18080 --data-dir ./data &
server=$!
for _ in $(seq 50); do curl -fsS http://127.0.0.1:18080/healthz > /dev/null 2>&1 && break; sleep 0.2; done
curl -fsS -X PUT --data-binary 'hello nix' -w 'PUT %{http_code}\n' http://127.0.0.1:18080/kv/greeting
curl -fsS http://127.0.0.1:18080/kv/greeting && echo
curl -sS -o /dev/null -w 'GET missing %{http_code}\n' http://127.0.0.1:18080/kv/missing
kill "$server" && wait "$server"
ls data
```

```text expect
PUT 201
hello nix
GET missing 404
greeting
```

## Stage 2 · The flake

The flake is a thin layer over `nix/package.nix`. Read it top to bottom; the stage comments say
when each part becomes real.

```nix file=flake.nix
{
  description = "kvstore: a tiny HTTP key-value service, packaged, tested and deployed with Nix";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { self, nixpkgs }:
    let
      inherit (nixpkgs) lib;
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      # nixpkgs for each system with our overlay applied, so `pkgs.kvstore` exists.
      forAllSystems =
        f: lib.genAttrs systems (system: f (nixpkgs.legacyPackages.${system}.extend self.overlays.default));
    in
    {
      # Any nixpkgs user can add kvstore to their package set with this.
      overlays.default = final: prev: {
        kvstore = final.callPackage ./nix/package.nix { };
      };

      packages = forAllSystems (pkgs: {
        default = pkgs.kvstore;
        kvstore = pkgs.kvstore;
        # Stage 4
        dockerImage = pkgs.callPackage ./nix/image.nix { };
      });

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShellNoCC {
          # Everything needed to build kvstore, plus tools for working on it.
          inputsFrom = [ pkgs.kvstore ];
          packages = [
            pkgs.python3
            pkgs.curl
            pkgs.nixfmt
          ];
          shellHook = ''
            export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
          '';
        };
      });

      # `nix fmt`: treefmt with nixfmt, the formatter nixpkgs uses.
      formatter = forAllSystems (pkgs: pkgs.nixfmt-tree);

      # `nix flake check` builds all of these.
      checks = forAllSystems (pkgs: {
        # Building the package runs the unit tests (unittestCheckHook).
        package = pkgs.kvstore;
        version = pkgs.kvstore.tests.version;
        formatting =
          pkgs.runCommand "kvstore-check-formatting" { nativeBuildInputs = [ pkgs.nixfmt ]; }
            ''
              cd ${self}
              nixfmt --check $(find . -name '*.nix')
              touch $out
            '';
        # Stage 3
        vm = pkgs.callPackage ./nix/vm-test.nix { inherit self; };
      });

      # Stage 3: the module, defaulting `package` to this flake's build of kvstore.
      nixosModules.default =
        { lib, pkgs, ... }:
        {
          imports = [ ./nix/module.nix ];
          services.kvstore.package =
            lib.mkDefault
              self.packages.${pkgs.stdenv.hostPlatform.system}.kvstore;
        };
    };
}
```

`nix/image.nix`, `nix/module.nix` and `nix/vm-test.nix` don't exist yet. That's fine: flake
outputs are lazy attributes, and nothing evaluates `checks.vm` or `packages.dockerImage` until
you ask for them. (`nix flake show` and `nix flake check` *would* ask — you'll run them in
stage 5.)

Flakes only see files Git knows about. Make it a repository, with an identity for this
repository only, and keep build outputs, data and — above all — secret keys out of it:

```text file=.gitignore
result*
/image
/data/
/cache/
*.sec
__pycache__/
*.egg-info/
```

```bash
git init -q -b main
git config user.name "Nix Mastery Learner"
git config user.email "learner@example.com"
git add .
nix flake lock
git add flake.lock
nix flake metadata 2>&1 | grep -E 'Locked URL|nixpkgs'
```

```text expect
github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808
```

Build through the flake. It's the *same derivation* as stage 1 — same nixpkgs source, and the
`fileset` source is identical — so nothing is rebuilt:

```bash timeout=1800
classic=$(nix-instantiate -E 'with import ./nixpkgs.nix { }; callPackage ./nix/package.nix { }')
flake=$(nix eval --raw .#kvstore.drvPath)
[ "$classic" = "$flake" ] && echo "same derivation: $flake"
nix run . -- --version
```

```text expect
same derivation: /nix/store/
kvstore-1.0.0.drv
kvstore 1.0.0
```

The dev shell is for working on the code *without* building the package: the tests run
against `src/` directly.

```bash timeout=1800
nix develop -c env PYTHONPATH=src python3 -m unittest discover -s tests 2>&1 | tail -n 3
```

```text expect
Ran 7 tests
OK
```

And `nix fmt` formats every Nix file with nixfmt (`nixfmt-tree` is treefmt preconfigured for it):

```bash
nix fmt
git add -A
git status --short
```

## Stage 3 · A NixOS module and a VM test

### The module

The module is the interface an operator sees: typed options with defaults and descriptions, and
an implementation that turns them into a systemd unit (course 06 L4). Two design decisions:

- **No system user.** `DynamicUser = true` makes systemd allocate a UID when the service starts
  and release it when it stops; `StateDirectory` makes systemd create and own the data
  directory (under `/var/lib/private`, with a `/var/lib/<name>` symlink). That is why
  `dataDir` must be under `/var/lib` — an *assertion* says so at evaluation time, before
  anything is built.
- **Sandboxing.** `DynamicUser` already implies `ProtectSystem=strict`, `PrivateTmp` and
  more; the rest of the list removes what an HTTP server never needs: capabilities, devices,
  kernel tunables, other address families, privileged system calls. See `systemd.exec(5)`.

```nix file=nix/module.nix
{
  config,
  lib,
  pkgs,
  utils,
  ...
}:

let
  cfg = config.services.kvstore;
in
{
  options.services.kvstore = {
    enable = lib.mkEnableOption "kvstore, a tiny HTTP key-value service";

    package = lib.mkPackageOption pkgs "kvstore" { };

    listenAddress = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
      example = "0.0.0.0";
      description = "Address the service listens on.";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8080;
      description = "TCP port the service listens on.";
    };

    dataDir = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/kvstore";
      description = ''
        Directory holding one file per key. It must be below {file}`/var/lib`,
        because systemd creates and owns it as the unit's `StateDirectory=`.
      '';
    };

    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether to open {option}`services.kvstore.port` in the firewall.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = lib.hasPrefix "/var/lib/" cfg.dataDir;
        message = "services.kvstore.dataDir must be below /var/lib/ (it is a systemd StateDirectory), got ${cfg.dataDir}";
      }
    ];

    systemd.services.kvstore = {
      description = "kvstore HTTP key-value service";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];

      serviceConfig = {
        # Quoted for systemd (which also expands % and $), not for a shell.
        ExecStart = utils.escapeSystemdExecArgs [
          (lib.getExe cfg.package)
          "--host"
          cfg.listenAddress
          "--port"
          cfg.port
          "--data-dir"
          cfg.dataDir
        ];
        Restart = "on-failure";

        DynamicUser = true;
        StateDirectory = lib.removePrefix "/var/lib/" cfg.dataDir;
        StateDirectoryMode = "0700";
        UMask = "0077";

        CapabilityBoundingSet = "";
        LockPersonality = true;
        NoNewPrivileges = true;
        PrivateDevices = true;
        PrivateUsers = true;
        ProtectClock = true;
        ProtectControlGroups = true;
        ProtectHome = true;
        ProtectHostname = true;
        ProtectKernelLogs = true;
        ProtectKernelModules = true;
        ProtectKernelTunables = true;
        ProtectProc = "invisible";
        RestrictAddressFamilies = [
          "AF_INET"
          "AF_INET6"
          "AF_UNIX"
        ];
        RestrictNamespaces = true;
        RestrictRealtime = true;
        SystemCallArchitectures = "native";
        SystemCallFilter = [
          "@system-service"
          "~@privileged"
        ];
      };
    };

    networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ cfg.port ];
  };
}
```

`package = lib.mkPackageOption pkgs "kvstore" { }` defaults to `pkgs.kvstore`, which exists only
where the overlay is applied. The flake's `nixosModules.default` therefore imports this file
*and* sets `package` with `lib.mkDefault` to the flake's own build — so the module works on any
NixOS, with or without the overlay, and users can still override it.

### Inspect before you boot

You don't need a VM to see what the module produces. Evaluate a minimal NixOS configuration
that uses it (`boot.isContainer` spares us a bootloader and file systems), and print the unit
file it generates:

```nix file=eval-system.nix
# Evaluate (not build) a NixOS system that uses the module, for inspection.
{
  settings ? { },
}:

let
  flake = builtins.getFlake (toString ./.);
in
flake.inputs.nixpkgs.lib.nixosSystem {
  modules = [
    flake.nixosModules.default
    {
      nixpkgs.hostPlatform = builtins.currentSystem;
      boot.isContainer = true;
      system.stateVersion = "26.05";
      services.kvstore = {
        enable = true;
      }
      // settings;
    }
  ];
}
```

```bash timeout=1800
git add -A
nix eval --impure --raw -f eval-system.nix 'config.systemd.units."kvstore.service".text' \
  | grep -E '^(ExecStart|DynamicUser|StateDirectory|SystemCallFilter)='
```

```text expect
DynamicUser=true
StateDirectory=kvstore
/bin/kvstore" "--host" "127.0.0.1" "--port" "8080" "--data-dir" "/var/lib/kvstore"
```

An option value that breaks the module's contract fails at evaluation, with your message:

```bash fails
nix eval --impure -f eval-system.nix --arg settings '{ dataDir = "/srv/kv"; }' config.system.build.toplevel.drvPath
```

```text expect
services.kvstore.dataDir must be below /var/lib/
```

### The VM test

Now prove it on real machines. `pkgs.testers.runNixOSTest` (`doc/build-helpers/testers.chapter.md`)
boots one QEMU VM per node on a virtual network; the Python test script drives them. The
`server` runs the module; the `client` is a separate machine that only has `curl`:

```nix file=nix/vm-test.nix
# Two machines: the server runs the module, the client talks to it over the network.
{ self, testers }:

testers.runNixOSTest {
  name = "kvstore";

  defaults.system.stateVersion = "26.05";

  nodes = {
    server = {
      imports = [ self.nixosModules.default ];
      services.kvstore = {
        enable = true;
        listenAddress = "0.0.0.0";
        openFirewall = true;
      };
    };

    client =
      { pkgs, ... }:
      {
        environment.systemPackages = [ pkgs.curl ];
      };
  };

  testScript = ''
    start_all()

    server.wait_for_unit("kvstore.service")
    server.wait_for_open_port(8080, "127.0.0.1")
    client.wait_for_unit("multi-user.target")

    with subtest("a client can PUT and then GET a value over the network"):
        client.succeed("curl -fsS -X PUT --data-binary 'hello from the client' http://server:8080/kv/greeting")
        value = client.succeed("curl -fsS http://server:8080/kv/greeting")
        assert value == "hello from the client", f"unexpected value: {value!r}"

    with subtest("missing keys are 404"):
        client.fail("curl -fsS http://server:8080/kv/missing")

    with subtest("values survive a service restart"):
        server.succeed("systemctl restart kvstore.service")
        server.wait_for_open_port(8080, "127.0.0.1")
        value = client.succeed("curl -fsS http://server:8080/kv/greeting")
        assert value == "hello from the client", f"lost after restart: {value!r}"

    with subtest("the service runs as an unprivileged dynamic user"):
        uid = server.succeed("stat -c %u /var/lib/private/kvstore/greeting").strip()
        assert uid != "0", "the value file is owned by root"
        print(server.succeed("systemd-analyze security kvstore.service | tail -n 1"))
  '';
}
```

The client reaches the server by name (`http://server:8080`): the test framework puts every
node in every node's `/etc/hosts`. The firewall is on by default in test VMs, so the request
also proves `openFirewall` works. Format, stage, and run it — with KVM a few minutes, without
(emulated) much longer:

```bash timeout=3600
nix fmt
git add -A
system=$(nix eval --impure --raw --expr builtins.currentSystem)
nix build --no-link ".#checks.$system.vm"
nix log ".#checks.$system.vm" | grep -E 'subtest: |Overall exposure level'
```

```text expect
subtest: a client can PUT and then GET a value over the network
subtest: missing keys are 404
subtest: values survive a service restart
subtest: the service runs as an unprivileged dynamic user
Overall exposure level for kvstore.service
```

`systemd-analyze security` scores a unit's sandboxing from 0 (locked down) to 10; a default
unit with no hardening scores around 9.6 ("UNSAFE").

## Stage 4 · A container image and a signed cache

### The image

`dockerTools.buildLayeredImage` (course 05 L3) turns the package's closure into an OCI/Docker
image — no Dockerfile, no base image, reproducible. Each store path tends to get its own layer,
so images built from the same nixpkgs share layers.

```nix file=nix/image.nix
# A Docker/OCI image of kvstore, built without a Dockerfile.
{ dockerTools, kvstore }:

dockerTools.buildLayeredImage {
  name = "kvstore";
  tag = kvstore.version;

  contents = [ kvstore ];

  # /data must exist and belong to the unprivileged user the container runs as.
  fakeRootCommands = ''
    mkdir -p data
    chown 65534:65534 data
  '';

  config = {
    Cmd = [
      "/bin/kvstore"
      "--host"
      "0.0.0.0"
      "--port"
      "8080"
      "--data-dir"
      "/data"
    ];
    User = "65534:65534";
    ExposedPorts."8080/tcp" = { };
    Volumes."/data" = { };
  };
}
```

```bash timeout=1800
git add -A
nix build .#dockerImage -o image
ls -l image
```

The result is a gzipped tarball in the format `docker load` reads. You don't need Docker to see
inside it: the manifest names the image and lists one tarball per layer, and the config holds
the command and user:

```bash
tar -tzf image | grep -c 'layer.tar$'
tar -xzOf image manifest.json | grep -A1 RepoTags
config=$(tar -xzOf image manifest.json | python3 -c 'import json, sys; print(json.load(sys.stdin)[0]["Config"])')
tar -xzOf image "$config" | python3 -c 'import json, sys; c = json.load(sys.stdin)["config"]; print(c["Cmd"]); print("User", c["User"])'
```

```text expect
"kvstore:1.0.0"
['/bin/kvstore', '--host', '0.0.0.0', '--port', '8080', '--data-dir', '/data']
User 65534:65534
```

With Docker or Podman installed you would run it like this (not run here):

```console
$ docker load < image
Loaded image: kvstore:1.0.0
$ docker run --rm -p 8080:8080 -v kvdata:/data kvstore:1.0.0
```

### A signed binary cache

Anyone who wants your package can rebuild it — or download it, if they trust whoever built it.
Trust is a signing key (course 05 L2). Make one, copy the package's closure into a file-based
cache, signing every path on the way:

```bash timeout=1800
nix key generate-secret --key-name kvstore-cache-1 > cache.sec
nix key convert-secret-to-public < cache.sec > cache.pub
pkg=$(nix build .#kvstore --no-link --print-out-paths)
nix copy --to "file://$PWD/cache?secret-key=$PWD/cache.sec&compression=zstd" "$pkg"
ls cache | grep -c '\.narinfo$'
nix path-info --store "file://$PWD/cache" --sigs "$pkg"
```

```text expect
kvstore-cache-1:
```

A client that trusts `cache.pub` accepts the path; one that trusts some other key doesn't:

```bash
nix store verify --store "file://$PWD/cache" --trusted-public-keys "$(cat cache.pub)" "$pkg"
echo "verified with kvstore-cache-1"
nix key generate-secret --key-name someone-else | nix key convert-secret-to-public > other.pub
```

```text expect
verified with kvstore-cache-1
```

```bash fails
nix store verify --store "file://$PWD/cache" --trusted-public-keys "$(cat other.pub)" "$pkg"
```

```bash
rm other.pub
```

In production the cache would be an S3 bucket or a service like Cachix or Attic, and users
would add `extra-substituters` and `extra-trusted-public-keys` to their `nix.conf` — or your
flake's `nixConfig`. `cache.sec` never leaves the machine that builds; `.gitignore` already
keeps it out of the repository.

## Stage 5 · CI for your own repository

### The workflow

Because every check is in the flake, CI only needs Nix and KVM. This is a template for your own
GitHub repository (this path's CI doesn't run it, it validates it):

```yaml file=.github/workflows/ci.yml
# Runs every check in the flake on each push to main and on each pull request.
name: CI

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  check:
    runs-on: ubuntu-24.04
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v5

      - uses: cachix/install-nix-action@v31
        with:
          extra_nix_config: |
            system-features = nixos-test benchmark big-parallel kvm

      # GitHub's Linux runners have /dev/kvm, but only root may open it until
      # this rule is in place. NixOS VM tests need it to run at full speed.
      - name: Enable KVM
        run: |
          echo 'KERNEL=="kvm", GROUP="kvm", MODE="0666", OPTIONS+="static_node=kvm"' \
            | sudo tee /etc/udev/rules.d/99-kvm4all.rules
          sudo udevadm control --reload-rules
          sudo udevadm trigger --name-match=kvm

      # Optional: push what CI builds to a binary cache (stage 4), e.g. with Cachix:
      # - uses: cachix/cachix-action@v16
      #   with:
      #     name: your-cache
      #     authToken: ${{ secrets.CACHIX_AUTH_TOKEN }}

      - name: Formatting, build, unit tests and VM test
        run: nix flake check --print-build-logs

      - name: Container image
        run: nix build --print-build-logs .#dockerImage
```

Validate it with `actionlint` (which also runs `shellcheck` on every `run:` script), taken from
the same pinned nixpkgs as the flake:

```bash timeout=1800
nix run github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808#actionlint -- .github/workflows/ci.yml
echo "actionlint: no problems"
```

```text expect
actionlint: no problems
```

It catches the mistakes that otherwise only show up after you push. For example, a job that
`needs` a job that doesn't exist:

```yaml file=scratch/broken.yml
name: Broken
on: push
jobs:
  check:
    needs: build
    runs-on: ubuntu-24.04
    steps:
      - run: echo hi
```

```bash fails
nix run github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808#actionlint -- scratch/broken.yml
```

```bash
rm -r scratch
```

### The final check

Everything together. `nix flake show` evaluates every output for this system (now that all the
files exist), and `nix flake check` evaluates them all and builds every check — formatting,
package and unit tests, version test, and the VM test (already built in stage 3, so it's
reused):

```bash timeout=3600
nix fmt
git add -A
nix flake show 2>&1 | grep -E 'NixOS module|kvstore|dockerImage|devShell|formatter'
nix flake check --print-build-logs
echo "all checks passed"
```

```text expect
NixOS module
dockerImage
all checks passed
```

Commit the result — this is the repository you show:

```bash
git add -A
git commit -q -m "kvstore: service, package, module, VM test, image and CI"
git log --oneline
git ls-files
```

```text expect
flake.lock
nix/module.nix
nix/vm-test.nix
.github/workflows/ci.yml
```

## Verification

- [ ] `nix-build -E '… callPackage ./nix/package.nix { }'` and `nix build .#kvstore` produce the
  same derivation, and its build log shows the unit tests ran;
- [ ] `nix develop` runs the tests against `src/`, `nix fmt` formats, `nix run . -- --version`
  prints `kvstore 1.0.0`;
- [ ] the module's unit has `DynamicUser=true` and `StateDirectory=kvstore`, and a bad `dataDir`
  fails evaluation with the module's message;
- [ ] the VM test passes all four subtests;
- [ ] the image's manifest says `kvstore:1.0.0` and its config runs as `65534:65534`;
- [ ] `nix store verify` accepts the cached path with `cache.pub` and rejects it with another key;
- [ ] `actionlint` accepts `ci.yml`, and `nix flake check` passes.

## Stretch goals

- **Publish it.** Push the repository to GitHub and watch `ci.yml` run. Add a Cachix cache (free
  for public projects) and uncomment the cache step.
- **Harder hardening.** Add `MemoryDenyWriteExecute = true` and `IPAddressAllow`/`IPAddressDeny`;
  re-run the VM test and compare the `systemd-analyze security` score. (Why is
  `MemoryDenyWriteExecute` fine for this CPython program but not for everything written in
  Python?)
- **Socket activation.** Let systemd own the port: a `systemd.sockets.kvstore` unit, and have the
  server accept the inherited file descriptor (`LISTEN_FDS`). Extend the VM test to check the
  service isn't running until the first request.
- **A second client.** Add a third node that tries to reach the server when `openFirewall` is
  false on a second server instance, and assert that it fails.
- **Upstream it.** Move `nix/package.nix` into a nixpkgs checkout as
  `pkgs/by-name/kv/kvstore/package.nix` (with a `fetchFromGitHub` source) and the module into
  `nixos/modules/services/misc/`, then go through course 07's project checklist.
- **Run the image under NixOS.** Use `virtualisation.oci-containers` in a third VM-test node to
  run `packages.dockerImage` and talk to it from the client.
