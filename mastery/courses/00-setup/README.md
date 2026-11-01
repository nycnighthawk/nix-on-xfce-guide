# Course 00 · Setup and first contact

**Goals.** After this course you can:
- install Nix on Xubuntu the supported way and check it's a safe version;
- tell the classic CLI (`nix-shell`, `nix-build`, `nix-store`) from the newer `nix` command;
- run any of 100,000+ packages without installing them;
- read a store path and say what each part means;
- write scripts that bring their own tools.

**Prerequisites.** Xubuntu 26.04 (or another Ubuntu-based Xfce desktop) and `sudo`.

**Structure.**

| | File | Time |
|---|---|---|
| Lesson 1 | [Install Nix and verify it](01-install.md) | 15 min |
| Lesson 2 | [First commands and the store](02-first-commands.md) | 30 min |
| Project | [Throwaway tool belt](project-a-tool-belt.md) | 30 min |

**Patterns you'll use from here on.**
- *Ad-hoc environments:* need a tool once? `nix shell nixpkgs#tool`, then it's gone.
- *Reproducible scripts:* the script declares its own dependencies, pinned to an exact nixpkgs.

**How this path is tested.** Every lesson's `bash` blocks run in CI on a fresh Xubuntu 26.04
VM in order. You can check your own work the same way:

```bash skip
python3 mastery/ci/mdrun.py mastery/courses/00-setup/02-first-commands.md
```

**Check yourself** (after the course)

<details><summary>Why does Nix use a daemon on a multi-user machine?</summary>
So builds run as unprivileged build users in a sandbox, and normal users can't write to
`/nix/store` directly. Everyone shares one store safely.
</details>
<details><summary>`nix shell nixpkgs#cowsay` — what changed on your system afterwards?</summary>
Only `/nix/store` gained some paths. Nothing was "installed": no profile changed and no
files outside `/nix` were touched. Garbage collection can remove them later.
</details>
