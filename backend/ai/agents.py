"""DeepSeek 调用封装：tutor_reply / quizzer_generate / grader_grade。

失败/超时返回 None，由调用方降级到固定引导语池（两层 Fallback L1）。
"""
import json
import os

import requests

from ai.usage_log import log_usage

TIMEOUT_SECONDS = 30


def _config(key: str, default):
    """读取配置；无 Flask 上下文（单测）时回退环境变量。"""
    from flask import current_app, has_app_context
    if has_app_context():
        return current_app.config.get(key, default)
    return os.environ.get(key, default)


def _thinking_off(feature: str) -> bool:
    """转换型任务默认关思考（成本纪律铁律 1）。

    提档方式（都走配置/环境变量，不改代码）：
      `LLM_THINKING=on`                     → 全局恢复思考（调试/对比用）
      `LLM_THINKING_FEATURES=tutor,grader`  → 只给这些 feature 恢复思考
    默认全关：判重/出题/判分/卡片抽取的输出都是结构化 JSON，思考链只烧钱不改结果。
    """
    if str(_config("LLM_THINKING", "") or "").strip().lower() == "on":
        return False
    allow = str(_config("LLM_THINKING_FEATURES", "") or "")
    feats = {x.strip() for x in allow.split(",") if x.strip()}
    return feature not in feats


def _chat(messages: list[dict], feature: str = "unknown") -> str | None:
    """请求 DeepSeek chat completions；任何异常/超时返回 None。

    批量 LLM 成本纪律（统一入口，共享技能 `llm-batch-cost-discipline`）：
    - 铁律 1（转换型默认关思考）：判重/出题/判分/卡片抽取都是「转换」不是「推理」。本地对照实测
      （2026-10-01，同一份提示词）：deepseek-flash 不带 thinking → 输出 946 tok、其中推理 516
      （占 54.5%）、4.2s；加 `thinking=disabled` → 输出 739（−22%）、推理 0、2.8s。
      deepseek-chat 本就推理 0，所以这道闸的收益是「换模型时防静默烧推理」，不是今天的省钱。
      `LLM_THINKING=on` 全局提档；`LLM_THINKING_FEATURES=tutor,grader` 只给这些 feature 提档。
      上游不认识 `thinking` 参数时（换 base_url / 换服务商）自动去掉重发一次，不占用任何重试预算。
    - 铁律 2（每次成功调用落账本）：账本记 `reasoning_tokens` / `thinking`，护栏据此查「有人绕过入口」。
    - 铁律 3：这里**不做重试**（失败即返回 None，由调用方降级到固定引导语池）——0 次也好过无上限。
    """
    api_key = _config("DEEPSEEK_API_KEY", "")
    if not api_key:
        return None
    url = _config("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = _config("DEEPSEEK_MODEL", "deepseek-chat")
    payload = {"model": model, "messages": messages, "temperature": 0.6}
    if _thinking_off(feature):
        payload["thinking"] = {"type": "disabled"}
    try:
        resp = requests.post(
            f"{url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
        if resp.status_code == 400 and "thinking" in payload:
            payload.pop("thinking", None)          # 上游不认该参数：去掉重发一次
            resp = requests.post(
                f"{url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=TIMEOUT_SECONDS,
            )
        if resp.status_code >= 500:
            return None
        resp.raise_for_status()
        data = resp.json()
        # HTTP 成功且拿到 JSON 才记一条用量（失败/超时/异常路径不记）
        log_usage(model, data.get("usage"), feature,
                  thinking="off" if "thinking" in payload else "unknown")
        return data["choices"][0]["message"]["content"]
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return None


def _parse_json(text: str):
    """从 LLM 输出中提取 JSON 对象（容错）。"""
    if not text:
        return None
    text = text.strip()
    # 去掉可能的 ```json 围栏
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def tutor_reply(system: str, history: list[dict]) -> str | None:
    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    return _chat(messages, feature="tutor")


def quizzer_generate(system: str) -> list[dict] | None:
    out = _chat([{"role": "system", "content": system}], feature="quizzer")
    if not out:
        return None
    parsed = _parse_json(out)
    if isinstance(parsed, dict) and isinstance(parsed.get("questions"), list):
        return parsed["questions"]
    return None


def grader_grade(system: str) -> dict | None:
    out = _chat([{"role": "system", "content": system}], feature="grader")
    if not out:
        return None
    parsed = _parse_json(out)
    if isinstance(parsed, dict):
        return parsed
    return None


def knowledge_generate(system: str) -> list[dict] | None:
    """调用知识卡片 Agent，严格读取 cards 数组。"""
    out = _chat([{"role": "system", "content": system}], feature="knowledge")
    parsed = _parse_json(out) if out else None
    return parsed["cards"] if isinstance(parsed, dict) and isinstance(parsed.get("cards"), list) else None


DUP_CHECK_SYSTEM = """你是「AI 学习小组」的知识卡片去重复核员。判断两张卡片是否为「同一考点的同一件事、答案可无损合并」。

卡片 A：
front: {front_a}
back: {back_a}

卡片 B：
front: {front_b}
back: {back_b}

判重口径（严格）：
- 只有「同一考点的同一件事、答案可无损合并」才 mergeable=true。
- 命中以下任一情况，一律 mergeable=false：
  * 同模板不同主体（如四家 IDE 的同类问句，主体不同）；
  * 数字或阈值不同；
  * 定义 vs 误区 vs 示例 vs 步骤（侧面不同，不可合并）。

只输出 JSON，不要任何多余文字：
{{"mergeable": true|false, "reason": "一句话理由"}}"""


def knowledge_dup_check(front_a: str, back_a: str, front_b: str, back_b=None) -> dict | None:
    """知识卡片去重复核（止血闸门用）：返回 {"mergeable": bool, "reason": str}；失败/超时返回 None。"""
    system = DUP_CHECK_SYSTEM.format(
        front_a=front_a, back_a=back_a or "",
        front_b=front_b, back_b=back_b or "")
    out = _chat([{"role": "system", "content": system}], feature="knowledge_dup_check")
    parsed = _parse_json(out) if out else None
    if isinstance(parsed, dict) and isinstance(parsed.get("mergeable"), bool):
        return {"mergeable": parsed["mergeable"], "reason": str(parsed.get("reason") or "")}
    return None
