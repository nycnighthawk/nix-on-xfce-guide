# mint: guide test

Neovim option tested: B

## Steps

| # | Step | Result | Notes |
|---|---|---|---|
| 0 | Update the system and get prerequisites | PASS |  |
| 1 | Run the official installer in daemon mode | PASS | --yes answers the installer's prompts; skipped `less` (paging needs a human) |
| 5 | Open a new terminal and verify | PASS | first try: nix not found in a new terminal; worked after logging out and back in, as the page advises |
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

## Checks

| Check | Result |
|---|---|
| diagnostics: how a new terminal's bash is set up after installing | PASS |
| HM tools on PATH in a new terminal | PASS |
| Session variables (EDITOR, PIP_REQUIRE_VIRTUALENV, XDG_DATA_DIRS) | PASS |
| git identity from Home Manager | PASS |
| Neovim starts with no errors | PASS |
| checkhealth reports no ERROR | PASS |
| nil_ls attaches + tree-sitter highlights a .nix file | FAIL |
| lua_ls attaches to a .lua file | PASS |
| option B: ~/.config/nvim is a live link to the repo copy | PASS |
| dev shell: python from .venv, pyright, ruff | PASS |
| pip refuses to install outside a venv | PASS |
| nix search finds neovim | PASS |

**31 passed, 1 failed**
