# xubuntu: guide test

Neovim option tested: A

## Steps

| # | Step | Result | Notes |
|---|---|---|---|
| 0 | Update the system and get prerequisites | PASS |  |
| 1 | Run the official installer in daemon mode | PASS | --yes answers the installer's prompts; skipped `less` (paging needs a human) |
| 5 | Open a new terminal and verify | FAIL |  |
| 6 | Write /etc/nix/nix.conf settings | PASS |  |
| 7 | Restart the daemon and check | FAIL |  |
| 8 | Create the config repo | PASS |  |
| 9 | Create flake.nix | PASS | file written exactly as shown |
| 10 | Create home.nix | PASS | file written exactly as shown |
| 11 | Create a placeholder nvim.nix | PASS |  |
| 12 | Bootstrap and switch | FAIL |  |
| 13 | Log out of Xfce and back in | PASS | logged out and back in (LightDM restart) |
| 14 | Replace nvim.nix | PASS | file written exactly as shown |
| 16 | Apply and check | FAIL | full-screen Neovim screenshotted, then quit |
| 17 | Pick a template and save it as flake.nix in the project root | PASS | Python template saved as ~/code/myproject/flake.nix |
| 17 | Pick a template and save it as flake.nix in the project root | PASS | node template dev shell |
| 17 | Pick a template and save it as flake.nix in the project root | PASS | rust template dev shell |
| 17 | Pick a template and save it as flake.nix in the project root | PASS | go template dev shell |
| 17 | Pick a template and save it as flake.nix in the project root | PASS | c template dev shell |
| 18 | Wire it to direnv | FAIL | full-screen Neovim screenshotted, then quit |
| 19 | One-off tools without installing anything | PASS | `nix shell` given a command instead of opening an interactive subshell |
| 20 | Audit what's already polluting the base system | PASS |  |
| 21 | Update your home environment deliberately | PASS |  |
| 22 | Roll back if an update breaks something | FAIL | `<hash>` filled in with the previous generation from the listing |
| 23 | Reclaim disk space | PASS |  |
| 24 | Set up a second machine | FAIL | emulated: cloned the local config repo instead of a remote one |
| 25 | Remove Home Manager's files first | PASS | `yes |` answers the uninstall confirmation |
| 27 | Undo the multi-user install | PASS |  |
| None | Nix fully removed; new terminal starts clean | PASS | Nix fully removed; new terminal starts clean |

## Checks

| Check | Result |
|---|---|
| HM tools on PATH in a new terminal | FAIL |
| Session variables (EDITOR, PIP_REQUIRE_VIRTUALENV, XDG_DATA_DIRS) | FAIL |
| git identity from Home Manager | FAIL |
| Neovim starts with no errors | FAIL |
| checkhealth reports no ERROR | PASS |
| nil_ls attaches + tree-sitter highlights a .nix file | FAIL |
| lua_ls attaches to a .lua file | FAIL |
| plugins load (telescope, blink.cmp, conform, gitsigns, lualine, which-key) | FAIL |
| format on save (conform + stylua) | FAIL |
| dev shell: python from .venv, pyright, ruff | FAIL |
| pip refuses to install outside a venv | FAIL |
| pyright attaches in the project | FAIL |
| nix search finds neovim | FAIL |
| roll forward again | FAIL |
| page's nix.gc snippet builds and installs a timer: nix.gc = { automatic = true; dates = "weekly"; options = "--delete-older-than 30d"; }; | FAIL |
| original ~/.bashrc restored after uninstall | PASS |

**23 passed, 21 failed**
