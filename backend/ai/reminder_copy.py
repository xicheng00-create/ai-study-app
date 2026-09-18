"""19:00 未打卡提醒文案池 + 萌图选择（NOTIF-005，纯函数、确定性、不调 LLM）。"""
from config import TASK_CARDS_REQUIRED, TASK_QUESTIONS_REQUIRED

IMG_LOW = "/img/notify/flame-low.png"    # 快灭（灰蓝丧脸）
IMG_OK = "/img/notify/flame-ok.png"      # 一般（珊瑚）
IMG_HOT = "/img/notify/flame-hot.png"    # 连胜 ≥7（暖黄笑脸+星星）


def pick_image(streak: int, cards_done: int, questions_done: int) -> str:
    """萌图选择：连胜 ≥7 → hot；连胜 ≥3 且今日 0 进度 → low（快灭）；否则 ok。"""
    if streak >= 7:
        return IMG_HOT
    if streak >= 3 and cards_done == 0 and questions_done == 0:
        return IMG_LOW
    return IMG_OK


def reminder_copy(name: str, streak: int, cards_done: int, questions_done: int) -> dict:
    """返回 {title, body, image}，按当前连胜 + 今日缺口挑俏皮文案。"""
    gap_cards = max(0, TASK_CARDS_REQUIRED - cards_done)
    gap_questions = max(0, TASK_QUESTIONS_REQUIRED - questions_done)
    image = pick_image(streak, cards_done, questions_done)

    if streak >= 3 and cards_done == 0 and questions_done == 0:
        body = (f"🔥 {streak} 天连胜要熄火了——今天还差 {gap_cards} 张卡片 + "
                f"{gap_questions} 道题，10 分钟就能续上！")
    elif streak >= 1 and (cards_done > 0 or questions_done > 0):
        body = (f"{name}，火焰还亮着 🔥 差最后 {gap_cards} 张卡片 + "
                f"{gap_questions} 道题就保住 {streak} 天连胜了。")
    else:
        body = (f"🔥 火焰还没点起来呢——今天翻 {TASK_CARDS_REQUIRED} 张卡、"
                f"刷 {TASK_QUESTIONS_REQUIRED} 道题，明天你就是有连胜的人。")

    return {"title": "🔥 今日打卡提醒", "body": body, "image": image}
