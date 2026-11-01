# Lesson 01.1 — The store and store paths

**You will:** put files into the Nix store, take a store path apart, show what its hash
depends on, and prove that store objects can't be changed.

## Why a store?

Most systems install software into shared locations (`/usr/lib`, `/usr/bin`), and each
install overwrites the last one. Nix puts every build result and every source file in its own
directory under `/nix/store` instead. The name of that directory contains a hash. Two things
follow from this, and the rest of Nix depends on both:

- **Many versions side by side.** `hello-2.12.3` built two different ways gets two
  different paths, so nothing ever gets overwritten.
- **A path names its contents.** If the hash comes from the inputs (or the bytes), anyone
  who has the same path has the same thing. That's what makes binary caches and sharing safe.

The manual calls each entry a **store object** and its name a **store path**
(Nix manual, *Store → Store Object* and *Store → Store Path*).

## Add a file to the store

`nix-store --add` copies a file or directory into the store and prints the new path:

```bash
echo "Hello, store" > hello.txt
p=$(nix-store --add hello.txt)
echo "$p"
```

```text expect
/nix/store/
-hello.txt
```

## Anatomy of a store path

```
/nix/store/b6gvzjyb2pg0kjfwrjmg1vfhh54ad73z-hello.txt
└────┬───┘ └──────────────┬───────────────┘ └───┬───┘
 store dir     hash part (32 chars)            name
```

The hash part is 160 bits written in Nix's own base-32 alphabet, which has no `e`, `o`,
`u` or `t` (so hashes don't spell words). Check this path against that rule:

```bash
basename "$p" | grep -E '^[0123456789abcdfghijklmnpqrsvwxyz]{32}-hello\.txt$'
```

### What the hash depends on

For a file added like this (a *content-addressed* store object), the hash covers the
**contents** (serialised as a NAR, the Nix ARchive format), the **name** and the store
directory. Test each one:

```bash
# same bytes, same name, different location on disk → same store path
mkdir other && echo "Hello, store" > other/hello.txt
p_same=$(nix-store --add other/hello.txt)
test "$p" = "$p_same"
echo "same content and name: same path"

# same bytes, different name → different path
cp hello.txt greeting.txt
p_name=$(nix-store --add greeting.txt)
test "$p" != "$p_name"
echo "different name: different path"

# different bytes → different path
echo "Hello, store!" > hello.txt
p_bytes=$(nix-store --add hello.txt)
test "$p" != "$p_bytes"
echo "different content: different path"
```

```text expect
same content and name: same path
different name: different path
different content: different path
```

You can also *compute* the path without adding anything. `nix-hash` hashes the NAR
serialisation of a file, and `nix-store --print-fixed-path` turns a content hash and a name
into a store path. The result matches what `--add` printed:

```bash
h=$(nix-hash --type sha256 other/hello.txt)
computed=$(nix-store --print-fixed-path --recursive sha256 "$h" hello.txt)
echo "$computed"
test "$computed" = "$p"
echo "computed path matches"
```

```text expect
computed path matches
```

The Nix language does exactly this when you write a path into a string. You'll see more of
this in course 02:

```bash
from_eval=$(nix eval --impure --raw --expr '"${./other/hello.txt}"')
test "$from_eval" = "$p"
echo "the evaluator puts files at the same path"
```

```text expect
the evaluator puts files at the same path
```

## Immutability

After a path is added, Nix takes away write permission, makes it owned by root (on a
multi-user install) and sets its timestamp to 1 second after the epoch, so timestamps can't
make two copies differ:

```bash
stat -c '%U %a %Y' "$p"
```

```text expect
root 444 1
```

You can't change a store object, even if you own the files that went into it:

```bash fails
echo "tamper" >> "$p"
```

The store directory itself belongs to root, is group-writable only by the build users'
group, and has the sticky bit set:

```bash
stat -c '%U:%G %A' /nix/store
```

```text expect
root:nixbld
```

## What Nix knows about a path

The store keeps a database (`/nix/var/nix/db`) of every valid path: its NAR hash and
size, what it references, and the derivation that built it (its **deriver**). Query it:

```bash
nix path-info --size --human-readable "$p"
nix-store --query --deriver "$p"
nix-store --query --hash "$p"
```

```text expect
unknown-deriver
sha256:
```

We added this file directly instead of building it, so it has no deriver. The NAR hash is
what `nix hash path` computes from the files on disk. If they ever differed, the store would
be corrupt (`nix store verify` checks this):

```bash
nar=$(nix-store --query --hash "$p")
from_disk=$(nix hash path "$p")
test "$(nix hash convert --hash-algo sha256 --to sri "${nar#sha256:}")" = "$from_disk"
echo "database and disk agree: $from_disk"
```

```text expect
database and disk agree: sha256-
```

## Two ways to address a store object

- **Content addressing** (what you just did): the hash comes from the bytes. Sources,
  fetched tarballs and `nix-store --add` work this way.
- **Input addressing** (most build outputs): the hash comes from the *recipe*, meaning the
  builder, its arguments, its environment and its inputs. That way the path is known before
  the build has run. Lesson 01.2 shows how.

Either way, a path never changes after it's created. "Updating" software means making new
paths and pointing something (a profile, a `result` symlink) at them.

## Check yourself

<details><summary>You add the same directory from two different machines. Do you get the same store path? Why?</summary>

Yes, if the contents and the name are identical and both use `/nix/store`. The path depends
only on the NAR serialisation (which includes file contents, the executable bit and
symlinks, but not owners or timestamps), the name and the store directory.
</details>

<details><summary>Why does Nix reset every file's modification time to 1?</summary>

So that two copies of a store object are identical down to the metadata, and so that tools
which embed timestamps (tar, zip, some compilers) get the same value everywhere. It also
reminds you that a store path doesn't have a "last changed" time: it never changes.
</details>

<details><summary>Why are there no `e`, `o`, `u`, `t` characters in store hashes?</summary>

Nix's base-32 alphabet leaves out those four letters so that hashes are less likely to
contain words, offensive ones included. The 32 characters × 5 bits encode a 160-bit hash
(a SHA-256 truncated by XOR-folding; see the manual's *Store Path* specification).
</details>
