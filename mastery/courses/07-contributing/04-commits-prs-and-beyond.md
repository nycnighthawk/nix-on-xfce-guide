# Lesson 07.4 — Commits, PRs, maintainers, and beyond packages

**You will:** write commits CI accepts (checked by a local copy of its lint), know what the PR
template asks, add a maintainer entry and validate it, give a package an update script, backport
with `cherry-pick -x` — and see where else in the ecosystem you can contribute.

```nix file=nixpkgs.nix
# nixpkgs 26.05, pinned to an exact commit
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
  sha256 = "16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z";
})
```

```bash
NIXPKGS=$(nix-instantiate --eval --expr 'toString (import ./nixpkgs.nix { }).path' | tr -d '"')
```

## Commits

nixpkgs history is read by people bisecting a regression years later, by bots, and by CI.
The rules (`CONTRIBUTING.md` "Commit conventions", and `pkgs/README.md`, `nixos/README.md`,
`doc/README.md`, `lib/README.md` for their areas):

- **One commit per logical change.** A version bump and an unrelated refactor are two commits.
  Squash `oops, fix typo` commits away before review.
- **Title: `<area>: <what>`, no trailing period.**

  | Change | Title |
  |---|---|
  | new package | `greet: init at 1.0.0` |
  | update | `greet: 1.0.0 -> 1.1.0` (`→` is accepted too) |
  | other package change | `greet: fix cross compilation` |
  | NixOS module | `nixos/greet: init module`, `nixos/nginx: add bazBaz option` |
  | docs | `doc: add information about nix-update-script` |
  | yourself as maintainer | `maintainers: add nix-mastery-learner` (its own commit, *before* the package) |

- **Body: why.** For updates, link the changelog. For new packages, say what it is.
- The `pkg:` prefix isn't decoration: it tells the build bot which attributes to build
  (`pkgs/README.md` has a table, including `python3{12,13}Packages.foo:` forms).

CI's `commits` job (`ci/github-script/lint-commits.ts`) rejects a title that has no `: `, ends in
`.`, starts with `fixup!`/`squash!`/`amend!`, or looks like Conventional Commits
(`feat:`, `fix(scope):` — nixpkgs has its own format). Here are the same rules as a shell
function, so you can check before you push:

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
lint_commit "greet: init at 1.0.0"
lint_commit "greet: 1.0.0 -> 1.1.0"
lint_commit "nixos/greet: init module"
```

```text expect
ok: greet: init at 1.0.0
ok: greet: 1.0.0 -> 1.1.0
ok: nixos/greet: init module
```

```bash fails
lint_commit "feat: add greet"
```

```text expect
x Conventional Commits style: feat: add greet
```

```bash fails
lint_commit "greet: init at 1.0.0."
```

```text expect
x ends with a period: greet: init at 1.0.0.
```

(The real check is a little smarter: it allows `doc: …` when the commit touches a path
segment named `doc`, so documentation commits pass.)

### Automation and AI tools

`CONTRIBUTING.md` ("Automation/AI policy") requires a responsible human who understands and
reviewed every contribution, and disclosure of non-trivial use of automated tools. For
LLM-based tools in commits this **must** be an `Assisted-by:` trailer naming the tool and model
(a `Co-authored-by:` trailer doesn't count):

```console
$ git commit -m "greet: init at 1.0.0" --trailer "Assisted-by: <tool> (<model and version>)"
```

Deterministic tools (formatters, `nix-update`, the r-ryantm bot) are exempt.

## The pull request

- **Title** = your commit title (or a summary for several commits). `WIP:` or `[WIP]` in the
  title stops automatic builds; a *draft* PR does not.
- **Base branch** from lesson 1 (`master` unless it's a mass rebuild).
- **Description**: what and why; for new packages, what the software is and its homepage.
- **The template** fills in a checklist. Tick only what you did:

```bash
sed -n '/^## Things done/,/^\[NixOS tests\]/p' "$NIXPKGS/.github/PULL_REQUEST_TEMPLATE.md"
```

```text expect
Built on platform:
Ran `nixpkgs-review` on this PR.
Tested basic functionality of all binary files
Follows the [automation/AI policy].
```

Then expect to wait. `CONTRIBUTING.md` ("I opened a PR, how do I get it merged?") is honest:
committers are volunteers; days or weeks without feedback are normal. Make the PR easy to
review (small, tested, explained), get a non-committer review, and ask politely in the
"PRs ready for review" Discourse thread or the review-requests Matrix room after a week.

## Becoming a maintainer

A maintainer keeps a package working and gets review requests for it; it doesn't give exclusive
control (`maintainers/README.md`). To become one, add yourself to
`maintainers/maintainer-list.nix` — alphabetically, in its own `maintainers: add <handle>`
commit — and put the handle in `meta.maintainers`. The entry (format from the file's header):

```nix
  nix-mastery-learner = {
    name = "Nix Mastery Learner";        # required
    github = "nix-mastery-learner";      # required: your GitHub login
    githubId = 4000000001;               # required: from https://api.github.com/users/<login>
    email = "you@example.org";           # optional; matrix and keys too
  };
```

`githubId` is required because logins can be renamed; the numeric id can't. CI validates every
entry against `lib/tests/maintainer-module.nix` (via `lib/tests/maintainers.nix`, part of
`lib-tests`). Check an entry the same way:

```nix file=maintainer-check.nix
{ entry }:
let
  pkgs = import ./nixpkgs.nix { };
  evaluated = pkgs.lib.evalModules {
    modules = [
      (pkgs.path + "/lib/tests/maintainer-module.nix")
      { config = entry; }
    ];
  };
in
removeAttrs evaluated.config [ "_module" ]
```

```bash
nix-instantiate --eval --strict maintainer-check.nix --arg entry '{
  name = "Nix Mastery Learner";
  github = "nix-mastery-learner";
  githubId = 4000000001;
}'
```

```text expect
github = "nix-mastery-learner";
githubId = 4000000001;
```

```bash fails
nix-instantiate --eval --strict maintainer-check.nix --arg entry '{
  name = "Nix Mastery Learner";
  github = "nix-mastery-learner";
}'
```

```text expect
githubId
```

Once your first PR with the entry is merged, you're invited to the `NixOS/nixpkgs-maintainers`
team (RFC 39) and can, among other things, ask the merge bot to merge eligible PRs to your
packages: comment `@NixOS/nixpkgs-merge-bot merge` on a PR by r-ryantm or a committer that
touches only by-name packages you maintain (`CONTRIBUTING.md`, "How to merge pull requests
yourself").

## Update scripts

The r-ryantm bot (nixpkgs-update) periodically tries to update every package with a
`passthru.updateScript`, opens the PR, and builds it. For most packages, `nix-update-script`
is enough: it runs `nix-update`, which finds the newest release, changes `version`, and fixes
every hash (`pkgs/README.md`, "Automatic package updates"). If upstream's tags aren't plain
versions — say an upstream tags its releases `greet-v1.0.0` — tell it how to read them:

```nix
{ nix-update-script, ... }:
{
  passthru.updateScript = nix-update-script {
    extraArgs = [
      "--version-regex"
      "greet-v(.*)"
    ];
  };
}
```

An update script is just a command (a list of strings) that maintainer tooling runs:

```bash
nix-instantiate --eval --strict --expr 'with import ./nixpkgs.nix { };
  nix-update-script { extraArgs = [ "--version-regex" "greet-v(.*)" ]; }'
```

```text expect
/bin/nix-update
"--version-regex"
"greet-v(.*)"
```

In a checkout you can run it yourself — `nix-shell maintainers/scripts/update.nix --argstr
package greet` — and `--arg commit true` makes one commit per update with the right title.

## Backports

From lesson 1: changes acceptable for a release are merged to `master` first, then
cherry-picked to `release-26.05`. `-x` appends the original commit hash, so anyone can trace the
backport. Try it on a toy repository:

```bash
git init -q -b master toy && cd toy
git config user.name "Nix Mastery Learner"
git config user.email "learner@example.com"
echo 1.0.0 > version && git add version && git commit -q -m "greet: init at 1.0.0"
git branch release-26.05
echo 1.0.1 > version && git commit -q -a -m "greet: 1.0.0 -> 1.0.1" -m "Fixes a crash on empty input."
fix=$(git rev-parse HEAD)
git switch -q release-26.05
git cherry-pick -x "$fix" > /dev/null
git log -1 --format=%B
cd ..
```

```text expect
greet: 1.0.0 -> 1.0.1
Fixes a crash on empty input.
(cherry picked from commit
```

Use `git cherry-pick -xe` when the reason for the backport isn't obvious, so you can add it.
The backport PR title starts with `[26.05]` and links the original PR. Maintainers can instead
add the `backport release-26.05` label and let a bot do all of this.

## Beyond packages

Packages are the easiest way in, not the only one.

**NixOS modules and tests.** Modules live under `nixos/modules/` and are listed in
`nixos/modules/module-list.nix`; tests live in `nixos/tests/` and are registered in
`nixos/tests/all-tests.nix` (`nginx = runTest ./nginx.nix;`). A new module needs a VM test, a
release-note entry in `nixos/doc/manual/release-notes/rl-2611.section.md` ("New Modules"), and a
`nixos/<name>: init module` commit; `nixos/README.md` has the reviewers' checklist. Course 06
and the capstone teach both halves.

```bash
grep -c 'runTest\|handleTest' "$NIXPKGS/nixos/tests/all-tests.nix"
wc -l < "$NIXPKGS/nixos/modules/module-list.nix"
```

**Documentation.** The nixpkgs manual is `doc/` and the NixOS manual is `nixos/doc/manual/`,
both CommonMark with extensions, rendered by `nixos-render-docs`. Build the one you changed with
`nix-build ci -A manual-nixpkgs` (or `-A manual-nixos`); commit as `doc: …`. Fixing a confusing
paragraph you just struggled with is a perfect first PR.

**`lib`.** Functions in `lib/` need tests in `lib/tests/` (`nix-build lib/tests/release.nix`)
and doc comments in the RFC 145 format that the manual renders.

**Nix itself.** Nix is a separate C++ repository, github.com/NixOS/nix, with its own team,
review process and release schedule. Its flake gives you the whole toolchain:

```console
$ git clone https://github.com/NixOS/nix && cd nix
$ nix develop            # compilers, Meson, test dependencies, pinned by the repo's flake.lock
$ nix build              # the default package, built exactly as CI does
```

Inside `nix develop` you build and run the unit and functional tests incrementally; the exact
commands for the current version are in the repo's `doc/manual/source/development/` chapter
("Building", "Testing"). Start with issues labelled *good first issue*, and with documentation:
the Nix manual lives in the same repository.

**RFCs.** Changes that affect the whole community — formats, policies, large migrations — go
through the RFC process at github.com/NixOS/rfcs: copy the template, open a PR, a shepherd team
is nominated, the discussion converges, and a final comment period ends in acceptance or
rejection. Several things in this course came from RFCs: `pkgs/by-name` (RFC 140), the nixfmt
style (RFC 166), the maintainer team invitations (RFC 39), and the plan to stabilise flakes and
the new CLI piece by piece (RFC 136). Reading accepted RFCs is the best way to learn *why*
nixpkgs works the way it does.

## Check yourself

<details><summary>You're adding a package and yourself as its maintainer. How many commits, in what order?</summary>

Two: `maintainers: add <handle>` first, then `<pkg>: init at <version>`. The package commit
refers to `lib.maintainers.<handle>`, so the history stays buildable at every commit.
</details>

<details><summary>Why does <code>maintainer-list.nix</code> require <code>githubId</code> and not just <code>github</code>?</summary>

GitHub logins can change or be re-registered by someone else; the numeric id is permanent. Review
requests and team invitations are tied to the account, not the name.
</details>

<details><summary>What does <code>git cherry-pick -x</code> add, and why does nixpkgs want it?</summary>

A `(cherry picked from commit <sha>)` line in the message, linking the backport to the commit on
`master`. Reviewers can check the backport matches, and tooling can track what has been
backported.
</details>

<details><summary>A PR titled <code>feat(greet): add greet package</code> — what will CI say?</summary>

The commit-lint job fails it as Conventional Commits style; nixpkgs wants `greet: init at 1.0.0`.
</details>

## Stretch goals

- Read `ci/github-script/lint-commits.ts` and extend `lint_commit` to take the list of changed
  paths, so that `doc: …` passes when a path segment is `doc`.
- Pick an accepted RFC from the list above and find the commit in nixpkgs that implemented it.
- Find an open nixpkgs PR for a package you use, run `nixpkgs-review pr <number>` on it, and
  leave a review saying what you tested.
