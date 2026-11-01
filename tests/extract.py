#!/usr/bin/env python3
"""Split guide/index.html into its steps, in page order.

Writes steps.json: a list of
  {"idx": 0, "section": "install", "title": "...", "only": ["arch"] | null,
   "tab": "nv-a" | null, "blocks": [{"label": "flake.nix" | null, "text": "..."}]}
Code text is exactly what the page's Copy button copies (username/arch substituted).
"""
import json, sys
from html.parser import HTMLParser

SRC = sys.argv[1] if len(sys.argv) > 1 else "guide/index.html"
OUT = sys.argv[2] if len(sys.argv) > 2 else "steps.json"
USER = sys.argv[3] if len(sys.argv) > 3 else "tester"
SYS = "x86_64-linux"


class P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []          # open div/section tags: dict(tag,id,cls,only)
        self.steps = []
        self.cur = None          # current step dict
        self.in_title = False
        self.in_pre = False
        self.code = None
        self.lbl = None
        self.in_lbl = False
        self.section = None

    def handle_starttag(self, t, a):
        a = dict(a)
        if t in ("div", "section"):
            info = {"tag": t, "id": a.get("id"), "cls": a.get("class", "") or "", "only": a.get("data-only")}
            self.stack.append(info)
            if t == "section":
                self.section = a.get("id")
            if "step" in info["cls"].split():
                only = [x["only"] for x in self.stack if x["only"]]
                tab = [x["id"] for x in self.stack if "tabpanel" in x["cls"].split()]
                self.cur = {"idx": len(self.steps), "section": self.section, "title": "",
                            "only": only[-1].split() if only else None,
                            "tab": tab[-1] if tab else None, "blocks": [], "_depth": len(self.stack)}
                self.steps.append(self.cur)
        elif t == "b" and self.cur is not None and not self.cur["title"] and not self.in_pre:
            self.in_title = True
        elif t == "span" and a.get("class") == "lbl":
            self.in_lbl, self.lbl = True, ""
        elif t == "pre":
            self.in_pre = True
        elif t == "code" and self.in_pre:
            self.code = ""

    def handle_endtag(self, t):
        if t in ("div", "section") and self.stack:
            if self.cur is not None and len(self.stack) == self.cur["_depth"]:
                self.cur = None
            self.stack.pop()
        elif t == "b":
            self.in_title = False
        elif t == "span" and self.in_lbl:
            self.in_lbl = False
        elif t == "pre":
            self.in_pre = False
            if self.cur is not None and self.code is not None:
                # a block inside a distro-only div within the step
                only = [x["only"] for x in self.stack[self.cur["_depth"]:] if x["only"]]
                tab = [x["id"] for x in self.stack[self.cur["_depth"]:] if "tabpanel" in x["cls"].split()]
                text = self.code.replace("{{USER}}", USER).replace("{{SYS}}", SYS)
                self.cur["blocks"].append({"label": (self.lbl or "").split("/")[-1] or None,
                                           "only": only[-1].split() if only else None,
                                           "tab": tab[-1] if tab else None,
                                           "text": text if text.endswith("\n") else text + "\n"})
            self.code, self.lbl = None, None

    def handle_data(self, d):
        if self.in_lbl:
            self.lbl += d
        elif self.code is not None:
            self.code += d
        elif self.in_title and self.cur is not None:
            self.cur["title"] += d


p = P()
p.feed(open(SRC).read())
for s in p.steps:
    s.pop("_depth")
    s["title"] = " ".join(s["title"].split())
json.dump(p.steps, open(OUT, "w"), indent=1)
if __name__ == "__main__" and "-v" in sys.argv:
    for s in p.steps:
        print(s["idx"], s["section"], s["only"], s["tab"], s["title"], [ (b["label"], b["only"], b["tab"]) for b in s["blocks"]])
