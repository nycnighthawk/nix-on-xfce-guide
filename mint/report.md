# mint: guide test

Neovim option tested: B

## Steps

| # | Step | Result | Notes |
|---|---|---|---|
| 0 | Update the system and get prerequisites | PASS |  |
| 1 | Run the official installer in daemon mode | PASS | --yes answers the installer's prompts; skipped `less` (paging needs a human) |
| 5 | Open a new terminal and verify | PASS |  |
| 6 | Write /etc/nix/nix.conf settings | PASS |  |
| 7 | Restart the daemon and check | PASS |  |
| 8 | Create the config repo | PASS |  |
| 9 | Create flake.nix | PASS | file written exactly as shown |
| 10 | Create home.nix | PASS | file written exactly as shown |
| 11 | Create a placeholder nvim.nix | PASS |  |
| 12 | Bootstrap and switch | PASS |  |
| 13 | Log out of Xfce and back in | PASS | logged out and back in (LightDM restart) |
| 15 | Version your existing config through Home Manager | PASS | a small hand-written ~/.config/nvim/init.lua stands in for your existing config |
| 16 | Apply and check | PASS | full-screen Neovim screenshotted, then quit |
| 17 | Pick a template and save it as flake.nix in the project root | PASS | Python template saved as ~/code/myproject/flake.nix |
| 17 | Pick a template and save it as flake.nix in the project root | PASS | node template dev shell |
| 17 | Pick a template and save it as flake.nix in the project root | PASS | rust template dev shell |
| 17 | Pick a template and save it as flake.nix in the project root | PASS | go template dev shell |
| 17 | Pick a template and save it as flake.nix in the project root | PASS | c template dev shell |
| 18 | Wire it to direnv | PASS | full-screen Neovim screenshotted, then quit |
| 19 | One-off tools without installing anything | PASS | `nix shell` given a command instead of opening an interactive subshell |
| 20 | Let Nix's bubblewrap create sandboxes | PASS |  |
| 21 | Create project A | PASS |  |
| 22 | Write project A's flake.nix | PASS | file written exactly as shown |
| 23 | Make project B with different versions | PASS |  |
| 24 | Prove the projects don't interfere | PASS |  |
| 25 | Pin Claude Code per project | PASS |  |
| 26 | Give Claude Code each project's rules | PASS |  |
| 27 | Start Claude Code inside project A | PASS | Claude Code's first screen (login) screenshotted, then quit |
| 28 | The reproducible build | PASS |  |
| 29 | Update one project, never both | PASS |  |
| 30 | Audit what's already polluting the base system | PASS | -y answers apt's [Y/n] on the example removal |
| 31 | Update your home environment deliberately | PASS |  |
| 32 | Roll back if an update breaks something | PASS | `<hash>` filled in with the previous generation from the listing |
| 33 | Reclaim disk space | PASS |  |
| 34 | Set up a second machine | PASS | emulated: cloned the local config repo instead of a remote one |
| 35 | Remove Home Manager's files first | PASS | `yes |` answers the uninstall confirmation |
| 37 | Undo the multi-user install | PASS |  |
| None | Nix fully removed; new terminal starts clean | PASS | Nix fully removed; new terminal starts clean |

## Checks

| Check | Result |
|---|---|
| HM tools on PATH in a new terminal | PASS |
| Session variables (EDITOR, PIP_REQUIRE_VIRTUALENV, XDG_DATA_DIRS) | PASS |
| git identity from Home Manager | PASS |
| Neovim starts with no errors | PASS |
| checkhealth reports no ERROR | PASS |
| nil_ls (from extraPackages) attaches to a .nix file with your own config | PASS |
| lua_ls attaches to a .lua file | PASS |
| option B: ~/.config/nvim is a live link to the repo copy | PASS |
| dev shell: python from .venv, pyright, ruff | PASS |
| pip refuses to install outside a venv | PASS |
| nix search finds neovim | PASS |
| unprivileged user namespaces work for Nix's bwrap (what Claude Code's sandbox needs) | PASS |
| project A: Node 22 + Python 3.12; npm -g went into A's .cache | PASS |
| project B: Node 24 + Python 3.13; no cowsay | PASS |
| host: no cowsay anywhere outside project A | PASS |
| claude comes from each project's /nix/store, not the host | PASS |
| project B's sandbox hides project A; A's hides B | PASS |
| direnv loads project A's shell (Node 22, Python 3.12, claude, bwrap) | PASS |
| leaving the project unloads it (no claude outside it) | PASS |
| build output is the same path every time (and identical on rebuild) | PASS |
| project B builds on Node 24 | PASS |
| a failing build makes the Stop hook block (exit 2) with the error | PASS |
| project A's lock didn't move | PASS |
| roll forward again | PASS |
| page's nix.gc snippet builds and installs a timer: nix.gc = { automatic = true; dates = "weekly"; options = "--delete-older-than 30d"; }; | PASS |
| original ~/.bashrc restored after uninstall | PASS |

**64 passed, 0 failed**
