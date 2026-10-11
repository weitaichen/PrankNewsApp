"""Exercise the spec's file selection without importing PyInstaller."""

import ast
from pathlib import Path

from prank_news.builder import REQUIRED_TEMPLATE_FILES, default_template_dir


def test_spec_includes_required_real_template_files():
    template = default_template_dir()
    tree = ast.parse((Path(__file__).parents[1] / "prank_news.spec").read_text(encoding="utf-8"))
    loop = next(node for node in tree.body if isinstance(node, ast.For))
    namespace = {"Path": Path, "template_dir": template, "template_data": []}
    exec(compile(ast.Module(body=[loop], type_ignores=[]), "spec-selection", "exec"), namespace)
    packaged = {
        (Path(source).relative_to(template).as_posix(), target)
        for source, target in namespace["template_data"]
    }
    for name in REQUIRED_TEMPLATE_FILES:
        assert (name, "pwa_template") in packaged
    assert all("tests" not in Path(name).parts and "README.md" not in Path(name).parts
               for name, target in packaged)



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
