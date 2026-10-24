# 视频生产规格（本仓库强制）

任何在本仓库生成复习视频 / 讲解视频的改动，**必须**满足
`/Users/xicheng/AgentMemory/projects/video-production-standard.md` 的 v2 规格。要点：

1. 出片只走 `videokit.cli.render_narration`，**禁止** `render_card`
   （`backend/video/daily_video.py` 已接线；改回去等于整批视频退回「一个图标 + 一行字」）。
2. 每场 = 一行字幕，8–20 汉字；全片 16–28 场；60–120 秒；句末带标点；不许「…」结尾。
   `backend/video/director.py` 的 `repair()` 对 >26 字的场次是 **fatal**，会打回重写。
3. 字幕固定压在画面下方 1/4（`subtitle_band(y=-4.95)`，画幅 8×14.22）。
4. 顶部永远有眉题+标题；标题与字幕重复时改用结构名（先破/前后对照/因果链/三步做法/结构层级/收束/机制/出处）。
5. 每页必须有真结构：crossout / transform / chain / steps / tree；单图标居中当一页 = 不合格。
6. 图标按当页主体词选（`from_card.py::SEMANTIC`），禁止兜底灯泡。

**验收**：`ffprobe` 时长 60–120 秒、1080×1920、h264+aac；抽帧核对「顶部有标题且不与字幕重复 /
字幕只有一行 / 页面有结构」；末场是出处卡。

## 未完成项（下次动视频前必须先做，2026-10-24 记）

**单句页中段偏空**：`data` / `statement` 这类只有一句字幕的页，画面仍是「一个大图标 + 上下留白」。
做法（已定）：
1. `backend/video/director.py` 要求每页除 text 外交 `chips`（2–3 个短词）或 `nodes`；
   已加软提醒（repair 会打「这页只有图标+一句字幕」），下一步升级为 **fatal**。
2. `~/VideoKit/videokit/scene.py` 的 `play_data` / `play_statement` 按 chips 铺胶囊/枝干，撑住中段。
3. 验收：抽帧看中段有没有内容承托，不是只有图标。
