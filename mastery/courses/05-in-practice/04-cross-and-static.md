# Lesson 05.4 — Cross-compilation and static builds: `pkgsCross`, `pkgsStatic`

**You will:** build GNU hello for 64-bit ARM on your x86-64 machine, prove with `file` that it
is an ARM binary, run it with QEMU user-mode emulation, and build a fully static hello with musl.

## Platforms are arguments to nixpkgs

nixpkgs is a function. Course 02 called it with `{ }`, and Nix then filled in your machine as the
platform. It accepts more (see `pkgs/top-level/default.nix`):

- `localSystem`: the **build platform**, the machine that runs the compiler;
- `crossSystem`: the **host platform**, the machine that will run the result. It defaults to
  `localSystem`, which means a native build.

(There is a third platform, the *target*, which only matters for compilers. Nixpkgs manual:
*Stdenv → Cross-compilation → Platform parameters*, source
`doc/stdenv/cross-compilation.chapter.md`.)

You rarely call nixpkgs again yourself. `pkgs/top-level/stage.nix` does it for you:

```nix
# pkgs/top-level/stage.nix (nixpkgs 26.05), abridged
pkgsCross = lib.mapAttrs (n: crossSystem: nixpkgsFun { inherit crossSystem; }) lib.systems.examples;

pkgsStatic = nixpkgsFun {
  crossSystem = {
    isStatic = true;
    config = …;  # your system with musl, e.g. x86_64-unknown-linux-musl
  };
};
```

So `pkgsCross.aarch64-multiplatform` is *all of nixpkgs* built on x86-64 for
`aarch64-unknown-linux-gnu` (`lib/systems/examples.nix`). `pkgsStatic` is all of nixpkgs for
static musl binaries, which is also a cross build. Every package in them is the same
`package.nix` as usual. Only the stdenv (compiler, linker, `strip`) and the dependencies change.
That works because packages say *which platform* each input is for:

| Attribute | Runs on | Example |
|---|---|---|
| `nativeBuildInputs` | build platform | `pkg-config`, `cmake`, code generators |
| `buildInputs` | host platform | `zlib`, `openssl`: libraries linked into the result |

When cross-compiling, nixpkgs *splices* each input: a `pkg-config` in `nativeBuildInputs` is
taken from the build platform's packages, a `zlib` in `buildInputs` from the host platform's.
Put an input in the wrong list and the native build still works, but the cross build breaks.
`strictDeps = true` makes the native build behave the same way, so you find such mistakes early.

## Set up

```bash
git init -q
```

```nix file=flake.nix
{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";

  outputs =
    { nixpkgs, ... }:
    let
      pkgs = nixpkgs.legacyPackages.x86_64-linux;
    in
    {
      packages.x86_64-linux = {
        hello = pkgs.hello;
        helloArm = pkgs.pkgsCross.aarch64-multiplatform.hello;
        helloStatic = pkgs.pkgsStatic.hello;
      };
    };
}
```

```bash
git add flake.nix
```

Ask nixpkgs what it thinks the platforms are, before building anything:

```bash
nix eval .#hello.stdenv.hostPlatform.config
nix eval .#helloArm.stdenv.buildPlatform.config
nix eval .#helloArm.stdenv.hostPlatform.config
nix eval .#helloStatic.stdenv.hostPlatform.config
nix eval .#helloStatic.stdenv.hostPlatform.isStatic
```

```text expect
"x86_64-unknown-linux-gnu"
"aarch64-unknown-linux-gnu"
"x86_64-unknown-linux-musl"
true
```

The three derivations are different. Their names show it:

```bash
nix eval --raw .#helloArm.name; echo
nix eval --raw .#helloArm.outPath; echo
```

```text expect
hello-aarch64-unknown-linux-gnu-2.12.3
```

## Cross-compile hello for ARM

The cross compiler for aarch64 comes from `cache.nixos.org` when Hydra has built it for this
nixpkgs revision. Otherwise Nix builds binutils, gcc and glibc for the cross target first. That
takes a while once, then it is in your store:

```bash timeout=5400
nix build .#helloArm -o hello-arm
nix shell --inputs-from . nixpkgs#file --command file -L hello-arm/bin/hello
```

```text expect
ELF 64-bit LSB
ARM aarch64
interpreter /nix/store/
```

Your CPU can't run that file. The kernel looks at the ELF header and gives up:

```bash fails
./hello-arm/bin/hello
```

```text expect
Exec format error
```

### Run it under QEMU user-mode emulation

`qemu-aarch64` is QEMU in *user mode*: it emulates an ARM CPU for one Linux process and turns its
system calls into calls to your x86-64 kernel. No VM and no ARM kernel are involved. The binary's
interpreter (`ld-linux-aarch64.so.1`) and its libraries are ARM files in `/nix/store`, and QEMU
loads them from there, so nothing needs to be installed.

`qemu-user` is QEMU built with only the user-mode emulators. It is also what nixpkgs itself
uses to run cross-compiled tests (`stdenv.hostPlatform.emulator`, `lib/systems/default.nix`).
The full `pkgs.qemu` package provides the same `qemu-aarch64` with much more besides.

```bash timeout=1800
nix shell --inputs-from . nixpkgs#qemu-user --command qemu-aarch64 ./hello-arm/bin/hello
```

```text expect
Hello, world!
```

On NixOS, `boot.binfmt.emulatedSystems = [ "aarch64-linux" ];` registers QEMU with the kernel's
`binfmt_misc`, so ARM binaries run directly. It also lets that machine *build* aarch64
derivations natively (slowly), as a remote builder for ARM.

## Fully static with `pkgsStatic`

A static binary has no ELF interpreter and no shared libraries, so you can copy it to any
x86-64 Linux machine, even one without Nix, and to a `FROM scratch` container. glibc is not
designed for static linking, so `pkgsStatic` uses musl.

```bash timeout=3600
nix build .#helloStatic -o hello-static
nix shell --inputs-from . nixpkgs#file --command file -L hello-static/bin/hello
nix shell --inputs-from . nixpkgs#file --command file -L hello-static/bin/hello \
  | grep -qE 'statically linked|static-pie linked' && echo "hello-static is static"
./hello-static/bin/hello
```

```text expect
x86-64
hello-static is static
Hello, world!
```

Compare with the normal build. The normal hello is dynamically linked and needs glibc and what
glibc needs. The static one needs (almost) nothing:

```bash
nix build .#hello -o hello-native
nix shell --inputs-from . nixpkgs#file --command file -L hello-native/bin/hello
echo "native closure:"; nix path-info -r ./hello-native
echo "static closure:"; nix path-info -r ./hello-static
n=$(nix path-info -r ./hello-native | wc -l)
s=$(nix path-info -r ./hello-static | wc -l)
[ "$s" -lt "$n" ] && echo "static closure is smaller: $s path(s) instead of $n"
```

```text expect
dynamically linked
native closure:
-glibc-
static closure:
static closure is smaller
```

## When cross-compilation breaks

Most of nixpkgs cross-compiles, but not all. Typical causes, and where they get fixed:

- **A tool in `buildInputs` instead of `nativeBuildInputs`**: the build tries to run an ARM
  `pkg-config`. Fix: move it.
- **Running a freshly built binary during the build** (tests, code generators): fails for cross.
  nixpkgs guards such steps with `lib.optionals (stdenv.buildPlatform.canExecute stdenv.hostPlatform)`.
  `doCheck` is turned off automatically when the build platform can't execute host binaries,
  which is why hello's test suite didn't run for ARM.
- **Hard-coded `gcc`, `ar`, `strip`**: cross tools are prefixed (`aarch64-unknown-linux-gnu-gcc`).
  Use `$CC`, `$AR`, `$STRIP`, which stdenv sets correctly.

Project 05c takes your own `package.nix` through native, cross and static builds and turns the
QEMU run into a `check`.

## Your turn

`lib.systems.examples` has many more platforms. Evaluate (don't build) the host platform of
GNU hello for 64-bit RISC-V, and the name of its output. Which attribute of `pkgsCross` is it?
Look in `lib/systems/examples.nix`.

<details><summary>Solution</summary>

The example is called `riscv64` (`config = "riscv64-unknown-linux-gnu"`). Evaluating doesn't
build anything:

```bash
nix eval --impure --raw --expr '
  let pkgs = (builtins.getFlake (toString ./.)).inputs.nixpkgs.legacyPackages.x86_64-linux;
  in pkgs.pkgsCross.riscv64.hello.name'; echo
nix eval --impure --raw --expr '
  let pkgs = (builtins.getFlake (toString ./.)).inputs.nixpkgs.legacyPackages.x86_64-linux;
  in pkgs.pkgsCross.riscv64.stdenv.hostPlatform.qemuArch'; echo
```

```text expect
hello-riscv64-unknown-linux-gnu-2.12.3
riscv64
```

`qemuArch` is the suffix of the emulator you would use: `qemu-riscv64`.
</details>

## Check yourself

<details><summary>What are the build platform and the host platform of <code>pkgsCross.aarch64-multiplatform.hello</code>, and of its <code>nativeBuildInputs</code>?</summary>

hello: build = x86_64-linux, host = aarch64-linux. Its `nativeBuildInputs` are built *and* run on
x86_64-linux (build = host = x86_64). They are tools used during the build. The cross compiler
itself runs on x86_64 and targets aarch64.
</details>

<details><summary>Why can QEMU user mode run the dynamically linked ARM hello without a sysroot (<code>-L</code>)?</summary>

All of hello's runtime paths are absolute `/nix/store` paths: the ELF interpreter, glibc, and
the library search path (RUNPATH). They are in your store because they are in the closure you just
built. On a normal distribution, the interpreter would be `/lib/ld-linux-aarch64.so.1`, which
doesn't exist on an x86-64 host, so you would need `-L /path/to/arm/sysroot`.
</details>

<details><summary>Why is <code>pkgsStatic</code> a cross package set, even though the result runs on your own CPU?</summary>

The host platform differs from the build platform: `x86_64-unknown-linux-musl` with
`isStatic = true`, versus `x86_64-unknown-linux-gnu`. The tools that run during the build are
still normal glibc binaries for x86-64. Only the output is built for musl and static linking.
</details>
