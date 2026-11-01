# Content curation

How the material in this path was chosen, what it is checked against, and the facts that
pin it to a point in time. Everything below was verified on 1 Nov 2026.

## Primary sources (authoritative, used to check every lesson)

| Source | Used for |
|---|---|
| Nix reference manual 2.35 — nix.dev/manual/nix/2.35 | store, derivations, language, CLI, nix.conf, sandbox, GC |
| Nixpkgs manual (in-tree `doc/` of nixpkgs 26.05) | stdenv phases, `finalAttrs`, `__structuredAttrs`, fetchers, language builders, testers |
| NixOS manual + `nixos/modules` (nixpkgs 26.05) | module system, options, `system.build.toplevel`, `system.stateVersion` |
| nixpkgs `CONTRIBUTING.md`, `pkgs/README.md`, `pkgs/by-name/README.md` (26.05) | layout, by-name rules, formatting (nixfmt / `nix fmt`), commit conventions |
| nix.dev tutorials | teaching order for first steps, language, callPackage, cross, module system, NixOS VM tests |
| Nix Pills | the "build a derivation by hand" progression used in course 01 |
| NixOS RFC process (github.com/NixOS/rfcs) and Nix team discussion on flake stabilisation | course 07 context; flakes status |

Secondary sources were used only to find topics, never as the basis for a claim:
Zero to Nix, the NixOS Wiki, community blog posts, the 2025 community survey discussion.

## Facts this path depends on (re-check when updating)

- **Nix version:** 2.35.4 from the official installer. Upstream versions before 2.35.3 had
  critical security fixes in Oct 2026 — the course requires ≥ 2.35.3 (course 00 checks).
  nixpkgs 26.05 itself ships Nix 2.34 as `pkgs.nix`.
- **Flakes and the `nix` CLI are still experimental features** (`nix-command flakes`). They are
  in very wide use; the Nix team is stabilising pieces separately (`fetch-tree` first). The path
  teaches both the stable classic commands (`nix-build`, `nix-instantiate`, `nix-store`) and
  flakes, and says which is which.
- **Pins used throughout** (exact commits = identical results for every learner, all cached):
  - nixpkgs 26.05: `fa1373130d5a21c040a47c5dbe1913d59ed91808` (channel nixos-26.05.13297)
  - nixpkgs 25.11: `b6018f87da91d19d0ab4cf979885689b469cdd41` (channel nixos-25.11.12484), for
    "two versions side by side" lessons
  - nixpkgs 26.05 tarball (for `fetchTarball`): `16x4xwxrp7aqrdd3k06rc94wnxh877incf2fscf03q6qnb326f0z`;
    25.11: `0ln4yw7z3g9lb0x081hc0pd2j1wsx2qqf6bgmwwvdbkcl4bcy1dp` (computed by `ci/probe.md`)
  - GNU hello sources: 2.12.3 `sha256-DV9gFUOC/uELEUocNOeF2LH0kgc64tOm97FHaHs2aqA=` (from nixpkgs);
    2.12.1 `sha256-jZkUKv2SV28wsM18tCqNxoCZmLxdYH2Idh9RLibH2yA=`; 2.10 `sha256-MeBmE3qWJnbon2nRtlOC3pWn732RS4y5VvQepy4PUWs=`
  - CI capability: nested KVM is available inside the Xubuntu VM on GitHub runners; a minimal NixOS
    VM test takes about 3 minutes there
- **Current packaging conventions (nixpkgs 26.05):**
  - `stdenv.mkDerivation (finalAttrs: { … })` is the preferred form.
  - "All new top level packages must enable `__structuredAttrs`" (stdenv chapter).
  - New packages go in `pkgs/by-name/<2-letter-prefix>/<name>/package.nix`.
  - Formatting is enforced by CI with nixfmt (`nix fmt` / `treefmt` in the nixpkgs dev shell).
  - Commit messages: `pkg-name: init at 1.0`, `pkg-name: 1.0 -> 1.1`; the prefix drives CI builds.
  - Go: `buildGoModule` with `vendorHash` (`null` when there are no dependencies).
  - Rust: `buildRustPackage` with `cargoHash`, or `cargoLock.lockFile`.
  - Python: `buildPythonApplication` with `pyproject = true`, `build-system`, `dependencies`.
  - NixOS VM tests: `pkgs.testers.runNixOSTest`.
  - Contributor tools in nixpkgs: `nixfmt`, `nixpkgs-review`, `nixpkgs-vet`.

## Processing: what was kept, cut, or reshaped

- **Kept and reshaped:** Nix Pills' hand-built derivation (course 01) — modernised to a pinned
  nixpkgs and `nix derivation show`; nix.dev's callPackage and module-system tutorials — turned
  into projects with tests instead of read-only walkthroughs.
- **Cut as out of date:** `nix-env -i` workflows, channels as the main pinning method,
  `mkDerivation rec { … }` as the default style, ofborg-era contribution steps, the category
  hierarchy for new packages.
- **Added because the sources are thin or scattered:** versioning strategies in one place
  (pin / override / overlay / second nixpkgs), a signed binary cache round trip, how NixOS is
  assembled from nixpkgs (from the module source, not just the manual), and a full nixpkgs
  contribution rehearsal that runs every check CI would run.
- **Everything runnable is tested:** every code block marked runnable in the lessons and
  projects is executed by GitHub Actions on Xubuntu (see `ci/`). A lesson that stops working
  fails the build.
