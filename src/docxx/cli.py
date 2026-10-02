"""Command-line interface: `docxx` / `python -m docxx`.

Writes docs.json into an output directory, and copies whatever of
index.html/styles.css/app.js it finds in the packaged viewer/ folder
alongside it — see src/docxx/viewer/README.md. A missing viewer file is a
warning, not an error, so this stays usable for generating just docs.json
while the viewer is developed separately.
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG
from .generator import build, collect_files
from .postprocess import assemble, postprocess, walk

VIEWER_DIR = Path(__file__).resolve().parent / "viewer"
VIEWER_FILES = ("index.html", "styles.css", "app.js")


def _load_config(config_path):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg_dir = Path.cwd()
    if config_path:
        cp = Path(config_path)
        cfg_dir = cp.resolve().parent
        with open(cp, encoding="utf-8") as fh:
            user = json.load(fh)
        for k, v in user.items():
            cfg[k] = v
    return cfg, cfg_dir


def build_parser():
    ap = argparse.ArgumentParser(
        prog="docxx",
        description="Doxygen-style C/C++ comments -> docs.json, plus your viewer copied alongside it. "
                     "No config needed to try it: `docxx include/`.")
    ap.add_argument("inputs", nargs="*", help="files or directories (recursive)")
    ap.add_argument("-p", "--patterns", help='file patterns, e.g. "*.h;*.cpp"')
    ap.add_argument("-c", "--config", help="docs.config.json")
    ap.add_argument("-o", "--out", default="docs",
                     help="output directory (default: docs/); a path ending .json writes just the data file")
    ap.add_argument("--overview", help="path to a text file of Doxygen-style content (@brief, @note, ...) "
                                        "for the overview page; overrides any @mainpage found in source")
    ap.add_argument("--root", help="paths in the output are relative to this dir (default: cwd)")
    ap.add_argument("--name", help="project name")
    ap.add_argument("--version", help="project version")
    ap.add_argument("--access", help="comma list: public,protected,private")
    ap.add_argument("--group-by", choices=["namespace", "group", "file", "dir"])
    ap.add_argument("--root-namespace", help="namespace stripped when choosing modules")
    ap.add_argument("--dump-tokens", action="store_true", help="debug: print tokens of the first file")
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument("--version-info", action="version", version=_version_string())
    return ap


def _version_string():
    from . import __version__
    return f"docxx {__version__}"


def _copy_viewer(out_dir, quiet, warnings):
    copied = []
    for name in VIEWER_FILES:
        src = VIEWER_DIR / name
        if src.exists():
            shutil.copyfile(src, out_dir / name)
            copied.append(name)
        else:
            warnings.append(f"viewer/{name} not found in the package.")
    return copied


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)

    cfg, cfg_dir = _load_config(a.config)
    if a.patterns:
        cfg["patterns"] = [a.patterns]
    if a.access:
        cfg["access"] = [x.strip() for x in a.access.split(",") if x.strip()]
    if a.group_by:
        cfg["group_by"] = a.group_by
    if a.root_namespace is not None:
        cfg["root_namespace"] = a.root_namespace
    if a.name:
        cfg["project"]["name"] = a.name
    if a.version:
        cfg["project"]["version"] = a.version
    if a.overview:
        cfg["overview_file"] = a.overview

    inputs = a.inputs or [str((cfg_dir / p)) for p in cfg["input"]]
    if not inputs:
        ap.error('no inputs (pass paths, e.g. "docxx include/", or set "input" in the config)')
    root = Path(a.root).resolve() if a.root else Path.cwd().resolve()
    files = collect_files(inputs, cfg["patterns"], cfg["exclude_files"], root)
    if not files:
        print("no files matched", file=sys.stderr)
        return 1
    if a.dump_tokens:
        from .tokenizer import tokenize
        for tk in tokenize(Path(files[0]).read_text(encoding="utf-8", errors="replace")):
            print(tk)
        return 0

    ctx = build(files, cfg, root)
    postprocess(ctx, cfg)
    name = cfg["project"].get("name") or (Path(inputs[0]).resolve().name if inputs else "docs")
    doc = assemble(ctx, cfg, name, cfg_dir=cfg_dir)

    out = Path(a.out)
    warnings = list(ctx.warnings)
    if out.suffix.lower() == ".json":
        out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        wrote = [out]
    else:
        out.mkdir(parents=True, exist_ok=True)
        json_path = out / "docs.json"
        json_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        wrote = [json_path] + [out / n for n in _copy_viewer(out, a.quiet, warnings)]

    if not a.quiet:
        n_items = sum(1 for _ in walk(ctx.items))
        names = ", ".join(str(w) for w in wrote)
        print(f"{len(files)} files, {n_items} items, {len(doc['modules'])} modules -> {names}", file=sys.stderr)
        if out.suffix.lower() != ".json" and (out / "index.html").exists():
            print(f"serve it locally, e.g.: python -m http.server -d {out}", file=sys.stderr)
        for w in warnings:
            print("warning:", w, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
