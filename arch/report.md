# arch: guide test

Neovim option tested: A

## Steps

| # | Step | Result | Notes |
|---|---|---|---|
| 2 | Install Arch's native package | PASS | --noconfirm answers pacman's [Y/n] |
| 3 | Enable the daemon and initialise the store | PASS |  |
| 4 | Log out of Xfce and back in | PASS | logged out and back in (LightDM restart) |
| 5 | Open a new terminal and verify | PASS |  |
| 6 | Write /etc/nix/nix.conf settings | PASS |  |
| 7 | Restart the daemon and check | PASS |  |
| 8 | Create the config repo | PASS |  |
| 9 | Create flake.nix | FAIL | file written exactly as shown |
| 10 | Create home.nix | FAIL | file written exactly as shown |
| 11 | Create a placeholder nvim.nix | FAIL |  |
| 12 | Bootstrap and switch | FAIL |  |
| 13 | Log out of Xfce and back in | PASS | logged out and back in (LightDM restart) |
| 14 | Replace nvim.nix | FAIL | file written exactly as shown |
| 16 | Apply and check | FAIL | full-screen Neovim screenshotted, then quit |
| 17 | Pick a template and save it as flake.nix in the project root | PASS | Python template saved as ~/code/myproject/flake.nix |
| 17 | Pick a template and save it as flake.nix in the project root | PASS | node template dev shell |
| 17 | Pick a template and save it as flake.nix in the project root | PASS | rust template dev shell |
| 17 | Pick a template and save it as flake.nix in the project root | PASS | go template dev shell |
| 17 | Pick a template and save it as flake.nix in the project root | PASS | c template dev shell |
| 18 | Wire it to direnv | FAIL | full-screen Neovim screenshotted, then quit |
| 19 | One-off tools without installing anything | PASS | `nix shell` given a command instead of opening an interactive subshell |
| 20 | Audit what's already polluting the base system | FAIL | skipped the example removal line (those packages aren't installed here) |
| 21 | Update your home environment deliberately | PASS |  |
| 22 | Roll back if an update breaks something | FAIL | `<hash>` filled in with the previous generation from the listing |
| 23 | Reclaim disk space | PASS |  |
| 24 | Set up a second machine | FAIL | emulated: cloned the local config repo instead of a remote one |
| 25 | Remove Home Manager's files first | PASS | `yes |` answers the uninstall confirmation |
| 26 | Remove the package and the store | PASS | --noconfirm answers pacman's [Y/n] |
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

**21 passed, 24 failed**
