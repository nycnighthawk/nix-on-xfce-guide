# Project 07 — Contribution rehearsal

**Goal:** add a real package to nixpkgs, in a real nixpkgs checkout, pass every check CI would
run, and end with commits and patches you could open a pull request with.

The upstream is `greet`, a small C program that lives in this repository at
[`mastery/src/greet/`](../../src/greet/); release 1.0.0 is published as commit
`7d4aabe07a77…` (upstream doesn't tag releases yet — a common situation). It has a
`Makefile` that honours `PREFIX` and `DESTDIR`, a `make check` target, `--version`, and an MIT
licence — everything a well-behaved upstream offers. You'll package it as
`pkgs/by-name/gr/greet/package.nix` on a branch of nixpkgs 26.05 (the pinned commit), so every
dependency comes from the binary cache.

**You'll practise:**

- *read upstream first* — inspect the release and verify its hash before writing Nix;
- *the package directory is the unit of review* — one `package.nix`, auto-wired by name;
- *tests travel with the package* — `make check`, `versionCheckHook`, `passthru.tests`;
- *run CI before CI does* — the same `nix-build ci -A …` derivations GitHub Actions builds;
- *small reviewable commits* — `maintainers: add …`, then `greet: init at 1.0.0`, as patches.

Nothing here pushes, opens a PR, or needs a GitHub token. The last section shows how you would.

## 1. Read the upstream

Before packaging anything, download the exact release and look at it. `nix-prefetch-url
--unpack` fetches the archive GitHub serves for that commit, unpacks it into the store, and prints
the hash of the unpacked tree — the same hash `fetchFromGitHub` will check:

```bash
url=https://github.com/nycnighthawk/nix-on-xfce-guide/archive/7d4aabe07a77d1ea9da3d011c5215bd112a09aa8.tar.gz
out=$(nix-prefetch-url --unpack --print-path "$url")
upstream=$(sed -n 2p <<< "$out")
sri=$(nix hash convert --hash-algo sha256 --to sri "$(sed -n 1p <<< "$out")")
echo "source hash: $sri"
ls "$upstream/mastery/src/greet"
grep -E '^(VERSION|PREFIX|BINDIR|DESTDIR)|^(all|check|install):' "$upstream/mastery/src/greet/Makefile"
```

```text expect
source hash: sha256-
LICENSE
Makefile
greet.c
VERSION = 1.0.0
PREFIX ?= /usr/local
check: greet
install: greet
```

What the reviewer in you notes: the program is in a **subdirectory** of a bigger repository
(so `sourceRoot` is needed); `make` builds, `make check` tests, `make install` respects
`PREFIX`/`DESTDIR` (so stdenv's default phases will do); the licence is MIT; there are no
dependencies; there are no release tags, so the source is pinned by its full commit hash.

## 2. A nixpkgs checkout, efficiently

A full clone of nixpkgs is several gigabytes of history you don't need. Fetch one commit — the
pinned 26.05 commit — with depth 1. (For a real PR you'd base on a recent `master`; see section
9. Basing on a channel commit is what `CONTRIBUTING.md` suggests to avoid rebuilding the world.)

```bash timeout=3600
BASE=fa1373130d5a21c040a47c5dbe1913d59ed91808
git init -q nixpkgs
cd nixpkgs
git fetch -q --depth 1 https://github.com/NixOS/nixpkgs "$BASE"
git checkout -q FETCH_HEAD
git log -1 --format='%H %s'
```

```text expect
fa1373130d5a21c040a47c5dbe1913d59ed91808
```

Set an identity for this repository only, and create a topic branch:

```bash
git config user.name "Nix Mastery Learner"
git config user.email "learner@example.com"
git switch -q -c init-greet
git status --short --branch
```

```text expect
## init-greet
```

## 3. Commit 1: add yourself as a maintainer

New packages must have `meta.maintainers` (`pkgs/README.md`), and a new maintainer entry is its
own commit, *before* the package (`CONTRIBUTING.md`). For a real PR use your GitHub login and
the numeric id from `https://api.github.com/users/<login>`. This rehearsal uses a placeholder
handle, `nix-mastery-learner`.

`maintainer-list.nix` is one big attribute set kept in alphabetical order by `keep-sorted`
(CI's treefmt checks it). Insert the entry at its sorted position:

```bash
python3 - <<'EOF'
import re

path = "maintainers/maintainer-list.nix"
handle = "nix-mastery-learner"
entry = f"""  {handle} = {{
    name = "Nix Mastery Learner";
    github = "{handle}";
    githubId = 4000000001;
  }};
"""
lines = open(path, encoding="utf-8").read().splitlines(keepends=True)
start = next(i for i, l in enumerate(lines) if "keep-sorted start" in l)
key = re.compile(r'^  ("?)([^" ]+)\1 = \{$')
for i in range(start + 1, len(lines)):
    m = key.match(lines[i].rstrip("\n"))
    if m and m.group(2).lower() > handle:
        lines.insert(i, entry)
        break
else:
    raise SystemExit("no insertion point found")
open(path, "w", encoding="utf-8").write("".join(lines))
print(f"inserted {handle} before {m.group(2)}")
EOF
git diff --stat
```

```text expect
inserted nix-mastery-learner before
maintainers/maintainer-list.nix | 5 +++++
```

Format it with the formatter CI uses. `ci/default.nix` exposes it as `fmt.pkg`: `treefmt`
wrapped with the configuration in `ci/treefmt.nix` (nixfmt, keep-sorted, nixf-diagnose,
editorconfig-checker, …), all taken from CI's own pinned nixpkgs (`ci/pinned.json`). It's what
`nix fmt` runs in a checkout. Given file names, it formats just those; keep-sorted would also fix
the order if the script had got it wrong:

```bash timeout=1800
TREEFMT=$(nix-build ci -A fmt.pkg --no-out-link)/bin/treefmt
"$TREEFMT" maintainers/maintainer-list.nix
git diff --stat
```

```text expect
maintainers/maintainer-list.nix | 5 +++++
```

Check it the way CI does — `lib/tests/maintainers.nix` validates every entry's fields and that
`github`/`githubId` are unique — and that it evaluates as `lib.maintainers.nix-mastery-learner`:

```bash
nix-build lib/tests/maintainers.nix --no-out-link
nix-instantiate --eval --strict -A lib.maintainers.nix-mastery-learner.github
```

```text expect
checked-maintainers-success
"nix-mastery-learner"
```

```bash
git add maintainers/maintainer-list.nix
git commit -q -m "maintainers: add nix-mastery-learner"
git log --oneline -1
```

```text expect
maintainers: add nix-mastery-learner
```

## 4. Commit 2: the package

The shard is `gr` (first two letters of `greet`). Every line below is there for a reason
covered in lessons 2–4:

```nix file=pkgs/by-name/gr/greet/package.nix
{
  lib,
  stdenv,
  fetchFromGitHub,
  testers,
  versionCheckHook,
  nix-update-script,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "greet";
  version = "1.0.0";

  __structuredAttrs = true;
  strictDeps = true;

  src = fetchFromGitHub {
    owner = "nycnighthawk";
    repo = "nix-on-xfce-guide";
    rev = "7d4aabe07a77d1ea9da3d011c5215bd112a09aa8";
    hash = "sha256-Kd0Lg2p5xN6A7QWPUYyRlVycCV69tSYwTogzSAOLkKg=";
  };

  # The program lives in a subdirectory of the repository.
  sourceRoot = "${finalAttrs.src.name}/mastery/src/greet";

  makeFlags = [
    "CC=${stdenv.cc.targetPrefix}cc"
    "PREFIX=${placeholder "out"}"
  ];

  doCheck = true;

  doInstallCheck = true;
  nativeInstallCheckInputs = [ versionCheckHook ];

  passthru = {
    tests.version = testers.testVersion { package = finalAttrs.finalPackage; };
    updateScript = nix-update-script { };
  };

  meta = {
    description = "Minimal greeting program used to rehearse Nixpkgs contributions";
    homepage = "https://github.com/nycnighthawk/nix-on-xfce-guide/tree/main/mastery/src/greet";
    license = lib.licenses.mit;
    maintainers = with lib.maintainers; [ nix-mastery-learner ];
    mainProgram = "greet";
    platforms = lib.platforms.unix;
  };
})
```

Notes a reviewer would check:

- **`rev = "7d4aabe…"`** (the full 40-character hash) — `fetchFromGitHub` takes either `tag` or
  `rev`, never both (`pkgs/build-support/fetchgithub/default.nix` asserts it). Upstream has no
  release tags, so the commit is the only stable name. When upstreams do tag releases, prefer
  `tag = "v${finalAttrs.version}"` so an update only touches `version` and `hash` — and it's
  worth asking upstream to start tagging.
- **`sourceRoot = "${finalAttrs.src.name}/mastery/src/greet"`** — stdenv unpacks the source into
  a directory named after the source derivation (`source`, the default from
  `config.fetchedSourceNameDefault`) and then `cd`s into `sourceRoot`. Using `src.name` instead
  of hard-coding `source` keeps it right if that name ever changes.
- **`CC=${stdenv.cc.targetPrefix}cc`** — the Makefile uses `$(CC)`; passing the prefixed compiler
  makes cross-compilation work (`aarch64-unknown-linux-gnu-cc`). `placeholder "out"` is the
  output path, known only at build time.
- **`doCheck`** runs `make check`; **`versionCheckHook`** runs `$out/bin/greet --version` in an
  empty environment; **`passthru.tests.version`** is the same check as a separate derivation that
  follows overrides.
- **`meta.description`**: no article, no package name, no period. **`license`** matches upstream.

Format it with CI's treefmt, then confirm with `nixfmt --check` — using the nixfmt from CI's
pinned package set (`nix-build ci -A pkgs.nixfmt`), so "formatted" means what CI means by it.
(Section 6 also runs CI's whole-tree format check.)

treefmt finds files through git, so stage the new file first:

```bash
git add pkgs/by-name/gr/greet/package.nix
"$TREEFMT" pkgs/by-name/gr/greet/package.nix
NIXFMT=$(nix-build ci -A pkgs.nixfmt --no-out-link)/bin/nixfmt
"$NIXFMT" --check pkgs/by-name/gr/greet/package.nix maintainers/maintainer-list.nix
grep -F "$sri" pkgs/by-name/gr/greet/package.nix
```

The last line confirms the hash in the package is the one you computed from the release
yourself in step 1 — trust on first use, but verified.

### Build it like a reviewer

From the root of the checkout, exactly as `pkgs/README.md` says:

```bash timeout=1800
nix-build -A greet
./result/bin/greet
./result/bin/greet --version
```

```text expect
Hello from greet 1.0.0
greet 1.0.0
```

Did the tests actually run? The build log says so:

```bash
nix log ./result | grep -E 'Running phase: (checkPhase|installCheckPhase)|Successfully managed to find version'
```

```text expect
Running phase: checkPhase
Running phase: installCheckPhase
Successfully managed to find version 1.0.0
```

Run the package tests (what ofborg builds for a `greet:` commit), and rebuild once more to
check the build is deterministic:

```bash
nix-build -A greet.tests --no-out-link
nix-build -A greet --check --no-out-link
```

```text expect
greet-1.0.0-test-version
```

Evaluate it the way CI's Eval job does — with `checkMeta` — and for another platform, and check
the update script evaluates:

```bash
nix-instantiate -A greet --arg config '{ checkMeta = true; }'
nix-instantiate -A pkgsCross.aarch64-multiplatform.greet
nix-instantiate --eval --strict -A greet.updateScript
```

```text expect
greet-1.0.0.drv
greet-aarch64-unknown-linux-gnu-1.0.0.drv
/bin/nix-update
```

Commit it with a title CI accepts and a body that says what the software is:

```bash
rm -f result
git add pkgs/by-name/gr/greet/package.nix
git commit -q -F - <<'EOF'
greet: init at 1.0.0

greet is a minimal C program that prints a greeting. It is the upstream
used by the Nix mastery path to rehearse a nixpkgs contribution.

https://github.com/nycnighthawk/nix-on-xfce-guide/tree/main/mastery/src/greet
EOF
git log --oneline "$BASE"..HEAD
```

```text expect
greet: init at 1.0.0
maintainers: add nix-mastery-learner
```

## 5. Pre-flight: the by-name rules, fast

`nixpkgs-vet` takes a few minutes (next section). A quick partial check of the same rules
first (the script from lesson 2):

```bash file=../by-name-check.sh
#!/usr/bin/env bash
# by-name-check.sh ROOT ATTR... — a quick, partial re-implementation of some
# nixpkgs-vet rules for pkgs/by-name. The real check is nixpkgs-vet.
set -uo pipefail
root=$1
shift
status=0
fail() {
  echo "by-name-check: $*"
  status=1
}
for attr in "$@"; do
  [[ $attr =~ ^[a-zA-Z_][a-zA-Z0-9_-]*$ ]] || fail "$attr: not a valid attribute name"
  shard=$(printf '%s' "${attr:0:2}" | tr '[:upper:]' '[:lower:]')
  dir=$root/pkgs/by-name/$shard/$attr
  if [[ ! -f $dir/package.nix ]]; then
    fail "$attr: expected pkgs/by-name/$shard/$attr/package.nix"
    continue
  fi
  if grep -rnE --include='*.nix' '(^|[^.])\.\./' "$dir"; then
    fail "$attr: refers to a path outside its directory"
  fi
  if grep -rn --include='*.nix' '<nixpkgs' "$dir"; then
    fail "$attr: uses <nixpkgs>"
  fi
  all=$root/pkgs/top-level/all-packages.nix
  if [[ -f $all ]] && grep -nE "^  $attr = callPackage .*\{ \};" "$all"; then
    fail "$attr: also defined in all-packages.nix with no arguments"
  fi
done
[[ $status == 0 ]] && echo "by-name-check: ok ($*)"
exit $status
```

```bash
bash ../by-name-check.sh . greet
```

```text expect
by-name-check: ok (greet)
```

## 6. Run CI's lint jobs locally

These are the exact derivations from `ci/default.nix` that `.github/workflows/lint.yml` builds.
They use CI's own pinned nixpkgs (`ci/pinned.json`, a `nixpkgs-unstable` commit) for the tools,
so the first run downloads that and the tools from the cache.

**nixpkgs-vet** compares a *base* tree with a *head* tree. CI checks out the target branch as
base and the PR's merge commit as head, each as a git worktree; do the same with the pinned
commit as base and your branch as head:

```bash timeout=3600
git worktree add -q --detach ../nixpkgs-base "$BASE"
nix-build ci -A nixpkgs-vet --arg base ../nixpkgs-base --arg head ./. --no-out-link
```

```text expect
nixpkgs-vet
```

(`./ci/nixpkgs-vet.sh master` does the same against the current `master`, fetching it first.)
Both trees are filtered through `lib.fileset.gitTracked`, so only committed (or staged) files
count — another reason to commit before you check.

**treefmt** formats a copy of the whole tree — nixfmt, keep-sorted (which is why the maintainer
entry had to be in order), editorconfig-checker, and more, as configured in `ci/treefmt.nix` —
and fails if anything changed:

```bash timeout=3600
nix-build ci -A fmt.check --no-out-link
```

If it fails, the log ends with the diff; `nix fmt` (or `nix-shell --run treefmt`) in the
checkout applies the fixes.

**Commit messages** — the rules of `ci/github-script/lint-commits.ts`, as in lesson 4, over
every commit on the branch:

```bash
lint_commit() {
  local subject=$1 status=0
  local conventional='^(build|chore|ci|doc|docs|feat|feature|fix|perf|refactor|services|style|test|update)!?(\(.*\))?!?:'
  if [[ $subject != *": "* ]]; then echo "x no ': ' in: $subject"; status=1; fi
  if [[ $subject == *. ]]; then echo "x ends with a period: $subject"; status=1; fi
  if [[ $subject =~ ^(amend|fixup|squash)! ]]; then echo "x unsquashed fixup: $subject"; status=1; fi
  if [[ $subject =~ $conventional ]]; then echo "x Conventional Commits style: $subject"; status=1; fi
  if (( status == 0 )); then echo "ok: $subject"; fi
  return $status
}
git log --format=%s "$BASE"..HEAD | while read -r subject; do lint_commit "$subject" || exit 1; done
git log --format='%an <%ae>' "$BASE"..HEAD | sort -u
```

```text expect
ok: greet: init at 1.0.0
ok: maintainers: add nix-mastery-learner
Nix Mastery Learner <learner@example.com>
```

## 7. The patches

`git format-patch` turns each commit into a mail-ready file: the form you'd send to the
Discourse "Patches" category without a GitHub account, and a portable record of the branch.

```bash
git format-patch -q -o ../patches "$BASE"..HEAD
ls ../patches
sed -n '1,/^---$/p' ../patches/0002-greet-init-at-1.0.0.patch
```

```text expect
0001-maintainers-add-nix-mastery-learner.patch
0002-greet-init-at-1.0.0.patch
Subject: [PATCH 2/2] greet: init at 1.0.0
greet is a minimal C program that prints a greeting.
```

Prove the patches are complete: apply them to a clean worktree of the base and compare trees.

```bash
git worktree add -q --detach ../verify "$BASE"
git -C ../verify am -q "$(cd ../patches && pwd)"/*.patch
git diff --quiet HEAD "$(git -C ../verify rev-parse HEAD)" && echo "patches reproduce the branch exactly"
```

```text expect
patches reproduce the branch exactly
```

Clean up the extra worktrees:

```bash
git worktree remove --force ../verify
git worktree remove --force ../nixpkgs-base
```

## 8. The PR description

Write it now, while you remember what you tested. It follows
`.github/PULL_REQUEST_TEMPLATE.md`; tick only what you did.

```markdown file=../pr-body.md
Add greet, a minimal C program that prints a greeting. It is the upstream used by the
Nix mastery path to rehearse a contribution:
https://github.com/nycnighthawk/nix-on-xfce-guide/tree/main/mastery/src/greet

Also adds myself as a maintainer.

## Things done

- Built on platform:
  - [x] x86_64-linux
  - [ ] aarch64-linux
  - [ ] aarch64-darwin
- Tested, as applicable:
  - [ ] [NixOS tests] in [nixos/tests].
  - [x] [Package tests] at `passthru.tests`.
  - [ ] Tests in [lib/tests] or [pkgs/test] for functions and "core" functionality.
- [ ] Ran `nixpkgs-review` on this PR. See [nixpkgs-review usage].
- [x] Tested basic functionality of all binary files, usually in `./result/bin/`.
- Nixpkgs Release Notes
  - [ ] Package update: when the change is major or breaking.
- NixOS Release Notes
  - [ ] Module addition: when adding a new NixOS module.
  - [ ] Module update: when the change is significant.
- [x] Fits [CONTRIBUTING.md], [pkgs/README.md], [maintainers/README.md] and other READMEs.
- [x] Follows the [automation/AI policy].
```

```bash
grep -c '\[x\]' ../pr-body.md
```

## 9. How you would open the real PR (not run)

For a real contribution, rebase onto the current `master` (new packages go to `master`; they
may be backported later), re-run the checks, push to your fork, and open the PR:

```console
$ git remote add upstream https://github.com/NixOS/nixpkgs.git
$ git fetch --depth 1 upstream master
$ git rebase upstream/master                 # shallow history is fine for a 2-commit branch
$ nixpkgs-review rev HEAD                    # builds greet and anything else affected
$ git remote add fork git@github.com:<you>/nixpkgs.git
$ git push --set-upstream fork init-greet
$ gh pr create --repo NixOS/nixpkgs --base master \
    --title "greet: init at 1.0.0" --body-file ../pr-body.md
```

Then watch the checks (Lint, Eval, Build, ofborg), answer every review comment in one round,
and keep the branch rebased and green. When it's merged, the package reaches
`nixpkgs-unstable` with the next channel update; with the `backport release-26.05` label (or a
manual `git cherry-pick -x`), 26.05 users get it too.

## Verification

You're done when all of these hold (each was checked above):

- [ ] `nix-build -A greet` succeeds and `./result/bin/greet` prints `Hello from greet 1.0.0`;
- [ ] the build log shows `make check` and the version check ran;
- [ ] `nix-build -A greet.tests` and `nix-build -A greet --check` succeed;
- [ ] it evaluates with `checkMeta = true` and for `aarch64-multiplatform`;
- [ ] `nix-build ci -A nixpkgs-vet` and `nix-build ci -A fmt.check` succeed;
- [ ] both commit titles pass the lint, and the patches reproduce the branch.

## Stretch goals

- Run `nixpkgs-review rev HEAD` in the checkout (it evaluates nixpkgs twice — give it time and
  a few GB of RAM) and read its report.
- Build the cross package for real: `nix-build -A pkgsCross.aarch64-multiplatform.greet`, then
  run it with `qemu-aarch64` (course 05 L4). What would have broken without the `CC=` flag?
- Add a `passthru.tests.run` that compares `greet`'s output with the expected greeting, in a
  `test.nix` next to `package.nix` (like `pkgs/by-name/he/hello/test.nix`).
- Pretend upstream released 1.0.1: change `version`, set `hash = lib.fakeHash`, and follow the
  error to the new hash — or run `nix-shell maintainers/scripts/update.nix --argstr package greet`
  and let `nix-update` do it. What would the commit title be?
