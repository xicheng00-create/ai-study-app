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


def _chat(messages: list[dict], feature: str = "unknown") -> str | None:
    """请求 DeepSeek chat completions；任何异常/超时返回 None。"""
    api_key = _config("DEEPSEEK_API_KEY", "")
    if not api_key:
        return None
    url = _config("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = _config("DEEPSEEK_MODEL", "deepseek-chat")
    try:
        resp = requests.post(
            f"{url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": messages, "temperature": 0.6},
            timeout=TIMEOUT_SECONDS,
        )
        if resp.status_code >= 500:
            return None
        resp.raise_for_status()
        data = resp.json()
        # HTTP 成功且拿到 JSON 才记一条用量（失败/超时/异常路径不记）
        log_usage(model, data.get("usage"), feature)
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
