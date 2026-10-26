"""卡片图标链路守卫：任何语义图标名都必须落到磁盘上真实存在的素材。

出处（2026-10-26 线上事故，Ray 第二次报同一个问号）：图标库从 11 个长到 18 个，
`ICON_FILE` 手写字典没跟上 → `icon_file` 返回裸名字（如 `book`）→ 前端
`<img src="/api/knowledge/icon/book">` 404 → 卡面正中一个破图问号。
两层修好后用本文件钉住：① 映射改为查磁盘；② 路由兜底永不 404 图片。
"""
import os
import sys
from pathlib import Path

VIDEOKIT_HOME = os.environ.get("VIDEOKIT_HOME", os.path.expanduser("~/VideoKit"))
if VIDEOKIT_HOME not in sys.path:
    sys.path.insert(0, VIDEOKIT_HOME)

def _icon_dir():
    return Path(VIDEOKIT_HOME) / "assets" / "icons3d"


def test_every_semantic_icon_maps_to_existing_file():
    from videokit.from_card import ICONS, SEMANTIC, icon_file

    names = {icon for _, icon in SEMANTIC} | {icon for _, icon in ICONS} | {"bulb", "book"}
    missing = []
    for name in sorted(names):
        f = icon_file(name)
        assert f and not f.endswith(".png"), f"{name} 应返回不带后缀的素材名，实得 {f!r}"
        if not (_icon_dir() / f"{f}.png").exists():
            missing.append((name, f))
    assert not missing, f"这些图标映射到了不存在的素材：{missing}"


def test_unknown_icon_falls_back_not_broken():
    """未知/空名字也必须给出一个存在的素材，绝不许让前端拿裸名去 404。"""
    from videokit.from_card import icon_file

    for bogus in ("", None, "不存在的图", "zzz_not_there"):
        f = icon_file(bogus)
        assert (_icon_dir() / f"{f}.png").exists(), f"{bogus!r} → {f!r} 素材不存在"


def test_icon_route_serves_png_even_for_unknown_name(client):
    """路由层：已知名 200 image/png；未知名也要回图（兜底），不能回 404 JSON。"""
    for name in ("books_3d", "book", "light_bulb_3d"):
        resp = client.get(f"/api/knowledge/icon/{name}")
        assert resp.status_code == 200, name
        assert resp.mimetype == "image/png", name
        assert len(resp.data) > 1024, name
    resp = client.get("/api/knowledge/icon/zzz_not_there")
    assert resp.status_code == 200, "未知图标必须兜底成图，否则卡面出现破图问号"
    assert resp.mimetype == "image/png"
