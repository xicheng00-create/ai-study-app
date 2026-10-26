from video_base import *  # noqa: F403
from video_base import _load, SPECS, DURS
from video_scenes_a import *  # noqa: F403
from video_scenes_b import *  # noqa: F403
KINDS = {
    "situation": k_situation, "crossout": k_crossout, "transform": k_transform,
    "chain": k_chain, "axis": k_axis, "threshold": k_threshold, "loop": k_loop,
    "balance": k_balance, "stack": k_stack, "nodes": k_nodes, "steps": k_steps,
    "close": k_close, "source": k_source, "text": k_text,
    # v5 开场器变体：开场不必再是「两个人 + 一条线 + 一个叉」
    "dayband": k_dayband, "object": k_object, "dialogue": k_dialogue,
    # v2 的六个 style 名一律降级到兜底场（v2 是 L1「方框+箭头」，已弃用）
    "hook": k_text, "map": k_nodes, "flow": k_text, "contrast": k_text,
    "checklist": k_steps, "title": k_text, "body": k_text, "action": k_text,
}


def _make(sid, spec):
    fn = KINDS.get(spec.get("style") or spec.get("kind") or "text", k_text)

    def construct(self):
        dur = float((DURS.get(sid) or {}).get("dur") or 7.0)
        if CAM and hasattr(self.camera, "frame"):
            self.camera.frame.scale(CAM_START)  # 起手略拉远，第一拍就是一次推镜（拉远不会裁内容）
        self.add(bg_layer())                   # 皮肤质感层：垫在所有内容之下
        fn(self, spec, dur, dur + PAD)

    return type(sid, (MovingCameraScene,), {"construct": construct})


_load()
for _sid, _spec in SPECS.items():
    globals()[_sid] = _make(_sid, _spec)
