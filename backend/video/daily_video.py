#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""薄壳：实现只有一份，在 ~/VideoKit/videokit/pipeline.py（2026-10-26 收编）。

brain 日更、DanKoe、AI 学习小组 app 都从这里进，改口径只改库里那一份。
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/VideoKit"))
from videokit.pipeline import main  # noqa: E402

if __name__ == "__main__":
    main()
