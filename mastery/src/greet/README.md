# greet

A tiny C program that prints a greeting. It exists to be packaged: it is the "upstream"
for [course 07](../../courses/07-contributing/) of the Nix mastery path, where you add it to a
nixpkgs checkout as `pkgs/by-name/gr/greet/package.nix`.

```console
$ make && ./greet
Hello from greet 1.0.0
$ ./greet --version
greet 1.0.0
$ make check
$ make install PREFIX=/usr DESTDIR=/tmp/stage   # installs /tmp/stage/usr/bin/greet
```

No dependencies beyond a C99 compiler and libc. Releases are tagged `greet-vX.Y.Z` in this
repository. MIT licensed (see `LICENSE`).

This file is not a lesson and has no runnable blocks.
