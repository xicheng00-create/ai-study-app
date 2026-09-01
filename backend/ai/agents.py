"""DeepSeek 调用封装：tutor_reply / quizzer_generate / grader_grade。

失败/超时返回 None，由调用方降级到固定引导语池（两层 Fallback L1）。
"""
import json
import os

import requests

TIMEOUT_SECONDS = 30


def _config(key: str, default):
    """读取配置；无 Flask 上下文（单测）时回退环境变量。"""
    from flask import current_app, has_app_context
    if has_app_context():
        return current_app.config.get(key, default)
    return os.environ.get(key, default)


def _chat(messages: list[dict]) -> str | None:
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
    return _chat(messages)


def quizzer_generate(system: str) -> list[dict] | None:
    out = _chat([{"role": "system", "content": system}])
    if not out:
        return None
    parsed = _parse_json(out)
    if isinstance(parsed, dict) and isinstance(parsed.get("questions"), list):
        return parsed["questions"]
    return None


def grader_grade(system: str) -> dict | None:
    out = _chat([{"role": "system", "content": system}])
    if not out:
        return None
    parsed = _parse_json(out)
    if isinstance(parsed, dict):
        return parsed
    return None
