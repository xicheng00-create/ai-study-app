"""每晚 19:00–23:00 阶梯式未达标提醒文案池 + 萌图选择（NOTIF-005，纯函数、确定性、不调 LLM）。"""
from config import TASK_CARDS_REQUIRED, TASK_QUESTIONS_REQUIRED

IMG_LOW = "/img/notify/flame-low.png"    # 快灭（灰蓝丧脸）
IMG_OK = "/img/notify/flame-ok.png"      # 一般（珊瑚）
IMG_HOT = "/img/notify/flame-hot.png"    # 连胜 ≥7（暖黄笑脸+星星）

# 每晚 5 档（Asia/Shanghai 触发小时）：单一真相，脚本与测试都引用这里
SLOTS = {"L1": 19, "L2": 20, "L3": 21, "L4": 22, "L5": 23}


def slot_for_hour(hour: int):
    """上海小时 → 档位；不在 19..23 → None。"""
    for slot, h in SLOTS.items():
        if h == hour:
            return slot
    return None


def pick_image(streak: int, cards_done: int, questions_done: int) -> str:
    """萌图选择：连胜 ≥7 → hot；连胜 ≥3 且今日 0 进度 → low（快灭）；否则 ok。"""
    if streak >= 7:
        return IMG_HOT
    if streak >= 3 and cards_done == 0 and questions_done == 0:
        return IMG_LOW
    return IMG_OK


_TITLES = {
    "L1": "🔥 今日打卡提醒",
    "L2": "🥺 小火焰在等你哦",
    "L3": "😭 连胜快熄火了！！",
    "L4": "🙏 求求你啦～就差一点点",
    "L5": "⏰ 最后 1 小时！我哭给你看",
}

# 每个档位三条分支：S1 有连胜且今日 0 进度 / S2 有连胜且有部分进度 / S3 无连胜
_BODIES = {
    "L1": (
        "🔥 {streak} 天连胜要熄火了——今天还差 {gc} 张卡片 + {gq} 道题，10 分钟就能续上！",
        "{name}，火焰还亮着 🔥 差最后 {gc} 张卡片 + {gq} 道题就保住 {streak} 天连胜了。",
        "🔥 火焰还没点起来呢——今天翻 {cr} 张卡、刷 {qr} 道题，明天你就是有连胜的人。",
    ),
    "L2": (
        "🥺 {name}～小火焰说它有点冷…还差 {gc} 张卡 + {gq} 道题，它就能继续烧下去啦",
        "加油加油～{name} 已经走了一半！再 {gc} 张卡 + {gq} 道题，小火焰就会开心地转圈圈 🌀",
        "(๑•́ ₃ •̀๑) {name}，今天还没人帮小火焰点火…翻 {cr} 张卡 + 刷 {qr} 道题，它就亮啦",
    ),
    "L3": (
        "不行了 {name}！{streak} 天连胜今晚就要归零 😭 还差 {gc} 张卡 + {gq} 道题，快点嘛！",
        "别停下 {name}！就差 {gc} 张卡 + {gq} 道题，{streak} 天连胜不能断在这里呀 😣",
        "😤 {name} 今天一张卡都还没翻耶…{cr} 张卡 + {qr} 道题而已，别让我一个人着急啦！",
    ),
    "L4": (
        "拜託拜託 {name} 🙏 我已经喊了三次了…{streak} 天连胜只差 {gc} 张卡 + {gq} 道题，求你翻一下好不好",
        "就快到了 {name}…再 {gc} 张卡 + {gq} 道题，{streak} 天连胜就能保住，我陪你再撑一下下 🙏",
        "求你啦 {name}，今天连胜还是 0 耶…现在翻 {cr} 张卡 + {qr} 道题，明天就有 🔥1 了",
    ),
    "L5": (
        "⏰ {name}！不到 1 小时了，{streak} 天连胜要化成灰了…{gc} 张卡 + {gq} 道题，现在打开 App 还来得及！",
        "⏰ 最后冲刺 {name}！{gc} 张卡 + {gq} 道题而已，{streak} 天连胜现在不救就没了！",
        "⏰ {name}！今天剩不到 1 小时，{cr} 张卡 + {qr} 道题都还没动…翻一下嘛，不然小火焰要哭了 😭",
    ),
}


def reminder_copy(name: str, streak: int, cards_done: int, questions_done: int,
                  slot: str = "L1", lapse_days: int = 0) -> dict:
    """返回 {title, body, image}；slot ∈ SLOTS，非法回落 L1；lapse_days ≥2 时正文加前缀。"""
    if slot not in SLOTS:
        slot = "L1"
    gc = max(0, TASK_CARDS_REQUIRED - cards_done)
    gq = max(0, TASK_QUESTIONS_REQUIRED - questions_done)
    cr = TASK_CARDS_REQUIRED
    qr = TASK_QUESTIONS_REQUIRED
    image = pick_image(streak, cards_done, questions_done)

    # 分支判定与 v2.4.0 文案池一致：S1 有连胜且 0 进度 / S2 有连胜且有进度 / S3 无连胜
    if streak >= 1 and cards_done == 0 and questions_done == 0:
        branch = 0
    elif streak >= 1 and (cards_done > 0 or questions_done > 0):
        branch = 1
    else:
        branch = 2

    body = _BODIES[slot][branch].format(
        name=name, streak=streak, gc=gc, gq=gq, cr=cr, qr=qr,
    )
    if lapse_days >= 2:
        body = f"已经 {lapse_days} 天没见到你了…" + body

    return {"title": _TITLES[slot], "body": body, "image": image}
