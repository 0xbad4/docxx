"""The C/C++ declaration scanner: Ctx (parse result accumulator) and Parser."""
from __future__ import annotations

import copy
import re

from .tokenizer import (
    ATTR_MACROS, BUILTIN_T, NOT_FUNC, QUAL_W, SPEC_FLAGS, STMT_WORDS,
    join, match, name_span, parse_bases, parse_params, split_top, strip_attrs, tokenize,
)
from .docparse import DOC_COPY, parse_doc

DEFINE_RE = re.compile(r"#\s*define\s+([A-Za-z_]\w*)(\([^)]*\))?[ \t]*(.*)$", re.S)
class Ctx:
    def __init__(self):
        self.items = []
        self.ns_docs = {}
        self.file_docs = []
        self.groups = {}
        self.pages = []
        self.mainpage = None
        self.orphans = []
        self.warnings = []


class Parser:
    def __init__(self, toks, path, is_header, cfg, ctx):
        self.t, self.i = toks, 0
        self.path, self.is_header, self.cfg, self.ctx = path, is_header, cfg, ctx
        self.gstack = []
        self.pending = None
        self.tmpl = None
        self.last = None
        self.file_group = None
        self.pending_mname = None

    # ---------------------------------------------------------- small helpers
    def tk(self, k=0):
        j = self.i + k
        return self.t[j] if 0 <= j < len(self.t) else None

    def isp(self, s, k=0):
        x = self.tk(k)
        return x is not None and x.t == "p" and x.s == s

    def isid(self, s=None, k=0):
        x = self.tk(k)
        return x is not None and x.t == "id" and (s is None or x.s == s)

    def skip_group(self):
        depth = 0
        while self.i < len(self.t):
            x = self.t[self.i]
            self.i += 1
            if x.t == "p":
                if x.s in ("(", "[", "{"):
                    depth += 1
                elif x.s in (")", "]", "}"):
                    depth -= 1
                    if depth <= 0:
                        return

    def skip_stmt(self):
        self.pending = None
        self.tmpl = None
        depth = 0
        while self.i < len(self.t):
            x = self.t[self.i]
            if x.t == "p":
                if x.s in ("(", "[", "{"):
                    depth += 1
                elif x.s in (")", "]", "}"):
                    if depth == 0:
                        return
                    depth -= 1
                    if depth == 0 and x.s == "}" and not self.isp(";", 1):
                        # a `{...}` body ends the statement (function / class)
                        pass
                elif x.s == ";" and depth == 0:
                    self.i += 1
                    return
            self.i += 1

    def until_semicolon(self):
        out, depth = [], 0
        while self.i < len(self.t):
            x = self.t[self.i]
            if x.t in ("doc", "pp"):
                self.i += 1
                continue
            if x.t == "p":
                if x.s in ("(", "[", "{"):
                    depth += 1
                elif x.s in (")", "]", "}"):
                    if depth == 0:
                        break
                    depth -= 1
                elif x.s == ";" and depth == 0:
                    self.i += 1
                    break
            out.append(x)
            self.i += 1
        return out

    def take_doc(self):
        d, self.pending = self.pending, None
        return d

    def take_tmpl(self):
        t, self.tmpl = self.tmpl, None
        return t

    def cur_group(self):
        for kind, name in reversed(self.gstack):
            if kind == "group":
                return name
        return None

    def cur_mgroup(self):
        for kind, name in reversed(self.gstack):
            if kind == "member":
                return name
        return None

    # ------------------------------------------------------------- item build
    def mk(self, kind, name, doc, line):
        it = {"kind": kind, "name": name, "line": line, "flags": []}
        if doc:
            self.apply_doc(it, doc)
        return it

    def apply_doc(self, it, d):
        for k in DOC_COPY:
            v = d.get(k)
            if v:
                it[k] = copy.deepcopy(v)
        it["_dparams"] = d.get("params", [])
        it["_dtparams"] = d.get("tparams", [])
        if d.get("internal"):
            it["_hidden"] = True
        if d.get("ingroup"):
            it["group"] = d["ingroup"][0]
        for k in ("mname",):
            pass

    def merge_params(self, it):
        dp = {p["name"]: p for p in it.pop("_dparams", [])}
        for p in it.get("params", []):
            m = dp.get(p["name"])
            if m:
                p["desc"] = m.get("desc", "")
                if m.get("dir"):
                    p["dir"] = m["dir"]
        dt = {p["name"]: p for p in it.pop("_dtparams", [])}
        for p in it.get("tparams", []):
            m = dt.get(p["name"])
            if m:
                p["desc"] = m.get("desc", "")

    def attach_after(self, it, text):
        d = parse_doc(text)
        if d["brief"] and not it.get("brief"):
            it["brief"] = d["brief"]
        elif d["brief"]:
            it["details"] = (it.get("details", "") + "\n\n" + d["brief"]).strip()
        if d["details"]:
            it["details"] = (it.get("details", "") + "\n\n" + d["details"]).strip()

    def add(self, item, container, ns, access):
        item["_ns"] = list(ns)
        item["_file"] = self.path
        item["_hdr"] = self.is_header
        g = self.cur_group() or self.file_group
        if g and not item.get("group"):
            item["group"] = g
        mg = self.cur_mgroup()
        if mg:
            item["mgroup"] = mg
        if container is not None:
            item["access"] = access
            if access not in self.cfg["access"]:
                self.last = None
                return False
            container["members"].append(item)
        else:
            self.ctx.items.append(item)
        self.last = item
        return True

    def drop(self, item, container):
        lst = container["members"] if container is not None else self.ctx.items
        for k, x in enumerate(lst):
            if x is item:
                del lst[k]
                break

    # ----------------------------------------------------------- scope walker
    def parse_scope(self, container, ns, access, cls):
        t = self.t
        while self.i < len(t):
            tok = t[self.i]
            if tok.t == "doc":
                self.i += 1
                if tok.after:
                    if self.last is not None:
                        self.attach_after(self.last, tok.s)
                    continue
                d = parse_doc(tok.s)
                if self.structural(d, ns):
                    continue
                self.pending = d
                continue
            if tok.t == "pp":
                self.i += 1
                self.handle_pp(tok, ns)
                continue
            if tok.t == "p":
                if tok.s == "}":
                    self.i += 1
                    return
                if tok.s == ";":
                    self.i += 1
                    continue
                if tok.s == "{":
                    self.skip_group()
                    continue
            if tok.t == "id":
                w = tok.s
                if w in ("public", "private", "protected") and self.isp(":", 1):
                    access = w
                    self.i += 2
                    continue
                if w == "namespace":
                    self.parse_namespace(ns, False)
                    continue
                if w == "inline" and self.isid("namespace", 1):
                    self.i += 1
                    self.parse_namespace(ns, True)
                    continue
                if w == "template":
                    self.parse_template()
                    continue
                if w == "extern" and self.tk(1) is not None and self.tk(1).t == "str":
                    self.i += 2
                    if self.isp("{"):
                        self.i += 1
                        self.parse_scope(container, ns, access, cls)
                    continue
                if w == "using":
                    self.parse_using(container, ns, access, cls)
                    continue
                if w == "typedef":
                    self.parse_typedef(container, ns, access, cls)
                    continue
                if w in ("static_assert", "friend"):
                    self.skip_stmt()
                    continue
                if w == "concept":
                    self.parse_concept(container, ns, access)
                    continue
                if w in ("class", "struct", "union", "enum"):
                    if self.parse_type(container, ns, access, cls, w):
                        continue
    
            self.parse_general(container, ns, access, cls)

    # -------------------------------------------------------- structural docs
    def structural(self, d, ns):
        s = False
        grp = None
        if d.get("file") is not None:
            self.ctx.file_docs.append((self.path, d))
            if d.get("ingroup"):
                self.file_group = d["ingroup"][0]
            s = True
        for key in ("defgroup", "addtogroup"):
            if d.get(key):
                name, title = d[key]
                g = self.ctx.groups.setdefault(name, {"name": name})
                if title:
                    g["title"] = title
                if d.get("brief"):
                    g["brief"] = d["brief"]
                if d.get("details"):
                    g["details"] = d["details"]
                grp = name
                s = True
        mname = d.get("mname")
        if mname is not None:
            self.pending_mname = mname
            s = True
        if d.get("page"):
            self.ctx.pages.append({"id": d["page"][0], "title": d["page"][1] or d["page"][0],
                                   "brief": d.get("brief", ""), "details": d.get("details", "")})
            s = True
        if d.get("mainpage") is not None:
            self.ctx.mainpage = {"title": d["mainpage"], "brief": d.get("brief", ""),
                                 "details": d.get("details", "")}
            s = True
        if d.get("orphan"):
            self.ctx.orphans.append({"kind": d["orphan"][0], "name": d["orphan"][1], "doc": d})
            # also keep it as a normal pending doc: @def/@fn/@var are commonly written
            # directly above the declaration they describe, not just cross-referenced.
            if d["orphan"][0] != "namespace":
                self.pending = d
            s = True
        if d.get("open"):
            if grp:
                self.gstack.append(("group", grp))
            elif self.pending_mname is not None:
                self.gstack.append(("member", self.pending_mname))
                self.pending_mname = None
            else:
                self.gstack.append(("group", self.cur_group()))
            s = True
        if d.get("close"):
            if self.gstack:
                self.gstack.pop()
            s = True
        return s

    # ------------------------------------------------------------------ macros
    def handle_pp(self, tok, ns):
        m = DEFINE_RE.match(tok.s)
        if not m:
            return
        if self.pending is None and not self.cfg.get("undocumented_macros"):
            return
        name = m.group(1)
        d = self.take_doc()
        it = self.mk("macro", name, d, tok.line)
        if m.group(2) is not None:
            it["params"] = [{"name": p.strip(), "type": ""} for p in
                            m.group(2)[1:-1].split(",") if p.strip()]
            it["flags"].append("function-like")
        body = " ".join(m.group(3).split())
        if body:
            it["value"] = body[:240]
        self.merge_params(it)
        self.add(it, None, ns, "public")

    # --------------------------------------------------------------- namespace
    def parse_namespace(self, ns, inline):
        self.i += 1
        names = []

        while self.i < len(self.t):
            x = self.t[self.i]
            if x.t == "id":
                names.append(x.s)
                self.i += 1
            elif self.isp("::"):
                self.i += 1
            elif self.isp("[") and self.isp("[", 1):
                self.skip_group()
            else:
                break
        if not self.isp("{"):
            self.skip_stmt()
            return
        self.i += 1
        d = self.take_doc()
        self.take_tmpl()
        if not names:
            # Anonymous namespace: parse contents in the current scope (not skipped).
            saved = self.last
            self.parse_scope(None, ns, "public", None)
            self.last = saved
            return
        child = ns + ([] if inline else names)
        if child:
            q = "::".join(child)
            cur = self.ctx.ns_docs.setdefault(q, {"brief": "", "details": ""})
            if d and d.get("brief") and not cur["brief"]:
                cur["brief"] = d["brief"]
            if d and d.get("details"):
                cur["details"] = (cur["details"] + "\n\n" + d["details"]).strip()
        saved = self.last
        self.parse_scope(None, child, "public", None)
        self.last = saved

    # ---------------------------------------------------------------- template
    def parse_template(self):
        self.i += 1
        if not self.isp("<"):
            self.skip_stmt()
            return
        t, j, d, pd = self.t, self.i, 0, 0
        while j < len(t):
            x = t[j]
            if x.t == "p":
                if x.s in ("(", "[", "{"):
                    pd += 1
                elif x.s in (")", "]", "}"):
                    pd -= 1
                elif pd == 0 and x.s == "<":
                    d += 1
                elif pd == 0 and x.s == ">":
                    d -= 1
                    if d == 0:
                        break
            j += 1
        inner = t[self.i + 1:j]
        self.i = j + 1
        params = []
        for seg in split_top(inner, ","):
            if not seg:
                continue
            default = None
            for k, x in enumerate(seg):
                if x.s == "=":
                    default = join(seg[k + 1:])
                    seg = seg[:k]
                    break
            ids = [x for x in seg if x.t == "id"]
            if ids:
                p = {"name": ids[-1].s if len(seg) > 1 or ids[-1].s not in ("typename", "class") else ""}
                if default:
                    p["default"] = default
                params.append(p)
        text = "template <" + join(inner) + ">"
        if self.isid("requires"):
            self.i += 1
            start = self.i
            while self.i < len(t):
                if self.isp("("):
                    self.skip_group()
                elif self.isid():
                    self.i += 1
                    while self.isp("::") and self.isid(None, 1):
                        self.i += 2
                    if self.isp("<"):
                        dd = 0
                        while self.i < len(t):
                            if self.isp("<"):
                                dd += 1
                            elif self.isp(">"):
                                dd -= 1
                                if dd == 0:
                                    self.i += 1
                                    break
                            self.i += 1
                else:
                    break
                if self.isp("&&") or self.isp("||"):
                    self.i += 1
                    continue
                break
            text += " requires " + join(t[start:self.i])
        if self.tmpl:
            self.tmpl["text"] += "\n" + text
            self.tmpl["params"] += params
        else:
            self.tmpl = {"text": text, "params": params}

    def apply_tmpl(self, it, tm):
        if tm:
            it["template"] = tm["text"]
            it["tparams"] = copy.deepcopy(tm["params"])

    # ------------------------------------------------------------ using / typedef
    def parse_using(self, container, ns, access, cls):
        nxt = self.tk(1)
        if nxt is not None and nxt.t == "id" and nxt.s in ("namespace", "enum"):
            d = self.take_doc()
            self.skip_stmt()
            if d and ns:
                q = "::".join(ns)
                cur = self.ctx.ns_docs.setdefault(q, {"brief": "", "details": ""})
                if d.get("brief") and not cur["brief"]:
                    cur["brief"] = d["brief"]
                if d.get("details"):
                    cur["details"] = (cur["details"] + "\n\n" + d["details"]).strip()
            return
        if nxt is not None and nxt.t == "id" and self.isp("=", 2):
            name = nxt.s
            self.i += 3
            toks = self.until_semicolon()
            d, tm = self.take_doc(), self.take_tmpl()
            it = self.mk("alias", name, d, nxt.line)
            it["type"] = join(toks)
            it["_style"] = "using"
            self.apply_tmpl(it, tm)
            self.merge_params(it)
            self.add(it, container, ns, access)
            return
        self.skip_stmt()

    def type_has_body(self, idx):
        t, depth = self.t, 0
        for j in range(idx + 1, len(t)):
            x = t[j]
            if x.t == "p":
                if x.s in ("(", "["):
                    depth += 1
                elif x.s in (")", "]"):
                    depth -= 1
                elif depth == 0 and x.s == "{":
                    return True
                elif depth == 0 and x.s in (";", "="):
                    return False
        return False

    def parse_typedef(self, container, ns, access, cls):
        nxt = self.tk(1)
        if nxt is not None and nxt.t == "id" and nxt.s in ("struct", "class", "union", "enum") \
                and self.type_has_body(self.i + 1):
            self.i += 1
            if self.parse_type(container, ns, access, cls, nxt.s, typedef=True):
                return
            self.i -= 1
        line = self.t[self.i].line
        self.i += 1
        toks = self.until_semicolon()
        d, tm = self.take_doc(), self.take_tmpl()
        toks, _ = strip_attrs(toks)
        name, idx = "", None
        for k in range(len(toks) - 3):
            if toks[k].s == "(" and toks[k + 1].s == "*" and toks[k + 2].t == "id" and toks[k + 3].s == ")":
                idx = k + 2
                break
        if idx is None:
            h = list(toks)
            while h and h[-1].s == "]":
                m = len(h) - 1
                while m >= 0 and h[m].s != "[":
                    m -= 1
                h = h[:max(m, 0)]
            for k in range(len(h) - 1, -1, -1):
                if h[k].t == "id":
                    idx = k
                    break
        if idx is None or len(toks) < 2:
            return
        name = toks[idx].s
        typ = join(toks[:idx] + toks[idx + 1:])
        it = self.mk("alias", name, d, line)
        it["type"] = typ
        it["_style"] = "typedef"
        self.apply_tmpl(it, tm)
        self.add(it, container, ns, access)

    def parse_concept(self, container, ns, access):
        line = self.t[self.i].line
        self.i += 1
        name = self.tk().s if self.isid() else ""
        self.i += 1
        toks = []
        if self.isp("="):
            self.i += 1
            toks = self.until_semicolon()
        else:
            self.skip_stmt()
        d, tm = self.take_doc(), self.take_tmpl()
        if not name:
            return
        it = self.mk("concept", name, d, line)
        it["value"] = join(toks)[:300]
        self.apply_tmpl(it, tm)
        self.merge_params(it)
        self.add(it, container, ns, access)

    # ------------------------------------------------------------- class / enum
    def parse_type(self, container, ns, access, cls, kw, typedef=False):
        t, n = self.t, len(self.t)
        j, depth, sawparen = self.i + 1, 0, False
        while j < n:
            x = t[j]
            if x.t == "p":
                if x.s in ("(", "["):
                    if x.s == "(" and depth == 0:
                        prev = t[j - 1]
                        if not (prev.t == "id" and prev.s in ATTR_MACROS):
                            sawparen = True
                    depth += 1
                elif x.s in (")", "]"):
                    depth -= 1
                elif depth == 0 and x.s in ("{", ";", "="):
                    break
            j += 1
        if j >= n:
            return False
        end = t[j]
        if sawparen or end.s == "=":
            return False
        if end.s == ";":
            if typedef:
                return False
            self.skip_stmt()
            return True
        header, _ = strip_attrs(t[self.i + 1:j])
        colon, ad = None, 0
        for k, x in enumerate(header):
            if x.s == "<":
                ad += 1
            elif x.s == ">":
                ad = max(0, ad - 1)
            elif x.s == ":" and ad == 0:
                colon = k
                break
        head = header[:colon] if colon is not None else header
        basetoks = header[colon + 1:] if colon is not None else []
        head = [x for x in head if x.s != "final" and x.s not in self.cfg["strip_macros"]]
        scoped = False
        if kw == "enum" and head and head[0].s in ("class", "struct"):
            scoped, head = True, head[1:]
        name, ad, last_id = "", 0, -1
        for k, x in enumerate(head):
            if x.s == "<":
                ad += 1
            elif x.s == ">":
                ad = max(0, ad - 1)
            elif x.t == "id" and ad == 0:
                last_id = k
        if last_id >= 0:
            name = join(head[last_id:])
        line = t[self.i].line
        self.i = j + 1
        d, tm = self.take_doc(), self.take_tmpl()
        item = self.mk(kw, name, d, line)
        self.apply_tmpl(item, tm)
        if kw == "enum":
            if scoped:
                item["flags"].append("scoped")
            if basetoks:
                item["underlying"] = join(basetoks)
            if not name and not typedef:
                item["name"] = "(anonymous)"
            item["values"] = self.parse_enum_body()
            self.add(item, container, ns, access)
        else:
            item["bases"] = parse_bases(basetoks, kw)
            item["members"] = []
            self.add(item, container, ns, access)
            saved_stack = list(self.gstack)
            self.parse_scope(item, ns, "private" if kw == "class" else "public",
                             name.split("<")[0])
            self.gstack = saved_stack
            self.last = item
        self.finish_type(item, typedef, container, ns, access)
        return True

    def finish_type(self, item, typedef, container, ns, access):
        ids, depth = [], 0
        while self.i < len(self.t):
            x = self.t[self.i]
            if x.t == "p":
                if x.s == ";" and depth == 0:
                    self.i += 1
                    break
                if x.s in ("(", "[", "{"):
                    depth += 1
                elif x.s in (")", "]", "}"):
                    if depth == 0:
                        break
                    depth -= 1
            elif x.t == "id" and depth == 0:
                ids.append(x.s)
            elif x.t == "doc" and x.after:
                self.attach_after(item, x.s)
            self.i += 1
        if typedef and ids:
            if not item["name"] or item["name"] == "(anonymous)":
                item["name"] = ids[0]
            elif ids[0] != item["name"]:
                al = self.mk("alias", ids[0], None, item["line"])
                al["type"] = item["kind"] + " " + item["name"]
                al["_style"] = "typedef"
                al["brief"] = item.get("brief", "")
                self.add(al, container, ns, access)
                self.last = item
        if not item["name"]:
            self.drop(item, container)

    def parse_enum_body(self):
        vals, pend = [], None
        t = self.t
        while self.i < len(t):
            x = t[self.i]
            if x.t == "doc":
                self.i += 1
                if x.after:
                    if vals:
                        d = parse_doc(x.s)
                        if d["brief"] and not vals[-1].get("brief"):
                            vals[-1]["brief"] = d["brief"]
                        elif d["brief"]:
                            vals[-1]["details"] = d["brief"]
                else:
                    pend = parse_doc(x.s)
                continue
            if x.t == "pp":
                self.i += 1
                continue
            if x.t == "p" and x.s == "}":
                self.i += 1
                break
            if x.t == "p" and x.s in (",", ";"):
                self.i += 1
                continue
            if x.t == "id":
                v = {"name": x.s}
                if pend:
                    if pend.get("brief"):
                        v["brief"] = pend["brief"]
                    if pend.get("details"):
                        v["details"] = pend["details"]
                    if pend.get("deprecated"):
                        v["deprecated"] = pend["deprecated"]
                    pend = None
                vals.append(v)
                self.i += 1
                if self.isp("[") and self.isp("[", 1):
                    self.skip_group()
                if self.isp("="):
                    self.i += 1
                    vt, depth = [], 0
                    while self.i < len(t):
                        y = t[self.i]
                        if y.t == "doc" and depth == 0:
                            break
                        if y.t == "p":
                            if y.s in ("(", "[", "{"):
                                depth += 1
                            elif y.s in (")", "]", "}"):
                                if depth == 0:
                                    break
                                depth -= 1
                            elif y.s == "," and depth == 0:
                                break
                        if y.t != "doc":
                            vt.append(y)
                        self.i += 1
                    v["value"] = join(vt)
                continue
            self.i += 1
        return vals

    # ----------------------------------------------------------- declarations
    def collect_decl(self):
        out, depth, seen_close, eq_seen, init_list = [], 0, False, False, False
        t = self.t
        while self.i < len(t):
            x = t[self.i]
            if x.t in ("doc", "pp"):
                self.i += 1
                continue
            if x.t == "p":
                s = x.s
                if s in ("(", "["):
                    depth += 1
                elif s in (")", "]"):
                    depth -= 1
                    if depth == 0 and s == ")":
                        seen_close = True
                        # `MACRO(args)` followed by a declaration on a later line
                        if (out and out[0].t == "id" and out[0].s.isupper() and len(out[0].s) > 2
                                and len(out) > 1 and out[1].s == "(" and match(out + [x], 1) == len(out)):
                            nx = t[self.i + 1] if self.i + 1 < len(t) else None
                            if (nx is not None and nx.line > x.line and nx.t != "doc"
                                    and not (nx.t == "p" and nx.s in (";", "{", "=", ":"))
                                    and not (nx.t == "id" and nx.s in ("const", "noexcept", "override", "final"))):
                                out.append(x)
                                self.i += 1
                                return out, "macro"
                elif depth == 0 and s == ";":
                    self.i += 1
                    return out, ";"
                elif depth == 0 and s == "}":
                    return out, "}"
                elif depth == 0 and s == "=":
                    eq_seen = True
                elif depth == 0 and s == ":" and seen_close:
                    init_list = True
                elif depth == 0 and s == "{":
                    prev = out[-1] if out else None
                    if eq_seen or not seen_close or (
                            init_list and prev is not None and (prev.t == "id" or prev.s == ">")):
                        start = self.i
                        self.skip_group()
                        out.extend(t[start:self.i])
                        continue
                    self.skip_group()
                    if self.isp(";"):
                        self.i += 1
                    return out, "{}"
            out.append(x)
            self.i += 1
        return out, "eof"

    def parse_general(self, container, ns, access, cls):
        line = self.t[self.i].line
        toks, endk = self.collect_decl()
        d, tm = self.take_doc(), self.take_tmpl()
        if not toks:
            return
        for it in self.build_decl(toks, d, tm, line, endk == "{}", cls):
            self.add(it, container, ns, access)

    def build_decl(self, toks, d, tm, line, has_body, cls):
        toks, attrs = strip_attrs(toks)
        toks = [x for x in toks if not (x.t == "id" and x.s in self.cfg["strip_macros"])]
        if not toks:
            return []
        if toks[0].t == "id" and toks[0].s in STMT_WORDS:
            return []
        fn = self.parse_function(toks, cls)
        if fn == "skip":
            return []
        if fn:
            fn["line"] = line
            items = [fn]
            if has_body:
                fn["_body"] = True
        else:
            items = self.parse_variables(toks, line)
        out = []
        for it in items:
            if d:
                self.apply_doc(it, d)
            self.apply_tmpl(it, tm)
            for a in attrs:
                if "nodiscard" in a and "nodiscard" not in it["flags"]:
                    it["flags"].append("nodiscard")
                if "deprecated" in a and not it.get("deprecated"):
                    m = re.search(r'"([^"]*)"', a)
                    it["deprecated"] = m.group(1) if m else True
            self.merge_params(it)
            out.append(it)
        return out

    # functions ---------------------------------------------------------
    def match_idx(self, toks, i):
        return match(toks, i)

    def parse_function(self, toks, cls):
        n, k, ad = len(toks), 0, 0
        while k < n:
            x = toks[k]
            if x.t == "id" and x.s == "operator" and ad == 0:
                j = k + 1
                if j + 1 < n and toks[j].s == "(" and toks[j + 1].s == ")":
                    optext, j = "()", j + 2
                else:
                    st = j
                    while j < n and toks[j].s != "(":
                        j += 1
                    optext = join(toks[st:j])
                if j >= n or toks[j].s != "(":
                    return None
                sep = " " if optext[:1].isalpha() or optext[:1] == "_" else ""
                return self.func_from(toks, k, "operator" + sep + optext, j, cls, optext)
            if x.t == "p":
                s = x.s
                if s == "(" and ad == 0:
                    prev = toks[k - 1] if k > 0 else None
                    if prev is not None and prev.t == "id" and prev.s not in NOT_FUNC:
                        nxt = toks[k + 1] if k + 1 < n else None
                        if nxt is not None and nxt.s in ("*", "&"):
                            return None
                        return self.func_from(toks, k - 1, None, k, cls, None)
                    e = match(toks, k)
                    if e is None:
                        return None
                    k = e + 1
                    continue
                if s in ("[", "{"):
                    e = match(toks, k)
                    if e is None:
                        return None
                    k = e + 1
                    continue
                if s == "<":
                    ad += 1
                elif s == ">" and ad > 0:
                    ad -= 1
                elif s == "=" and ad == 0:
                    return None
            k += 1
        return None

    def func_from(self, toks, name_end, opname, paren, cls, optext):
        start, quals, parts = name_span(toks, name_end)
        name = opname if opname else "".join(parts)
        prefix = toks[:start]
        close = match(toks, paren)
        if close is None:
            return None
        params = parse_params(toks[paren + 1:close])
        suffix = toks[close + 1:]
        flags, ptoks = [], []
        for x in prefix:
            if x.t == "id" and x.s in SPEC_FLAGS:
                flags.append(x.s)
            else:
                ptoks.append(x)
        base_cls = (cls or "").split("<")[0]
        if name.startswith("~"):
            kind = "destructor"
        elif (base_cls and name == base_cls) or (quals and quals[-1] == name):
            kind = "constructor"
        elif name.startswith("operator"):
            kind = "operator"
        else:
            kind = "function"
        if kind == "function" and not ptoks:
            return "skip"
        rtype = join(ptoks)
        if kind == "operator" and not ptoks and optext and (optext[0].isalpha() or optext[0] == "_"):
            rtype = optext
        i, n = 0, len(suffix)
        noexcept_expr = requires = None
        while i < n:
            x = suffix[i]
            if x.t == "id":
                if x.s in ("const", "volatile"):
                    flags.append(x.s)
                elif x.s == "noexcept":
                    flags.append("noexcept")
                    if i + 1 < n and suffix[i + 1].s == "(":
                        e = match(suffix, i + 1)
                        if e is not None:
                            noexcept_expr = join(suffix[i + 2:e])
                            i = e
                elif x.s in ("override", "final"):
                    flags.append(x.s)
                elif x.s == "requires":
                    requires = join(suffix[i + 1:])
                    break
                elif x.s == "throw" and i + 1 < n and suffix[i + 1].s == "(":
                    e = match(suffix, i + 1)
                    i = e if e is not None else i
            elif x.s == "->":
                j = i + 1
                while j < n and not (suffix[j].s == "=" or (suffix[j].t == "id" and suffix[j].s == "requires")):
                    j += 1
                rtype = join(suffix[i + 1:j])
                i = j
                continue
            elif x.s in ("&", "&&"):
                flags.append(x.s)
            elif x.s == "=" and i + 1 < n:
                v = suffix[i + 1]
                if v.s == "0":
                    flags.append("pure")
                elif v.s == "default":
                    flags.append("defaulted")
                elif v.s == "delete":
                    flags.append("deleted")
            elif x.s == ":":
                break
            i += 1
        it = {"kind": kind, "name": name, "flags": flags, "params": params}
        if rtype and kind != "constructor" and kind != "destructor":
            it["type"] = rtype
        if noexcept_expr:
            it["noexcept"] = noexcept_expr
        if requires:
            it["requires"] = requires
        if quals:
            it["_scope"] = quals
        return it

    # variables ---------------------------------------------------------
    @staticmethod
    def cut_init(seg):
        d = ad = 0
        for k, x in enumerate(seg):
            if x.t != "p":
                continue
            if x.s in ("(", "["):
                d += 1
            elif x.s in (")", "]"):
                d -= 1
            elif d == 0 and x.s == "<" and k > 0 and seg[k - 1].t == "id":
                ad += 1
            elif d == 0 and x.s == ">" and ad > 0:
                ad -= 1
            elif d == 0 and ad == 0 and x.s in ("=", "{", ":"):
                return seg[:k], seg[k:]
        return seg, []

    def parse_variables(self, toks, line):
        segs = split_top(toks, ",")
        out, base_type, flags0 = [], None, []
        for si, seg in enumerate(segs):
            if not seg:
                continue
            head, init = self.cut_init(seg)
            h = list(head)
            arr = []
            while h and h[-1].s == "]":
                d, idx = 0, len(h) - 1
                while idx >= 0:
                    if h[idx].s == "]":
                        d += 1
                    elif h[idx].s == "[":
                        d -= 1
                    if d == 0:
                        break
                    idx -= 1
                arr = h[max(idx, 0):] + arr
                h = h[:max(idx, 0)]
            name, typ_toks = "", []
            fp = None
            for k in range(len(h) - 3):
                if h[k].s == "(" and h[k + 1].s in ("*", "&") and h[k + 2].t == "id" and h[k + 3].s == ")":
                    fp = k + 2
                    break
            if fp is not None:
                name = h[fp].s
                typ_toks = h[:fp] + h[fp + 1:]
            elif h and h[-1].t == "id":
                name, typ_toks = h[-1].s, h[:-1]
            else:
                return out
            if si == 0:
                flags, tt = [], []
                for x in typ_toks:
                    if x.t == "id" and x.s in SPEC_FLAGS:
                        flags.append(x.s)
                    else:
                        tt.append(x)
                if not tt or any(x.t == "id" and x.s in STMT_WORDS for x in tt):
                    return []
                if name in ("operator",):
                    return []
                base = list(tt)
                while base and base[-1].s in ("*", "&", "&&"):
                    base.pop()
                base_type, flags0 = base, flags
                typ = join(tt + arr)
            else:
                lead = []
                while typ_toks and typ_toks[0].s in ("*", "&", "&&"):
                    lead.append(typ_toks.pop(0))
                typ = join((base_type or []) + lead + arr)
                flags = list(flags0)
            it = {"kind": "variable", "name": name, "type": typ, "flags": flags, "line": line}
            if init and init[0].s == "=":
                it["value"] = join(init[1:])[:240]
            elif init and init[0].s == "{":
                it["value"] = join(init)[:240]
            out.append(it)
        return out


