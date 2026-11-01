# Authoring conventions

Every course lives in `mastery/courses/NN-slug/`:

```
README.md              course overview: goals, prerequisites, structure, patterns, "check yourself"
01-<lesson>.md         lessons, in order
02-<lesson>.md
project-a-<name>.md    projects, in order (project-b-…, project-c-…)
```

CI runs `README.md`, then every other `*.md` in sorted order, **each in a fresh empty
directory**, in one shell per file, after Nix is installed by `00-setup/01-install.md`.
So every file must be self-contained: create the files it needs, don't rely on another lesson's
leftovers. (Nix's store and `nix.conf` do carry over — that's the machine, not the lesson.)

## Runnable Markdown (executed by `ci/mdrun.py`)

| Fence info string | Meaning |
|---|---|
| ` ```bash ` | Run. Every command must succeed (`set -e`). One persistent shell per file. |
| ` ```bash fails ` | Run. Must exit non-zero. Use it to show an error on purpose (hash mismatch, purity violation). Keep these to one command. |
| ` ```bash timeout=3600 ` | Run with a longer timeout (seconds; default 2400). |
| ` ```nix file=path/x.nix ` | Write this file (path relative to the shell's current directory). Any language works: ` ```c file=src/main.c `. |
| ` ```text expect ` | Every non-empty line must appear (substring) in the previous run block's output. |
| ` ```console `, ` ```text `, ` ```nix ` (no `file=`), ` ```bash skip ` | Shown only, never run. Use for sample output, interactive commands (`nix repl`), fragments. |

Rules:
- Never assert exact store hashes or timings in `expect` — they differ by machine/time.
  Assert stable text (`hello-2.12.3`, `true`, a version string).
- Interactive programs (`nix repl`, `nvim`, `less`) go in ` ```console ` blocks; give a
  runnable non-interactive equivalent next to them (`nix eval`, `nix-instantiate --eval`).
- Long-running commands get `timeout=`.
- Files the learner writes are given in full with `file=`. For "your turn" exercises, state the
  task, then put the solution under a `<details><summary>Solution</summary>` element — and the
  solution's blocks **are run** (so solutions are tested too).

## Pins (use these, don't invent new ones)

- Classic (non-flake) lessons import nixpkgs like this (create it as `nixpkgs.nix` in the lesson):
  ```nix
  # nixpkgs 26.05, pinned to an exact commit
  import (builtins.fetchTarball {
    url = "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz";
    sha256 = "@@NIXPKGS_2605_SHA256@@";
  })
  ```
- Flakes use `inputs.nixpkgs.url = "github:NixOS/nixpkgs/fa1373130d5a21c040a47c5dbe1913d59ed91808";`
  and, where a second version is needed, `github:NixOS/nixpkgs/b6018f87da91d19d0ab4cf979885689b469cdd41` (25.11).
- Lessons may mention the moving branches (`nixos-26.05`, `nixos-unstable`) when teaching pinning.
- Known source hash: GNU hello 2.12.3 `sha256-DV9gFUOC/uELEUocNOeF2LH0kgc64tOm97FHaHs2aqA=`
  (`mirror://gnu/hello/hello-2.12.3.tar.gz`). Placeholders `@@HELLO_2_12_1_SRI@@`,
  `@@HELLO_2_10_SRI@@` are filled in from the CI probe.
- System: `x86_64-linux`. User: whoever runs it (CI uses `tester`); never hard-code a username.

## Voice

- Second person, present tense, short sentences. Explain *why* before *how*.
- Each lesson: a one-line "You will:", then sections, then a "Check yourself" with 2–4
  questions and answers in `<details>`.
- Each project: goal, what you'll practise (named patterns), steps, verification, stretch goals.
- Cite the primary source for non-obvious claims (manual section names, nixpkgs file paths).
- Prefer current conventions (see `CURATION.md`): `finalAttrs`, `__structuredAttrs = true`,
  by-name, `nix fmt`/nixfmt, SRI hashes.
