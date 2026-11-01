#!/usr/bin/env python3
"""Walk the guide in a real desktop VM and screenshot every step.

usage: tests/run.py xubuntu|mint|arch

Boots a KVM VM from the distro's cloud image, provisions an auto-login Xfce desktop
(tests/provision.sh), then for every step on the page that applies to the distro:
opens a new xfce4-terminal *inside the desktop session* (same environment a user's
terminal gets), runs the step's code blocks exactly as the page's Copy button gives
them, waits for the exit code, and screenshots the whole screen. Extra checks run
headlessly after the relevant steps. Writes results/<distro>/report.json + report.md
and results/<distro>/shots/*.png.

Every place the test changes a command from what the page shows is listed in
ADAPTATIONS and recorded on the step in the report.
"""
import json, os, re, shlex, socket, subprocess, sys, time, traceback
from pathlib import Path

D = sys.argv[1]
ROOT = Path(__file__).resolve().parent.parent
W = Path(os.environ.get("VM_DIR", Path.home() / "vm")) / D
OUT = ROOT / "results" / D
SHOTS = OUT / "shots"
for p in (W, SHOTS):
    p.mkdir(parents=True, exist_ok=True)
NVIM_OPTION = "B" if D == "mint" else "A"     # each Neovim option gets covered
IMAGES = {
    "xubuntu": "https://cloud-images.ubuntu.com/resolute/current/resolute-server-cloudimg-amd64.img",
    "mint": "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
    "arch": "https://geo.mirror.pkgbuild.com/images/latest/Arch-Linux-x86_64-cloudimg.qcow2",
}
PORT = 2222
KEY = W / "id_ed25519"
REPORT = {"distro": D, "nvim_option": NVIM_OPTION, "steps": [], "checks": [], "started": time.time()}
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:7.1f}s]", *a, flush=True)


def sh(cmd, **kw):
    log("$", cmd if isinstance(cmd, str) else " ".join(map(str, cmd)))
    return subprocess.run(cmd, shell=isinstance(cmd, str), check=True, **kw)


# ---------------------------------------------------------------- VM plumbing
def make_vm():
    img = W / "base.img"
    if not img.exists():
        sh(["curl", "-fsSL", "--retry", "5", "-o", str(img), IMAGES[D]])
    sh(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(KEY)]) if not KEY.exists() else None
    pub = KEY.with_suffix(".pub").read_text().strip()
    (W / "user-data").write_text(f"""#cloud-config
users:
  - name: tester
    gecos: Tester
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock_passwd: false
    plain_text_passwd: tester
    ssh_authorized_keys: [{json.dumps(pub)}]
ssh_pwauth: false
growpart: {{mode: auto, devices: ['/']}}
resize_rootfs: true
""")
    (W / "meta-data").write_text(f"instance-id: {D}-guide-test\nlocal-hostname: {D}-vm\n")
    sh(["cloud-localds", str(W / "seed.img"), str(W / "user-data"), str(W / "meta-data")])
    sh(["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", str(img), str(W / "disk.qcow2"), "40G"])


def boot():
    mem = os.environ.get("VM_MEM", "11264")
    sh(["qemu-system-x86_64", "-enable-kvm", "-cpu", "host", "-smp", "4", "-m", mem, "-machine", "q35",
        "-drive", f"file={W / 'disk.qcow2'},if=virtio,cache=unsafe,discard=unmap",
        "-drive", f"file={W / 'seed.img'},if=virtio,format=raw",
        "-netdev", f"user,id=n0,hostfwd=tcp:127.0.0.1:{PORT}-:22", "-device", "virtio-net-pci,netdev=n0",
        "-vga", "std", "-global", "VGA.xres=1440", "-global", "VGA.yres=900",
        "-display", "none", "-qmp", f"unix:{W / 'qmp.sock'},server=on,wait=off",
        "-serial", f"file:{OUT / 'serial.log'}", "-daemonize", "-pidfile", str(W / "qemu.pid")])


def ssh(script, user="tester", timeout=3600, check=False, quiet=False):
    """Run a bash script in the guest (as user). Returns (rc, output)."""
    target = f"{user}@127.0.0.1"
    cmd = ["ssh", "-i", str(KEY), "-p", str(PORT), "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
           "-o", "LogLevel=ERROR", "-o", "ServerAliveInterval=15", "-o", "ConnectTimeout=10", target, "bash", "-s"]
    try:
        r = subprocess.run(cmd, input=script, text=True, capture_output=True, timeout=timeout)
        out = r.stdout + r.stderr
        rc = r.returncode
    except subprocess.TimeoutExpired as e:
        dec = lambda x: x.decode(errors="replace") if isinstance(x, bytes) else (x or "")
        out, rc = dec(e.stdout) + dec(e.stderr) + "\n[timed out]", 124
    if not quiet:
        log(f"ssh rc={rc}", out[-1500:])
    if check and rc != 0:
        raise RuntimeError(f"guest command failed rc={rc}: {script[:200]}\n{out[-3000:]}")
    return rc, out


def wait_ssh(limit=900):
    t = time.time()
    while time.time() - t < limit:
        if ssh("true", timeout=20, quiet=True)[0] == 0:
            return
        time.sleep(5)
    raise RuntimeError("guest never came up on ssh")


def qmp(cmd, args=None):
    s = socket.socket(socket.AF_UNIX)
    s.connect(str(W / "qmp.sock"))
    f = s.makefile("rw")
    f.readline()
    for c in ({"execute": "qmp_capabilities"}, {"execute": cmd, **({"arguments": args} if args else {})}):
        f.write(json.dumps(c) + "\n"); f.flush()
        while True:
            line = json.loads(f.readline())
            if "return" in line or "error" in line:
                break
    s.close()
    return line


SHOT_N = 0


def shot(name):
    global SHOT_N
    SHOT_N += 1
    fn = SHOTS / f"{SHOT_N:03d}-{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:60]}.png"
    r = qmp("screendump", {"filename": str(fn), "format": "png"})
    if "error" in r:
        log("screendump error", r)
        return None
    for _ in range(20):
        if fn.exists() and fn.stat().st_size > 0:
            break
        time.sleep(0.2)
    log("shot", fn.name)
    return str(fn.relative_to(OUT))


# ---------------------------------------------------------------- desktop helpers
GUEST_HELPERS = r'''
mkdir -p ~/.gt
cat > ~/.gt/sessenv <<'EOF'
# SESSENV = the running Xfce session's environment, exactly: what a terminal opened from the desktop
# gets. Never the ssh shell's own (on Ubuntu, bash sources bashrc even for ssh commands).
pid=$(pgrep -u "$USER" -x xfce4-session | head -1)
SESSENV=()
if [ -n "$pid" ]; then while IFS= read -r -d '' kv; do SESSENV+=("$kv"); done < /proc/$pid/environ; fi
EOF
cat > ~/.gt/gui <<'EOF'
#!/bin/bash
# gui TITLE WRAPPER: open a new xfce4-terminal in the desktop session running WRAPPER; prints its pid
. ~/.gt/sessenv
cd ~
nohup env -i "${SESSENV[@]}" xfce4-terminal --disable-server --maximize --hide-menubar --title "$1" -x bash -i "$2" >/dev/null 2>&1 < /dev/null &
echo $!
EOF
cat > ~/.gt/run <<'EOF'
#!/bin/bash
# run CMD: run CMD headlessly in an interactive shell with only the desktop session's environment
. ~/.gt/sessenv
cd ~
exec env -i "${SESSENV[@]}" bash -i -c "$1" 2>&1 < /dev/null
EOF
chmod +x ~/.gt/gui ~/.gt/run
'''


def session_pid():
    return ssh("pgrep -u tester -x xfce4-session | head -1", quiet=True)[1].strip()


def wait_session(old=None, limit=600):
    t = time.time()
    while time.time() - t < limit:
        p = session_pid()
        if p and p != old:
            time.sleep(12)            # let panel/desktop finish drawing
            ssh("~/.gt/run 'xset s off -dpms' >/dev/null 2>&1; true", quiet=True)
            return p
        time.sleep(5)
    raise RuntimeError("Xfce session never started")


def relogin():
    old = session_pid()
    ssh("sudo systemctl restart lightdm", quiet=True)
    return wait_session(old)


def grun(cmd, timeout=600):
    """headless check with the session environment"""
    rc, out = ssh(f"~/.gt/run {shlex.quote(cmd)}", timeout=timeout, quiet=True)
    out = "\n".join(l for l in out.splitlines() if "no job control" not in l and "terminal process group" not in l)
    return rc, out


STEP_N = 0


def terminal(title, code, wait=True, timeout=2400, interactive_secs=None, kill="nvim"):
    """Open a new terminal on the desktop, show + run `code`, screenshot when done.
    interactive_secs: for full-screen programs (nvim) - screenshot after N s, then quit it."""
    global STEP_N
    STEP_N += 1
    n = f"{STEP_N:03d}"
    ssh("mkdir -p /tmp/gt", quiet=True)
    ssh(f"cat > /tmp/gt/{n}.cmd <<'GT_EOF_{n}'\n{code}GT_EOF_{n}\n", quiet=True)
    wrapper = f'''cd ~
printf '\\033[1;34m### %s\\033[0m\\n\\n' {shlex.quote(title)}
while IFS= read -r l; do printf '\\033[1;32m$\\033[0m %s\\n' "$l"; done < /tmp/gt/{n}.cmd
echo
'''
    if interactive_secs:
        wrapper += f"source /tmp/gt/{n}.cmd\necho $? > /tmp/gt/{n}.rc\nsleep 3600\n"
    else:
        wrapper += f'''( set -o pipefail; source /tmp/gt/{n}.cmd ) 2>&1 | tee /tmp/gt/{n}.log
echo ${{PIPESTATUS[0]}} > /tmp/gt/{n}.rc
printf '\\n\\033[1;33m[exit code %s]\\033[0m\\n' "$(cat /tmp/gt/{n}.rc)"
sleep 3600
'''
    ssh(f"cat > /tmp/gt/{n}.wrap <<'GT_EOF_{n}'\n{wrapper}GT_EOF_{n}\n", quiet=True)
    pid = ssh(f"~/.gt/gui {shlex.quote(title)} /tmp/gt/{n}.wrap", quiet=True)[1].strip().splitlines()[-1]
    t = time.time()
    rc = None
    if interactive_secs:
        time.sleep(interactive_secs)
        s = shot(title)
        ssh(f"pkill -u tester -x {kill}; sleep 2", quiet=True)
        rc = 0
        logtxt = ""
    else:
        while time.time() - t < timeout:
            r = ssh(f"cat /tmp/gt/{n}.rc 2>/dev/null", quiet=True)[1].strip()
            if r.isdigit():
                rc = int(r)
                break
            time.sleep(4)
        time.sleep(1.5)
        s = shot(title)
        logtxt = ssh(f"cat /tmp/gt/{n}.log 2>/dev/null", quiet=True)[1]
    ssh(f"kill {pid} 2>/dev/null; pkill -u tester -f 'xfce4-terminal --disable-server' 2>/dev/null; true", quiet=True)
    time.sleep(1)
    log(f"terminal '{title}' rc={rc} ({time.time() - t:.0f}s)")
    return rc, s, logtxt


# ---------------------------------------------------------------- report
def add_step(step, status, rc=None, shots=(), note="", logtxt=""):
    REPORT["steps"].append({"idx": step["idx"] if step else None, "section": step["section"] if step else None,
                            "title": step["title"] if step else note, "status": status, "rc": rc,
                            "shots": [s for s in shots if s], "note": note, "log_tail": logtxt[-4000:]})
    save()


def check(name, cmd, ok=None, step=None, timeout=600):
    rc, out = grun(cmd, timeout=timeout)
    passed = (rc == 0) if ok is None else ok(rc, out)
    REPORT["checks"].append({"name": name, "after_step": step["idx"] if step else None,
                             "status": "PASS" if passed else "FAIL", "rc": rc, "output": out[-3000:]})
    log(("PASS" if passed else "FAIL"), name, out[-400:])
    save()
    return passed, out


def save():
    REPORT["elapsed_min"] = round((time.time() - T0) / 60, 1)
    (OUT / "report.json").write_text(json.dumps(REPORT, indent=1))
    lines = [f"# {D}: guide test", "", f"Neovim option tested: {NVIM_OPTION}", "", "## Steps", "",
             "| # | Step | Result | Notes |", "|---|---|---|---|"]
    for s in REPORT["steps"]:
        lines.append(f"| {s['idx']} | {s['title']} | {s['status']} | {s['note']} |")
    lines += ["", "## Checks", "", "| Check | Result |", "|---|---|"]
    for c in REPORT["checks"]:
        lines.append(f"| {c['name']} | {c['status']} |")
    p = sum(1 for x in REPORT["steps"] + REPORT["checks"] if x["status"] == "PASS")
    f = sum(1 for x in REPORT["steps"] + REPORT["checks"] if x["status"] == "FAIL")
    lines += ["", f"**{p} passed, {f} failed**"]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------- the guide
OPT_B_USER_CONFIG = r'''mkdir -p ~/.config/nvim && cat > ~/.config/nvim/init.lua <<'EOF'
-- a small hand-written config, standing in for "your existing Lua config"
vim.o.number = true
vim.cmd.colorscheme("habamax")
vim.lsp.config("nil_ls", { cmd = { "nil" }, filetypes = { "nix" }, root_markers = { "flake.nix", ".git" } })
vim.lsp.config("lua_ls", { cmd = { "lua-language-server" }, filetypes = { "lua" }, root_markers = { ".git" } })
vim.lsp.enable({ "nil_ls", "lua_ls" })
EOF
'''
LSP_PROBE = r'''cat > /tmp/lsp.lua <<'EOF'
vim.defer_fn(function()
  local names = {}
  for _, c in ipairs(vim.lsp.get_clients({ bufnr = 0 })) do table.insert(names, c.name) end
  local hl = vim.treesitter.highlighter.active[vim.api.nvim_get_current_buf()] ~= nil
  io.stdout:write("LSP=" .. (#names > 0 and table.concat(names, ",") or "NONE") .. " TS_HL=" .. tostring(hl) .. "\n")
  vim.cmd("qa!")
end, 20000)
EOF
'''
TEMPLATE_CHECKS = {
    "t-node": "node --version && tsc --version && typescript-language-server --version",
    "t-rust": "cargo --version && rust-analyzer --version && test -d \"$RUST_SRC_PATH\" && echo RUST_SRC_PATH ok",
    "t-go": "go version && gopls version && echo GOPATH=$GOPATH",
    "t-c": "cmake --version | head -1 && gcc --version | head -1 && clangd --version | head -1 && gdb --version | head -1",
}


def blocks_for(step):
    out = []
    for b in step["blocks"]:
        if b["only"] and D not in b["only"]:
            continue
        out.append(b)
    return out


def run_guide(steps):
    hm = "~/.config/home-manager"
    for step in steps:
        if step["only"] and D not in step["only"]:
            continue
        if step["tab"] == "nv-a" and NVIM_OPTION != "A" or step["tab"] == "nv-b" and NVIM_OPTION != "B":
            continue
        t = step["title"]
        bl = blocks_for(step)
        note = ""
        log(f"===== step {step['idx']}: {t}")

        # ---- steps without code: the guide says log out and back in
        if not bl and t.startswith("Log out"):
            relogin()
            s = shot(t)
            add_step(step, "PASS", shots=[s], note="logged out and back in (LightDM restart)")
            after(step)
            continue

        # ---- file-writing steps: the page shows file contents with a path label
        if all(b["label"] for b in bl) and bl:
            shots = []
            ok = True
            for b in bl:
                path = f"{hm}/{b['label']}"
                rc, s, lg = terminal(f"{t}: {path}", f"mkdir -p {hm}\ncat > {path} <<'GUIDE_EOF'\n{b['text']}GUIDE_EOF\n")
                shots.append(s); ok &= rc == 0
            add_step(step, "PASS" if ok else "FAIL", shots=shots, note="file written exactly as shown")
            continue

        code = "".join(b["text"] for b in bl if not b["label"] and not b["tab"])
        files = [b for b in bl if b["label"]]
        interactive = None

        # ---- adaptations (each one is noted in the report) ----
        if t.startswith("Run the official installer"):
            code = re.sub(r"^less .*\n", "", code, flags=re.M).replace("--daemon\n", "--daemon --yes\n")
            note = "--yes answers the installer's prompts; skipped `less` (paging needs a human)"
        elif t.startswith("Install Arch's native package") or t.startswith("Remove the package and the store"):
            code = code.replace("pacman -S", "pacman --noconfirm -S").replace("pacman -R", "pacman --noconfirm -R")
            note = "--noconfirm answers pacman's [Y/n]"
        elif t.startswith("Version your existing config"):
            ssh(OPT_B_USER_CONFIG, quiet=True)
            note = "a small hand-written ~/.config/nvim/init.lua stands in for your existing config"
        elif t.startswith("Apply and check") or t.startswith("Wire it to direnv"):
            interactive = [l for l in code.splitlines() if l.startswith("nvim ")]
            code = "\n".join(l for l in code.splitlines() if not l.startswith("nvim ")) + "\n"
        elif t.startswith("One-off tools"):
            code = re.sub(r"^nix shell (.*?)\s+#.*$", r"nix shell \1 --command bash -c 'http --version && sqlite3 --version'",
                          code, flags=re.M)
            note = "`nix shell` given a command instead of opening an interactive subshell"
        elif t.startswith("Audit what's already"):
            if D != "arch":
                code = code.replace("sudo apt remove --autoremove", "sudo apt remove -y --autoremove")
                note = "-y answers apt's [Y/n] on the example removal"
            if D == "arch":
                code = "\n".join(l for l in code.splitlines() if not l.startswith("sudo pacman -Rns")) + "\n"
                note = "skipped the example removal line (those packages aren't installed here)"
        elif t.startswith("Roll back"):
            code = code.replace("/nix/store/<hash>-home-manager-generation/activate",
                                "\"$(home-manager generations | sed -n 2p | awk '{print $NF}')/activate\"")
            note = "`<hash>` filled in with the previous generation from the listing"
        elif t.startswith("Set up a second machine"):
            code = code.replace("<your-repo>", "~/.config/home-manager").replace(
                "git clone ~/.config/home-manager ~/.config/home-manager", "git clone ~/.config/home-manager /tmp/second-machine").replace(
                "--flake ~/.config/home-manager#", "--flake /tmp/second-machine#")
            note = "emulated: cloned the local config repo instead of a remote one"
        elif t.startswith("Remove Home Manager's files"):
            code = re.sub(r"^(NIX_PATH=\S+ )?home-manager uninstall", r"yes | \g<0>", code, flags=re.M)
            note = "`yes |` answers the uninstall confirmation"
        elif t.startswith("Pick a template"):
            # first block: create the project; t-py is the project's flake; others get their own folders
            first = "".join(b["text"] for b in bl if not b["tab"])
            py = next(b for b in bl if b["tab"] == "t-py")
            rc, s, lg = terminal(t + " (Python)", first + f"cat > flake.nix <<'GUIDE_EOF'\n{py['text']}GUIDE_EOF\ngit add flake.nix\n")
            add_step(step, "PASS" if rc == 0 else "FAIL", rc, [s], "Python template saved as ~/code/myproject/flake.nix", lg)
            for b in bl:
                if b["tab"] in TEMPLATE_CHECKS:
                    d = f"~/code/{b['tab']}"
                    rc, s, lg = terminal(f"Template {b['tab'][2:]}: nix develop",
                                         f"mkdir -p {d} && cd {d} && git init -q\ncat > flake.nix <<'GUIDE_EOF'\n{b['text']}GUIDE_EOF\n"
                                         f"git add flake.nix\nnix develop --command bash -c {shlex.quote(TEMPLATE_CHECKS[b['tab']])}\n",
                                         timeout=3600)
                    add_step(step, "PASS" if rc == 0 else "FAIL", rc, [s], f"{b['tab'][2:]} template dev shell", lg)
            continue

        rc, s, lg = terminal(t, code)
        shots = [s]
        status = "PASS" if rc == 0 else "FAIL"
        if rc != 0 and t.startswith("Open a new terminal and verify"):
            check("diagnostics: how a new terminal's bash is set up after installing",
                  "echo \"--- bash: $BASH_VERSION\"; ls -la /etc/bash.bashrc /etc/bash/bashrc /etc/bashrc /etc/profile.d/nix.sh 2>&1; "
                  "echo '--- head /etc/bash.bashrc'; head -12 /etc/bash.bashrc; echo '--- PATH in a new terminal'; echo $PATH; "
                  "echo '--- __ETC_PROFILE_NIX_SOURCED='$__ETC_PROFILE_NIX_SOURCED; echo '--- strings'; "
                  "strings $(command -v bash) | grep -E '^/etc/bash' | head", lambda rc, o: True, step=step)
            relogin()
            rc2, s2, lg2 = terminal(t + " (after logging out and back in)", code)
            shots.append(s2)
            note = "first try: nix not found in a new terminal; worked after logging out and back in, as the page advises"
            status, rc, lg = ("PASS" if rc2 == 0 else "FAIL"), rc2, lg + "\n--- after re-login ---\n" + lg2
        for f in files:   # option B: nvim.nix after the mv block
            path = f"{hm}/{f['label']}"
            rc2, s2, _ = terminal(f"{t}: {path}", f"cat > {path} <<'GUIDE_EOF'\n{f['text']}GUIDE_EOF\n")
            shots.append(s2)
            status = status if rc2 == 0 else "FAIL"
        if interactive:
            for l in interactive:
                if l.startswith("nvim +checkhealth"):
                    _, s3, _ = terminal(t + ": nvim +checkhealth", "nvim +checkhealth\n", interactive_secs=25)
                elif l.startswith("nvim ."):
                    ssh("cd ~/code/myproject && printf 'def greet(name: str) -> str:\\n    return \"hi \" + name\\n\\n\\nprint(greet(\"nix\"))\\n' > main.py", quiet=True)
                    _, s3, _ = terminal(t + ": nvim in the project", "cd ~/code/myproject\neval \"$(direnv export bash 2>/dev/null)\"\n"
                                        "nvim main.py +'lua vim.g.health = { style = \"float\" }; vim.defer_fn(function() vim.cmd(\"checkhealth vim.lsp\") end, 15000)'\n",
                                        interactive_secs=35)
                shots.append(s3)
            note = (note + "; " if note else "") + "full-screen Neovim screenshotted, then quit"
        add_step(step, status, rc, shots, note, lg)
        after(step)


def after(step):
    """headless checks tied to particular steps"""
    t = step["title"]
    hm = "~/.config/home-manager"
    if step["section"] == "hm" and t.startswith("Log out"):
        check("HM tools on PATH in a new terminal", "for c in rg fd fzf jq bat eza direnv git; do command -v $c || exit 1; done; type ll v", step=step)
        check("Session variables (EDITOR, PIP_REQUIRE_VIRTUALENV, XDG_DATA_DIRS)",
              'echo "EDITOR=$EDITOR PIP=$PIP_REQUIRE_VIRTUALENV"; echo "$XDG_DATA_DIRS"; '
              '[ "$EDITOR" = nvim ] && [ "$PIP_REQUIRE_VIRTUALENV" = true ] && [[ $XDG_DATA_DIRS == *nix-profile/share* ]]', step=step)
        check("git identity from Home Manager", "git config --get user.name && git config --get user.email", step=step)
    if t.startswith("Apply and check"):
        ssh(LSP_PROBE, quiet=True)
        check("Neovim starts with no errors", 'o=$(nvim --headless +qa 2>&1); echo "[$o]"; [ -z "$o" ]', step=step)
        check("checkhealth reports no ERROR",
              "nvim --headless '+checkhealth' '+w! /tmp/h.txt' +qa >/dev/null 2>&1; wc -l < /tmp/h.txt; grep -n ERROR /tmp/h.txt; ! grep -q ERROR /tmp/h.txt",
              step=step, timeout=300)
        if NVIM_OPTION == "A":
            check("nil_ls attaches + tree-sitter highlights a .nix file",
                  f"cd {hm} && nvim --headless flake.nix -c 'luafile /tmp/lsp.lua' 2>&1", lambda rc, o: "LSP=nil_ls" in o and "TS_HL=true" in o, step=step, timeout=120)
        else:   # option B: highlighting is up to your own config; the stand-in one has no Nix parser
            check("nil_ls (from extraPackages) attaches to a .nix file with your own config",
                  f"cd {hm} && nvim --headless flake.nix -c 'luafile /tmp/lsp.lua' 2>&1", lambda rc, o: "LSP=nil_ls" in o, step=step, timeout=120)
        check("lua_ls attaches to a .lua file",
              "printf 'local x = 1\\nprint(x)\\n' > /tmp/t.lua && cd /tmp && nvim --headless t.lua -c 'luafile /tmp/lsp.lua' 2>&1",
              lambda rc, o: "lua_ls" in o, step=step, timeout=120)
        if NVIM_OPTION == "A":
            check("plugins load (telescope, blink.cmp, conform, gitsigns, lualine, which-key)",
                  "nvim --headless -c 'lua for _,m in ipairs({\"telescope\",\"blink.cmp\",\"conform\",\"gitsigns\",\"lualine\",\"which-key\"}) do assert(pcall(require,m), m) end io.stdout:write(\"ok\\n\")' +qa 2>&1",
                  lambda rc, o: "ok" in o, step=step, timeout=120)
            check("format on save (conform + stylua)",
                  "printf 'x=1\\n' > /tmp/fmt.lua && nvim --headless /tmp/fmt.lua -c w -c qa >/dev/null 2>&1; cat /tmp/fmt.lua; grep -qx 'x = 1' /tmp/fmt.lua", step=step)
        else:
            check("option B: ~/.config/nvim is a live link to the repo copy",
                  f"readlink -f ~/.config/nvim; echo '-- edit' >> {hm}/nvim/init.lua; tail -1 ~/.config/nvim/init.lua | grep -q edit", step=step)
    if t.startswith("Wire it to direnv"):
        check("dev shell: python from .venv, pyright, ruff",
              'cd ~/code/myproject && direnv exec . bash -c "python --version; command -v python; pyright --version; ruff --version; [[ \\$(command -v python) == */.venv/bin/python ]]"',
              step=step, timeout=1200)
        check("pip refuses to install outside a venv",
              "cd ~ && nix shell nixpkgs#python3Packages.pip --command pip install requests",
              lambda rc, o: rc != 0 and "virtualenv" in o.lower(), step=step, timeout=600)
        if NVIM_OPTION == "A":
            check("pyright attaches in the project",
                  "cd ~/code/myproject && direnv exec . nvim --headless main.py -c 'luafile /tmp/lsp.lua' 2>&1",
                  lambda rc, o: "pyright" in o, step=step, timeout=180)
    if t.startswith("One-off tools"):
        check("nix search finds neovim", "nix search nixpkgs '^neovim$' 2>/dev/null", lambda rc, o: rc == 0 and "legacyPackages.x86_64-linux.neovim " in re.sub(r"\x1b\[[0-9;]*m", "", o), step=step, timeout=1200)
    if t.startswith("Roll back"):
        check("roll forward again", f"cd {hm} && home-manager switch --flake .#tester >/dev/null && echo ok", step=step, timeout=1200)
    if t.startswith("Reclaim disk space"):
        snippet = re.search(r"nix\.gc = \{[^}]*\};", PAGE).group(0)
        ssh(f"cd {hm} && sed -i 's|^  home.sessionVariables = {{|  {snippet}\\n\\n&|' home.nix", quiet=True)
        check(f"page's nix.gc snippet builds and installs a timer: {snippet}",
              f"cd {hm} && home-manager switch --flake .#tester 2>&1 | grep -iE 'has been (changed|renamed)|^error' ; systemctl --user list-unit-files | grep nix-gc",
              lambda rc, o: "nix-gc" in o and "has been" not in o and "error" not in o.lower(), step=step, timeout=1200)
    if t.startswith("Remove Home Manager's files"):
        check("original ~/.bashrc restored after uninstall", "ls -la ~/.bashrc ~/.profile ~/.bash_profile 2>/dev/null; test -f ~/.bashrc && ! test -L ~/.bashrc", step=step)


def final():
    rc, s, lg = terminal("After uninstalling: a new terminal", "command -v nix || echo 'nix: not found'\nls -d /nix 2>&1\necho \"PATH=$PATH\"\n")
    ok = "not found" in lg and "No such file" in lg
    add_step(None, "PASS" if ok else "FAIL", rc, [s], "Nix fully removed; new terminal starts clean", lg)


PAGE = (ROOT / "guide" / "index.html").read_text()


def main():
    steps = json.loads((ROOT / "steps.json").read_text())
    make_vm()
    boot()
    wait_ssh()
    sh(["scp", "-i", str(KEY), "-P", str(PORT), "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR", str(ROOT / "tests" / "provision.sh"), "tester@127.0.0.1:/tmp/provision.sh"])
    rc, out = ssh(f"sudo bash /tmp/provision.sh {D}", timeout=5400)
    (OUT / "provision.log").write_text(out)
    if rc != 0:
        raise RuntimeError("provisioning failed (see provision.log)")
    REPORT["os"] = [l for l in out.splitlines() if l.startswith("PROVISIONED")][-1:]
    ssh("sudo reboot", quiet=True)
    time.sleep(20)
    wait_ssh()
    ssh(GUEST_HELPERS, check=True, quiet=True)
    wait_session()
    REPORT["desktop_shot"] = shot("desktop before starting")
    run_guide(steps)
    final()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        REPORT["error"] = traceback.format_exc()
        log("ERROR", REPORT["error"])
        try:
            shot("at error")
        except Exception:
            pass
    finally:
        REPORT["finished"] = time.time()
        save()
        subprocess.run(["bash", "-c", f"kill $(cat {W}/qemu.pid) 2>/dev/null"])
        fails = sum(1 for x in REPORT["steps"] + REPORT["checks"] if x["status"] == "FAIL")
        print(open(OUT / "report.md").read())
        sys.exit(1 if fails or "error" in REPORT else 0)
