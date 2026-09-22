"""HTML 资料解析（2026-09-22 新增：课件里存在 HTML 导出的演示稿）。

覆盖：可见文本保留 / script-style 丢弃 / 实体解码 / 块级标签换行 / SUPPORTED 收录。
"""
from ai import parser


HTML = """<!DOCTYPE html>
<html><head><title>DeepSeek Harness 拆解课</title>
<style>.a{color:red}</style><script>var x = "不该出现的脚本文本";</script></head>
<body>
  <h1>进门四问</h1>
  <p>装完 dsh，先关注这四件事。</p>
  <ul><li>权限</li><li>成本 &amp; 留痕</li></ul>
  <div>失败&nbsp;处理</div>
  <noscript>无脚本提示</noscript>
  <svg><text>矢量图文字</text></svg>
</body></html>"""


def test_supported_includes_html():
    assert "html" in parser.SUPPORTED
    assert "htm" in parser.SUPPORTED


def test_extract_html_keeps_visible_text_drops_scripts():
    text = parser.extract_text("deck.html", HTML.encode("utf-8"))
    for expected in ("DeepSeek Harness 拆解课", "进门四问", "装完 dsh，先关注这四件事。", "权限", "成本 & 留痕"):
        assert expected in text
    for forbidden in ("不该出现的脚本文本", "color:red", "无脚本提示", "矢量图文字"):
        assert forbidden not in text


def test_extract_html_decodes_entities_and_keeps_blocks_separate():
    text = parser.extract_text("d.htm", HTML.encode("utf-8"))
    assert "失败 处理" in text.replace("&nbsp;", " ")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert "进门四问" in lines
    assert lines.index("进门四问") < lines.index("权限")  # 块级标签产生换行，顺序保持


def test_extract_html_tolerates_broken_markup():
    text = parser.extract_text("bad.html", "<div>未闭合<b>标签 文本".encode("utf-8"))
    assert "未闭合" in text and "文本" in text


def test_extract_html_empty_input():
    assert parser.extract_text("empty.html", b"") == ""
