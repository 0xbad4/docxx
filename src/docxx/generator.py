"""File discovery and the parse orchestration loop (files -> Ctx), plus a small
library-friendly generate() that runs the whole pipeline in one call."""
from __future__ import annotations

import fnmatch
import os
import re
import sys
from pathlib import Path

from .cpp_parser import Ctx, Parser
from .postprocess import assemble, postprocess
from .tokenizer import tokenize

def collect_files(inputs, patterns, exclude_files, root):
    files = []
    pats = [p for p in re.split(r"[;,]", ";".join(patterns) if isinstance(patterns, list) else patterns) if p]
    skip_dirs = {".git", "node_modules", "__pycache__", ".svn", ".hg"}
    for inp in inputs:
        p = Path(inp)
        if p.is_file():
            files.append(str(p))
        elif p.is_dir():
            for dp, dn, fn in os.walk(p):
                dn[:] = sorted(d for d in dn if d not in skip_dirs)
                for f in sorted(fn):
                    if any(fnmatch.fnmatch(f, pt) for pt in pats):
                        full = os.path.join(dp, f)
                        rel = os.path.relpath(full, root).replace(os.sep, "/")
                        if not any(fnmatch.fnmatch(rel, ex) for ex in exclude_files):
                            files.append(full)
        else:
            print(f"warning: {inp} does not exist", file=sys.stderr)
    seen, out = set(), []
    for f in sorted(files):
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out

def build(files, cfg, root):
    ctx = Ctx()
    for path in files:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            ctx.warnings.append(f"cannot read {path}: {e}")
            continue
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        is_hdr = Path(path).suffix.lower() in cfg["header_exts"]
        p = Parser(tokenize(text), rel, is_hdr, cfg, ctx)
        while p.i < len(p.t):
            before = p.i
            p.parse_scope(None, [], "public", None)
            if p.i == before:
                p.i += 1
    return ctx


def generate(inputs, cfg, root=None, project_name=None, cfg_dir=None):
    """Run the full pipeline (parse -> postprocess -> assemble) and return the
    output document as a plain dict. Convenience entry point for using docxx
    as a library instead of the CLI.

        import docxx
        cfg = dict(docxx.DEFAULT_CONFIG, **{"project": {"name": "mylib"}})
        doc = docxx.generate(["include/"], cfg)
    """
    root = Path(root).resolve() if root else Path.cwd().resolve()
    resolved_inputs = [str(root / p) if not Path(p).is_absolute() else p for p in inputs]
    files = collect_files(resolved_inputs, cfg.get("patterns", []), cfg.get("exclude_files", []), root)
    if not files:
        raise FileNotFoundError("no input files matched the given patterns")
    ctx = build(files, cfg, root)
    postprocess(ctx, cfg)
    name = project_name or cfg.get("project", {}).get("name") or Path(inputs[0]).resolve().name
    return assemble(ctx, cfg, name, cfg_dir=cfg_dir)
