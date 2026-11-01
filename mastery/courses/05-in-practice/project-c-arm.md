# Project 05c — Build for ARM on x86

**Goal:** take one `package.nix` for a small C program and build it three ways from the same
file: native x86-64, cross-compiled for 64-bit ARM, and static with musl. Run the ARM build under
QEMU, and make "it runs" a test that travels with the package and works on every platform.

**You will practise:**

- **platforms as package-set arguments**: `pkgs.callPackage`, `pkgsCross.aarch64-multiplatform.callPackage`
  and `pkgsStatic.callPackage` on the same file;
- **tests travel with the package**: `passthru.tests` that use
  `stdenv.hostPlatform.emulator buildPackages`, so the same test runs natively and under QEMU;
- **reading platform facts** with `nix eval` before building anything.

## 1. The program

It reports what it was compiled for, what the kernel says it is running on, and which C library
it uses. Under QEMU user mode, `uname()` reports the *emulated* machine.

```bash
git init -q
mkdir -p src
```

```c file=src/archinfo.c
#include <stdio.h>
#include <sys/utsname.h>

int main(void) {
    struct utsname u;
    if (uname(&u) != 0)
        return 1;
#if defined(__aarch64__)
    const char *target = "aarch64";
#elif defined(__x86_64__)
    const char *target = "x86_64";
#else
    const char *target = "something else";
#endif
    printf("compiled for %s, running on %s %s\n", target, u.sysname, u.machine);
#ifdef __GLIBC__
    printf("libc: glibc %d.%d\n", __GLIBC__, __GLIBC_MINOR__);
#else
    printf("libc: not glibc (musl)\n");
#endif
    return 0;
}
```

## 2. One `package.nix` for every platform

Read the inputs closely. `stdenv` is the *host* platform's stdenv, and its `$CC` is the right
(possibly prefixed) compiler. `buildPackages` is the set for the *build* platform, and that is
where the emulator must come from, because it runs during the build.

```nix file=package.nix
{
  lib,
  stdenv,
  buildPackages,
  runCommand,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "archinfo";
  version = "1.0";
  src = ./src;

  __structuredAttrs = true;
  strictDeps = true;

  buildPhase = ''
    runHook preBuild
    $CC -O2 -Wall -o archinfo archinfo.c
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    install -Dm755 archinfo $out/bin/archinfo
    runHook postInstall
  '';

  passthru.tests.runs =
    runCommand "${finalAttrs.pname}-runs-${stdenv.hostPlatform.system}"
      {
        # For a native build this is a tiny `exec "$@"` wrapper; for aarch64 on
        # x86_64 it is qemu-aarch64 from qemu-user (see lib/systems/default.nix).
        emulator = stdenv.hostPlatform.emulator buildPackages;
        expected = if stdenv.hostPlatform.isAarch64 then "aarch64" else "x86_64";
      }
      ''
        $emulator ${finalAttrs.finalPackage}/bin/archinfo | tee $out
        grep -q "compiled for $expected, running on Linux $expected" $out
      '';

  meta = {
    description = "Report the architecture and libc a binary was built for";
    license = lib.licenses.mit;
    mainProgram = "archinfo";
    platforms = lib.platforms.linux;
  };
})
```

The flake calls it three times. The only difference is *which package set* calls it:

```nix file=flake.nix
{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      p = self.packages.${system};
    in
    {
      packages.${system} = {
        native = pkgs.callPackage ./package.nix { };
        arm = pkgs.pkgsCross.aarch64-multiplatform.callPackage ./package.nix { };
        static = pkgs.pkgsStatic.callPackage ./package.nix { };
        default = p.native;
      };

      checks.${system} = {
        native = p.native.tests.runs;
        arm = p.arm.tests.runs;
        static = p.static.tests.runs;
      };
    };
}
```

```bash
git add src/archinfo.c package.nix flake.nix
```

## 3. Ask before you build

```bash
for v in native arm static; do
  echo "$v: $(nix eval --raw .#$v.name)"
done
nix eval .#arm.stdenv.hostPlatform.system
nix eval --raw .#arm.tests.runs.name; echo
```

```text expect
native: archinfo-1.0
arm: archinfo-aarch64-unknown-linux-gnu-1.0
static: archinfo-static-x86_64-unknown-linux-musl-1.0
"aarch64-linux"
archinfo-runs-aarch64-linux
```

## 4. Native and static

```bash timeout=3600
nix build .#native -o native && ./native/bin/archinfo
nix build .#static -o static && ./static/bin/archinfo
nix shell --inputs-from . nixpkgs#file --command file -L native/bin/archinfo static/bin/archinfo
```

```text expect
compiled for x86_64, running on Linux x86_64
libc: glibc
libc: not glibc (musl)
dynamically linked
static
```

## 5. Cross-compile for ARM

If lesson 05.4 ran on this machine, the aarch64 cross toolchain is already in your store and
this takes seconds:

```bash timeout=5400
nix build .#arm -o arm
nix shell --inputs-from . nixpkgs#file --command file -L arm/bin/archinfo
```

```text expect
ARM aarch64
```

Run it by hand under QEMU user mode:

```bash timeout=1800
nix shell --inputs-from . nixpkgs#qemu-user --command qemu-aarch64 ./arm/bin/archinfo
```

```text expect
compiled for aarch64, running on Linux aarch64
libc: glibc
```

## 6. The tests, everywhere

`checks` are just derivations. Building one runs the test in the sandbox. For `arm`, the sandbox
runs QEMU:

```bash timeout=1800
nix build .#checks.x86_64-linux.arm -o check-arm && cat check-arm
nix build .#checks.x86_64-linux.native -o check-native && cat check-native
```

```text expect
compiled for aarch64, running on Linux aarch64
compiled for x86_64, running on Linux x86_64
```

`nix flake check` evaluates the whole flake and builds every check:

```bash timeout=1800
nix flake check && echo "all checks pass"
```

```text expect
all checks pass
```

## 7. Verify: a test that can fail

A test is only useful if it can fail. The emulator is an ordinary attribute of the test
derivation, so you can override it. Remove QEMU from the ARM test and the sandbox has to run an
aarch64 binary on x86-64 directly. The kernel refuses, and the test fails:

```bash fails
nix build --impure --no-link --expr '
  let f = builtins.getFlake (toString ./.);
  in f.packages.x86_64-linux.arm.tests.runs.overrideAttrs { emulator = ""; }'
```

```text expect
Exec format error
```

So the passing `checks.x86_64-linux.arm` above really ran ARM code, under QEMU.

## Stretch goals

1. **Static ARM.** `pkgs.pkgsCross.aarch64-multiplatform.pkgsStatic.callPackage ./package.nix { }`
   builds a static musl binary for ARM. It needs a cross musl toolchain, which may have to be
   built first. Copy the result to a Raspberry Pi 4/5 running any 64-bit Linux and run it there.
2. **More targets.** Add `riscv64` and `armv7l-hf-multiplatform` (see `lib/systems/examples.nix`).
   Does the test still work unchanged? What does `expected` need to become?
3. **Native ARM from the cache instead of cross.** `nix build nixpkgs#legacyPackages.aarch64-linux.hello`
   *downloads* a native aarch64 hello: substitution doesn't care about your CPU. Compare its
   store path and interpreter with `pkgsCross.aarch64-multiplatform.hello`. Why are they
   different derivations?
4. **Splicing.** Add `pkg-config` and `zlib` (lesson 05.1's program). Put `pkg-config` in
   `buildInputs` on purpose and watch the ARM build fail, then fix it.
