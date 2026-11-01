#!/usr/bin/env python3
"""Run one course of the mastery path inside a Xubuntu 26.04 VM.

usage: mastery/ci/course_vm.py COURSE_DIR_NAME      (e.g. 03-packaging, or "probe")

1. Boots Ubuntu 26.04 (KVM), installs the Xubuntu desktop packages (tests/provision.sh).
2. Copies mastery/ into the VM as user "tester".
3. Runs course 00's install lesson (installs Nix exactly as a learner does), then every
   Markdown file of the course in order with mdrun.py, each in a fresh work directory.
4. Copies logs + JSON back to results/mastery/<course>/ and writes a job summary.
"""
import json, os, shlex, subprocess, sys, time
from pathlib import Path

COURSE = sys.argv[1]
ROOT = Path(__file__).resolve().parents[2]
M = ROOT / "mastery"
W = Path(os.environ.get("VM_DIR", Path.home() / "vm")) / "mastery"
OUT = ROOT / "results" / "mastery" / COURSE
W.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
IMG = "https://cloud-images.ubuntu.com/resolute/current/resolute-server-cloudimg-amd64.img"
KEY, PORT = W / "id_ed25519", 2222
T0 = time.time()
SSHO = ["-i", str(KEY), "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
        "-o", "ServerAliveInterval=15", "-o", "ConnectTimeout=10"]


def log(*a):
    print(f"[{time.time() - T0:7.1f}s]", *a, flush=True)


def sh(cmd):
    log("$", " ".join(map(str, cmd)))
    subprocess.run(cmd, check=True)


def ssh(script, timeout=3600, stream=False):
    cmd = ["ssh", *SSHO, "-p", str(PORT), "tester@127.0.0.1", "bash", "-s"]
    if stream:
        r = subprocess.run(cmd, input=script, text=True, timeout=timeout)
        return r.returncode, ""
    r = subprocess.run(cmd, input=script, text=True, capture_output=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def vm():
    base = W / "base.img"
    if not base.exists():
        sh(["curl", "-fsSL", "--retry", "5", "-o", str(base), IMG])
    if not KEY.exists():
        sh(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(KEY)])
    pub = KEY.with_suffix(".pub").read_text().strip()
    (W / "user-data").write_text(f"""#cloud-config
users:
  - name: tester
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock_passwd: false
    plain_text_passwd: tester
    ssh_authorized_keys: [{json.dumps(pub)}]
growpart: {{mode: auto, devices: ['/']}}
""")
    (W / "meta-data").write_text("instance-id: mastery\nlocal-hostname: xubuntu\n")
    sh(["cloud-localds", str(W / "seed.img"), str(W / "user-data"), str(W / "meta-data")])
    sh(["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", str(base), str(W / "disk.qcow2"), "80G"])
    sh(["qemu-system-x86_64", "-enable-kvm", "-cpu", "host", "-smp", "4", "-m", os.environ.get("VM_MEM", "12288"),
        "-machine", "q35", "-drive", f"file={W / 'disk.qcow2'},if=virtio,cache=unsafe,discard=unmap",
        "-drive", f"file={W / 'seed.img'},if=virtio,format=raw",
        "-netdev", f"user,id=n0,hostfwd=tcp:127.0.0.1:{PORT}-:22", "-device", "virtio-net-pci,netdev=n0",
        "-display", "none", "-serial", f"file:{OUT / 'serial.log'}", "-daemonize", "-pidfile", str(W / "qemu.pid")])
    for _ in range(180):
        if ssh("true", timeout=20)[0] == 0:
            break
        time.sleep(5)
    else:
        raise SystemExit("VM never came up")
    sh(["scp", *SSHO, "-P", str(PORT), str(ROOT / "tests" / "provision.sh"), "tester@127.0.0.1:/tmp/provision.sh"])
    rc, out = ssh("sudo bash /tmp/provision.sh xubuntu", timeout=5400)
    (OUT / "provision.log").write_text(out)
    if rc:
        raise SystemExit("provisioning failed:\n" + out[-3000:])
    log([l for l in out.splitlines() if l.startswith("PROVISIONED")])
    sh(["scp", *SSHO, "-P", str(PORT), "-r", str(M), "tester@127.0.0.1:/home/tester/mastery"])


def docs(course):
    d = M / "courses" / course
    files = sorted(p.name for p in d.glob("*.md") if p.name != "README.md")
    return [f"{course}/README.md"] + [f"{course}/{f}" for f in files]


def run_doc(rel):
    name = rel.replace("../", "").replace("/", "__").removesuffix(".md")
    script = f"""set -o pipefail
mkdir -p ~/work/{name} ~/results && cd ~/work/{name}
python3 ~/mastery/ci/mdrun.py ~/mastery/courses/{rel} --json ~/results/{name}.json 2>&1 | tee ~/results/{name}.log
"""
    log(f"===== {rel}")
    rc, _ = ssh(script, timeout=4 * 3600, stream=True)
    return name, rc


def main():
    vm()
    rc, out = ssh("ls -l /dev/kvm 2>&1; grep -cE 'vmx|svm' /proc/cpuinfo; nproc; free -g | head -2")
    log("guest kvm/cpu:", out)
    (OUT / "guest-kvm.txt").write_text(out)
    plan = ["00-setup/01-install.md"] if COURSE != "00-setup" else []
    if COURSE == "probe":
        plan += ["../ci/probe.md"]
    else:
        plan += docs(COURSE)
    results = []
    for rel in plan:
        name, rc = run_doc(rel)
        if rel == "00-setup/01-install.md" and COURSE != "00-setup":
            name = "setup"
            if rc:
                results.append((rel, rc))
                break
            # CI only: without nested KVM the NixOS tests fall back to (slow) emulation
            ssh("[ -e /dev/kvm ] || echo 'extra-system-features = kvm nixos-test' | sudo tee -a /etc/nix/nix.conf && sudo systemctl restart nix-daemon")
            continue
        results.append((rel, rc))
    subprocess.run(["scp", *SSHO, "-P", str(PORT), "-r", "tester@127.0.0.1:/home/tester/results/.", str(OUT)])
    lines = [f"## Course {COURSE}", "", "| File | Result | Run blocks |", "|---|---|---|"]
    allok = True
    for rel, rc in results:
        j = OUT / (rel.replace("../", "").replace("/", "__").removesuffix(".md") + ".json")
        info = json.loads(j.read_text()) if j.exists() else {}
        lines.append(f"| {rel} | {'PASS' if rc == 0 else 'FAIL'} | {info.get('ran', '?')} |")
        allok &= rc == 0
    (OUT / "summary.md").write_text("\n".join(lines) + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    subprocess.run(["bash", "-c", f"kill $(cat {W}/qemu.pid) 2>/dev/null"])
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    main()
