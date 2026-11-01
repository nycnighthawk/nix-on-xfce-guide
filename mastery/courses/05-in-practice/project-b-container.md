# Project 05b — Container from your package

**Goal:** turn your own `package.nix` into a layered container image, without a Dockerfile,
load it into Docker on Xubuntu and run it. Then load a *streamed* image and compare how the two
images share layers.

**You will practise:**

- **images as Nix outputs**: the image is `dockerTools.buildLayeredImage` of the package's
  closure;
- **one package, many artifacts**: the same `package.nix` gives a binary, an image and a
  streamed image;
- **least privilege by construction**: no shell, no package manager, a numeric non-root user.

## 1. Install Docker

Ubuntu's `docker.io` package is enough. Nix doesn't need Docker to *build* images, only to run
them.

```bash timeout=1800
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io > /dev/null
sudo systemctl enable --now docker
sudo docker version --format 'docker server {{.Server.Version}}'
```

```text expect
docker server
```

This project uses `sudo docker`. To use Docker without sudo you would add yourself to the
`docker` group, which is root-equivalent on that machine, so think before you do.

## 2. The package

A small web-less "service" that prints its configuration from environment variables and its
arguments, so you can see what `Cmd`, `Env` and `docker run -e` do.

```bash
git init -q
mkdir -p src
```

```c file=src/greet.c
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(int argc, char **argv) {
    const char *who = getenv("GREETING");
    printf("%s from a Nix-built image\n", who ? who : "Hello");
    printf("running as uid %d\n", (int) getuid());
    for (int i = 1; i < argc; i++)
        printf("arg %d: %s\n", i, argv[i]);
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
    $CC -O2 -Wall -o greet greet.c
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    install -Dm755 greet $out/bin/greet
    runHook postInstall
  '';

  meta = {
    description = "Print a greeting and the process's uid and arguments";
    license = lib.licenses.mit;
    mainProgram = "greet";
  };
})
```

## 3. The images

```nix file=flake.nix
{
  description = "greet: a package and its container images";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      inherit (pkgs) lib dockerTools;
      greet = self.packages.${system}.greet;

      config = {
        Entrypoint = [ (lib.getExe greet) ];
        Cmd = [ "default-arg" ];
        Env = [ "GREETING=Hello" ];
        User = "65534:65534";
        Labels."org.opencontainers.image.source" = "local project 05b";
      };
    in
    {
      packages.${system} = {
        greet = pkgs.callPackage ./package.nix { };
        default = greet;

        # A .tar.gz in the store, for `docker load < result`.
        image = dockerTools.buildLayeredImage {
          name = "greet";
          tag = "1.0";
          inherit config;
        };

        # A script that writes the image to stdout, for `./stream | docker load`.
        stream = dockerTools.streamLayeredImage {
          name = "greet-stream";
          tag = "1.0";
          config = config // {
            Env = [ "GREETING=Streamed hello" ];
          };
        };
      };
    };
}
```

`Entrypoint` + `Cmd` work as in any image. `docker run IMAGE x y` replaces `Cmd`, so it
replaces only the default arguments.

```bash
git add src/greet.c package.nix flake.nix
nix build .#greet && ./result/bin/greet
nix build .#image -o image.tar.gz
```

```text expect
Hello from a Nix-built image
```

## 4. Load and run

```bash
sudo docker load < image.tar.gz
sudo docker run --rm greet:1.0
```

```text expect
Loaded image: greet:1.0
Hello from a Nix-built image
running as uid 65534
arg 1: default-arg
```

Override the environment and the arguments the usual way:

```bash
sudo docker run --rm -e GREETING=Bonjour greet:1.0 one two
```

```text expect
Bonjour from a Nix-built image
arg 1: one
arg 2: two
```

## 5. What's in the image?

Docker's view agrees with the closure. The layer count is the number of store paths plus one,
and the history comments name the store paths:

```bash
closure=$(nix path-info -r .#greet | wc -l)
layers=$(sudo docker image inspect greet:1.0 --format '{{len .RootFS.Layers}}')
echo "closure: $closure paths, image layers: $layers"
[ "$layers" -eq $((closure + 1)) ] && echo "layers = store paths + 1"
sudo docker history --no-trunc --format '{{.Comment}}' greet:1.0 | grep -o 'store paths: .*' | head -n 3
```

```text expect
layers = store paths + 1
store paths:
```

There is no shell inside, so there is nothing for an attacker to `exec` into:

```bash fails
sudo docker run --rm --entrypoint /bin/sh greet:1.0 -c 'echo hi'
```

```text expect
/bin/sh
```

Export the filesystem and look: only `/nix/store` (and the few directories Docker itself adds):

```bash
cid=$(sudo docker create greet:1.0)
sudo docker export "$cid" | tar -t | grep -v '^nix/store/.' | sort
sudo docker rm "$cid" > /dev/null
```

```text expect
nix/
nix/store/
```

## 6. Stream straight into Docker

```bash
nix build .#stream -o stream
./stream 2>/dev/null | sudo docker load
sudo docker run --rm greet-stream:1.0
```

```text expect
Loaded image: greet-stream:1.0
Streamed hello from a Nix-built image
```

The two images have different configs but the same store paths, so all the store-path layers
are shared. Only the customisation layer and the config differ. Compare the layer digests:

```bash
a=$(sudo docker image inspect greet:1.0 --format '{{range .RootFS.Layers}}{{println .}}{{end}}' | sort)
b=$(sudo docker image inspect greet-stream:1.0 --format '{{range .RootFS.Layers}}{{println .}}{{end}}' | sort)
shared=$(comm -12 <(echo "$a") <(echo "$b") | grep -c sha256)
echo "shared layers: $shared"
[ "$shared" -ge "$closure" ] && echo "every store-path layer is shared"
```

```text expect
every store-path layer is shared
```

## 7. Verify

```bash
out=$(sudo docker run --rm -e GREETING=Verified greet:1.0 ok)
echo "$out"
case "$out" in *"Verified from a Nix-built image"*"arg 1: ok"*) echo "PROJECT 05b OK" ;; *) exit 1 ;; esac
```

```text expect
PROJECT 05b OK
```

Clean up the images (the store paths stay until you collect garbage):

```bash
sudo docker image rm greet:1.0 greet-stream:1.0 > /dev/null
```

## Stretch goals

1. **Push without Docker.** `nix shell nixpkgs#skopeo -c skopeo copy docker-archive:image.tar.gz oci:greet-oci:1.0`
   writes an OCI layout directory. With a registry you would use `docker://registry/greet:1.0`,
   and `./stream | skopeo copy docker-archive:/dev/stdin docker://…` pushes without a file.
2. **A debugging variant.** Add `contents = [ pkgs.busybox ];` in a second image and `docker run`
   a shell in it. Compare the image sizes with `docker images`.
3. **An image for ARM.** Build the same image from `pkgs.pkgsCross.aarch64-multiplatform`
   (`dockerTools` and `callPackage` from that set), check `.architecture` in the config, and
   relate it to lesson 05.4.
4. **Reproducibility across machines.** Build `.#image` on a second machine with the same
   `flake.lock` and compare `sha256sum image.tar.gz`. Why does it match even though nothing was
   downloaded from a cache?
5. **A NixOS service in a container.** Read `nixos/modules/virtualisation/oci-containers.nix`
   and run this image as a systemd-managed container on a NixOS machine (course 06).
