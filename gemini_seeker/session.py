"""Gemini 会话管理层：封装 gemini_webapi + 常驻 ChatSession + 号池切换 + 模型透传。"""

import asyncio
import logging
import threading

from . import pool

logger = logging.getLogger("gemini_seeker.session")

_client = None
_session = None
_client_key = None
_current_model_name = None
_lock = threading.Lock()
_loop = None
_loop_thread = None


def _ensure_loop():
    global _loop, _loop_thread
    if _loop is not None:
        return _loop
    _loop = asyncio.new_event_loop()

    def _run():
        asyncio.set_event_loop(_loop)
        _loop.run_forever()

    _loop_thread = threading.Thread(target=_run, name="gemini-loop", daemon=True)
    _loop_thread.start()
    return _loop


def _run_coro(coro, timeout=300):
    loop = _ensure_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=timeout)


async def _build_client(key, psid, psidts):
    from gemini_webapi import GeminiClient
    client = GeminiClient(secure_1psid=psid, secure_1psidts=psidts)
    # cookie 处于降级状态时库会等到 timeout 附近；压到 90s 避免死等 450s
    client.timeout = 90
    await client.init(timeout=120, auto_close=False, auto_refresh=True, refresh_interval=600)
    logger.info("GeminiClient ready for account %s", key)
    return client


def _resolve_model(model_name):
    """把客户端传的模型名解析成账号实际支持的 AvailableModel。

    库的 resolve_model 本身带模糊匹配（pro->gemini-pro, gemini-3.8-flash->gemini-flash），
    所以官方模型名换了也不用改代码。解析失败返回 None，让库用默认模型。
    """
    if not model_name:
        return None
    try:
        return _client.resolve_model(model_name)
    except Exception as e:
        logger.warning("resolve model %r failed (%s), fallback to default", model_name, e)
        return None


def ensure_ready(model_name=None):
    global _client, _session, _client_key, _current_model_name
    k, psid, psidts, auth_user = pool.get_cookies()
    if not psid:
        raise RuntimeError("账号池里没有可用的 __Secure-1PSID")
    with _lock:
        # 换号了：client + session 全部重建
        if _client is None or _client_key != k:
            logger.info("building client for account %s (old=%s)", k, _client_key)
            if _client is not None:
                try:
                    _run_coro(_client.close(), timeout=10)
                except Exception as e:
                    logger.warning("close old client failed: %s", e)
            _client = _run_coro(_build_client(k, psid, psidts), timeout=180)
            _client_key = k
            _session = None
            _current_model_name = None
        # 模型变了才重建 session（client 保留，避免重复 init）
        resolved = _resolve_model(model_name)
        resolved_name = getattr(resolved, "model_name", None)
        if _session is None or resolved_name != _current_model_name:
            _session = _client.start_chat(model=resolved)
            _current_model_name = resolved_name
            logger.info("session ready (account=%s, requested=%r -> %r)",
                        k, model_name, resolved_name)
        return _session, k


_send_lock = threading.Lock()


def send(prompt, timeout=300, model=None):
    # 串行化：同一个 ChatSession 不能并发灌多条，否则 Gemini 端会串轮次
    with _send_lock:
        session, key = ensure_ready(model_name=model)

        async def _do():
            return await session.send_message(prompt)

        resp = _run_coro(_do(), timeout=timeout)
        text = getattr(resp, "text", None)
        if text is None:
            text = str(resp)
        return text, key


def list_models():
    """实时拉取当前账号支持的模型列表（给 /v1/models 端点用）。"""
    ensure_ready()
    with _lock:
        try:
            return _client.list_models() or []
        except Exception as e:
            logger.warning("list_models failed: %s", e)
            return []


def status():
    return {
        "client_key": _client_key,
        "has_client": _client is not None,
        "has_session": _session is not None,
        "current_model": _current_model_name,
        "cid": getattr(_session, "cid", None) if _session else None,
    }
