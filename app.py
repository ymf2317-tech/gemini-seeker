"""gemini-seeker: Flask 主入口。OpenAI + Anthropic 双协议。"""

import json
import re
import logging
import os
import time
import uuid

from flask import Flask, Response, jsonify, request, stream_with_context

from gemini_seeker import session as gsession
from gemini_seeker import prompt as gprompt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("gemini_seeker.app")

app = Flask(__name__)

API_KEY = os.environ.get("GEMINI_SEEKER_API_KEY", "")
HISTORY_TURNS = int(os.environ.get("GEMINI_SEEKER_HISTORY_TURNS", "3"))
_history = []


def _check_auth():
    if not API_KEY:
        return True
    auth = request.headers.get("Authorization", "")
    xkey = request.headers.get("x-api-key", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else (xkey.strip() if xkey else "")
    return token == API_KEY


def _append_history(role, text):
    _history.append((role, text))
    max_msgs = HISTORY_TURNS * 2
    if len(_history) > max_msgs:
        del _history[: len(_history) - max_msgs]


def _extract_user_text(messages):
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content", "")
            if isinstance(c, list):
                return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
            return c
    return ""


def _flatten_content(c):
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
    return c or ""


def _messages_to_prompt(messages, tools):
    MAX_PROMPT_CHARS = 100000
    system_prompt = gprompt.build_system_prompt(tools)
    head = [system_prompt, '', '## Recent conversation']
    body = []
    # 先收集所有非 system 消息渲染成的行
    for m in messages:
        role = m.get('role', '')
        if role == 'system':
            continue
        if role == 'user':
            body.append('user: ' + _flatten_content(m.get('content')))
        elif role == 'assistant':
            tcs = m.get('tool_calls') or []
            if tcs:
                calls = []
                for tc in tcs:
                    fn = tc.get('function', {}) if isinstance(tc, dict) else {}
                    calls.append(fn.get('name') + '(' + str(fn.get('arguments', '{}')) + ')')
                body.append('assistant: [calling tools] ' + '; '.join(calls))
            txt = _flatten_content(m.get('content'))
            if txt:
                body.append('assistant: ' + txt)
        elif role == 'tool':
            name = m.get('name') or m.get('tool_call_id') or 'tool'
            body.append('tool[' + str(name) + '] result: ' + _flatten_content(m.get('content')))
    # 从最新往回累加，保证当前问题不丢
    fixed = chr(10).join(head) + chr(10)
    budget = MAX_PROMPT_CHARS - len(fixed)
    kept = []
    total = 0
    for line in reversed(body):
        if total + len(line) + 1 > budget:
            break
        kept.append(line)
        total += len(line) + 1
    kept.reverse()
    tail = [chr(10).join(kept), '']
    tail.append('## Current request')
    tail.append('Continue based on the tool results above. If you have enough info, reply with content JSON. If you need another tool, reply with tool_calls JSON.')
    parts = [fixed] + kept + tail
    return chr(10).join(parts)


def _run_llm(messages, tools):
    full_prompt = _messages_to_prompt(messages, tools)
    logger.info("sending (msgs=%d, prompt_len=%d)", len(messages), len(full_prompt))
    raw, key = gsession.send(full_prompt)
    logger.info("reply (account=%s, raw_len=%d)", key, len(raw))
    try:
        from gemini_seeker import parser as _parser
        # parse_tools 返回 (tools, clean_text)：tools 是 list，clean_text 是正文
        res = _parser.parse_tools(raw)
        if isinstance(res, tuple) and len(res) == 2:
            tool_calls, content = res
        elif isinstance(res, dict):
            tool_calls, content = res.get("tool_calls", []), res.get("content", raw)
        else:
            tool_calls, content = [], raw
    except Exception as e:
        logger.warning("parse failed: %s", e)
        tool_calls, content = [], raw
    # 纯 JSON 兜底：parser 只管 XML/DSML，不认 {"content":..} / {"tool_calls":..}
    content, tool_calls = _strip_json_wrapper(content, raw, tool_calls)
    if not content and not tool_calls:
        content = raw
    return content, tool_calls, raw


def _strip_json_wrapper(content, raw, tool_calls):
    """把 Gemini 吐回来的 {"content": "..."} / {"tool_calls": [...]} 外壳剥掉。

    兼容三种情况：
    1. 正常 dict：{"content": "..."}
    2. 字符串形式 JSON：'{"content": "..."}'（json.loads 出来是 str，再 parse 一次）
    3. JSON 解析失败（转义/换行问题）：用正则抠 content 字段
    """
    candidates = []
    if content:
        candidates.append(content)
    if raw and raw not in candidates:
        candidates.append(raw)

    for cand in candidates:
        s = (cand or "").strip()
        if not s:
            continue
        if not (s.startswith("{") or s.startswith('"')):
            continue
        j = None
        try:
            j = json.loads(s)
        except Exception:
            j = None

        # 情况 2：解析出来还是 str（外面套了一层引号），再 parse 一次
        if isinstance(j, str):
            try:
                j = json.loads(j.strip())
            except Exception:
                j = None

        if isinstance(j, dict):
            tc = j.get("tool_calls")
            if isinstance(tc, list) and tc:
                return j.get("content", "") or "", tc
            if "content" in j:
                return str(j.get("content", "") or ""), tool_calls

    # 情况 3：正则兜底抠 {"content": "..."}
    for cand in candidates:
        s = (cand or "").strip()
        m = re.match(r'^\{\s*"content"\s*:\s*"(.*)"\s*\}\s*$', s, re.DOTALL)
        if m:
            try:
                inner = json.loads('"' + m.group(1) + '"')
            except Exception:
                inner = m.group(1)
            return inner, tool_calls

    return content, tool_calls


@app.route("/health")
def health():
    return jsonify({"ok": True, "time": time.time(), **gsession.status()})


@app.route("/")
def index():
    return jsonify({"service": "gemini-seeker", "endpoints": ["/v1/chat/completions", "/v1/messages", "/health"]})


@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    if not _check_auth():
        return jsonify({"error": {"message": "unauthorized", "type": "auth_error"}}), 401
    body = request.get_json(force=True, silent=True) or {}
    messages = body.get("messages", [])
    tools = body.get("tools") or []
    stream = bool(body.get("stream"))
    model = body.get("model", "gemini-3.8-flash")
    user_text = _extract_user_text(messages)
    try:
        content, tool_calls, raw = _run_llm(messages, tools)
    except Exception as e:
        logger.exception("llm failed")
        return jsonify({"error": {"message": str(e), "type": "upstream_error"}}), 502
    _append_history("user", user_text)
    _append_history("assistant", content or raw)
    if not stream:
        msg = {"role": "assistant", "content": content or None}
        if tool_calls:
            msg["tool_calls"] = [{"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function", "function": {"name": tc.get("name"), "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=False)}} for tc in tool_calls]
        return jsonify({"id": f"chatcmpl-{uuid.uuid4().hex[:24]}", "object": "chat.completion", "created": int(time.time()), "model": model, "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if tool_calls else "stop"}], "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})
    def gen():
        cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())
        base = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model}
        if tool_calls:
            delta = {"role": "assistant", "tool_calls": [{"index": i, "id": f"call_{uuid.uuid4().hex[:12]}", "type": "function", "function": {"name": tc.get("name"), "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=False)}} for i, tc in enumerate(tool_calls)]}
            yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}, ensure_ascii=False) + "\n\n"
            yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}, ensure_ascii=False) + "\n\n"
        else:
            yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}, ensure_ascii=False) + "\n\n"
            yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {"content": content or ""}, "finish_reason": None}]}, ensure_ascii=False) + "\n\n"
            yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"
    return Response(stream_with_context(gen()), mimetype="text/event-stream")


@app.route("/v1/messages", methods=["POST"])
def anthropic_messages():
    if not _check_auth():
        return jsonify({"type": "error", "error": {"type": "authentication_error", "message": "unauthorized"}}), 401
    body = request.get_json(force=True, silent=True) or {}
    messages = body.get("messages", [])
    tools = body.get("tools") or []
    openai_tools = [{"type": "function", "function": {"name": t.get("name"), "description": t.get("description", ""), "parameters": t.get("input_schema", {})}} for t in tools]
    user_text = _extract_user_text(messages)
    try:
        content, tool_calls, raw = _run_llm(messages, openai_tools)
    except Exception as e:
        logger.exception("llm failed")
        return jsonify({"type": "error", "error": {"type": "api_error", "message": str(e)}}), 502
    _append_history("user", user_text)
    _append_history("assistant", content or raw)
    blocks = []
    if content:
        blocks.append({"type": "text", "text": content})
    for tc in tool_calls:
        blocks.append({"type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:12]}", "name": tc.get("name"), "input": tc.get("arguments", {})})
    if not blocks:
        blocks.append({"type": "text", "text": raw})
    return jsonify({"id": f"msg_{uuid.uuid4().hex[:24]}", "type": "message", "role": "assistant", "model": body.get("model", "gemini-3.8-flash"), "content": blocks, "stop_reason": "tool_use" if tool_calls else "end_turn", "usage": {"input_tokens": 0, "output_tokens": 0}})


if __name__ == "__main__":
    port = int(os.environ.get("GEMINI_SEEKER_PORT", "4983"))
    app.run(host="0.0.0.0", port=port, threaded=True)
