"""资料解析：PDF/PPTX/DOCX/MD/TXT/HTML → 纯文本 → 分块（RAG 降维替代）。

不引入向量嵌入；文本分块写 SQLite chunks，供 keyword 检索。
"""
import contextlib
import io
import re
from html.parser import HTMLParser

CHUNK_SIZE = 500
CHUNK_OVERLAP = 80

# 支持的文件类型 → 解析函数名（html/htm 2026-09-22 起支持：课件里存在
# HTML 导出的演示稿，如 第15章「VibeCoding到AICoding-PPT…html」、第16章「DeepSeek-Harness.html」）
SUPPORTED = {"pdf", "pptx", "docx", "md", "txt", "markdown", "html", "htm"}


def extract_text(filename: str, blob: bytes) -> str:
    """按扩展名分发解析，返回纯文本（失败抛异常，由调用方兜底）。"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("md", "markdown", "txt"):
        return _decode(blob)
    if ext == "pdf":
        return _extract_pdf(blob)
    if ext == "pptx":
        return _extract_pptx(blob)
    if ext == "docx":
        return _extract_docx(blob)
    if ext in ("html", "htm"):
        return _extract_html(blob)
    raise ValueError(f"不支持的文件类型: {ext}")



def _decode(blob: bytes) -> str:
    for enc in ("utf-8", "gb18030", "latin-1"):
        try:
            return blob.decode(enc)
        except UnicodeDecodeError:
            continue
    return blob.decode("utf-8", errors="ignore")


def _extract_pdf(blob: bytes) -> str:
    import pdfplumber

    parts = []
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            if txt:
                parts.append(txt)
    return "\n".join(parts)


def _extract_pptx(blob: bytes) -> str:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(blob))
    parts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.text:
                parts.append(shape.text)
    return "\n".join(parts)


def _extract_docx(blob: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(blob))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(parts)


# HTML 解析：只要可见文本。脚本/样式/矢量图整段丢，块级标签当换行
_SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe", "template", "canvas"}
_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "h1", "h2", "h3",
    "h4", "h5", "h6", "section", "article", "header", "footer", "blockquote", "pre",
    "figure", "figcaption", "main", "nav", "aside", "hr", "title",
}


class _HtmlText(HTMLParser):
    """把 HTML 转成「块级标签分隔的纯文本」（convert_charrefs 已解实体）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            # \xa0（&nbsp;）等 Unicode 空白归一成普通空格，保证 keyword 检索能命中
            text = re.sub(r"\s+", " ", data.replace("\xa0", " ")).strip()
            if text:
                self.parts.append(text + " ")


def _extract_html(blob: bytes) -> str:
    """HTML 演示稿/文档 → 纯文本（slide 文本可被 keyword 检索命中）。"""
    p = _HtmlText()
    with contextlib.suppress(Exception):  # 容错：畸形 HTML 不阻断入库
        p.feed(_decode(blob))
        p.close()
    lines, blank = [], False
    for raw in "".join(p.parts).splitlines():
        line = raw.strip()
        if line:
            lines.append(line)
            blank = False
        elif not blank:
            lines.append("")
            blank = True
    return "\n".join(lines).strip()


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """按近似字符数滑窗分块（按段落优先，落到近似 size）。"""
    text = (text or "").strip()
    if not text:
        return []
    # 以换行/句号切粗块，避免从句子中间硬切
    paragraphs = [p.strip() for p in text.replace("\r", "\n").split("\n")]
    flat = "\n".join(p for p in paragraphs if p)
    if not flat:
        return []
    chunks = []
    start = 0
    n = len(flat)
    while start < n:
        end = min(start + size, n)
        if end < n:
            # 尽量退到最近的换行，避免截断句子
            nl = flat.rfind("\n", start, end)
            if nl > start + size // 2:
                end = nl + 1
        chunks.append(flat[start:end].strip())
        if end >= n:
            break
        start = max(start + size - overlap, end - overlap)
    return [c for c in chunks if c]


def chunk_text_list(text: str) -> list[dict]:
    """分块并带 chunk_idx（入库用）。"""
    return [{"chunk_idx": i, "text": c} for i, c in enumerate(chunk_text(text))]
