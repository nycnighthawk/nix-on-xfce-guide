# Lesson 05.3 — Containers with `dockerTools` (no Dockerfile)

**You will:** build an OCI/Docker image of a small program with
`dockerTools.buildLayeredImage`, open the tarball and read its manifest, see that every layer is
one store path, and stream an image without writing it to the store.

## Why Nix doesn't need a Dockerfile

A Dockerfile starts `FROM` a base image (a whole distribution), then runs commands such as
`apt-get install` whose results depend on the day you build. Nix already knows the **exact
runtime closure** of a program: the store paths it references, found by scanning (course 01). An
image only has to contain those paths and a little JSON that says what to run. So
`dockerTools` builds the image as an ordinary derivation:

- no daemon, no root and no network while building, inside the normal sandbox;
- no base image: the image contains glibc and your program, and nothing else;
- reproducible: the same inputs give the same image, byte for byte (timestamps are fixed at
  1970-01-01 unless you ask otherwise);
- cacheable and diffable like any store path.

The functions live in `pkgs/build-support/docker/default.nix` and are documented in the nixpkgs
manual (*Build helpers → Images → dockerTools*, source `doc/build-helpers/images/dockertools.section.md`):

| Function | Output |
|---|---|
| `buildLayeredImage` | a `.tar.gz` in the store; one layer per store path (up to `maxLayers`, default 100) |
| `streamLayeredImage` | a *script* that writes the image tarball to stdout; nothing big in the store |
| `buildImage` | a single-layer image (plus `fromImage` layers); needed for `runAsRoot` |
| `pullImage` | a fixed-output fetch of an image from a registry, for `fromImage` |

`buildLayeredImage` is just `streamLayeredImage` piped through gzip, as you can read in its
definition.

## The program and the image

```bash
git init -q
mkdir -p src
```

```c file=src/greet.c
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    const char *who = getenv("GREETING");
    printf("%s from a Nix-built image\n", who ? who : "Hello");
    return 0;
}
```

```nix file=package.nix
{ lib, stdenv }:

stdenv.mkDerivation (finalAttrs: {
  pname = "greet";
  version = "1.0";
  src = ./src;
  __structuredAttrs = true;
  strictDeps = true;

  buildPhase = ''
    runHook preBuild
    $CC -O2 -o greet greet.c
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    install -Dm755 greet $out/bin/greet
    runHook postInstall
  '';

  meta = {
    description = "Print a greeting";
    license = lib.licenses.mit;
    mainProgram = "greet";
  };
})
```

```nix file=flake.nix
{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { self, nixpkgs }:
    let
      pkgs = nixpkgs.legacyPackages.x86_64-linux;
      inherit (pkgs) lib dockerTools;
      greet = pkgs.callPackage ./package.nix { };

      # The image configuration, shared by both variants below. These keys are
      # the OCI image config (`Cmd`, `Env`, `User`, `WorkingDir`, `ExposedPorts`, ...).
      imageArgs = {
        name = "greet";
        tag = "1.0";
        config = {
          Cmd = [ (lib.getExe greet) ];
          Env = [ "GREETING=Hello" ];
          User = "65534:65534"; # nobody: no /etc/passwd needed for a numeric user
        };
      };
    in
    {
      packages.x86_64-linux = {
        inherit greet;
        default = greet;
        image = dockerTools.buildLayeredImage imageArgs;
        imageStream = dockerTools.streamLayeredImage imageArgs;
      };
    };
}
```

`Cmd` uses the absolute store path of the program. There is no `/bin` and no shell in this image,
and none is needed.

```bash
git add src/greet.c package.nix flake.nix
nix build .#image
readlink result
```

```text expect
greet.tar.gz
```

## Look inside

The output is a `docker load` style archive (the "docker-archive" format): a `manifest.json`,
an image config JSON, and one directory per layer, each holding a `layer.tar`. Use the pinned
`jq`:

```bash
jq() { nix run --inputs-from . nixpkgs#jq -- "$@"; }
tar -tzf result | sort
tar -xzOf result manifest.json | jq '.[0] | {RepoTags, Config, layers: (.Layers | length)}'
```

```text expect
manifest.json
/layer.tar
"greet:1.0"
"layers":
```

The config JSON is what `docker inspect` shows. Note `Cmd` pointing into `/nix/store`, and the
`history` comments, which name the store paths in each layer:

```bash
cfg=$(tar -xzOf result manifest.json | jq -r '.[0].Config')
tar -xzOf result "$cfg" | jq '{created, architecture, config, comments: [.history[].comment]}'
```

```text expect
"created": "1970-01-01T00:00:01
"architecture": "amd64"
"Cmd": [
"/nix/store/
"User": "65534:65534"
store paths:
-greet-1.0
-glibc-
```

### One layer per store path

`buildLayeredImage` gives each store path of the closure its own layer, and adds one last
*customisation* layer for `contents`/`extraCommands`. Two images that share glibc then share
that layer in a registry and on disk. Check the arithmetic:

```bash
closure=$(nix path-info -r .#greet | wc -l)
layers=$(tar -xzOf result manifest.json | jq '.[0].Layers | length')
echo "closure of greet: $closure store paths; image: $layers layers"
[ "$layers" -eq $((closure + 1)) ] && echo "one layer per store path, plus the customisation layer"
```

```text expect
one layer per store path, plus the customisation layer
```

When a closure has more paths than `maxLayers`, the "popularity contest" algorithm
(`pkgs/build-support/docker/auto-layer.nix` → `auto-layer.py`) keeps the most-shared paths in
their own layers and merges the rest into the last one.

## Streaming: images without a copy in the store

A `.tar.gz` of a large closure doubles your disk use: the paths are in `/nix/store` *and* in
the tarball. `streamLayeredImage` builds a small script instead, which assembles the tarball from
the store paths each time it runs:

```bash
nix build .#imageStream -o stream
file -L stream | cut -d, -f1
./stream > /dev/null
```

```text expect
script
Creating layer 1 from paths:
with customisation...
Adding manifests...
```

You pipe it straight into a consumer: `./stream | docker load`, `./stream | gzip > img.tar.gz`,
or `skopeo copy docker-archive:/dev/stdin docker://registry/...`. Project 05b loads it into
Docker.

The output is reproducible. Run it twice and compare:

```bash
a=$(./stream 2>/dev/null | sha256sum)
b=$(./stream 2>/dev/null | sha256sum)
[ "$a" = "$b" ] && echo "identical image bytes on every run"
```

```text expect
identical image bytes on every run
```

## Adding things to the image

`contents` puts store paths **and symlinks to their contents** at the image root. That is how
you get a `/bin/sh` or CA certificates when a program needs them. `dockerTools` has small helpers
for common needs (defined at the end of `default.nix`):

```nix
dockerTools.buildLayeredImage {
  name = "tool";
  contents = [
    dockerTools.binSh            # /bin/sh (bash)
    dockerTools.usrBinEnv        # /usr/bin/env, for scripts with #!/usr/bin/env
    dockerTools.caCertificates   # /etc/ssl/certs/ca-bundle.crt and friends
    pkgs.coreutils
  ];
  config.Cmd = [ "/bin/sh" ];
}
```

Only add what the program needs at run time. Each item makes the image larger and gives an
attacker more tools.

## Your turn

Make a variant of the image with `maxLayers = 2` and confirm it has exactly two layers: all of
the closure merged into one, plus the customisation layer. Add it as `packages.x86_64-linux.imageFlat`
using `imageArgs // { maxLayers = 2; }`.

<details><summary>Solution</summary>

```nix file=flake.nix
{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { self, nixpkgs }:
    let
      pkgs = nixpkgs.legacyPackages.x86_64-linux;
      inherit (pkgs) lib dockerTools;
      greet = pkgs.callPackage ./package.nix { };
      imageArgs = {
        name = "greet";
        tag = "1.0";
        config = {
          Cmd = [ (lib.getExe greet) ];
          Env = [ "GREETING=Hello" ];
          User = "65534:65534";
        };
      };
    in
    {
      packages.x86_64-linux = {
        inherit greet;
        default = greet;
        image = dockerTools.buildLayeredImage imageArgs;
        imageStream = dockerTools.streamLayeredImage imageArgs;
        imageFlat = dockerTools.buildLayeredImage (imageArgs // { maxLayers = 2; });
      };
    };
}
```

```bash
git add flake.nix
nix build .#imageFlat -o flat
tar -xzOf flat manifest.json | jq '.[0].Layers | length'
```

```text expect
2
```
</details>

## Check yourself

<details><summary>Why does this image work without a base image or a <code>/bin</code>?</summary>

`Cmd` is the absolute store path of `greet`. The ELF interpreter and libraries it needs are also
absolute `/nix/store` paths, and the image contains the program's whole closure. Nothing looks
anything up in `/bin`, `/lib` or `/usr`.
</details>

<details><summary>When would you choose <code>streamLayeredImage</code> over <code>buildLayeredImage</code>?</summary>

When the image is large or you only push it somewhere: the stream script is tiny in the store
and writes the tarball on the fly, so the closure isn't stored twice. Use `buildLayeredImage`
when you need a file, for example as a `fromImage` or a CI artifact.
</details>

<details><summary>Two images both contain glibc from the same nixpkgs. What does a registry store twice?</summary>

Nothing for glibc. Its layer has the same contents and so the same digest in both images, so
the registry stores it once. That is the point of one store path per layer.
</details>
