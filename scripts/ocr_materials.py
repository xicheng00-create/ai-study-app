#!/usr/bin/env python3
"""课件素材文本获取：图片型 PDF/PPTX 走 macOS Vision OCR，其余用原生解析。

图片型幻灯片的原生文本极少（12.6MB 的 PDF 只能抽出 1.7K 字），
直接入库会造成「AI 对话切片对不上课件原内容」。本模块为这类文件生成
`材料/_ocr/<文件名>.ocr.txt` 缓存，供切片使用；原始文件仍作为可下载资料。

对外接口：best_text(path) -> str
"""
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from ai import parser  # noqa: E402

OCR_BIN = Path("/tmp/ocrbin3")
# 原生文本低于此字数视为「图片型」，需要 OCR 补齐
NATIVE_MIN_CHARS = 4000
OCR_DIRNAME = "_ocr"


def _ensure_bin() -> Path:
    """OCR 二进制缺失时现场编译（源码随仓库走，机器无关）。"""
    if OCR_BIN.is_file():
        return OCR_BIN
    src = Path(__file__).resolve().parent / "ocr.swift"
    out = Path("/tmp/ocrbin3")
    subprocess.run(["swiftc", "-O", "-o", str(out), str(src)], check=True)
    return out


def _pptx_slide_images(path: Path, tmp: Path) -> list[Path]:
    """按幻灯片顺序取出 PPTX 里的图片（ppt/slides/_rels 精确映射）。"""
    imgs: list[Path] = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        slides = sorted(
            (n for n in names if n.startswith("ppt/slides/slide") and n.endswith(".xml")),
            key=lambda n: int("".join(c for c in Path(n).stem if c.isdigit()) or 0),
        )
        for rel in [n.replace("ppt/slides/", "ppt/slides/_rels/") + ".rels" for n in slides]:
            if rel not in names:
                continue
            xml = z.read(rel).decode("utf-8", "ignore")
            for target in [t for t in xml.split('Target="')[1:]]:
                t = target.split('"')[0]
                if not t.lower().endswith((".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif")):
                    continue
                media = "ppt/" + t.replace("../", "").lstrip("/")
                if media not in names:
                    continue
                dest = tmp / f"{len(imgs):04d}_{Path(media).name}"
                dest.write_bytes(z.read(media))
                imgs.append(dest)
    return imgs


def ocr_file(path: Path) -> str:
    """对单个 PDF/PPTX 做 OCR，返回纯文本（失败返回空串）。"""
    try:
        binary = _ensure_bin()
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] OCR 二进制不可用: {e}")
        return ""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        targets: list[Path]
        if path.suffix.lower() == ".pptx":
            targets = _pptx_slide_images(path, tmp)
            if not targets:
                return ""
        else:
            targets = [path]
        out = tmp / "out.txt"
        try:
            subprocess.run([str(binary), str(out), *[str(t) for t in targets]],
                           check=False, timeout=1200, capture_output=True)
        except subprocess.TimeoutExpired:
            print(f"  [warn] OCR 超时 {path.name}")
            return ""
        if out.is_file():
            return out.read_text(encoding="utf-8", errors="ignore")
        return ""


def cached_ocr(path: Path, quiet: bool = False) -> str:
    """带缓存的 OCR：<材料>/_ocr/<文件名>.ocr.txt。"""
    cache = path.parent / OCR_DIRNAME / (path.name + ".ocr.txt")
    if cache.is_file() and cache.stat().st_mtime >= path.stat().st_mtime:
        return cache.read_text(encoding="utf-8", errors="ignore")
    if not quiet:
        print(f"  [ocr] {path.name} ...", flush=True)
    text = ocr_file(path)
    if not text.strip():
        return ""
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    if not quiet:
        print(f"        -> {len(text)} 字", flush=True)
    return text


def native_text(path: Path) -> str:
    try:
        return parser.extract_text(path.name, path.read_bytes())
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] 原生解析失败 {path.name}: {e}")
        return ""


def best_text(path: Path, allow_ocr: bool = True, quiet: bool = False) -> str:
    """返回该素材最适合入库的文本：原生文本够多就直用，否则拼上 OCR 文本。"""
    native = native_text(path)
    ext = path.suffix.lower().lstrip(".")
    if ext not in ("pdf", "pptx") or not allow_ocr:
        return native
    if len(native) >= NATIVE_MIN_CHARS:
        return native
    ocr = cached_ocr(path, quiet=quiet)
    if not ocr.strip():
        return native
    return (native.strip() + "\n\n" + ocr).strip()


def warm_cache(course_dir: Path, quiet: bool = False, keys: list[str] | None = None) -> dict:
    """预热：扫描 课件/W*/材料/ 下所有图片型素材，生成 OCR 缓存。

    keys 形如 ["W2S1","W2S2"]，只处理这些 session 目录；None = 全量。
    """
    stats = {"scanned": 0, "ocr": 0, "skipped": 0, "chars": 0}
    wanted = {k.upper() for k in keys} if keys else None
    for sdir in sorted(p for p in course_dir.iterdir() if p.is_dir() and p.name.startswith("W")):
        if wanted is not None and sdir.name.upper() not in wanted:
            continue
        mdir = sdir / "材料"
        if not mdir.is_dir():
            continue
        for f in sorted(mdir.iterdir()):
            if not f.is_file() or f.suffix.lower().lstrip(".") not in ("pdf", "pptx"):
                continue
            stats["scanned"] += 1
            native = native_text(f)
            if len(native) >= NATIVE_MIN_CHARS:
                stats["skipped"] += 1
                continue
            text = cached_ocr(f, quiet=quiet)
            if text.strip():
                stats["ocr"] += 1
                stats["chars"] += len(text)
            else:
                stats["skipped"] += 1
    return stats


if __name__ == "__main__":
    course = Path("/Users/xicheng/WorkBuddy/AI学习小组app/课件")
    if shutil.which("swiftc") is None:
        print("缺少 swiftc（需 Xcode Command Line Tools）")
        raise SystemExit(1)
    result = warm_cache(course)
    print("\n=== OCR 预热完成 ===")
    for k, v in result.items():
        print(f"  {k}: {v}")
