#!/usr/bin/env python3
"""课件「材料」文件发现：`课件/第N章/材料/` → 待入库文件列表。

2026-09-22 起课件目录改名 `第N章`（原 `WxSy`）；部分章节的资料放在子目录里
（如 第14章 的 `ChemAI产品设计文档（纯产品设计）/`、`PPT/slides/`）。
本模块统一「哪些文件该入库」，供 inject_curriculum / ocr_materials 复用，
避免两处各写一套规则而漂移。

规则
  1. 只取 parser.SUPPORTED 类型（pdf / pptx / docx / md / txt / markdown / html / htm）
  2. 递归深度 ≤ 2（材料/ 的直接子目录、以及子目录的子目录）
  3. 跳过隐藏项、`_ocr` 缓存目录、`*_extracted.txt` 预抽取副本
  4. **程序资源包整棵跳过**：子目录含 package.json 或文件总数 > 40 时视为
     前端/npm 打包目录（实测 第15章 `课件-双击index.html打开/直播课PPT/` 785 文件、
     node_modules），整棵不入库，避免把 .ts/.map/.sh 当资料吃掉
  5. 排序稳定（目录序 + 文件名字典序），保证幂等注入的顺序一致
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from ai import parser  # noqa: E402

SKIP_SUFFIXES = ("_extracted.txt",)
SKIP_DIRNAMES = {"_ocr", "__pycache__", "node_modules"}
BUNDLE_FILE_LIMIT = 40


def _file_count(d: Path) -> int:
    n = 0
    for _root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if not x.startswith(".") and x not in SKIP_DIRNAMES]
        n += sum(1 for f in files if not f.startswith("."))
    return n


def is_bundle(d: Path) -> bool:
    """程序资源包判定（整棵跳过）：自身或后代含 `node_modules`、自身含
    `package.json`、或文件数超阈值。实测 第15章 `课件-双击index.html打开/`
    根下没有 package.json（它在二层 `直播课PPT/` 里）、且 node_modules 被计数
    剪枝后仅剩个位数文件 —— 只判「直接子项 + 文件数」会误放行。"""
    if (d / "package.json").is_file():
        return True
    for _root, dirs, _files in os.walk(d):
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        if "node_modules" in dirs:
            return True
    return _file_count(d) > BUNDLE_FILE_LIMIT


def _ok(f: Path) -> bool:
    if f.name.startswith(".") or f.name.endswith(SKIP_SUFFIXES):
        return False
    return f.suffix.lower().lstrip(".") in parser.SUPPORTED


def _subdirs(d: Path) -> list[Path]:
    return sorted(
        (x for x in d.iterdir() if x.is_dir() and not x.name.startswith(".") and x.name not in SKIP_DIRNAMES),
        key=lambda p: p.name,
    )


def _copy_rank(f: Path) -> tuple[int, int]:
    """重复副本取舍：优先「没有 (1)/(2) 后缀」且名字更短的那份。"""
    has_copy_tag = 1 if re.search(r"\s*\(\d+\)\s*$", f.stem) else 0
    return (has_copy_tag, len(f.name))


def _dedupe_same_bytes(files: list[Path]) -> list[Path]:
    """字节完全相同的重复副本只留一份（优先保留原名那份）；不判「近似重复」。"""
    import hashlib

    best: dict[tuple[int, str], Path] = {}
    for f in files:
        try:
            key = (f.stat().st_size, hashlib.sha1(f.read_bytes()).hexdigest())
        except OSError:
            continue
        cur = best.get(key)
        if cur is None or _copy_rank(f) < _copy_rank(cur):
            best[key] = f
    keep = {p for p in best.values()}
    out = []
    for f in files:
        if f in keep:
            keep.discard(f)
            out.append(f)
        else:
            print(f"  [skip-dup] {f.name} 与同内容副本重复，只入库一份")
    return out


def iter_material_files(mdir: Path) -> list[Path]:
    """返回 材料/ 下应入库的文件（稳定排序；不含 课件.md 本身）。"""
    mdir = Path(mdir)
    if not mdir.is_dir():
        return []
    found = [f for f in sorted(mdir.iterdir(), key=lambda p: p.name) if _ok(f) and f.name != "课件.md"]
    for d in _subdirs(mdir):
        if is_bundle(d):
            continue
        found += [f for f in sorted(d.iterdir(), key=lambda p: p.name) if _ok(f)]
        for d2 in _subdirs(d):
            if is_bundle(d2):
                continue
            found += [f for f in sorted(d2.iterdir(), key=lambda p: p.name) if _ok(f)]
    return _dedupe_same_bytes(found)
