"""Real ffmpeg artifacts exercise scene and audio/video coverage gates."""
import json
import os
import subprocess
import time

import sys

import pytest

# 闸门的唯一实现在 ~/VideoKit/videokit/pipeline.py（v3 收编后 daily_video.py 是 14 行薄壳，
# 曾经这三个函数只留在 .bak 里 → 本文件在收集阶段 ImportError，整套 pytest 中断）。
sys.path.insert(0, os.environ.get("VIDEOKIT_HOME", os.path.expanduser("~/VideoKit")))
from videokit.pipeline import (  # noqa: E402
    MID_FILES, check_duration, check_intermediates, check_scene_outputs)


def media(path, duration, audio=False):
    cmd = ['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=10']
    if audio:
        cmd += ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100']
    cmd += ['-t', str(duration), '-c:v', 'libx264', '-pix_fmt', 'yuv420p']
    if audio:
        cmd += ['-c:a', 'aac']
    subprocess.run(cmd + [str(path)], check=True, capture_output=True)


@pytest.mark.parametrize('bad', ['missing', 'short', 'no_audio', 'duplicate'])
def test_reject_real_bad_media(tmp_path, bad):
    rows = [{'id': 'S1', 'dur': 2}, {'id': 'S2', 'dur': 2}]
    (tmp_path / 'narration.json').write_text(json.dumps({'scenes': rows}))
    (tmp_path / 'durations.json').write_text(json.dumps(rows if bad != 'duplicate' else [rows[0], rows[0]]))
    media(tmp_path / 'S1.mp4', 2)
    if bad != 'missing':
        media(tmp_path / 'S2.mp4', 0.2 if bad == 'short' else 2)
    media(tmp_path / 'final.mp4', 4, audio=bad != 'no_audio')
    # All of these genuinely generated bad builds pass the old total-only gate.
    assert check_duration(str(tmp_path), 4) == 4
    with pytest.raises(SystemExit):
        check_scene_outputs(str(tmp_path), str(tmp_path), str(tmp_path / 'final.mp4'))


def test_real_complete_media(tmp_path):
    rows = [{'id': 'S1', 'dur': 2}]
    (tmp_path / 'narration.json').write_text(json.dumps({'scenes': rows}))
    (tmp_path / 'durations.json').write_text(json.dumps(rows))
    media(tmp_path / 'S1.mp4', 2)
    media(tmp_path / 'final.mp4', 2, audio=True)
    check_duration(str(tmp_path), 2)
    check_scene_outputs(str(tmp_path), str(tmp_path), str(tmp_path / 'final.mp4'))


def test_reject_zero_duration_row(tmp_path):
    """任一拍时长为 0：只看总时长的体检会放行，逐拍断言必须拦住。"""
    rows = [{'id': 'S1', 'dur': 2}, {'id': 'S2', 'dur': 0}]
    (tmp_path / 'durations.json').write_text(json.dumps(rows))
    with pytest.raises(SystemExit):
        check_duration(str(tmp_path), 2)


def test_reject_empty_duration_table(tmp_path):
    (tmp_path / 'durations.json').write_text('[]')
    with pytest.raises(SystemExit):
        check_duration(str(tmp_path), 2)


def _seed_intermediates(tmp_path):
    """把中间产物铺成「昨天的」并返回拼接前 mtime 表。"""
    before, old = {}, time.time() - 86400
    for name in MID_FILES:
        p = tmp_path / name
        p.write_bytes(b'OLD')
        os.utime(p, (old, old))
        before[name] = p.stat().st_mtime
    return before


def test_reject_stale_intermediates(tmp_path):
    """stitch 没重写中间产物 = 拿旧片重封：final.mp4 再新也要拦。"""
    before = _seed_intermediates(tmp_path)
    (tmp_path / 'final.mp4').write_bytes(b'NEW')      # final 是新的，正是在骗人
    with pytest.raises(SystemExit):
        check_intermediates(str(tmp_path), before)


def test_reject_missing_intermediates(tmp_path):
    with pytest.raises(SystemExit):
        check_intermediates(str(tmp_path), {MID_FILES[0]: 0})


def test_accept_fresh_intermediates(tmp_path):
    """正常重跑：中间产物确实变新 → 放行，不误杀。"""
    before = _seed_intermediates(tmp_path)
    time.sleep(0.01)
    for name in MID_FILES:
        (tmp_path / name).write_bytes(b'NEW')
    check_intermediates(str(tmp_path), before)
