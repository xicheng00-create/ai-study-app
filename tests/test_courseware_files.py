"""材料文件发现规则（scripts/courseware_files.py）。

覆盖：子目录递归深度 2 / 资源包整棵跳过（package.json、node_modules、文件数超阈值）
/ 隐藏项与 _ocr 跳过 / 类型白名单 / 字节级重复副本去重 / 课件.md 本身不入材料列表。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import courseware_files as cf  # noqa: E402


def _w(p, text="内容"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def test_recursive_depth_and_filters(tmp_path):
    m = tmp_path / "材料"
    _w(str(m / "a.md"), "a")
    _w(str(m / "图.png"))                      # 类型不支持
    _w(str(m / ".隐藏.md"))                     # 隐藏项
    _w(str(m / "旧_extracted.txt"))             # 预抽取副本
    _w(str(m / "_ocr" / "a.md.ocr.txt"))        # OCR 缓存目录
    _w(str(m / "课件.md"))                      # 教案本体不算材料
    _w(str(m / "设计文档" / "b.md"), "b")             # 深度 1
    _w(str(m / "设计文档" / "细" / "c.pdf"), "c")      # 深度 2
    _w(str(m / "设计文档" / "细" / "更细" / "d.md"), "d")  # 深度 3 → 不取

    got = {p.name for p in cf.iter_material_files(m)}
    assert got == {"a.md", "b.md", "c.pdf"}


def test_bundle_dirs_are_skipped(tmp_path):
    m = tmp_path / "材料"
    _w(str(m / "正常.md"))
    # 含 package.json
    _w(str(m / "前端包" / "package.json"), "{}")
    _w(str(m / "前端包" / "index.md"))
    # 含 node_modules（package.json 在内层，只判直接子项会漏）
    _w(str(m / "演示" / "deck" / "package.json"), "{}")
    _w(str(m / "演示" / "deck" / "node_modules" / "x" / "readme.md"), "x")
    _w(str(m / "演示" / "deck" / "index.html"), "<h1>slide</h1>")
    # 文件数超阈值
    for i in range(cf.BUNDLE_FILE_LIMIT + 5):
        _w(str(m / "大目录" / f"f{i}.md"))

    got = {p.name for p in cf.iter_material_files(m)}
    assert got == {"正常.md"}


def test_identical_duplicates_are_deduped(tmp_path, capsys):
    m = tmp_path / "材料"
    _w(str(m / "课程讲义.pdf"), "same-bytes")
    _w(str(m / "课程讲义 (1).pdf"), "same-bytes")   # 字节相同 → 只留一份
    _w(str(m / "课程讲义 (2).pdf"), "different")     # 近似但不同 → 保留

    got = [p.name for p in cf.iter_material_files(m)]
    # 重复副本保留「原名那份」（不带 (1) 后缀），近似但内容不同的保留
    assert got == ["课程讲义 (2).pdf", "课程讲义.pdf"]
    assert "skip-dup" in capsys.readouterr().out


def test_missing_dir_returns_empty(tmp_path):
    assert cf.iter_material_files(tmp_path / "不存在") == []


@pytest.mark.parametrize("name,expected", [
    ("deck.html", True), ("deck.htm", True), ("deck.md", True),
    ("deck.css", False), ("deck.js", False), ("deck.png", False),
])
def test_supported_types(tmp_path, name, expected):
    m = tmp_path / "材料"
    _w(str(m / name))
    assert bool(cf.iter_material_files(m)) is expected
