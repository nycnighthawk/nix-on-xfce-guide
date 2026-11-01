#!/usr/bin/env python3
"""mdrun — run a lesson's Markdown exactly as written.

usage: python3 mdrun.py LESSON.md [--json OUT.json] [--keep-going]

Fenced code blocks are interpreted by their info string:

  ```bash                 run it; every command must succeed (set -e)
  ```bash fails           run it; it must exit non-zero (lessons that show errors on purpose)
  ```bash timeout=1800    run with a longer timeout (seconds; default 2400)
  ```nix file=flake.nix   write the block to that path (relative to the current directory)
  ```text expect          each non-empty line must appear in the previous run block's output
  anything else           shown to the reader only (```console, ```text, ```bash skip, ...)

All run blocks share one bash session per file, so `cd` and variables carry over, just
like typing the lesson into one terminal. Learners can use this to check their work:
    python3 mastery/ci/mdrun.py mastery/courses/03-packaging/project-a-hello.md
"""
import json, os, re, subprocess, sys, tempfile, time

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")


def parse(path):
    blocks, lines, i = [], open(path, encoding="utf-8").read().split("\n"), 0
    while i < len(lines):
        m = FENCE.match(lines[i])
        if m:
            indent, fence, info = m.group(1), m.group(2), m.group(3).strip()
            body, j = [], i + 1
            while j < len(lines) and not (lines[j].strip().startswith(fence) and lines[j].strip().strip(fence[0]) == ""):
                l = lines[j]
                body.append(l[len(indent):] if l.startswith(indent) else l)
                j += 1
            words = info.split()
            lang = words[0] if words else ""
            flags = {}
            for w in words[1:]:
                k, _, v = w.partition("=")
                flags[k] = v or True
            blocks.append({"line": i + 1, "lang": lang, "flags": flags, "text": "\n".join(body) + "\n"})
            i = j + 1
        else:
            i += 1
    return blocks


class Session:
    def __init__(self, workdir):
        self.dir = tempfile.mkdtemp(prefix="mdrun-")
        self.p = subprocess.Popen(["bash", "--login"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, cwd=workdir, bufsize=1,
                                  env={**os.environ, "TERM": "dumb", "NO_COLOR": "1"})
        self.n = 0

    def _send(self, cmd, timeout):
        marker = f"__MDRUN_DONE_{time.time_ns()}__"
        self.p.stdin.write(cmd + f"\necho {marker} $?\n")
        self.p.stdin.flush()
        out, t0 = [], time.time()
        while True:
            line = self.p.stdout.readline()
            if line == "":          # the shell exited (set -e tripped)
                return self.p.wait(), "".join(out), True
            if line.startswith(marker):
                return int(line.split()[-1]), "".join(out), False
            out.append(line)
            if time.time() - t0 > timeout:
                self.p.kill()
                return 124, "".join(out) + "\n[mdrun: timed out]\n", True

    def run(self, code, must_fail, timeout):
        self.n += 1
        f = os.path.join(self.dir, f"b{self.n}.sh")
        o = os.path.join(self.dir, f"b{self.n}.out")
        open(f, "w").write(code)
        if must_fail:
            cmd = f"source {f} > {o} 2>&1"
        else:
            cmd = f"set -e; source {f} > {o} 2>&1; set +e"
        rc, _, died = self._send(cmd, timeout)
        out = open(o, errors="replace").read() if os.path.exists(o) else ""
        return rc, ANSI.sub("", out), died

    def cwd(self):
        rc, out, _ = self._send("pwd", 30)
        return out.strip().splitlines()[-1]


def main():
    args = sys.argv[1:]
    path = args[0]
    jout = args[args.index("--json") + 1] if "--json" in args else None
    keep = "--keep-going" in args
    blocks = parse(path)
    s = Session(os.getcwd())
    results, last_out, ok = [], "", True
    for b in blocks:
        lang, fl = b["lang"], b["flags"]
        rec = {"line": b["line"], "kind": None, "status": "PASS"}
        t0 = time.time()
        if "file" in fl:
            rec["kind"] = "file"
            dest = fl["file"]
            dest = dest if os.path.isabs(dest) else os.path.join(s.cwd(), dest)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            open(dest, "w").write(b["text"])
            print(f"\n--- {path}:{b['line']} write {dest}")
        elif lang in ("bash", "sh") and "skip" not in fl:
            rec["kind"] = "run"
            must_fail = "fails" in fl
            print(f"\n--- {path}:{b['line']} run{' (must fail)' if must_fail else ''}")
            print("".join("$ " + l + "\n" for l in b["text"].rstrip("\n").split("\n")), end="")
            rc, out, died = s.run(b["text"], must_fail, int(fl.get("timeout", 2400)))
            print(out, end="" if out.endswith("\n") or not out else "\n")
            last_out = out
            rec.update(rc=rc, seconds=round(time.time() - t0, 1), output=out[-4000:])
            if (must_fail and rc == 0) or (not must_fail and rc != 0):
                rec["status"] = "FAIL"
                print(f"[mdrun] FAIL: exit code {rc}" + (" (expected non-zero)" if must_fail else ""))
            if died:
                if rec["status"] == "PASS":
                    rec["status"] = "FAIL"
                results.append(rec)
                ok = False
                break
        elif lang == "text" and "expect" in fl:
            rec["kind"] = "expect"
            missing = [l.strip() for l in b["text"].splitlines() if l.strip() and l.strip() not in last_out]
            print(f"--- {path}:{b['line']} expect: {'ok' if not missing else 'MISSING ' + repr(missing)}")
            if missing:
                rec.update(status="FAIL", missing=missing)
        else:
            continue
        results.append(rec)
        if rec["status"] == "FAIL":
            ok = False
            if not keep:
                break
    s.p.kill()
    summary = {"file": path, "ok": ok, "blocks": results,
               "ran": sum(1 for r in results if r["kind"] == "run"),
               "failed": sum(1 for r in results if r["status"] == "FAIL")}
    if jout:
        json.dump(summary, open(jout, "w"), indent=1)
    print(f"\n[mdrun] {path}: {'PASS' if ok else 'FAIL'} ({summary['ran']} run blocks, {summary['failed']} failed)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
