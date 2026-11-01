# Lesson 06.1 — The module system on its own: `lib.evalModules`

**You will:** describe a small web server's configuration as typed options, merge the settings
of several modules, override with priorities, make settings conditional with `mkIf`, split
modules with `imports`, add NixOS-style assertions, and watch the type checker reject bad values.
No NixOS is involved, only `lib.evalModules` from nixpkgs' `lib`.

## What `evalModules` does

`lib.evalModules { modules = [ m1 m2 … ]; }` (in `lib/modules.nix`) takes a list of *modules* and
returns `{ config, options, … }`. A module is an attribute set, or a function returning one, with
up to three parts:

```nix
{ config, lib, ... }:      # every module receives the FINAL config (and lib, options, ...)
{
  imports = [ ./other.nix ];   # more modules to include
  options = { … };             # declarations: name, type, default, description
  config = { … };              # definitions: values for options (declared anywhere)
}
```

The algorithm, simplified:

1. Collect all modules, following `imports` recursively.
2. Merge all `options` declarations into one tree. An option may be declared only once, but a
   submodule type can be extended by several declarations.
3. For each option, gather every module's definitions for it, keep only those with the best
   **priority**, check each against the option's **type**, and merge them with the type's merge
   function. If there are none, use the `default`.
4. That merged tree is `config`. It is passed back into every module that asked for `config`.
   That makes it a fixed point, and laziness makes it computable.

A module with neither `options` nor `config` (nor `imports`) is shorthand for `config`. So
`{ server.port = 80; }` means `{ config.server.port = 80; }`.

## Set up

The lesson uses nixpkgs' `lib` from the pinned nixpkgs:

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

`eval.nix` takes a list of modules and evaluates them:

```nix file=eval.nix
modules:
let
  lib = (import ./nixpkgs.nix { }).lib;
in
lib.evalModules { inherit modules; }
```

## 1. Declare options

`options.nix` is the *interface*: what can be configured, with which types and defaults. It
doesn't set anything.

```nix file=options.nix
{ lib, ... }:
let
  inherit (lib) mkOption mkEnableOption types;
in
{
  options.server = {
    enable = mkEnableOption "the web server";

    hostName = mkOption {
      type = types.str;
      example = "www.example.org";
      description = "Public host name of the server.";
    };

    port = mkOption {
      type = types.port;
      default = 8080;
      description = "TCP port to listen on.";
    };

    logLevel = mkOption {
      type = types.enum [
        "error"
        "warn"
        "info"
        "debug"
      ];
      default = "info";
      description = "How much to log.";
    };

    workers = mkOption {
      type = types.int;
      default = 4;
      description = "Number of worker processes (1 to 64, checked by an assertion).";
    };

    allowedIPs = mkOption {
      type = types.listOf types.str;
      default = [ ];
      description = "Networks allowed to connect. Empty means everyone.";
    };

    headers = mkOption {
      type = types.attrsOf types.str;
      default = { };
      description = "Extra HTTP response headers.";
    };

    sites = mkOption {
      default = { };
      description = "Virtual hosts, by name.";
      type = types.attrsOf (
        types.submodule (
          { name, ... }:
          {
            options = {
              root = mkOption {
                type = types.str;
                description = "Directory to serve.";
              };
              serverName = mkOption {
                type = types.str;
                default = name; # the attribute name, e.g. "blog"
                description = "Host name this site answers to.";
              };
              tls = mkOption {
                type = types.bool;
                default = false;
                description = "Serve this site over HTTPS.";
              };
            };
          }
        )
      );
    };
  };
}
```

`mkEnableOption "x"` is shorthand for a `bool` option with `default = false` and the description
"Whether to enable x.". A `submodule` is a nested `evalModules`: each `sites.<name>` value is its
own small configuration with its own options and defaults, and receives its attribute name as
`name`.

`site.nix` is a *user* of the interface:

```nix file=site.nix
{
  server = {
    enable = true;
    hostName = "example.org";
    sites.blog.root = "/srv/blog";
    sites.shop = {
      root = "/srv/shop";
      tls = true;
    };
  };
}
```

Evaluate it. `--strict` forces the whole value (Nix is lazy, course 02), and `--json` prints it:

```bash
nix-instantiate --eval --strict --json -E '(import ./eval.nix [ ./options.nix ./site.nix ]).config.server'
```

```text expect
"enable":true
"hostName":"example.org"
"logLevel":"info"
"port":8080
"blog":{"root":"/srv/blog","serverName":"blog","tls":false}
"serverName":"shop","tls":true
```

Defaults filled in what `site.nix` didn't say, and each site got `serverName` from its own name.
The new CLI does the same with `nix eval --file`:

```bash
echo 'import ./eval.nix [ ./options.nix ./site.nix ]' > site-eval.nix
nix eval --json --file site-eval.nix config.server.sites.shop
```

```text expect
{"root":"/srv/shop","serverName":"shop","tls":true}
```

`hostName` has no default. Leave it out, and the error says which option is missing, but only
when something *uses* it, because evaluation is lazy:

```bash fails
nix-instantiate --eval --strict --json -E '(import ./eval.nix [ ./options.nix ]).config.server'
```

```text expect
The option `server.hostName' was accessed but has no value defined
```

The `options` half of the result is data too: types, defaults, descriptions, and where things
were declared and defined. This is what the NixOS manual and `search.nixos.org` are generated
from:

```bash
nix-instantiate --eval --strict --json -E '
  let o = (import ./eval.nix [ ./options.nix ./site.nix ]).options.server;
  in { portType = o.port.type.description; logLevelType = o.logLevel.type.description;
       hostNameDefinedIn = map baseNameOf o.hostName.files; }'
```

```text expect
"portType":"16 bit unsigned integer; between 0 and 65535 (both inclusive)"
"logLevelType":"one of \"error\", \"warn\", \"info\", \"debug\""
"hostNameDefinedIn":["site.nix"]
```

## 2. Merging: many modules, one value

Two teams each add to the same options:

```nix file=team.nix
{
  server.allowedIPs = [ "10.0.0.0/8" ];
  server.headers."X-Frame-Options" = "DENY";
}
```

```nix file=ops.nix
{
  server.allowedIPs = [ "192.168.0.0/16" ];
  server.headers."X-Content-Type-Options" = "nosniff";
}
```

```bash
nix-instantiate --eval --strict --json -E '
  let c = (import ./eval.nix [ ./options.nix ./site.nix ./team.nix ./ops.nix ]).config.server;
  in { inherit (c) allowedIPs headers; }'
```

```text expect
"10.0.0.0/8"
"192.168.0.0/16"
"X-Content-Type-Options":"nosniff"
"X-Frame-Options":"DENY"
```

The **type** decides how definitions merge: `listOf` concatenates, `attrsOf` merges by key (and
then merges values per key with the element type), `submodule` merges like a whole module.
Scalars (`str`, `int`, `port`, `enum`) can only merge when all definitions are equal. Two
different ports are a conflict:

```nix file=other-port.nix
{ server.port = 9090; }
```

```nix file=yet-another-port.nix
{ server.port = 8443; }
```

```bash fails
nix-instantiate --eval --strict --json -E '(import ./eval.nix [ ./options.nix ./site.nix ./other-port.nix ./yet-another-port.nix ]).config.server.port'
```

```text expect
The option `server.port' has conflicting definition values
other-port.nix
yet-another-port.nix
```

The message names the files, because every definition remembers where it came from.

## 3. Priorities: `mkDefault`, `mkForce`, `mkOverride`

Module order doesn't decide who wins. **Priority** does, and a lower number wins
(`lib/modules.nix`):

| Function | Priority | Typical use |
|---|---|---|
| option `default` | 1500 (`mkOptionDefault`) | the declaring module's fallback |
| `mkDefault v` | 1000 | profiles and library modules: "a sensible value, override me" |
| plain `v` | 100 | your configuration |
| `mkForce v` | 50 | "use this no matter what" |
| `mkOverride n v` | n | anything else, e.g. `mkVMOverride` is 10 |

Only definitions with the best (lowest) priority are kept. Then they are merged as above. A
"hardening profile" that suggests values:

```nix file=profile.nix
{ lib, ... }:
{
  server.port = lib.mkDefault 443;
  server.logLevel = lib.mkDefault "warn";
  server.workers = lib.mkOverride 900 8;
}
```

```nix file=override.nix
{ lib, ... }:
{
  server.port = 8443; # plain (100) beats the profile's mkDefault (1000)
  server.workers = lib.mkDefault 2; # 1000 loses to the profile's 900
  server.logLevel = lib.mkForce "debug"; # 50 beats everything here
}
```

```bash
nix-instantiate --eval --strict --json -E '
  let e = import ./eval.nix [ ./options.nix ./site.nix ./profile.nix ];
  in { inherit (e.config.server) port logLevel workers; }'
nix-instantiate --eval --strict --json -E '
  let e = import ./eval.nix [ ./options.nix ./site.nix ./profile.nix ./override.nix ];
  in { inherit (e.config.server) port logLevel workers;
       logLevelPriority = e.options.server.logLevel.highestPrio; }'
```

```text expect
{"logLevel":"warn","port":443,"workers":8}
{"logLevel":"debug","logLevelPriority":50,"port":8443,"workers":8}
```

So when NixOS says "use `mkForce` to override", what it means is "your plain definition
conflicts with one at the same priority (100) in some NixOS module; win by priority instead".
Use `mkForce` sparingly: it also silences definitions you didn't know about.

Lists are the exception that ordering *does* matter for. `mkBefore`/`mkAfter` (`mkOrder 500`
/ `mkOrder 1500`) sort list elements from different modules. They don't change priority.

## 4. Conditional configuration: `mkIf` and `mkMerge`

A module often sets other options depending on its own. It is tempting to write a plain `if`.
That recurses forever:

```nix file=bad-if.nix
{ config, ... }:
{
  config = if config.server.enable then { server.headers."Server" = "mini/1.0"; } else { };
}
```

```bash fails
nix-instantiate --eval --strict --json -E '(import ./eval.nix [ ./options.nix ./site.nix ./bad-if.nix ]).config.server.headers'
```

```text expect
infinite recursion encountered
```

Why: to compute `config.server.enable`, the module system must first know *which options every
module defines*. That means the attribute names of every module's `config`, including this one.
But this module's `config` attribute names depend on `config.server.enable`, so the value
depends on itself.

`mkIf cond value` solves it. It returns a marker, `{ _type = "if"; condition; content; }`, whose
*structure* is visible without evaluating `cond`. The module system pushes the condition down to
each option inside `content` and evaluates it only when that option is merged. `mkMerge [ … ]`
combines several such pieces in one module:

```nix file=features.nix
{ config, lib, ... }:
let
  cfg = config.server;
in
{
  config = lib.mkIf cfg.enable (
    lib.mkMerge [
      { server.headers."Server" = "mini/1.0"; }

      (lib.mkIf (cfg.logLevel == "debug") {
        server.headers."X-Debug" = "1";
      })

      (lib.mkIf (lib.any (site: site.tls) (lib.attrValues cfg.sites)) {
        server.headers."Strict-Transport-Security" = "max-age=31536000";
      })
    ]
  );
}
```

```bash
nix-instantiate --eval --strict --json -E '(import ./eval.nix [ ./options.nix ./site.nix ./features.nix ]).config.server.headers'
nix-instantiate --eval --strict --json -E '(import ./eval.nix [ ./options.nix ./site.nix ./features.nix ./override.nix ]).config.server.headers'
```

```text expect
{"Server":"mini/1.0","Strict-Transport-Security":"max-age=31536000"}
"X-Debug":"1"
```

`shop` has `tls = true`, so the HSTS header appeared. With `override.nix` (log level `debug`),
`X-Debug` appeared as well. This is the shape of almost every NixOS module:
`config = lib.mkIf cfg.enable { … };`.

## 5. `imports`: one module that brings its parts

Users shouldn't have to list `options.nix` and `features.nix` themselves. A module can import
others:

```nix file=server-module.nix
{
  imports = [
    ./options.nix
    ./features.nix
    ./checks.nix
  ];
}
```

`checks.nix` is next.

## 6. Assertions, the way NixOS does them

Types check one value at a time. Some rules relate several options, or are easier to say as a
condition: "`workers` must be 1–64", "enabling the server without any site is a mistake".
NixOS handles these with two options, `assertions` and `warnings`
(`nixos/modules/misc/assertions.nix`), and a check before it builds the system
(`nixos/modules/system/activation/top-level.nix`, which calls `lib.asserts.checkAssertWarn`).
Here is the same mechanism, written out.

The two options:

```nix file=assertions.nix
{ lib, ... }:
{
  options = {
    assertions = lib.mkOption {
      type = lib.types.listOf (
        lib.types.submodule {
          options = {
            assertion = lib.mkOption { type = lib.types.bool; };
            message = lib.mkOption { type = lib.types.str; };
          };
        }
      );
      default = [ ];
      description = "Conditions that must hold. Checked by checked.nix.";
    };
    warnings = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Messages to print during evaluation.";
    };
  };
}
```

The server module contributes rules. Because `assertions` is a `listOf`, every module just adds
its own:

```nix file=checks.nix
{ config, lib, ... }:
let
  cfg = config.server;
in
{
  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.workers >= 1 && cfg.workers <= 64;
        message = "server.workers must be between 1 and 64, got ${toString cfg.workers}.";
      }
      {
        assertion = cfg.sites != { };
        message = "server.enable is true, but no server.sites are defined.";
      }
    ];
    warnings = lib.concatMap (
      site:
      lib.optional (
        site.tls && cfg.port != 443
      ) "site ${site.serverName} uses TLS on port ${toString cfg.port}; clients expect 443."
    ) (lib.attrValues cfg.sites);
  };
}
```

And the check, which evaluates, refuses the result if an assertion failed, and prints warnings:

```nix file=checked.nix
modules:
let
  lib = (import ./nixpkgs.nix { }).lib;
  eval = lib.evalModules { modules = [ ./assertions.nix ] ++ modules; };
  inherit (eval) config;
  failed = map (a: a.message) (lib.filter (a: !a.assertion) config.assertions);
  showWarnings = value: lib.foldr (w: v: lib.warn w v) value config.warnings;
in
if failed != [ ] then
  throw "\nFailed assertions:\n${lib.concatMapStrings (m: "- ${m}\n") failed}"
else
  showWarnings config
```

```bash
nix-instantiate --eval --strict --json -E '(import ./checked.nix [ ./server-module.nix ./site.nix ]).server.port'
```

```text expect
evaluation warning: site shop uses TLS on port 8080; clients expect 443.
8080
```

A value that is a perfectly good `int` but breaks the rule:

```nix file=too-many-workers.nix
{ server.workers = 100; }
```

```bash fails
nix-instantiate --eval --strict --json -E '(import ./checked.nix [ ./server-module.nix ./site.nix ./too-many-workers.nix ]).server.port'
```

```text expect
Failed assertions:
- server.workers must be between 1 and 64, got 100.
```

You could also have used `types.ints.between 1 64` for `workers`. Prefer types when a rule is
about one value: the error then names the option and the file. Use assertions for rules about
several options.

## 7. Type errors and typos

The type checker catches bad values before anything is built. A string where a port belongs:

```nix file=bad-port.nix
{ server.port = "eighty"; }
```

```bash fails
nix-instantiate --eval --strict --json -E '(import ./eval.nix [ ./options.nix ./site.nix ./bad-port.nix ]).config.server.port'
```

```text expect
A definition for option `server.port' is not of type `16 bit unsigned integer
bad-port.nix
```

A value outside an `enum`:

```nix file=bad-level.nix
{ server.logLevel = "verbose"; }
```

```bash fails
nix-instantiate --eval --strict --json -E '(import ./eval.nix [ ./options.nix ./site.nix ./bad-level.nix ]).config.server.logLevel'
```

```text expect
is not of type `one of "error", "warn", "info", "debug"'
```

And a typo in an option name. Undeclared options are errors, which is why NixOS tells you
immediately when you misspell `services.openssh.enable`:

```nix file=typo.nix
{ server.prot = 80; }
```

```bash fails
nix-instantiate --eval --strict --json -E '(import ./eval.nix [ ./options.nix ./site.nix ./typo.nix ]).config.server.port'
```

```text expect
The option `server.prot' does not exist
```

## Your turn

1. Add an option `server.maxBodySize`: a string such as `"10m"` or `"512k"`, checked by
   `types.strMatching "[0-9]+[kmg]"`, default `"1m"`. Show the default, a good value and a
   rejected value `"lots"`.
2. Replace the hand-written check in `checked.nix` with `lib.asserts.checkAssertWarn` (read it in
   `lib/asserts.nix`) and show that a failing assertion still produces `Failed assertions:`.

<details><summary>Solution</summary>

A separate module can declare the new option. Option *declarations* merge as long as each
option is declared once:

```nix file=body-size.nix
{ lib, ... }:
{
  options.server.maxBodySize = lib.mkOption {
    type = lib.types.strMatching "[0-9]+[kmg]";
    default = "1m";
    description = "Largest request body to accept, e.g. 512k or 10m.";
  };
}
```

```nix file=big-body.nix
{ server.maxBodySize = "10m"; }
```

```nix file=bad-body.nix
{ server.maxBodySize = "lots"; }
```

```bash
nix-instantiate --eval --strict --json -E '(import ./eval.nix [ ./options.nix ./body-size.nix ./site.nix ]).config.server.maxBodySize'
nix-instantiate --eval --strict --json -E '(import ./eval.nix [ ./options.nix ./body-size.nix ./site.nix ./big-body.nix ]).config.server.maxBodySize'
```

```text expect
"1m"
"10m"
```

```bash fails
nix-instantiate --eval --strict --json -E '(import ./eval.nix [ ./options.nix ./body-size.nix ./site.nix ./bad-body.nix ]).config.server.maxBodySize'
```

```text expect
is not of type `string matching the pattern [0-9]+[kmg]'
```

The library version of the check is one line:

```nix file=checked2.nix
modules:
let
  lib = (import ./nixpkgs.nix { }).lib;
  inherit (lib.evalModules { modules = [ ./assertions.nix ] ++ modules; }) config;
in
lib.asserts.checkAssertWarn config.assertions config.warnings config
```

```bash fails
nix-instantiate --eval --strict --json -E '(import ./checked2.nix [ ./server-module.nix ./site.nix ./too-many-workers.nix ]).server.port'
```

```text expect
Failed assertions:
- server.workers must be between 1 and 64, got 100.
```
</details>

## Check yourself

<details><summary>Why does <code>config = if config.x.enable then … else { };</code> recurse forever, while <code>config = lib.mkIf config.x.enable { … };</code> works?</summary>

The module system needs the attribute *names* of every module's `config` to know which options
are defined. Only then can it compute any option, including `x.enable`. With `if`, the names
depend on `x.enable`. `mkIf` returns a fixed structure (`_type = "if"`, `condition`, `content`).
Its names are known without evaluating the condition, which is checked later, per option.
</details>

<details><summary>A NixOS module sets <code>services.foo.port = 80;</code> and so do you, with <code>81</code>. What happens, and what are your two ways out?</summary>

Both definitions have priority 100, and a port can't merge two different values, so evaluation
fails with "conflicting definition values". Use `lib.mkForce 81` (priority 50) to win, or, if
the module wrote `lib.mkDefault 80` instead, your plain `81` already wins. That is why
well-written modules use `mkDefault` for values they only suggest.
</details>

<details><summary>Where does <code>types.listOf</code> get the order of elements from several modules?</summary>

From the order in which the definitions are collected (module order), adjusted by
`mkOrder`/`mkBefore`/`mkAfter`. Order is the one thing in merging that depends on the list
of modules, which is why `mkBefore`/`mkAfter` exist for cases where it matters.
</details>

<details><summary>Types or assertions: which would you use for "port must not be 22" and for "if TLS is on, a certificate path must be set"?</summary>

The first is about one value: a type, for example `types.addCheck types.port (p: p != 22)`.
The second relates two options: an assertion. Types give better error locations. Assertions can
see the whole `config`.
</details>
