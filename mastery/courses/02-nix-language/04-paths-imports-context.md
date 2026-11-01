# Lesson 02.4 — Paths, imports and string context

**You will:** tell paths and strings apart, see exactly when a file is copied into the
store, import files and directories, use lookup paths, and follow the *string context* that
turns a string into derivation inputs.

## Paths are their own type

`./data.txt` is a **path**, not a string. Relative paths are resolved against the file that
contains them (or the current directory for `--expr`) when they're *parsed*, so they're
always absolute by the time you use them:

```bash
echo "some data" > data.txt
nix eval --impure --expr 'builtins.typeOf ./data.txt'
test "$(nix eval --impure --raw --expr 'toString ./data.txt')" = "$PWD/data.txt"
echo "toString gives the absolute path on disk"
```

```text expect
"path"
toString gives the absolute path on disk
```

`+` on a path makes a longer path: `./. + "/data.txt"`. Paths can be read directly
(`builtins.readFile ./data.txt`), and in pure evaluation mode only paths inside the flake
or the store may be read.

## Interpolating a path copies it to the store

Putting a path inside a string (`"${./data.txt}"`) does something `toString` doesn't: it
**copies the file into the store** and returns the store path. The store copy is the only
version a builder can see (lesson 01.4):

```bash
nix eval --impure --raw --expr '"${./data.txt}"'; echo
```

```text expect
/nix/store/
-data.txt
```

`toString ./x` gives you a *location*. `"${./x}"` gives you a *store object*. Mixing them
up causes one of the most common bugs: a derivation that refers to `/home/you/project/x`,
which the sandbox doesn't have.

## String context: strings that remember where they came from

How does Nix know that a string contains a store path that has to exist? Every string
carries a hidden **context**, the set of store paths it was made from. Interpolation
adds to it; concatenation keeps it. Look at it with `builtins.getContext`:

```nix file=context.nix
let
  thing = derivation {
    name = "ctx-demo";
    system = "x86_64-linux";
    builder = "/bin/sh"; # never built in this lesson
  };
in
{
  plainString = builtins.getContext "just text";
  fromPath = builtins.getContext "${./data.txt}";
  fromDerivation = builtins.getContext "${thing}/bin/tool";
  locationOnly = builtins.hasContext (toString ./data.txt);
}
```

```bash
nix eval --json -f context.nix
```

```text expect
"plainString":{}
"locationOnly":false
-data.txt":{"path":true}
-ctx-demo.drv":{"outputs":["out"]}
```

- A copied source has a **plain path** context: "this store path must exist".
- A derivation's output has an **output** context that points at the `.drv` and the
  output name: "this output must be *built* first".
- `toString` on a path gives you no context, so nothing will make that path available.

Context isn't a curiosity: it's **how derivations get their inputs**. When you pass a
string to `derivation`, Nix collects its context. Plain paths become *input sources*;
outputs become *input derivations*. You never list inputs separately. Compare two otherwise
identical derivations, one of which throws the context away:

```nix file=inputs.nix
let
  mk =
    name: src:
    derivation {
      inherit name src;
      system = "x86_64-linux";
      builder = "/bin/sh";
    };
in
{
  withContext = mk "with-context" "${./data.txt}";
  withoutContext = mk "without-context" (builtins.unsafeDiscardStringContext "${./data.txt}");
}
```

```bash
with=$(nix-instantiate inputs.nix -A withContext)
without=$(nix-instantiate inputs.nix -A withoutContext)
echo "inputs of with-context:";    nix-store --query --references "$with"
echo "inputs of without-context:"; nix-store --query --references "$without"
test -z "$(nix-store --query --references "$without")"
```

```text expect
-data.txt
```

The second `.drv` still has `src=/nix/store/…-data.txt` in its environment, but nothing
tells Nix to make that path available, so in the sandbox it wouldn't exist. That's why the
function is called *unsafe*. (`.drv` files' references *are* their inputs, as you saw in
lesson 01.2.)

## Controlling what gets copied: `builtins.path`

`"${./src}"` copies the whole directory, junk included, and the store path's name comes
from the directory's name. `builtins.path` lets you set a fixed `name` and a `filter`.
(For anything bigger, nixpkgs' `lib.fileset` is the modern way to pick files; see
nixpkgs' `lib/fileset/README.md` and the nix.dev tutorial *Working with local files*.)

```bash
mkdir -p src
echo 'int main(void) { return 0; }' > src/main.c
echo 'temporary junk' > src/build.log
```

```nix file=src.nix
builtins.path {
  path = ./src;
  name = "my-src"; # stable name, whatever the directory is called
  filter = path: type: builtins.match ".*\\.log" path == null; # drop *.log
}
```

```bash
copy=$(nix eval --raw -f src.nix)
echo "$copy"
ls "$copy"
test ! -e "$copy/build.log"
```

```text expect
-my-src
main.c
```

Edit `build.log` and you get the same store path again, because filtered-out files don't
affect the hash. Edit `main.c` and you get a new one. A good filter keeps unrelated changes
from causing rebuilds.

## `import`

`import path` evaluates the Nix file at `path` and returns its value. A directory means its
`default.nix`. The imported file sees *nothing* from the importing file. It's a separate
expression, and you pass it data by making it a function:

```bash
mkdir -p greeter
```

```nix file=greeter/default.nix
{ name }: "Hello, ${name}!"
```

```nix file=main.nix
let
  greet = import ./greeter; # a directory: imports ./greeter/default.nix
  settings = builtins.fromJSON (builtins.readFile ./settings.json);
in
{
  message = greet { inherit (settings) name; };
  inherit (settings) port;
}
```

```bash
echo '{ "name": "Nix", "port": 8080 }' > settings.json
nix eval --json -f main.nix
```

```text expect
{"message":"Hello, Nix!","port":8080}
```

`import` is cached per file, so importing the same file twice evaluates it once.
`builtins.fromJSON`/`fromTOML` and `readFile` let you keep data outside Nix.

## Lookup paths: `<name>`

`<nixpkgs>` is a **lookup path**: Nix searches the entries of `NIX_PATH` and the `-I`
options for `nixpkgs`. It's an impure input (it depends on your environment), so pinned
code avoids it, and flakes forbid it. Using a local directory shows how it resolves:

```bash
nix-instantiate --eval -I tools="$PWD/greeter" --expr 'import <tools> { name = "lookup path"; }'
```

```text expect
"Hello, lookup path!"
```

Course 04 replaces `<nixpkgs>` with flake inputs. Until then, this path's lessons
import `./nixpkgs.nix`, a pinned `fetchTarball` (see [CONVENTIONS.md](../../CONVENTIONS.md)).

## Check yourself

<details><summary>What's the difference between <code>toString ./foo</code> and <code>"${./foo}"</code>?</summary>

`toString ./foo` is the absolute path on disk, with no string context, and nothing is
copied. `"${./foo}"` copies `foo` into the store and returns the store path, with context,
so a derivation using it gets `foo` as an input.
</details>

<details><summary>Your derivation's builder can't find <code>/home/me/project/patch.diff</code>. What's the likely bug?</summary>

The patch was passed as `toString ./patch.diff` (or a string literal) instead of the path
itself or `"${./patch.diff}"`. Without string context it isn't an input, and the sandbox
doesn't have your home directory.
</details>

<details><summary>Why does nixpkgs prefer <code>lib.fileset</code> or <code>builtins.path</code> with a <code>name</code> over <code>src = ./.;</code>?</summary>

`./.` copies everything, including `.git`, build outputs and editor files, so the hash
changes (and everything rebuilds) when unrelated files change. Also, the store path name
comes from the directory name, so a different checkout location can give a different path.
A fixed name and an explicit file set make the source reproducible.
</details>
