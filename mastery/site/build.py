#!/usr/bin/env python3
"""Build the Nix mastery path website (one self-contained HTML file) from the course Markdown.

usage: mastery/site/build.py OUT_DIR [RESULTS_DIR]
RESULTS_DIR: optional folder of CI results (<course>/<course>__<file>.json) to show pass badges.
"""
import html, json, re, sys, time
from pathlib import Path
import markdown
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, TextLexer

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1])
RES = Path(sys.argv[2]) if len(sys.argv) > 2 else None
OUT.mkdir(parents=True, exist_ok=True)
FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")

courses = sorted(p for p in (ROOT / "courses").iterdir() if p.is_dir())


def anchor(course, fname):
    c = course.name.split("-")[0]
    stem = Path(fname).stem
    return f"c{c}-{re.sub(r'[^a-z0-9]+', '-', stem.lower()).strip('-')}"


def lexer(lang):
    try:
        return get_lexer_by_name({"console": "console", "sh": "bash"}.get(lang, lang))
    except Exception:
        return TextLexer()


def render_block(lang, flags, text):
    if "file" in flags:
        badge, cls = f"creates <code>{html.escape(flags['file'])}</code>", "file"
    elif lang in ("bash", "sh") and "skip" not in flags:
        badge, cls = ("runs in CI · must fail" if "fails" in flags else "runs in CI"), ("fails" if "fails" in flags else "run")
    elif lang == "text" and "expect" in flags:
        badge, cls = "expected output (checked by CI)", "expect"
    else:
        badge, cls = (lang or "text"), "show"
    code = highlight(text, lexer("text" if cls == "expect" else lang), HtmlFormatter(nowrap=True))
    return (f'<div class="code {cls}"><div class="lbl">{badge}</div>'
            f'<pre><code>{code}</code></pre><button class="copy" type="button">Copy</button></div>')


def md_to_html(path, course, links):
    lines = path.read_text(encoding="utf-8").split("\n")
    out, blocks, i = [], [], 0
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
            flags = {}
            for w in words[1:]:
                k, _, v = w.partition("=")
                flags[k] = v or True
            blocks.append(render_block(words[0] if words else "", flags, "\n".join(body) + "\n"))
            out.append(f"{indent}\n{indent}MDBLOCK{len(blocks) - 1}X\n")
            i = j + 1
        else:
            out.append(lines[i])
            i += 1
    src = "\n".join(out)
    # cross-file links -> in-page anchors
    def relink(m):
        target = m.group(2)
        t = target.split("#")[0]
        if target.startswith(("http:", "https:", "#", "mailto:")):
            return m.group(0)
        p = (path.parent / t).resolve()
        if p in links:
            return f"[{m.group(1)}](#{links[p]})"
        try:
            rel = p.relative_to(ROOT.parent)
        except ValueError:
            return m.group(0)
        kind = "tree" if (p.is_dir() or target.endswith("/")) else "blob"
        return f"[{m.group(1)}](https://github.com/nycnighthawk/nix-on-xfce-guide/{kind}/main/{rel.as_posix()})"
    src = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", relink, src)
    h = markdown.markdown(src, extensions=["tables", "md_in_html", "sane_lists"])
    for n, b in enumerate(blocks):
        h = re.sub(rf"<p>\s*MDBLOCK{n}X\s*</p>|MDBLOCK{n}X", lambda _: b, h, count=1)
    return h


def status(course, fname):
    if not RES:
        return None
    f = RES / course.name / f"{course.name}__{Path(fname).stem}.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text())
    return d.get("ok"), d.get("ran", 0)


links = {}
for c in courses:
    for f in sorted(c.glob("*.md")):
        links[f.resolve()] = anchor(c, f.name)

nav, pages, total_runs = [], [], 0
for c in courses:
    files = [c / "README.md"] + sorted(p for p in c.glob("*.md") if p.name != "README.md")
    title = (c / "README.md").read_text().split("\n")[0].lstrip("# ").strip()
    items = []
    for f in files:
        a = anchor(c, f.name)
        first = f.read_text().split("\n")[0].lstrip("# ").strip()
        short = "Overview" if f.name == "README.md" else re.sub(r"^(Lesson|Project) [\w.]+ — ", "", first).replace("`", "")
        kind = "project" if f.name.startswith("project") else ("overview" if f.name == "README.md" else "lesson")
        st = status(c, f.name)
        badge = ""
        if st:
            total_runs += st[1]
            badge = f'<span class="st {"ok" if st[0] else "bad"}" title="{st[1]} commands run by CI">{"✓" if st[0] else "✗"}</span>'
        items.append(f'<a href="#{a}" class="{kind}" data-page="{a}"><input type="checkbox" class="done" data-k="{a}" aria-label="mark done">{html.escape(short)}{badge}</a>')
        pages.append(f'<article id="{a}" class="page" data-title="{html.escape(first)}">{md_to_html(f, c, links)}'
                     f'<div class="pager"></div></article>')
    nav.append(f'<details class="course" open><summary>{html.escape(title)}</summary>{"".join(items)}</details>')

home_md = (ROOT / "SYLLABUS.md").read_text()
home = markdown.markdown(home_md, extensions=["tables", "fenced_code"])
cur = markdown.markdown((ROOT / "CURATION.md").read_text(), extensions=["tables"])
when = time.strftime("%-d %b %Y")
tested = (f"Every command on these pages ({total_runs} of them) was run by CI on a fresh Xubuntu 26.04 VM."
          if total_runs else "Every runnable block is executed by CI on a fresh Xubuntu 26.04 VM.")
pyg = HtmlFormatter(style="monokai").get_style_defs(".code pre")

page = f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nix mastery path — from the store to nixpkgs</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{{--bg:#0f1218;--panel:#161b24;--panel2:#1c2330;--line:#2a3342;--text:#dfe5ee;--muted:#93a0b4;--accent:#7eb6ff;--accent2:#9ae6b4;--warn:#f6c177;--bad:#ff8b8b;--code:#0b0e13}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15.5px/1.65 "IBM Plex Sans",system-ui,sans-serif}}
a{{color:var(--accent)}}code,pre{{font-family:"JetBrains Mono",ui-monospace,monospace}}
:not(pre)>code{{background:var(--panel2);border:1px solid var(--line);padding:.05em .35em;border-radius:4px;font-size:.88em}}
.layout{{display:grid;grid-template-columns:300px 1fr;min-height:100vh}}
nav{{position:sticky;top:0;height:100vh;overflow:auto;border-right:1px solid var(--line);padding:18px 12px;background:#0c0f14}}
nav h1{{font-size:16px;margin:0 6px 2px}}nav .sub{{color:var(--muted);font-size:12.5px;margin:0 6px 14px}}
nav .home{{display:block;padding:5px 8px;color:var(--text);text-decoration:none;border-radius:6px;font-weight:600}}
details.course{{margin:6px 0}}details.course summary{{cursor:pointer;font-weight:600;font-size:13.5px;padding:5px 6px;color:var(--text)}}
nav a[data-page]{{display:flex;gap:8px;align-items:center;color:var(--muted);text-decoration:none;padding:4px 8px 4px 14px;border-radius:6px;font-size:13.2px}}
nav a[data-page]:hover,nav a.cur{{background:var(--panel);color:var(--text)}}nav a.project{{color:#c6b4ff}}nav a.overview{{font-style:italic}}
nav input.done{{accent-color:var(--accent2);margin:0;flex:none}}.st{{margin-left:auto;font-size:12px}}.st.ok{{color:var(--accent2)}}.st.bad{{color:var(--bad)}}
.prog{{margin:14px 8px 0;font-size:12px;color:var(--muted)}}.bar{{height:6px;background:var(--panel2);border-radius:4px;overflow:hidden;margin-top:5px}}.bar i{{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--accent),var(--accent2))}}
main{{padding:24px 44px 120px;max-width:980px}}
.page{{display:none}}.page.on{{display:block}}
h1{{font-size:28px;line-height:1.25;margin:4px 0 14px}}h2{{font-size:21px;margin:30px 0 8px}}h3{{font-size:17px;margin:22px 0 6px}}
table{{border-collapse:collapse;width:100%;font-size:14px;margin:10px 0}}th,td{{border:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}}th{{background:var(--panel2)}}
blockquote{{border-left:3px solid var(--accent);margin:12px 0;padding:6px 14px;background:#141c28;border-radius:0 8px 8px 0;color:var(--text)}}
details{{border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:8px 0;background:var(--panel)}}details summary{{cursor:pointer;font-weight:500}}
.code{{position:relative;margin:14px 0 14px;border:1px solid var(--line);border-radius:8px;background:var(--code)}}
.code .lbl{{font:600 11px "JetBrains Mono",monospace;color:var(--muted);padding:6px 12px 0}}
.code.run .lbl{{color:var(--accent2)}}.code.fails .lbl{{color:var(--warn)}}.code.file .lbl{{color:var(--accent)}}.code.expect{{background:#10161d;border-style:dashed}}
.code pre{{margin:0;padding:8px 14px 12px;overflow:auto;font-size:13.2px;line-height:1.55;background:transparent!important}}
.copy{{position:absolute;top:6px;right:8px;background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:3px 10px;font:12px "IBM Plex Sans";cursor:pointer}}.copy.ok{{color:var(--accent2);border-color:var(--accent2)}}
.code.expect .copy,.code.show .copy{{opacity:.6}}
.banner{{border:1px solid #2c4a3a;background:#13221b;border-radius:10px;padding:12px 16px;margin:6px 0 18px;font-size:14.5px}}
.pager{{display:flex;justify-content:space-between;margin-top:40px;gap:12px}}.pager a{{border:1px solid var(--line);border-radius:8px;padding:10px 14px;text-decoration:none;background:var(--panel);max-width:48%}}
{pyg}
@media (max-width:900px){{.layout{{grid-template-columns:1fr}}nav{{position:static;height:auto}}main{{padding:16px}}}}
</style></head><body>
<div class="layout"><nav>
<h1>Nix mastery path</h1><div class="sub">Store → language → packages → flakes → NixOS → nixpkgs · on Xubuntu</div>
<a class="home" href="#home">Start here</a>
{"".join(nav)}
<a class="home" href="#curation" style="font-weight:400;color:var(--muted);margin-top:10px">How this content was curated</a>
<div class="prog">Progress: <span id="pc">0</span> done<div class="bar"><i id="pb"></i></div></div>
</nav><main>
<article id="home" class="page"><div class="banner"><b>Tested {when}.</b> {tested}
Grey blocks marked <i>runs in CI</i> are executed exactly as shown; blocks marked <i>creates</i> write that file; dashed
<i>expected output</i> blocks are checked. Run any lesson yourself with
<code>python3 mastery/ci/mdrun.py &lt;lesson.md&gt;</code> from <a href="https://github.com/nycnighthawk/nix-on-xfce-guide/tree/main/mastery">the repository</a>.</div>
{home}<div class="pager"></div></article>
<article id="curation" class="page">{cur}</article>
{"".join(pages)}
</main></div>
<script>
(function(){{
const S={{get(k,d){{try{{const v=localStorage.getItem(k);return v===null?d:JSON.parse(v)}}catch(e){{return d}}}},set(k,v){{try{{localStorage.setItem(k,JSON.stringify(v))}}catch(e){{}}}}}};
const pages=[...document.querySelectorAll("article.page")];const order=pages.map(p=>p.id);
function show(id){{if(!document.getElementById(id))id="home";pages.forEach(p=>p.classList.toggle("on",p.id===id));
document.querySelectorAll("nav a[data-page]").forEach(a=>a.classList.toggle("cur",a.dataset.page===id));
const art=document.getElementById(id),i=order.indexOf(id),pg=art.querySelector(".pager");
if(pg){{const prev=order[i-1],next=order[i+1];const t=x=>{{const e=document.getElementById(x);return e.dataset.title||"Start here"}};
pg.innerHTML=(prev&&prev!=="curation"?`<a href="#${{prev}}">← ${{t(prev)}}</a>`:"<span></span>")+(next&&next!=="curation"?`<a href="#${{next}}">${{t(next)}} →</a>`:"");}}
window.scrollTo(0,0);}}
window.addEventListener("hashchange",()=>show(location.hash.slice(1)));show(location.hash.slice(1)||"home");
const done=S.get("nixpath-done",{{}});const boxes=[...document.querySelectorAll("input.done")];
function prog(){{const n=boxes.filter(b=>b.checked).length;document.getElementById("pc").textContent=n+"/"+boxes.length;document.getElementById("pb").style.width=(n/boxes.length*100)+"%";}}
boxes.forEach(b=>{{b.checked=!!done[b.dataset.k];b.addEventListener("click",e=>{{e.stopPropagation();done[b.dataset.k]=b.checked;S.set("nixpath-done",done);prog();}});}});prog();
document.querySelectorAll(".copy").forEach(btn=>btn.addEventListener("click",async()=>{{const t=btn.parentElement.querySelector("pre").innerText;let ok=false;
try{{await navigator.clipboard.writeText(t);ok=true}}catch(e){{try{{const a=document.createElement("textarea");a.value=t;document.body.appendChild(a);a.select();ok=document.execCommand("copy");a.remove()}}catch(_){{}}}}
btn.textContent=ok?"Copied ✓":"Select & copy";btn.classList.toggle("ok",ok);setTimeout(()=>{{btn.textContent="Copy";btn.classList.remove("ok")}},1500);}}));
}})();
</script></body></html>'''
(OUT / "index.html").write_text(page)
print(f"built {OUT / 'index.html'}: {len(pages)} pages, {total_runs} CI-run commands counted, {len(page) / 1e6:.2f} MB")
