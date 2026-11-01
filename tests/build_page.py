#!/usr/bin/env python3
"""Build the published page: guide/index.html + screenshots from a test run.

usage: tests/build_page.py RESULTS_DIR OUT_DIR [RUN_URL]
RESULTS_DIR holds <distro>/report.json and <distro>/shots/*.png (the "results" branch).
Writes OUT_DIR/index.html and OUT_DIR/shots/<distro>/*.webp. Under every step it adds a
collapsible gallery of that step's screenshots for the distro picked at the top of the page.
"""
import html, json, sys, time
from html.parser import HTMLParser
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
RES, OUT = Path(sys.argv[1]), Path(sys.argv[2])
RUN_URL = sys.argv[3] if len(sys.argv) > 3 else ""
DISTROS = ["xubuntu", "mint", "arch"]
NAMES = {"xubuntu": "Xubuntu", "mint": "Mint Xfce", "arch": "Arch"}
page = (ROOT / "guide" / "index.html").read_text()
lines = page.split("\n")


def offset(pos):  # HTMLParser (line, col) -> string index
    l, c = pos
    return sum(len(x) + 1 for x in lines[: l - 1]) + c


class Steps(HTMLParser):
    """character offset of the closing </div> of every .step div, in page order"""
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack, self.ends = [], []

    def handle_starttag(self, t, a):
        if t == "div":
            self.stack.append("step" in (dict(a).get("class") or "").split())

    def handle_endtag(self, t):
        if t == "div" and self.stack and self.stack.pop():
            self.ends.append(offset(self.getpos()))


p = Steps()
p.feed(page)
ends = p.ends

reports = {}
for d in DISTROS:
    f = RES / d / "report.json"
    if f.exists():
        reports[d] = json.loads(f.read_text())

# convert screenshots
for d, r in reports.items():
    (OUT / "shots" / d).mkdir(parents=True, exist_ok=True)
    for s in r["steps"]:
        for sh in s["shots"]:
            src = RES / d / sh
            dst = OUT / "shots" / d / (Path(sh).stem + ".webp")
            if src.exists() and not dst.exists():
                Image.open(src).convert("RGB").save(dst, "WEBP", quality=78, method=6)

# gallery html per step index
gal = {}  # idx -> list of html
last_idx = max(i for i in range(len(ends)))
for d, r in reports.items():
    per = {}
    for s in r["steps"]:
        idx = s["idx"] if s["idx"] is not None else last_idx
        per.setdefault(idx, []).append(s)
    for idx, entries in per.items():
        figs = []
        for s in entries:
            for sh in s["shots"]:
                cap = Path(sh).stem.split("-", 1)[1].replace("-", " ")
                src = f"shots/{d}/{Path(sh).stem}.webp"
                badge = "ok" if s["status"] == "PASS" else "bad"
                figs.append(f'<figure><img loading="lazy" src="{src}" alt="{html.escape(cap)}">'
                            f'<figcaption><span class="res {badge}">{s["status"]}</span> {html.escape(cap)}'
                            + (f'<br><i>{html.escape(s["note"])}</i>' if s["note"] else "") + "</figcaption></figure>")
        if figs:
            gal.setdefault(idx, []).append(
                f'<details class="shots" data-only="{d}"><summary>Screenshots on {NAMES[d]} ({len(figs)})</summary>'
                f'<div class="gallery">{"".join(figs)}</div></details>')

out = page
for idx in sorted(gal, reverse=True):
    pos = ends[idx]
    out = out[:pos] + "\n    " + "\n    ".join(gal[idx]) + "\n  " + out[pos:]

# results panel
rows = []
for d in DISTROS:
    if d not in reports:
        continue
    r = reports[d]
    items = r["steps"] + r["checks"]
    ok = sum(1 for x in items if x["status"] == "PASS")
    bad = [x.get("title") or x.get("name") for x in items if x["status"] != "PASS"]
    os_ = (r.get("os") or [""])[0].replace("PROVISIONED: ", "")
    rows.append(f"<tr><td>{NAMES[d]}</td><td>{html.escape(os_)}</td><td>{len(r['steps'])} steps, {len(r['checks'])} checks</td>"
                f"<td><span class='res {'ok' if not bad else 'bad'}'>{ok}/{len(items)} passed</span>"
                + (f"<br>{html.escape('; '.join(map(str, bad)))}" if bad else "") + "</td></tr>")
when = time.strftime("%-d %b %Y", time.gmtime(max(r.get("finished", time.time()) for r in reports.values())))
panel = f'''  <div class="note ok tested"><b>Tested {when}</b> in real Xfce desktops (KVM virtual machines on GitHub Actions).
  Every code block on this page was run in a new Xfce terminal exactly as the Copy button gives it, and every step has
  screenshots: open <i>Screenshots</i> under a step. Neovim was tested with option A on Xubuntu and Arch, option B on Mint.
  <table><tr><th>Distro</th><th>Tested on</th><th>Coverage</th><th>Result</th></tr>{"".join(rows)}</table>
  {"<a href='" + RUN_URL + "'>Test run, reports and full-size screenshots</a> · " if RUN_URL else ""}<a href="https://github.com/nycnighthawk/nix-on-xfce-guide">Test code</a></div>
'''
start = out.index('  <div class="note ok"><b>Tested ')
end_ = out.index("</div>", start) + len("</div>\n")
out = out[:start] + panel + out[end_:]

css = '''
details.shots{margin:4px 0 12px;border:1px solid var(--line);border-radius:8px;background:var(--panel2)}
details.shots summary{cursor:pointer;padding:7px 12px;color:var(--muted);font-size:13.5px}
details.shots[open] summary{border-bottom:1px solid var(--line)}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;padding:12px}
.gallery figure{margin:0}.gallery img{width:100%;border-radius:6px;border:1px solid var(--line);cursor:zoom-in;display:block}
.gallery figcaption{font-size:12.5px;color:var(--muted);margin-top:5px;line-height:1.4}
.res{font:600 11px "JetBrains Mono",monospace;padding:1px 6px;border-radius:4px}.res.ok{background:#1f3b2c;color:var(--accent2)}.res.bad{background:#3b1f24;color:var(--bad)}
.tested table{margin:10px 0 6px;font-size:13.5px}.tested td,.tested th{padding:6px 8px}
body[data-distro="xubuntu"] details[data-only~="xubuntu"],body[data-distro="arch"] details[data-only~="arch"],body[data-distro="mint"] details[data-only~="mint"]{display:block}
#lightbox{position:fixed;inset:0;background:rgba(0,0,0,.88);display:none;align-items:center;justify-content:center;z-index:50;cursor:zoom-out}
#lightbox img{max-width:96vw;max-height:94vh;border-radius:6px}
'''
out = out.replace("</style>", css + "</style>", 1)
js = '''<div id="lightbox"><img alt=""></div>
<script>
(function(){const lb=document.getElementById("lightbox"),im=lb.querySelector("img");
document.addEventListener("click",e=>{if(e.target.matches(".gallery img")){im.src=e.target.src;lb.style.display="flex";}else if(e.target.closest("#lightbox")){lb.style.display="none";}});
document.addEventListener("keydown",e=>{if(e.key==="Escape")lb.style.display="none";});})();
</script>
</body>'''
out = out.replace("</body>", js, 1)
(OUT / "index.html").write_text(out)
n = sum(1 for _ in (OUT / "shots").rglob("*.webp"))
size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
print(f"built {OUT/'index.html'}: {sum(len(v) for v in gal.values())} galleries, {n} screenshots, {size/1e6:.1f} MB total")
