"""Real ffmpeg artifacts exercise scene and audio/video coverage gates."""
import json
import subprocess

import pytest
from video.daily_video import check_duration, check_scene_outputs


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
