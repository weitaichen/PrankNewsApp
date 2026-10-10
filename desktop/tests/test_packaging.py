"""Exercise the spec's file selection without importing PyInstaller."""

import ast
from pathlib import Path


def test_spec_excludes_vercel_and_node_modules(tmp_path):
    template = tmp_path / "pwa_template"
    template.mkdir()
    for directory in (".vercel", "node_modules", "tests", "assets"):
        (template / directory).mkdir()
        (template / directory / "file.js").write_text("test")
    (template / "index.html").write_text("page")
    tree = ast.parse((Path(__file__).parents[1] / "prank_news.spec").read_text(encoding="utf-8"))
    loop = next(node for node in tree.body if isinstance(node, ast.For))
    namespace = {"Path": Path, "template_dir": template, "template_data": []}
    exec(compile(ast.Module(body=[loop], type_ignores=[]), "spec-selection", "exec"), namespace)
    assert {Path(source).relative_to(template).as_posix() for source, target in namespace["template_data"]} == {
        "index.html", "assets/file.js",
    }
