# Nix mastery path

From how the Nix store works to getting a package merged into nixpkgs, in nine courses with
hands-on projects. Every command in every lesson and project is run by CI on a fresh
**Xubuntu 26.04** virtual machine, so what you read is what works.

| Course | You'll be able to… | Projects |
|---|---|---|
| [00 Setup](courses/00-setup/README.md) | install Nix safely on Xubuntu, run anything without installing it | Throwaway tool belt |
| [01 How Nix works](courses/01-how-nix-works/README.md) | explain store, derivations, closures, sandbox, caches, GC — with proof | Derivation by hand · Prove reproducibility |
| [02 The Nix language](courses/02-nix-language/README.md) | read and write any Nix, including nixpkgs' fixed points | Tested mini library · Your own overlay system |
| [03 Packaging](courses/03-packaging/README.md) | package C, Go, Rust and Python software nixpkgs-style | GNU hello from a tarball · Repair a broken build · One tool, three languages |
| [04 Flakes & versioning](courses/04-flakes-versioning/README.md) | pin, override and run several versions side by side | Versions on demand · Lock hygiene |
| [05 Nix in practice](courses/05-in-practice/README.md) | dev shells, signed binary caches, containers, cross builds | Signed cache round trip · Container · ARM on x86 |
| [06 Modules & NixOS](courses/06-modules-nixos/README.md) | write typed modules, understand how NixOS is built, test NixOS VMs | Config generator · Service + VM test · Take a system apart |
| [07 Contributing](courses/07-contributing/README.md) | make a contribution nixpkgs would accept | Contribution rehearsal in a real nixpkgs checkout |
| [08 Capstone](courses/08-capstone/README.md) | ship a service with package, flake, NixOS module, VM test, image, cache and CI | Key-value service |

Start with [course 00](courses/00-setup/README.md). The [syllabus](SYLLABUS.md) lists every
course's goals and structure; [curation](CURATION.md) records the sources and the facts the
path depends on (Nix 2.35, nixpkgs 26.05).

## Check your own work

Each lesson is runnable Markdown. From a clone of this repository:

```bash skip
python3 mastery/ci/mdrun.py mastery/courses/03-packaging/project-a-hello-tarball.md
```

`mdrun` runs the lesson's `bash` blocks in one shell, writes the files it gives, and checks the
expected output — the same way CI does ([conventions](CONVENTIONS.md)).

## How it's tested

[`.github/workflows/mastery.yml`](../.github/workflows/mastery.yml) runs one job per course.
Each boots Ubuntu 26.04 with the Xubuntu desktop packages in a KVM virtual machine
([`ci/course_vm.py`](ci/course_vm.py)), installs Nix by running lesson 00.1, then runs every
file of the course with `mdrun`. NixOS VM tests run inside that VM with nested KVM.
