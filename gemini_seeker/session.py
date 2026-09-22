"""Gemini 会话管理层：封装 gemini_webapi + 常驻 ChatSession + 号池切换。"""

import asyncio
import logging
import threading

from . import pool

logger = logging.getLogger("gemini_seeker.session")

_client = None
_session = None
_client_key = None
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


def ensure_ready():
    global _client, _session, _client_key
    k, psid, psidts, auth_user = pool.get_cookies()
    if not psid:
        raise RuntimeError("账号池里没有可用的 __Secure-1PSID")
    with _lock:
        if _client is not None and _client_key == k:
            return _session, k
        logger.info("building client for account %s (old=%s)", k, _client_key)
        if _client is not None:
            try:
                _run_coro(_client.close(), timeout=10)
            except Exception as e:
                logger.warning("close old client failed: %s", e)
        _client = _run_coro(_build_client(k, psid, psidts), timeout=180)
        _session = _client.start_chat()
        _client_key = k
        return _session, k


_send_lock = threading.Lock()


def send(prompt, timeout=300):
    # 串行化：同一个 ChatSession 不能并发灌多条，否则 Gemini 端会串轮次
    with _send_lock:
        session, key = ensure_ready()

        async def _do():
            return await session.send_message(prompt)

        resp = _run_coro(_do(), timeout=timeout)
        text = getattr(resp, "text", None)
        if text is None:
            text = str(resp)
        return text, key


def status():
    return {
        "client_key": _client_key,
        "has_client": _client is not None,
        "has_session": _session is not None,
        "cid": getattr(_session, "cid", None) if _session else None,
    }
