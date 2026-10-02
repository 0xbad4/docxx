"""Doxygen comment-body parser: turns one comment string into a structured dict."""
from __future__ import annotations

import re
import textwrap

BLOCK_CMDS = {
    "brief", "short", "details", "param", "tparam", "return", "returns", "result",
    "retval", "throws", "throw", "exception", "note", "warning", "attention", "remark",
    "remarks", "see", "sa", "since", "version", "deprecated", "todo", "bug", "pre",
    "post", "invariant", "author", "authors", "date", "par", "file", "defgroup",
    "addtogroup", "ingroup", "name", "page", "mainpage", "internal", "class", "struct",
    "union", "enum", "namespace", "fn", "var", "typedef", "def", "concept", "copyright",
    "markdown", "markdownend", "{", "}",
}
ORPHAN_CMDS = {"class", "struct", "union", "enum", "namespace", "fn", "var", "typedef",
               "def", "concept"}
CMD_RE = re.compile(r"(?:(?<=\s)|^)[@\\](?P<cmd>[A-Za-z]+|[{}])(?:\[(?P<opt>[^\]]*)\])?", re.M)
CODE_RE = re.compile(
    r"(?:(?<=\s)|^)[@\\](?P<k>code|verbatim)(?:\{\.?(?P<lang>[^}]*)\})?[ \t]*\n?"
    r"(?P<body>.*?)[@\\]end(?P=k)", re.S | re.M)
FENCE_RE = re.compile(r"^[ \t]*```.*?^[ \t]*```[ \t]*$", re.S | re.M)
LIST_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+")
INLINE_RE = re.compile(
    r"(?<![\w@\\])[@\\](?P<c>c|p|a|e|em|b|ref)\s+(?P<w>\S+?)(?P<p>[.,;:!?]*)(?=\s|$)")


def convert_inline(s: str) -> str:
    s = re.sub(r"(?m)^[ \t]*[@\\]li\b[ \t]*", "- ", s)

    def rep(m):
        c, w, p = m.group("c"), m.group("w"), m.group("p")
        if c in ("c", "p", "ref"):
            return f"`{w}`{p}"
        if c == "b":
            return f"**{w}**{p}"
        return f"*{w}*{p}"

    s = INLINE_RE.sub(rep, s)
    s = re.sub(r"(?<![\w@])@n\b", "\n", s)
    s = re.sub(r"</?b>", "**", s, flags=re.I)
    s = re.sub(r"</?(?:i|em)>", "*", s, flags=re.I)
    s = re.sub(r"</?(?:tt|code)>", "`", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", s, flags=re.I | re.S)
    return s


def strip_comment_markers(s: str) -> str:
    lines = s.splitlines()
    cleaned = []
    for line in lines:
        l = line.rstrip()
        if l.strip().startswith("*/"):
            continue
        if l.strip().startswith("/**"):
            l = l.replace("/**", "", 1).lstrip()
        if l.strip().startswith("*"):
            l = l.strip()[1:].lstrip()
        cleaned.append(l)
    return "\n".join(cleaned).strip()


def paragraphs(s: str):
    lines = [l.rstrip() for l in s.strip("\n").split("\n")]
    paras, cur = [], []
    for l in lines + [""]:
        if not l.strip():
            if cur:
                paras.append(cur)
                cur = []
        else:
            cur.append(l.strip())
    out = []
    for p in paras:
        if any(LIST_RE.match(x) for x in p):
            out.append("\n".join(p))
        else:
            out.append(" ".join(p))
    return out


def one_line(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_doc(text: str) -> dict:
    text = strip_comment_markers(text)
    text = re.sub(r"(?m)^[ \t]*\* ?", "", text)
    stash = []

    def hold(txt):
        stash.append(txt)
        return f"\n\n\x00{len(stash) - 1}\x00\n\n"

    def code_sub(m):
        body = textwrap.dedent(m.group("body")).strip("\n")
        lang = (m.group("lang") or ("cpp" if m.group("k") == "code" else "")).strip()
        return hold(f"```{lang}\n{body}\n```")

    def fence_sub(m):
        lines = m.group(0).split("\n")
        inner = textwrap.dedent("\n".join(lines[1:-1]))
        return hold(f"{lines[0].strip()}\n{inner}\n```")

    text = CODE_RE.sub(code_sub, text)
    text = FENCE_RE.sub(fence_sub, text)

    text = re.sub(r"(?:(?<=\s)|^)@code(?:\{\.?([^}]*)\})?[ \t]*\n?\s*(.*?)\s*@endcode\b",
                  lambda m: f"\n\n```{(m.group(1) or 'cpp').strip()}\n{m.group(2).strip()}\n```\n\n",
                  text, flags=re.S | re.M)

    ms = [m for m in CMD_RE.finditer(text) if m.group("cmd") in BLOCK_CMDS]
    secs = [(None, None, text[:ms[0].start()] if ms else text)]
    for k, m in enumerate(ms):
        end = ms[k + 1].start() if k + 1 < len(ms) else len(text)
        secs.append((m.group("cmd"), m.group("opt"), text[m.end():end]))

    d = {"brief": "", "details": [], "params": [], "tparams": [], "returns": "",
         "retvals": [], "throws": [], "notes": [], "see": [], "pre": [], "post": []}
    head_paras, cmd_details = [], []

    def restore(s):
        return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], s)

    for cmd, opt, body in secs:
        body = convert_inline(body)
        body = re.sub(r"(?m)^\s*\* ?", "", body)
        if cmd is None:
            head_paras = paragraphs(body)
            continue
        ps = paragraphs(body)
        if cmd in ("brief", "short"):
            if ps:
                d["brief"] = one_line(ps[0])
                cmd_details.extend(ps[1:])
        elif cmd == "details":
            cmd_details.extend(ps)
        elif cmd in ("param", "tparam"):
            m = re.match(r"\s*(\S+)\s*(.*)", body, re.S)
            if not m:
                continue
            names = m.group(1).split(",")
            rest = paragraphs(m.group(2))
            desc = rest[0] if rest else ""
            cmd_details.extend(rest[1:])
            for nm in names:
                e = {"name": nm, "desc": desc}
                if opt and cmd == "param":
                    e["dir"] = opt.replace(" ", "")
                d["params" if cmd == "param" else "tparams"].append(e)
        elif cmd in ("return", "returns", "result"):
            if ps:
                d["returns"] = ps[0]
                cmd_details.extend(ps[1:])
        elif cmd == "retval":
            m = re.match(r"\s*(\S+)\s*(.*)", body, re.S)
            if m:
                rest = paragraphs(m.group(2))
                d["retvals"].append({"value": m.group(1), "desc": rest[0] if rest else ""})
        elif cmd in ("throws", "throw", "exception"):
            m = re.match(r"\s*(\S+)\s*(.*)", body, re.S)
            if m:
                rest = paragraphs(m.group(2))
                d["throws"].append({"type": m.group(1), "desc": rest[0] if rest else ""})
        elif cmd in ("note", "remark", "remarks"):
            d["notes"].append({"kind": "note", "text": "\n\n".join(ps)})
        elif cmd in ("warning", "attention"):
            d["notes"].append({"kind": "warning", "text": "\n\n".join(ps)})
        elif cmd == "todo":
            d["notes"].append({"kind": "todo", "text": "\n\n".join(ps)})
        elif cmd == "bug":
            d["notes"].append({"kind": "bug", "text": "\n\n".join(ps)})
        elif cmd in ("see", "sa"):
            if ps:
                d["see"].append(ps[0])
        elif cmd == "deprecated":
            d["deprecated"] = ps[0] if ps else True
        elif cmd in ("since", "version", "author", "authors", "date", "copyright"):
            if ps:
                d["authors" if cmd == "authors" else cmd] = ps[0]
        elif cmd in ("pre", "post"):
            if ps:
                d[cmd].append(ps[0])
        elif cmd == "invariant":
            if ps:
                d["pre"].append("invariant: " + ps[0])
        elif cmd == "par":
            first, _, rest = body.strip().partition("\n")
            txt = " ".join(paragraphs(rest)) if rest.strip() else ""
            title = first.strip()
            cmd_details.append(f"**{title}.** {txt}".strip() if title else txt)
        elif cmd == "file":
            m = re.match(r"\s*(\S*)", body)
            d["file"] = m.group(1) if m else ""
        elif cmd in ("defgroup", "addtogroup"):
            m = re.match(r"\s*(\S+)[ \t]*([^\n]*)", body)
            if m:
                d[cmd] = (m.group(1), m.group(2).strip())
        elif cmd == "ingroup":
            d.setdefault("ingroup", []).extend(body.split())
        elif cmd == "name":
            d["mname"] = one_line(body)
        elif cmd == "page":
            m = re.match(r"\s*(\S+)[ \t]*([^\n]*)\n?(.*)", body, re.S)
            if m:
                d["page"] = (m.group(1), m.group(2).strip())
                cmd_details.extend(paragraphs(m.group(3)))
        elif cmd == "mainpage":
            first, _, rest = body.strip().partition("\n")
            d["mainpage"] = first.strip()
            cmd_details.extend(paragraphs(rest))
        elif cmd == "internal":
            d["internal"] = True
        elif cmd == "markdown":
            d.setdefault("markdown_blocks", []).append({
                "type": "markdown",
                "content": restore(body).strip(),
                "description": "",
            })
        elif cmd == "markdownend":
            pass
        elif cmd in ORPHAN_CMDS:
            first, _, rest = body.strip().partition("\n")
            if cmd in ("fn", "def"):
                m = re.search(r"([~\w:]+)\s*\(", first)
                nm = m.group(1) if m else first.split()[0] if first.split() else ""
            else:
                nm = first.split()[0] if first.split() else ""
            d["orphan"] = (cmd, nm)
            extra = paragraphs(rest)
            if extra and not head_paras:
                head_paras = extra
        elif cmd == "{":
            d["open"] = True
        elif cmd == "}":
            d["close"] = True

    if head_paras:
        if not d["brief"]:
            d["brief"] = one_line(head_paras[0])
            details = head_paras[1:] + cmd_details
        else:
            details = head_paras + cmd_details
    else:
        details = cmd_details
    d["details"] = restore("\n\n".join(details))
    d["brief"] = restore(d["brief"])
    for k in ("notes",):
        for n in d[k]:
            n["text"] = restore(n["text"])
    d["returns"] = restore(d["returns"])
    d["see"] = [restore(x) for x in d["see"]]
    if d.get("markdown_blocks"):
        d["markdown"] = d["markdown_blocks"]
        d.pop("markdown_blocks", None)
    return d


# --------------------------------------------------------------------------
# parser  (tokens -> items)
# --------------------------------------------------------------------------


DOC_COPY = ("brief", "details", "returns", "retvals", "throws", "notes", "see", "since",
            "version", "deprecated", "pre", "post", "author", "date", "markdown")
