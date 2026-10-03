"""Post-parse transforms: definition merging, exclusion, grouping into modules,
and assembling the final JSON document (see README's "JSON schema" section).

Internally, parsed items still use the field names cpp_parser.py has always
used (`kind`, `details`, `desc`, `members`, `mgroup`, ...) — only the final
serialize_item()/assemble() step maps those onto the output shape. Keeping
the internal representation unchanged means tokenizer.py/docparse.py/
cpp_parser.py never needed to change for this schema switch, only this file.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from .cpp_parser import Parser
from .docparse import DOC_COPY, parse_doc

TYPE_KINDS = ("class", "struct", "union", "enum", "alias", "concept")
FUNC_KINDS = ("function", "constructor", "destructor", "operator")

# Doxygen's \note/\warning become the viewer's info/warn; \todo and \bug pass through as-is.
NOTE_KIND_MAP = {"note": "info", "warning": "warn", "todo": "todo", "bug": "bug"}

# Order items appear within a module's "content": types-like things, then free
# functions, then free variables, then macros — ties keep source encounter order.
_KIND_ORDER = {"enum": 0, "alias": 0, "concept": 0, "union": 0, "struct": 0, "class": 0,
               "function": 1, "variable": 2, "macro": 3}


def walk(items):
    for it in items:
        yield it
        yield from walk(it.get("members", []))


def slug(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", s).strip("-")
    return s or "x"


def assign_qual(it, prefix):
    """Internal-only fully-qualified name, used for merge/exclude/warning bookkeeping.
    Never appears in the output — the new schema has no id/qualified field."""
    it["_qparts"] = prefix + [it["name"]]
    it["qualified"] = "::".join(it["_qparts"])
    for m in it.get("members", []):
        assign_qual(m, it["_qparts"])


def norm_types(it):
    return [re.sub(r"\s+", "", p.get("type", "")) for p in it.get("params", [])]


def merge_definition(cand, dfn):
    for k in DOC_COPY:
        if not cand.get(k) and dfn.get(k):
            cand[k] = dfn[k]
    dp, cp = dfn.get("params", []), cand.get("params", [])
    for i, p in enumerate(cp):
        q = next((x for x in dp if x["name"] and x["name"] == p["name"]), dp[i] if i < len(dp) else None)
        if q is not None:
            if not p.get("desc") and q.get("desc"):
                p["desc"] = q["desc"]
            if not p["name"] and q.get("name"):
                p["name"] = q["name"]
            if not p.get("dir") and q.get("dir"):
                p["dir"] = q["dir"]
    if not cand.get("returns") and dfn.get("returns"):
        cand["returns"] = dfn["returns"]


def postprocess(ctx, cfg):
    items = ctx.items
    for it in items:
        assign_qual(it, it["_ns"] + it.pop("_scope", []))

    # ---- merge out-of-class definitions into declarations
    decls = {}
    for it in walk(items):
        if not it.get("_scope_def"):
            decls.setdefault(it["qualified"], []).append(it)
    # A top-level function/method item only acts as a *definition* to merge away
    # (rather than a declaration to keep) when it has an inline body or comes
    # from a .cpp file — otherwise a header declaration with no .cpp counterpart
    # would spuriously "merge into itself" via the other direction and vanish.
    merged = []
    for it in items:
        if it["kind"] in FUNC_KINDS:
            is_definition_side = bool(it.get("_body")) or not it["_hdr"]
            cands = [c for c in decls.get(it["qualified"], []) if c is not it and c["kind"] in FUNC_KINDS]
            if is_definition_side and cands:
                exact = [c for c in cands if norm_types(c) == norm_types(it)]
                same = [c for c in cands if len(c.get("params", [])) == len(it.get("params", []))]
                target = (exact or same or cands)[0]
                if target is not it and (target.get("members") is None):
                    merge_definition(target, it)
                    continue
        merged.append(it)
    ctx.items = items = merged

    # ---- drop undocumented items that only come from source files
    def only_doc_ok(it):
        if it["_hdr"]:
            return True
        return bool(it.get("brief") or it.get("details")) and "static" not in it.get("flags", [])
    ctx.items = items = [it for it in items if only_doc_ok(it)]

    # ---- orphan docs (@class Foo, @fn ..., @namespace ...)
    by_q = {}
    for it in walk(items):
        by_q.setdefault(it["qualified"], []).append(it)
    for o in ctx.orphans:
        d, nm = o["doc"], o["name"]
        if o["kind"] == "namespace":
            cur = ctx.ns_docs.setdefault(nm, {"brief": "", "details": ""})
            cur["brief"] = cur["brief"] or d.get("brief", "")
            cur["details"] = cur["details"] or d.get("details", "")
            continue
        target = by_q.get(nm) or next((v for k, v in by_q.items() if k.endswith("::" + nm)), None)
        if not target:
            ctx.warnings.append(f"@{o['kind']} {nm}: no matching declaration found")
            continue
        t = target[0]
        for k in DOC_COPY:
            if d.get(k) and not t.get(k):
                t[k] = d[k]
        t["_dparams"] = d.get("params", [])
        Parser.merge_params(None, t)

    # ---- exclude
    pats = cfg["exclude"]
    fpats = cfg["exclude_files"]

    def hidden(it):
        if it.get("_hidden"):
            return True
        if any(fnmatch.fnmatch(it["qualified"], p) for p in pats):
            return True
        if any(fnmatch.fnmatch(it["_file"], p) for p in fpats):
            return True
        return False

    def prune(lst):
        out = []
        for it in lst:
            if hidden(it):
                continue
            if "members" in it:
                it["members"] = prune(it["members"])
            if not cfg["include_undocumented"]:
                documented = bool(it.get("brief") or it.get("details"))
                if not documented and not it.get("members"):
                    continue
            out.append(it)
        return out
    ctx.items = prune(ctx.items)


def file_url(cfg, it):
    if cfg.get("source_url") and it.get("_file"):
        return cfg["source_url"].replace("{file}", it["_file"]).replace("{line}", str(it.get("line", 1)))
    return ""


def _serialize_param(p):
    out = {"name": p.get("name", "")}
    if p.get("type"):
        out["type"] = p["type"]
    if p.get("default"):
        out["default"] = p["default"]
    if p.get("desc"):
        out["description"] = p["desc"]
    if p.get("dir"):
        out["dir"] = p["dir"]
    return out


def _serialize_note(n):
    return {"type": NOTE_KIND_MAP.get(n["kind"], n["kind"]), "content": n["text"]}


def _serialize_base(b):
    out = {"name": b["name"], "access": b.get("access", "public")}
    if b.get("virtual"):
        out["virtual"] = True
    return out


def _serialize_enum_value(v):
    out = {"name": v["name"]}
    if v.get("value") not in (None, ""):
        out["value"] = v["value"]
    desc = md_text(v.get("brief", ""), v.get("details", ""))
    if desc:
        out["description"] = desc
    return out


def serialize_item(it, cfg, is_member):
    """Map one internal item dict onto the output shape. `is_member` decides
    function->method / variable->field, and whether "access" is emitted at all
    (namespace-scope items have no access level)."""
    kind = it["kind"]
    out = {}

    if kind in ("function", "operator"):
        out["type"] = "method" if is_member else "function"
    elif kind == "variable":
        out["type"] = "field" if is_member else "variable"
    else:
        out["type"] = kind

    out["name"] = it["name"]
    if is_member and it.get("access"):
        out["access"] = it["access"]
    if it.get("brief"):
        out["brief"] = it["brief"]
    if it.get("details"):
        out["description"] = it["details"]
    if it.get("deprecated"):
        out["deprecated"] = it["deprecated"]
    if it.get("template"):
        out["template"] = it["template"]
    if it.get("tparams"):
        out["tparams"] = [_serialize_param(p) for p in it["tparams"]]

    flags = list(it.get("flags", []))
    if kind == "enum" and "scoped" in flags:
        flags.remove("scoped")
        out["scoped"] = True
    flags = ["default" if f == "defaulted" else f for f in flags]
    if flags:
        out["flags"] = flags

    if it.get("notes"):
        out["notes"] = [_serialize_note(n) for n in it["notes"]]
    if it.get("see"):
        out["see"] = it["see"]
    if it.get("pre"):
        out["pre"] = it["pre"]
    if it.get("post"):
        out["post"] = it["post"]
    for k in ("since", "version", "author", "date"):
        if it.get(k):
            out[k] = it[k]

    if kind in ("function", "operator", "constructor", "destructor"):
        if it.get("params"):
            out["params"] = [_serialize_param(p) for p in it["params"]]
        if kind in ("function", "operator"):
            ret = {}
            if it.get("type"):
                ret["type"] = it["type"]
            if it.get("returns"):
                ret["description"] = it["returns"]
            if ret:
                out["return"] = ret
        if it.get("retvals"):
            out["retvals"] = [{"value": r["value"], "description": r.get("desc", "")} for r in it["retvals"]]
        if it.get("throws"):
            out["throws"] = [{"type": t["type"], "description": t.get("desc", "")} for t in it["throws"]]
        if it.get("requires"):
            out["requires"] = it["requires"]
        if it.get("noexcept"):
            out["noexcept"] = it["noexcept"]

    elif kind == "variable":
        if it.get("type"):
            out["field_type"] = it["type"]
        if it.get("value") not in (None, ""):
            out["value"] = it["value"]

    elif kind == "enum":
        if it.get("underlying"):
            out["underlying"] = it["underlying"]
        if it.get("values"):
            out["values"] = [_serialize_enum_value(v) for v in it["values"]]

    elif kind in ("class", "struct", "union"):
        if it.get("bases"):
            bases = [_serialize_base(b) for b in it["bases"]]
            out["bases"] = bases
            out["parent"] = bases
        if it.get("members"):
            out["content"] = [serialize_item(m, cfg, True) for m in it["members"]]

    elif kind == "alias":
        if it.get("type"):
            out["underlying"] = it["type"]
        if it.get("_style"):
            out["style"] = it["_style"]

    elif kind == "concept":
        if it.get("value"):
            out["value"] = it["value"]

    elif kind == "macro":
        if it.get("value") not in (None, ""):
            out["value"] = it["value"]
        if it.get("params"):
            out["params"] = [{"name": p["name"]} for p in it["params"]]

    # Emit embedded Markdown blocks authored with @markdown/@markdownend so
    # the viewer can render them through its Markdown pipeline.
    if it.get("markdown"):
        out["markdown"] = it["markdown"]

    if it.get("mgroup"):   # @name member-group, e.g. "Iterators" — distinct from module grouping
        out["group"] = it["mgroup"]

    src = {"file": it.get("_file", "")}
    if it.get("line"):
        src["line"] = it["line"]
    url = file_url(cfg, it)
    if url:
        src["url"] = url
    out["source"] = src

    return out


def module_key(it, cfg):
    g = it.get("group")
    mode = cfg["group_by"]
    if g and mode != "file":
        return g
    if mode == "group":
        return "other"
    if mode == "file":
        return it["_file"]
    if mode == "dir":
        parts = it["_file"].split("/")
        return parts[0] if len(parts) > 1 else "(root)"
    ns = list(it["_ns"])
    root = [x for x in cfg["root_namespace"].split("::") if x]
    if root and ns[:len(root)] == root:
        ns = ns[len(root):]
    if not ns:
        return cfg["root_namespace"] or "global"
    return ns[0]


def md_text(brief, details):
    return "\n\n".join(x for x in (brief, details) if x)


def _order_items_for_module(its):
    return sorted(its, key=lambda it: _KIND_ORDER.get(it["kind"], 1))


_MODULE_TYPE = {"namespace": "namespace", "group": "group", "file": "file", "dir": "dir"}


def _read_overview_file(path, ctx):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        ctx.warnings.append(f"overview_file: cannot read {path}: {e}")
        return None
    return parse_doc(text)


def _trim_root_ns(ns, cfg):
    root = [x for x in cfg["root_namespace"].split("::") if x]
    if root and ns[:len(root)] == root:
        return ns[len(root):]
    return ns


def _sort_content_items(items):
    def key(it):
        kind = it.get("type")
        if kind == "namespace":
            return (0, it.get("name", "").lower())
        return (1, _KIND_ORDER.get(kind, 1), it.get("name", "").lower())
    return sorted(items, key=key)


def _namespace_content_for_module(its, cfg, ctx, module_key=""):
    if cfg["group_by"] != "namespace":
        return [serialize_item(it, cfg, False) for it in _order_items_for_module(its)]

    ns_map = {}
    direct = []
    root_name = [x for x in cfg["root_namespace"].split("::") if x]
    root_last = root_name[-1] if root_name else ""

    for it in its:
        rel = _trim_root_ns(list(it.get("_ns", [])), cfg)
        item = serialize_item(it, cfg, False)
        if not rel:
            direct.append(item)
            continue

        if len(rel) == 1 and rel[0] == root_last:
            direct.append(item)
            continue

        # Strip the leading segment when it equals the module key (or root_last).
        # This prevents double-nesting: a module named "testlib" must not also
        # wrap all its items in an inner "testlib" namespace node. The strip
        # applies uniformly so that e.g. _ns=["testlib","cfg"] becomes ["cfg"]
        # instead of creating a redundant testlib→cfg chain.
        if rel and rel[0] in (module_key, root_last) and (module_key or root_last):
            rel = rel[1:]
            if not rel:
                direct.append(item)
                continue

        for i in range(1, len(rel) + 1):
            path = tuple(rel[:i])
            if path not in ns_map:
                name = path[-1]
                full = "::".join(path)
                nd = _lookup_namespace_doc(ctx, path, cfg, module_key)
                node = {"name": name, "type": "namespace", "content": []}
                if nd:
                    brief = nd.get("brief", "")
                    details = nd.get("details", "")
                    if brief:
                        node["brief"] = brief
                    if details:
                        node["description"] = details
                ns_map[path] = node

        ns_map[tuple(rel)]["content"].append(item)

    # Ensure documented namespaces that have no serializable items still
    # appear as nodes in the module tree.
    root_name = [x for x in cfg["root_namespace"].split("::") if x]
    for q in list(ctx.ns_docs.keys()):
        parts = q.split("::")
        if root_name and parts[:len(root_name)] == root_name:
            parts = parts[len(root_name):]
        if not parts:
            continue
        # Align with the same strip logic used above: if the leading
        # segment equals the module_key (or root_last) drop it for rel.
        rel_parts = parts[:]
        if rel_parts and rel_parts[0] in (module_key, root_last) and (module_key or root_last):
            rel_parts = rel_parts[1:]
            if not rel_parts:
                continue
        # offset is how many leading segments were stripped (usually 0 or 1)
        offset = len(parts) - len(rel_parts)
        for i in range(1, len(rel_parts) + 1):
            path = tuple(rel_parts[:i])
            if path not in ns_map:
                name = path[-1]
                full = "::".join(path)
                full_q = f"{cfg['root_namespace']}::{full}" if cfg.get("root_namespace") else full
                original_full = "::".join(parts[:offset + i])
                nd = (
                    ctx.ns_docs.get(original_full)
                    or ctx.ns_docs.get(full_q)
                    or ctx.ns_docs.get(full)
                    or _lookup_namespace_doc(ctx, path, cfg, module_key)
                )
                node = {"name": name, "type": "namespace", "content": []}
                if nd:
                    brief = nd.get("brief", "")
                    details = nd.get("details", "")
                    if brief:
                        node["brief"] = brief
                    if details:
                        node["description"] = details
                ns_map[path] = node

    root = []
    for path in sorted(ns_map, key=lambda p: (len(p), p)):
        node = ns_map[path]
        if len(path) == 1:
            root.append(node)
            continue
        parent = ns_map.get(path[:-1])
        if parent is not None and node not in parent["content"]:
            parent["content"].append(node)

    for node in ns_map.values():
        node["content"] = _sort_content_items(node["content"])

    return _sort_content_items(root + direct)


def assemble(ctx, cfg, project_name, cfg_dir=None):
    buckets = {}
    for it in ctx.items:
        buckets.setdefault(module_key(it, cfg), []).append(it)

    # Ensure top-level namespaces that only have doc comments still
    # produce an (empty) module so their brief/description render.
    root_ns = cfg.get("root_namespace", "") or ""

    for q in list(ctx.ns_docs.keys()):
        parts = q.split("::")
        root = [x for x in root_ns.split("::") if x]
        if root and parts[:len(root)] == root:
            parts = parts[len(root):]
        if parts:
            buckets.setdefault(parts[0], [])
            
    mtype = _MODULE_TYPE.get(cfg["group_by"], "namespace")
    mods = []
    root_ns = cfg["root_namespace"]
    for key, its in buckets.items():
        mc = cfg["modules"].get(key, {})
        name = mc.get("name", key)
        brief, description = "", ""
        if key in ctx.groups:
            g = ctx.groups[key]
            name = mc.get("name") or g.get("title") or key
            brief = g.get("brief", "")
            description = g.get("details", "")
        else:
            q = f"{root_ns}::{key}" if root_ns else key
            nd = ctx.ns_docs.get(q) or ctx.ns_docs.get(key)
            if nd and cfg["group_by"] == "namespace":
                brief = nd.get("brief", "")
                description = nd.get("details", "")
        if mc.get("brief"):
            brief = mc["brief"]
        if mc.get("description"):
            description = mc["description"]

        content = _namespace_content_for_module(its, cfg, ctx, module_key=key)
        mod_type = "group" if key in ctx.groups else mtype
        mod = {"name": name, "type": mc.get("type", mod_type)}
        if brief:
            mod["brief"] = brief
        if description:
            mod["description"] = description
        mod["content"] = content
        mod["_order"] = mc.get("order")
        mods.append(mod)

    order = cfg["module_order"]

    def sort_key(m):
        if m["name"] in order:
            return (0, order.index(m["name"]), "")
        if m.get("_order") is not None:
            return (1, m["_order"], m["name"].lower())
        return (2, 0, m["name"].lower())
    mods.sort(key=sort_key)
    for m in mods:
        m.pop("_order", None)

    # ---- overview: an explicit --overview file wins; otherwise fall back to
    # a source @mainpage comment; otherwise warn, the way Doxygen flags a
    # handful of structural omissions (missing \brief, undocumented members, ...).
    overview_doc = None
    if cfg.get("overview_file"):
        overview_doc = _read_overview_file(cfg["overview_file"], ctx)
    if overview_doc is None and ctx.mainpage:
        overview_doc = {"brief": ctx.mainpage.get("brief", ""), "details": ctx.mainpage.get("details", ""),
                        "notes": []}
    overview = []
    if overview_doc:
        # Emit brief and details as "markdown" so the viewer runs them through
        # its Markdown pipeline instead of plain-text escaping them.
        if overview_doc.get("brief"):
            overview.append({"type": "markdown", "text": overview_doc["brief"]})
        if overview_doc.get("details"):
            overview.append({"type": "markdown", "text": overview_doc["details"]})
        for n in overview_doc.get("notes") or []:
            overview.append({"type": "note", "kind": NOTE_KIND_MAP.get(n["kind"], n["kind"]), "text": n["text"]})
    else:
        ctx.warnings.append(
            "no overview: no @mainpage comment found in source and no --overview file given — "
            "the overview page will be empty. Add a /** @mainpage ... */ comment, or pass "
            "--overview path/to/file.txt")

    metadata = dict(cfg["project"])
    metadata.setdefault("name", project_name)
    # Expose configured highlight.js theme to the viewer; default to
    # atom-one-dark when unset.
    metadata.setdefault("hjs_code_theme", cfg.get("hjs_code_theme", "atom-one-dark"))
    if "description" not in metadata and overview_doc:
        d = md_text(overview_doc.get("brief", ""), overview_doc.get("details", ""))
        if d:
            metadata["description"] = d
    # Forward source_base so the viewer can build file links without per-item url templates.
    if cfg.get("source_base") and "source_base" not in metadata:
        metadata["source_base"] = cfg["source_base"]

    # Process nav entries: markdown type → read file and embed content.
    nav_entries = metadata.get("nav", [])
    if nav_entries and cfg_dir is not None:
        processed_nav = []
        base = Path(cfg_dir)
        for entry in nav_entries:
            e = dict(entry)  # don't mutate the original cfg
            nav_type = e.get("type", "external").lower()
            e["type"] = nav_type
            if nav_type == "markdown" and e.get("url"):
                md_path = (base / e["url"]).resolve()
                try:
                    e["content"] = md_path.read_text(encoding="utf-8")
                except OSError as err:
                    ctx.warnings.append(
                        f"nav item '{e.get('label', e['url'])}': cannot read {md_path}: {err}"
                    )
                    e["content"] = ""
            processed_nav.append(e)
        metadata["nav"] = processed_nav

    doc = {
        "metadata": metadata,
        "overview": overview,
        "modules": mods,
    }

    # module-level overrides, keyed by the module's final "name"
    ov = cfg.get("overrides", {})
    if ov:
        for m in doc["modules"]:
            if m["name"] in ov:
                m.update(ov[m["name"]])
    return doc


def _lookup_namespace_doc(ctx, path, cfg, module_key=""):
    """Resolve namespace docs for both fully-qualified and stripped paths."""
    parts = list(path)
    if not parts:
        return None
    root = [x for x in (cfg.get("root_namespace") or "").split("::") if x]
    candidates = []
    for prefix in ([], root):
        if prefix:
            candidates.append("::".join(prefix + parts))
        for i in range(1, len(parts) + 1):
            candidates.append("::".join(prefix + parts[:i]))
    if module_key:
        candidates.extend(["::".join([module_key] + parts), "::".join([module_key] + parts[:1])])
    for key in candidates:
        if key in ctx.ns_docs:
            return ctx.ns_docs[key]
    return None
