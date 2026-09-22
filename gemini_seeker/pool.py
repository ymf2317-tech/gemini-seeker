"""账号池：读 gemini-panel 的 accounts.json，默认用 A 号。"""

import json
import os
import time

POOL_PATH = os.environ.get("GEMINI_POOL_PATH", "/root/gemini-panel/accounts.json")
DEFAULT_KEY = os.environ.get("GEMINI_POOL_DEFAULT", "A")
_CACHE_TTL = float(os.environ.get("GEMINI_POOL_TTL", "3"))

_cache = {"ts": 0.0, "pool": None}


def _load_raw():
    with open(POOL_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_pool(force=False):
    now = time.time()
    if not force and _cache["pool"] is not None and now - _cache["ts"] < _CACHE_TTL:
        return _cache["pool"]
    pool = _load_raw()
    _cache["pool"] = pool
    _cache["ts"] = now
    return pool


def get_account(key=None):
    pool = load_pool()
    if not isinstance(pool, dict) or not pool:
        return None, None
    want = key or DEFAULT_KEY
    if want in pool and isinstance(pool[want], dict):
        return want, pool[want]
    for k, v in pool.items():
        if isinstance(v, dict) and v.get("cookies"):
            return k, v
    return None, None


def parse_cookie_header(header):
    out = {}
    if not header:
        return out
    for part in header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def get_cookies(key=None):
    k, acct = get_account(key)
    if not acct:
        return None, None, None, None
    header = acct.get("cookies", "")
    parsed = parse_cookie_header(header)
    psid = parsed.get("__Secure-1PSID")
    psidts = parsed.get("__Secure-1PSIDTS")
    auth_user = acct.get("auth_user", "") or None
    return k, psid, psidts, auth_user


if __name__ == "__main__":
    k, psid, psidts, au = get_cookies()
    if k:
        print("key=%s psid_len=%s psidts=%s" % (k, len(psid) if psid else 0, bool(psidts)))
    else:
        print("no account found")
