#!/usr/bin/env python3
"""Gemini Cookie 管理面板 —— 多号池 + 一键切换（AJAX 版）"""
import os, re, json, html, time, subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

POOL  = "/root/gemini-panel/accounts.json"
ENV   = "/root/gemini-seeker/.env"   # gemini-seeker 的 env（切号只改 systemd，这里保留兼容）
SVC   = "gemini-seeker.service"
PORT  = 4982
API_URL = "http://127.0.0.1:4983/health"
API_KEY = "ky-ymf050334"


def load_pool():
    if os.path.exists(POOL):
        try:
            return json.load(open(POOL))
        except Exception:
            return {}
    return {}

def save_pool(pool):
    json.dump(pool, open(POOL, "w"), ensure_ascii=False, indent=2)

def read_env():
    d = {}
    if os.path.exists(ENV):
        for line in open(ENV):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d

def write_env(cookies, auth_user=""):
    env = read_env()
    env["GEMINI_COOKIES"] = cookies
    env["GEMINI_AUTH_USER"] = auth_user
    order = ["PORT","LOG_LEVEL","APP_ENV","RATE_LIMIT_ENABLED","RATE_LIMIT_WINDOW_MS",
             "RATE_LIMIT_MAX_REQUESTS","GEMINI_COOKIES","GEMINI_AUTH_USER",
             "GEMINI_REFRESH_INTERVAL","GEMINI_MAX_RETRIES","GEMINI_TEMPORARY"]
    lines = ["# managed by panel"]
    for k in order:
        if k in env:
            lines.append(f"{k}={env[k]}")
    for k, v in env.items():
        if k not in order:
            lines.append(f"{k}={v}")
    open(ENV, "w").write("\n".join(lines) + "\n")

def _psid_of(ck):
    m = re.search(r"__Secure-1PSID=([^;]+)", ck or "")
    return m.group(1) if m else ""

def current_key():
    # gemini-seeker 用 systemd 的 GEMINI_POOL_DEFAULT 决定默认号
    try:
        out = subprocess.run(
            ["systemctl", "show", SVC, "-p", "Environment"],
            capture_output=True, text=True, timeout=10).stdout
        m = re.search(r"GEMINI_POOL_DEFAULT=([A-Za-z0-9_]+)", out)
        if m:
            return m.group(1)
    except Exception:
        pass
    # 回退：对比号池第一个槽
    pool = load_pool()
    return next(iter(pool), "") if pool else ""


def set_default_key(slot):
    """把 gemini-seeker 的 GEMINI_POOL_DEFAULT 改成 slot，并重启。"""
    unit = "/etc/systemd/system/gemini-seeker.service"
    try:
        txt = open(unit, encoding="utf-8").read()
    except Exception as e:
        return False, f"读 unit 失败: {e}"
    if "GEMINI_POOL_DEFAULT=" in txt:
        txt = re.sub(r"GEMINI_POOL_DEFAULT=[A-Za-z0-9_]+",
                     f"GEMINI_POOL_DEFAULT={slot}", txt)
    else:
        txt = txt.replace("[Service]", f"[Service]\nEnvironment=GEMINI_POOL_DEFAULT={slot}", 1)
    open(unit, "w", encoding="utf-8").write(txt)
    subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
    subprocess.run(["systemctl", "restart", SVC], capture_output=True)
    time.sleep(2)
    return True, slot


def svc_state():
    return subprocess.run(["systemctl","is-active",SVC],
                          capture_output=True,text=True).stdout.strip()

def restart_svc():
    subprocess.run(["systemctl","restart",SVC], capture_output=True)
    time.sleep(3)

def test_cookie_effective():
    try:
        r = subprocess.run(["curl","-s","-o","/dev/null","-w","%{http_code}",
                            "-H", f"x-api-key: {API_KEY}", API_URL],
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip()
    except Exception:
        return "000"


PAGE = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gemini Cookie 面板</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:720px;margin:30px auto;padding:0 16px;background:#0f1115;color:#e6e6e6}}
h1{{font-size:20px}} h2{{font-size:15px;color:#9aa4b2;margin-top:24px}}
.box{{background:#1a1d23;border-radius:12px;padding:16px;margin:12px 0}}
label{{display:block;font-size:13px;color:#9aa4b2;margin:10px 0 4px}}
textarea,input,select{{width:100%;box-sizing:border-box;background:#0f1115;color:#e6e6e6;border:1px solid #2a2f3a;border-radius:8px;padding:10px;font-family:ui-monospace,monospace;font-size:13px}}
textarea{{min-height:120px}}
button{{background:#3b82f6;color:#fff;border:0;border-radius:8px;padding:10px 16px;font-size:14px;cursor:pointer;margin:8px 6px 0 0}}
button:hover{{background:#2563eb}}
button.danger{{background:#374151}} button.danger:hover{{background:#4b5563}}
button:disabled{{opacity:.5;cursor:wait}}
.ok{{color:#4ade80}} .err{{color:#f87171}} .muted{{color:#6b7280;font-size:12px}}
.status{{font-size:13px;line-height:1.8}}
.acct{{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border:1px solid #2a2f3a;border-radius:10px;margin:8px 0;gap:10px;flex-wrap:wrap}}
.acct .meta{{font-size:12px;color:#9aa4b2;word-break:break-all}}
.badge{{font-size:11px;padding:2px 8px;border-radius:999px;background:#16a34a;color:#fff;margin-left:6px}}
#toast{{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);max-width:90%;padding:12px 18px;border-radius:10px;font-size:14px;display:none;z-index:99;box-shadow:0 4px 20px rgba(0,0,0,.4)}}
#toast.ok{{background:#16a34a}} #toast.err{{background:#b91c1c}} #toast.info{{background:#374151}}
</style></head><body>
<h1>🔷 Gemini Cookie 面板</h1>
<div class="box"><div class="status" id="status">{status}</div></div>

<h2>号池（点一下切换）</h2>
<div id="pool">{acct_html}</div>

<h2>保存新 Cookie</h2>
<div class="box">
<label>存为哪个槽位</label>
<select id="slot">
  <option value="A">号 A</option>
  <option value="B">号 B</option>
  <option value="C">号 C</option>
</select>
<label>GEMINI_COOKIES（完整 Cookie 头）</label>
<textarea id="ck" placeholder="__Secure-1PSID=...; __Secure-1PSIDTS=...; NID=...">{cookies}</textarea>
<label>GEMINI_AUTH_USER（可选，如 URL 含 /u/2/ 则填 2，否则留空）</label>
<input id="au" value="{auth_user}">
<button onclick="doSave(false)">保存并激活此号</button>
<button class="danger" onclick="doSave(true)">仅保存不切换</button>
</div>
<p class="muted">「保存并激活」会写入 .env → 重启服务 → 自动实测 Cookie 有效性。</p>

<div id="toast"></div>
<script>
function toast(msg, kind){{
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.className = kind || 'info';
  t.style.display = 'block';
  clearTimeout(window._tt);
  window._tt = setTimeout(function(){{ t.style.display='none'; }}, 3500);
}}
function post(url, data){{
  return fetch(url, {{
    method:'POST',
    headers:{{'Content-Type':'application/x-www-form-urlencoded'}},
    body: new URLSearchParams(data).toString()
  }}).then(function(r){{ return r.json(); }});
}}
function refresh(){{
  fetch(location.pathname, {{headers:{{'X-Refresh':'1'}}}})
    .then(function(r){{ return r.text(); }})
    .then(function(html){{
      var doc = new DOMParser().parseFromString(html, 'text/html');
      document.getElementById('status').innerHTML = doc.getElementById('status').innerHTML;
      document.getElementById('pool').innerHTML   = doc.getElementById('pool').innerHTML;
    }});
}}
function doSwitch(slot, btn){{
  if(btn){{ btn.disabled = true; btn.textContent = '切换中…'; }}
  toast('正在切换到 ' + slot + ' …', 'info');
  post('/panel/switch', {{slot: slot}}).then(function(j){{
    if(j.ok){{ toast(j.msg, 'ok'); }}
    else    {{ toast(j.msg, 'err'); }}
    refresh();
    setTimeout(function(){{ if(btn){{ btn.disabled=false; btn.textContent='切换到 '+slot; }} }}, 1200);
  }}).catch(function(e){{
    toast('请求失败: ' + e, 'err');
    if(btn){{ btn.disabled=false; btn.textContent='切换到 '+slot; }}
  }});
}}
function doSave(onlySave){{
  var ck = document.getElementById('ck').value.trim();
  var au = document.getElementById('au').value.trim();
  var slot = document.getElementById('slot').value;
  if(ck.indexOf('__Secure-1PSID') < 0){{ toast('Cookie 里没找到 __Secure-1PSID', 'err'); return; }}
  toast('正在保存 …', 'info');
  post('/panel/save', {{slot:slot, cookies:ck, auth_user:au, only_save: onlySave?'1':'0'}}).then(function(j){{
    toast(j.msg, j.ok ? 'ok' : 'err');
    refresh();
  }}).catch(function(e){{ toast('请求失败: ' + e, 'err'); }});
}}
document.addEventListener('click', function(e){{
  var b = e.target.closest('button[data-switch]');
  if(b){{ doSwitch(b.getAttribute('data-switch'), b); }}
}});
</script>
</body></html>"""


def build_acct_html():
    pool = load_pool()
    cur = current_key()
    if not pool:
        return "<div class='box muted'>号池为空</div>"
    rows = []
    for k in sorted(pool.keys()):
        v = pool[k]
        ck = v.get("cookies", "")
        if ck:
            psid = _psid_of(ck)[:22] + "..."
            info = f"{html.escape(psid)} · {len(ck)} 字符 · 存于 {html.escape(v.get('saved_at',''))}"
        else:
            info = "（空槽位）"
        badge = "<span class='badge'>当前使用</span>" if k == cur else ""
        btn = (f"<button data-switch='{k}'>切换到 {k}</button>") if k != cur and ck else ""
        rows.append(
            f"<div class='acct'><div><b>{html.escape(v.get('name',k))}</b>{badge}"
            f"<div class='meta'>{info}</div></div><div>{btn}</div></div>")
    return "".join(rows)


def page(msg=""):
    env = read_env()
    ck  = env.get("GEMINI_COOKIES","")
    au  = env.get("GEMINI_AUTH_USER","")
    state = svc_state()
    cur = current_key()
    st = f"服务状态：<b class='{'ok' if state=='active' else 'err'}'>{state}</b>"
    st += f"　当前号：<b>{html.escape(cur) if cur else '未识别（Cookie 不在号池中）'}</b>"
    if ck:
        st += f"<br><span class='muted'>当前 Cookie：{html.escape(ck[:60])}...</span>"
    if msg:
        st = msg + "<br>" + st
    return PAGE.format(status=st, acct_html=build_acct_html(),
                       cookies=html.escape(ck), auth_user=html.escape(au))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _html(self, body):
        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def _json(self, ok, msg):
        self.send_response(200)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": ok, "msg": msg}, ensure_ascii=False).encode())

    def do_GET(self):
        self._html(page())

    def do_POST(self):
        n = int(self.headers.get("Content-Length",0))
        q = parse_qs(self.rfile.read(n).decode())
        path = self.path

        if path in ("/switch", "/panel/switch"):
            slot = q.get("slot",[""])[0]
            pool = load_pool()
            if slot not in pool or not pool[slot].get("cookies"):
                self._json(False, "该槽位没有 Cookie"); return
            ok, info = set_default_key(slot)
            if not ok:
                self._json(False, f"切换失败: {info}"); return
            code = test_cookie_effective()
            if code == "200":
                self._json(True, f"已把 {slot} 设为默认号，实测有效（HTTP 200）")
            else:
                self._json(False, f"已把 {slot} 设为默认号，但实测 HTTP {code}，Cookie 可能已过期")
            return

        # /save
        slot = q.get("slot",["A"])[0]
        ck   = q.get("cookies",[""])[0].strip()
        au   = q.get("auth_user",[""])[0].strip()
        only_save = q.get("only_save",[""])[0] == "1"
        if "__Secure-1PSID" not in ck:
            self._json(False, "Cookie 里没找到 __Secure-1PSID，未保存"); return
        pool = load_pool()
        pool.setdefault(slot, {"name": f"号 {slot}"})
        pool[slot]["cookies"] = ck
        pool[slot]["auth_user"] = au
        pool[slot]["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_pool(pool)
        if only_save:
            self._json(True, f"已保存到槽位 {slot}（未切换）"); return
        write_env(ck, au)
        restart_svc()
        code = test_cookie_effective()
        if code == "200":
            self._json(True, f"已保存并激活槽位 {slot}，实测有效（HTTP 200）")
        else:
            self._json(False, f"已保存并激活 {slot}，但实测 HTTP {code}")
        return


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()
