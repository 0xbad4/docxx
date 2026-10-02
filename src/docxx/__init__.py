"""docxx — Doxygen-style C/C++ comments -> a JSON document for your own viewer.

Library use:

    import docxx
    cfg = dict(docxx.DEFAULT_CONFIG, project={"name": "mylib"})
    doc = docxx.generate(["include/"], cfg)   # -> dict, json.dumps it yourself

CLI use: `docxx include/` (see `docxx --help`).
"""
from .config import DEFAULT_CONFIG
from .generator import build, collect_files, generate

__version__ = "0.1.0"

__all__ = ["DEFAULT_CONFIG", "generate", "build", "collect_files", "__version__"]
