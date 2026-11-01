# Project 06a — Typed config generator

**Goal:** build a small tool that turns a Nix description of an application's settings into a
validated `app.toml`. Bad values are rejected *before* any file exists: wrong types, unknown
enum values, values TOML can't represent, and combinations that make no sense. This is how NixOS
modules generate configuration files for services, here without NixOS.

**You will practise:**

- **options are an interface**: a schema module declares the settings you know about, with types
  and defaults;
- **freeform settings** (NixOS RFC 42): `freeformType = format.type` passes through settings the
  schema doesn't know, but still type-checks them as TOML;
- **`pkgs.formats`**: `format.type` validates, `format.generate` renders
  (`pkgs/pkgs-lib/formats.nix`);
- **assertions and warnings** for rules about several settings, checked with
  `lib.asserts.checkAssertWarn`;
- **docs from types**: the same options produce reference documentation.

## 1. The pieces

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

The schema. Read `settings`: a submodule whose declared options are typed, and whose
`freeformType` accepts anything else as long as it is valid TOML.

```nix file=schema.nix
{
  config,
  lib,
  pkgs,
  ...
}:
let
  inherit (lib) mkOption types;
  format = pkgs.formats.toml { };
  cfg = config.app;
  s = cfg.settings;
in
{
  options = {
    assertions = mkOption {
      type = types.listOf types.unspecified;
      default = [ ];
      internal = true;
    };
    warnings = mkOption {
      type = types.listOf types.str;
      default = [ ];
      internal = true;
    };

    app = {
      name = mkOption {
        type = types.strMatching "[a-z][a-z0-9-]*";
        description = "Application name; also the name of the generated file.";
      };

      settings = mkOption {
        default = { };
        description = ''
          Contents of the generated TOML file. The options below are checked
          precisely; any other key is passed through, but must be valid TOML.
        '';
        type = types.submodule {
          freeformType = format.type;
          options = {
            server.host = mkOption {
              type = types.str;
              default = "127.0.0.1";
              description = "Address to listen on.";
            };
            server.port = mkOption {
              type = types.port;
              default = 8080;
              description = "Port to listen on.";
            };
            log.level = mkOption {
              type = types.enum [
                "error"
                "warn"
                "info"
                "debug"
              ];
              default = "info";
              description = "Log level.";
            };
            database.url = mkOption {
              type = types.nullOr (types.strMatching "(postgres|sqlite)://.+");
              default = null;
              description = "Database URL. Omitted from the file when null.";
            };
            tls.enable = mkOption {
              type = types.bool;
              default = false;
              description = "Serve over TLS.";
            };
            tls.certFile = mkOption {
              type = types.nullOr types.str;
              default = null;
              description = "Path to the certificate. Required when TLS is on.";
            };
          };
        };
      };

      configFile = mkOption {
        type = types.package;
        readOnly = true;
        description = "The rendered TOML file (output, don't set).";
      };
    };
  };

  config = {
    # TOML has no null: drop unset optional values before rendering.
    app.configFile = format.generate "${cfg.name}.toml" (
      lib.filterAttrsRecursive (_: v: v != null) s
    );

    assertions = [
      {
        assertion = s.tls.enable -> s.tls.certFile != null;
        message = "app.settings.tls.enable = true needs app.settings.tls.certFile.";
      }
      {
        assertion = s.server.host == "0.0.0.0" -> s.tls.enable;
        message = "Listening on all interfaces (0.0.0.0) requires app.settings.tls.enable.";
      }
    ];

    warnings = lib.optional (
      s.log.level == "debug"
    ) "app.settings.log.level = \"debug\" logs request bodies; don't use it in production.";
  };
}
```

The tool. It evaluates the schema with one user file, refuses to continue if an assertion
fails, and offers three outputs: the file, the merged settings (for debugging), and the docs.

```nix file=generate.nix
{
  userConfig ? ./app.nix,
}:
let
  pkgs = import ./nixpkgs.nix { };
  inherit (pkgs) lib;

  eval = lib.evalModules {
    modules = [
      { _module.args = { inherit pkgs; }; }
      ./schema.nix
      userConfig
    ];
  };
  inherit (eval) config;

  checked = lib.asserts.checkAssertWarn config.assertions config.warnings;
in
{
  file = checked config.app.configFile;

  settings = checked config.app.settings;

  docs = map (o: { inherit (o) name type description; }) (
    lib.filter (o: o.visible && !o.internal && lib.hasPrefix "app." o.name) (
      lib.optionAttrSetToDocList eval.options
    )
  );
}
```

## 2. A good configuration

```nix file=app.nix
{
  app.name = "shop";
  app.settings = {
    server.port = 9000;
    log.level = "warn";
    database.url = "postgres://db.internal/shop";

    # Not in the schema: passed through by the freeform type.
    cache = {
      size_mb = 256;
      backends = [ "redis://cache.internal:6379" ];
    };
  };
}
```

Render it:

```bash timeout=1800
nix-build generate.nix -A file -o shop.toml
cat shop.toml
```

```text expect
[cache]
size_mb = 256
[database]
url = "postgres://db.internal/shop"
[log]
level = "warn"
[server]
host = "127.0.0.1"
port = 9000
```

Defaults filled in (`server.host`), the freeform `cache` section passed through, and the null
`tls.certFile` was dropped. Is the result really TOML? Parse it back with a different tool than
the one that wrote it. `nix shell --file ./nixpkgs.nix python3` takes Python from the same pin:

```bash
nix shell --file ./nixpkgs.nix python3 --command python3 -c '
import tomllib
d = tomllib.load(open("shop.toml", "rb"))
print("port", d["server"]["port"], "cache", d["cache"]["size_mb"])'
```

```text expect
port 9000 cache 256
```

## 3. Validation catches bad values

Every check below happens during evaluation. No file is written.

**Wrong type** for a declared setting:

```nix file=bad-port.nix
{
  imports = [ ./app.nix ];
  app.settings.server.port = lib.mkForce 99999;
}
```

Oops: that module uses `lib` without taking it as an argument. Nix says so, and that is your
first error:

```bash fails
nix-build generate.nix -A file --arg userConfig ./bad-port.nix
```

```text expect
undefined variable 'lib'
```

Fixed, it reaches the type check:

```nix file=bad-port.nix
{ lib, ... }:
{
  imports = [ ./app.nix ];
  app.settings.server.port = lib.mkForce 99999;
}
```

```bash fails
nix-build generate.nix -A file --arg userConfig ./bad-port.nix
```

```text expect
A definition for option `app.settings.server.port' is not of type `16 bit unsigned integer
```

**A value outside an enum**, and **a malformed URL** (`strMatching`):

```nix file=bad-level.nix
{ lib, ... }:
{
  imports = [ ./app.nix ];
  app.settings.log.level = lib.mkForce "loud";
}
```

```bash fails
nix-build generate.nix -A file --arg userConfig ./bad-level.nix
```

```text expect
is not of type `one of "error", "warn", "info", "debug"'
```

```nix file=bad-url.nix
{ lib, ... }:
{
  imports = [ ./app.nix ];
  app.settings.database.url = lib.mkForce "mysql://db";
}
```

```bash fails
nix-build generate.nix -A file --arg userConfig ./bad-url.nix
```

```text expect
app.settings.database.url
string matching the pattern (postgres|sqlite)://.+
```

**A freeform value that TOML can't represent.** The schema doesn't know `cache.ttl`, but the
freeform type still checks it:

```nix file=bad-freeform.nix
{
  imports = [ ./app.nix ];
  app.settings.cache.ttl = null;
}
```

```bash fails
nix-build generate.nix -A file --arg userConfig ./bad-freeform.nix
```

```text expect
TOML value
```

**A combination that makes no sense**, caught by an assertion. Each value is fine on its own:

```nix file=bad-tls.nix
{
  imports = [ ./app.nix ];
  app.settings.server.host = "0.0.0.0";
}
```

```bash fails
nix-build generate.nix -A file --arg userConfig ./bad-tls.nix
```

```text expect
Failed assertions:
- Listening on all interfaces (0.0.0.0) requires app.settings.tls.enable.
```

Fix it the way the message asks. That trips the *other* assertion, which is what you want:

```nix file=half-tls.nix
{
  imports = [ ./app.nix ];
  app.settings.server.host = "0.0.0.0";
  app.settings.tls.enable = true;
}
```

```bash fails
nix-build generate.nix -A file --arg userConfig ./half-tls.nix
```

```text expect
- app.settings.tls.enable = true needs app.settings.tls.certFile.
```

## 4. Warnings don't stop the build

```nix file=debug.nix
{ lib, ... }:
{
  imports = [ ./app.nix ];
  app.settings.log.level = lib.mkForce "debug";
}
```

```bash
nix-build generate.nix -A file --arg userConfig ./debug.nix -o debug.toml
grep level debug.toml
```

```text expect
evaluation warning: app.settings.log.level = "debug" logs request bodies
level = "debug"
```

## 5. Documentation for free

The types and descriptions you wrote are the reference manual. This is how the NixOS options
search is built (`nixos/lib/make-options-doc/`):

```bash
nix-instantiate --eval --strict --json generate.nix -A docs > docs.json
nix shell --file ./nixpkgs.nix jq --command jq -r '.[] | "\(.name): \(.type)"' docs.json
```

```text expect
app.name: string matching the pattern [a-z][a-z0-9-]*
app.settings.server.port: 16 bit unsigned integer; between 0 and 65535 (both inclusive)
app.settings.log.level: one of "error", "warn", "info", "debug"
app.settings.database.url: null or string matching the pattern (postgres|sqlite)://.+
```

## 6. Verify

All of it, as one script that fails loudly if any check doesn't behave:

```bash timeout=1800
ok=0
nix-build generate.nix -A file -o verify.toml > /dev/null 2>&1 && grep -q 'port = 9000' verify.toml && ok=$((ok+1))
for bad in bad-port bad-level bad-url bad-freeform bad-tls half-tls; do
  if nix-build generate.nix -A file --arg userConfig ./$bad.nix --no-out-link > /dev/null 2>&1; then
    echo "NOT REJECTED: $bad"; exit 1
  else
    ok=$((ok+1))
  fi
done
echo "checks passed: $ok of 7"
```

```text expect
checks passed: 7 of 7
```

## Stretch goals

1. **Another format.** Switch to `pkgs.formats.json { }` or `pkgs.formats.ini { }`. Which of
   your freeform values does INI reject, and why? (Look at `iniSection` in `formats.nix`.)
2. **Secrets.** A `database.passwordFile` setting must *not* put the password in the store
   (everything in `/nix/store` is world-readable). How do NixOS modules handle this? Read
   `nixos/modules/services/web-apps/` for `passwordFile` and `LoadCredential=`.
3. **Make it a NixOS module.** Wrap the schema as `services.shop.settings` and write the file to
   `environment.etc."shop/shop.toml".source = cfg.configFile;`. Lesson 06.4 shows the rest.
4. **Type merging.** Declare `app.settings.server.port` a second time in another module with the
   same type. What happens? With a different type? (`lib/modules.nix`: options can be declared
   once, but `submodule` types merge.)
