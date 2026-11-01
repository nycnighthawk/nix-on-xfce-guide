# Nix on Xubuntu, Arch & Linux Mint Xfce

A step-by-step guide to adding Nix, Home Manager and a reproducible Neovim dev setup to
Xubuntu, Arch and Linux Mint Xfce — and an automated test that walks every step of it in
real desktop VMs.

- **The guide:** [`guide/index.html`](guide/index.html) (single page, copy buttons, per-distro view)
- **The test:** [`.github/workflows/test-guide.yml`](.github/workflows/test-guide.yml) runs one job per distro on
  GitHub's free runners. Each job boots a KVM VM from the distro's cloud image, gives it an
  auto-login Xfce desktop ([`tests/provision.sh`](tests/provision.sh)), then
  [`tests/run.py`](tests/run.py) opens a new Xfce terminal for every step on the page, runs the
  page's own code blocks (extracted by [`tests/extract.py`](tests/extract.py)), screenshots the
  screen and runs extra checks (Neovim LSP/tree-sitter, dev shells, rollback, uninstall…).
- **Results:** the [`results` branch](../../tree/results) — a report and screenshots per distro.

Distros tested: Xubuntu (Ubuntu 26.04 + `xubuntu-core`), Linux Mint 22.3 Xfce (Ubuntu 24.04 +
Mint's repositories and `mint-meta-xfce`), Arch Linux (official cloud image + Xfce).
Edit [`tests/DISTROS`](tests/DISTROS) to choose which ones run.

Where the test has to change a command (for example answering a `[Y/n]` prompt with
`--noconfirm`), the change is listed on that step in the report.

## Building the page with screenshots

    git clone -b results https://github.com/nycnighthawk/nix-on-xfce-guide results
    python3 tests/build_page.py results site      # needs Pillow; writes site/index.html + site/shots/
