"""Basic regression tests. Run with: pytest

These exercise the fixture library under examples/testlib/ - chosen because it
deliberately covers templates, operators, out-of-line .cpp definitions,
function-pointer typedefs, groups, and multi-level inheritance, so a passing
run here is a meaningful signal, not just "it didn't crash".
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "examples" / "testlib"

sys.path.insert(0, str(REPO / "src"))
import docxx  # noqa: E402


def _load_fixture_config():
    with open(FIXTURE / "docs.config.json", encoding="utf-8") as fh:
        return json.load(fh)


def _walk(items):
    for it in items:
        yield it
        yield from _walk(it.get("content", []))


def _by_name(doc):
    """First match wins; fine for these tests since fixture names don't collide."""
    out = {}
    for mod in doc["modules"]:
        for it in _walk(mod["content"]):
            out.setdefault(it["name"], it)
    return out


@pytest.fixture(scope="module")
def doc():
    cfg = dict(docxx.DEFAULT_CONFIG, **_load_fixture_config())
    return docxx.generate(["include", "src"], cfg, root=FIXTURE)


def test_shape(doc):
    assert set(doc.keys()) == {"metadata", "overview", "modules"}
    assert "generated" not in doc
    assert "schema" not in doc
    assert len(doc["modules"]) >= 3
    assert doc["metadata"]["name"] == "testlib"
    for m in doc["modules"]:
        assert set(m.keys()) >= {"name", "type", "content"}
        assert m["type"] in ("namespace", "group", "file", "dir")


def test_no_id_or_sig_fields(doc):
    # the new schema deliberately carries no id/qualified/sig - the viewer
    # derives anchors and formats signatures itself.
    for it in _walk([b for m in doc["modules"] for b in m["content"]]):
        assert "id" not in it
        assert "qualified" not in it
        assert "sig" not in it


def test_expected_symbols_present(doc):
    names = _by_name(doc)
    for expected in ("Widget", "render", "FixedStack", "Container", "ScrollView",
                      "error_type", "run", "frame_callback_t", "load"):
        assert expected in names, f"missing {expected}"


def test_method_vs_function_split(doc):
    names = _by_name(doc)
    assert names["render"]["type"] == "method"     # Widget::render -> member
    assert names["run"]["type"] == "function"       # free function
    assert names["verbose"]["type"] == "variable"    # free variable (testlib::cfg::verbose)
    vec2 = names["Vec2"]
    field_names = {m["name"]: m["type"] for m in vec2["content"]}
    assert field_names.get("x") == "field"           # class member -> field, not variable


def test_return_shape(doc):
    names = _by_name(doc)
    render = names["render"]
    assert render["return"] == {"type": "int", "description": "number of bytes written, or -1 on error"}
    widget = names["Widget"]
    constructor = next(m for m in widget["content"] if m["type"] == "constructor")
    assert "return" not in constructor


def test_function_pointer_typedef_underlying(doc):
    it = _by_name(doc)["frame_callback_t"]
    assert it["type"] == "alias"
    assert it["style"] == "using" or "underlying" in it


def test_header_and_source_definitions_are_merged(doc):
    # Widget::render is declared in core.h and defined (with extra @param text) in core.cpp;
    # postprocess() should merge them into one entry, not two.
    count = sum(1 for it in _walk([b for m in doc["modules"] for b in m["content"]]) if it["name"] == "render")
    assert count == 1


def test_free_function_survives_merge_with_cpp_definition(doc):
    # regression test for a real bug: run() has both a header declaration and a
    # .cpp definition; a tautological condition used to make both sides merge
    # into each other and vanish entirely.
    names = _by_name(doc)
    assert "run" in names
    assert names["run"].get("brief")


def test_inheritance_bases_and_parent(doc):
    names = _by_name(doc)
    container = names["Container"]
    assert container["bases"] == [{"name": "Widget", "access": "public"}]
    assert container["parent"] == container["bases"]
    assert names["ScrollView"]["bases"][0]["name"] == "Container"


def test_operators_are_method_or_function_not_their_own_type(doc):
    # regression test for a real bug: "operator" is a distinct internal kind
    # from "function"/"variable", and was falling through to a literal
    # type:"operator" with params/return silently dropped entirely.
    names = _by_name(doc)
    op = names["operator+"]
    assert op["type"] == "method"          # Vec2::operator+ is a class member
    assert op["params"][0]["type"] == "const Vec2&"
    assert op["return"] == {"type": "Vec2"}
    conv = names["operator bool"]
    assert conv["type"] == "method"
    assert conv["return"] == {"type": "bool"}


def test_destructor_shape(doc):
    d = _by_name(doc)["~Widget"]
    assert d["type"] == "destructor"
    assert d["access"] == "public"
    assert d["description"]
    assert d["notes"][0]["type"] == "info"
    assert "params" not in d
    assert "return" not in d


def test_field_flags_and_value(doc):
    f = _by_name(doc)["render_calls"]
    assert f["type"] == "field"
    assert f["flags"] == ["mutable"]
    assert f["field_type"] == "int"
    assert f["value"] == "0"


def test_method_with_description_and_notes(doc):
    render = _by_name(doc)["render"]
    assert render["description"]
    assert render["notes"][0]["type"] == "info"
    assert render["params"] and render["return"]


def test_internal_namespace_excluded(doc):
    names = _by_name(doc)
    assert "secret_helper" not in names


def test_enum_values(doc):
    et = _by_name(doc)["error_type"]
    assert et["type"] == "enum"
    assert et["scoped"] is True
    assert et["underlying"] == "uint8_t"
    values = {v["name"]: v for v in et["values"]}
    assert values["NONE"]["value"] == "0"
    assert values["NONE"]["description"] == "No error."


def test_macro_shape(doc):
    m = _by_name(doc)["TESTLIB_MAX_WIDGETS"]
    assert m["type"] == "macro"
    assert "value" in m


def test_group_module_typed_as_group_not_namespace(doc):
    # Math helpers comes from an explicit @defgroup, and should be tagged
    # "group" even though the overall group_by mode is "namespace".
    math = next(m for m in doc["modules"] if m["name"] == "Math helpers")
    assert math["type"] == "group"


def test_notes_renamed(doc):
    widget = _by_name(doc)["Widget"]
    assert widget["notes"][0]["type"] == "info"
    assert "content" in widget["notes"][0]


def test_overview_file_overrides_source_mainpage(tmp_path):
    overview = tmp_path / "overview.txt"
    overview.write_text("@brief custom overview.\n\nBody text here.\n\n@note a note.\n", encoding="utf-8")
    cfg = dict(docxx.DEFAULT_CONFIG, **_load_fixture_config())
    cfg["overview_file"] = str(overview)
    doc = docxx.generate(["include", "src"], cfg, root=FIXTURE)
    texts = [b["text"] for b in doc["overview"] if b["type"] == "text"]
    assert any("custom overview" in t for t in texts)
    notes = [b for b in doc["overview"] if b["type"] == "note"]
    assert notes and notes[0]["kind"] == "info"


def test_missing_overview_warning(tmp_path):
    from docxx.generator import build, collect_files
    from docxx.postprocess import assemble, postprocess
    cfg = dict(docxx.DEFAULT_CONFIG, project={"name": "core-only"}, patterns=["core.h"],
               root_namespace="testlib")
    files = collect_files([str(FIXTURE / "include" / "testlib" / "core.h")], cfg["patterns"], [], FIXTURE)
    ctx = build(files, cfg, FIXTURE)
    postprocess(ctx, cfg)
    assemble(ctx, cfg, "core-only")
    assert any("no overview" in w for w in ctx.warnings)


def test_cli_directory_mode_writes_json_and_warns_on_missing_viewer(tmp_path):
    out_dir = tmp_path / "docs"
    result = subprocess.run(
        [sys.executable, "-m", "docxx",
         str(FIXTURE / "include"), str(FIXTURE / "src"),
         "-c", str(FIXTURE / "docs.config.json"),
         "-o", str(out_dir), "--root", str(FIXTURE)],
        cwd=REPO, env={"PYTHONPATH": str(REPO / "src")},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (out_dir / "docs.json").exists()
    data = json.loads((out_dir / "docs.json").read_text(encoding="utf-8"))
    assert data["modules"]
    # viewer files aren't in this package yet (see src/docxx/viewer/README.md);
    # the CLI should warn, not fail.
    assert "viewer/index.html not found" in result.stderr


def test_cli_json_only_mode(tmp_path):
    out_file = tmp_path / "out.json"
    result = subprocess.run(
        [sys.executable, "-m", "docxx",
         str(FIXTURE / "include"), str(FIXTURE / "src"),
         "-c", str(FIXTURE / "docs.config.json"),
         "-o", str(out_file), "--root", str(FIXTURE)],
        cwd=REPO, env={"PYTHONPATH": str(REPO / "src")},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["modules"]


def test_cli_overview_flag(tmp_path):
    overview = tmp_path / "overview.txt"
    overview.write_text("@brief from the CLI flag.\n", encoding="utf-8")
    out_file = tmp_path / "out.json"
    result = subprocess.run(
        [sys.executable, "-m", "docxx",
         str(FIXTURE / "include"), str(FIXTURE / "src"),
         "-c", str(FIXTURE / "docs.config.json"), "--overview", str(overview),
         "-o", str(out_file), "--root", str(FIXTURE)],
        cwd=REPO, env={"PYTHONPATH": str(REPO / "src")},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert any("from the CLI flag" in b.get("text", "") for b in data["overview"])


def test_namespace_content_is_nested(doc):
    cfg = dict(docxx.DEFAULT_CONFIG, **_load_fixture_config())
    doc = docxx.generate(["include", "src"], cfg, root=FIXTURE)
    mod = next(m for m in doc["modules"] if m["name"] == "cfg")
    assert mod["content"][0]["type"] == "namespace"
    assert mod["content"][0]["name"] == "cfg"
    assert any(item["name"] == "load" for item in mod["content"][0]["content"])


def test_documented_inner_namespace_survives_in_json(tmp_path):
    src = tmp_path / "nested.hpp"
    src.write_text('''
/**
 * @brief Utility helpers used throughout the library.
 */
namespace lynx::utils {
    /**
     * @brief Status-to-string conversion helpers.
     */
    namespace err {
        int x = 0;
    }
}
''', encoding="utf-8")

    doc = docxx.generate([str(src)], dict(docxx.DEFAULT_CONFIG), root=tmp_path)
    mod = next(m for m in doc["modules"] if m["name"] == "lynx")
    utils = next(n for n in mod["content"] if n["name"] == "utils")
    err = next(n for n in utils["content"] if n["name"] == "err")
    assert utils["brief"] == "Utility helpers used throughout the library."
    assert err["brief"] == "Status-to-string conversion helpers."
    assert any(item["name"] == "x" for item in err["content"])
