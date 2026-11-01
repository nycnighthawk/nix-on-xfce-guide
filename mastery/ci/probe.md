# CI probe: values the lessons depend on

Not a lesson. CI runs this once to compute hashes and check the VM's capabilities.

```bash timeout=1800
for rev in fa1373130d5a21c040a47c5dbe1913d59ed91808 b6018f87da91d19d0ab4cf979885689b469cdd41; do
  h=$(nix-prefetch-url --unpack "https://github.com/NixOS/nixpkgs/archive/$rev.tar.gz" 2>/dev/null)
  echo "PROBE nixpkgs $rev base32=$h sri=$(nix hash convert --hash-algo sha256 --to sri "$h")"
done
for v in 2.12.1 2.12.2 2.10; do
  h=$(nix-prefetch-url "https://ftp.gnu.org/gnu/hello/hello-$v.tar.gz" 2>/dev/null)
  echo "PROBE hello-$v sri=$(nix hash convert --hash-algo sha256 --to sri "$h")"
done
ls -l /dev/kvm || echo "PROBE no /dev/kvm"
nix config show system-features
```

```nix file=vmtest.nix
let
  pkgs = import (builtins.fetchTarball "https://github.com/NixOS/nixpkgs/archive/fa1373130d5a21c040a47c5dbe1913d59ed91808.tar.gz") { };
in
pkgs.testers.runNixOSTest {
  name = "probe";
  nodes.machine = { };
  testScript = ''
    machine.wait_for_unit("multi-user.target")
    machine.succeed("true")
  '';
}
```

```bash timeout=3600
start=$(date +%s)
nix-build vmtest.nix --no-out-link 2>&1 | tail -5
echo "PROBE nixos-test seconds=$(( $(date +%s) - start ))"
```
