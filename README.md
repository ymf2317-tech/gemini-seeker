# gemini-seeker

把 **Gemini 网页版**（gemini.google.com，用你自己的账号 cookie）转成
**OpenAI / Anthropic 兼容 API** 的轻量桥接服务。

- 协议：OpenAI `/v1/chat/completions`（含流式）+ Anthropic `/v1/messages`
- 工具调用：支持多轮 tool_calls 回传（标准 OpenAI 协议）
- 号池：读 `accounts.json`，支持多账号 + 面板热切换（短 TTL 重读）
- 会话：常驻一个 ChatSession，保留最近 N 轮 history

> ⚠️ 本项目通过逆向 Gemini 网页接口实现，仅供个人学习与自用。
> 请遵守 Google 服务条款，不要用于商业或滥用场景。cookie 是你的登录凭证，务必保密。

## 原理

```
客户端(OpenAI/Anthropic 协议)
        │
        ▼
   app.py (Flask)          ← 解析 messages / tools，拼 prompt
        │
        ▼
  gemini_seeker/session.py  ← gemini_webapi 常驻 ChatSession + 线程锁
        │
        ▼
  gemini_seeker/pool.py     ← 读 accounts.json 拿 cookie
        │
        ▼
   gemini_webapi  →  gemini.google.com
```

Gemini 网页端不认原生 tools 字段，所以用「prompt 桥接」：把工具定义写进 system prompt，
要求模型只输出 JSON（`{"tool_calls":[...]}` 或 `{"content":"..."}`），
`parser.py` 再把模型输出宽容地解析回标准格式。

## 目录结构

```
gemini-seeker/
├── app.py                  # Flask 主入口
├── requirements.txt
├── gemini_seeker/
│   ├── __init__.py
│   ├── pool.py             # 账号池读取
│   ├── session.py          # client + 常驻会话 + 锁
│   ├── prompt.py           # 工具桥接 prompt
│   └── parser.py           # 宽容解析模型输出
├── deploy/
│   ├── gemini-seeker.service
│   └── Caddyfile.example
└── config.example.json     # accounts.json 示例
```

## 安装

### 1. 依赖

```bash
git clone <repo-url> /root/gemini-seeker
cd /root/gemini-seeker
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`requirements.txt`：

```
flask>=3.0
requests>=2.31
gemini-webapi>=2.1.1
```

### 2. 账号池 `accounts.json`

放在项目根目录（默认路径 `/root/gemini-panel/accounts.json`，可用环境变量 `GEMINI_POOL_PATH` 改）。

```json
{
  "A": {
    "name": "账号A",
    "cookies": "__Secure-1PSID=g.a000...; __Secure-1PSIDTS=sidts...",
    "auth_user": ""
  },
  "B": {
    "name": "账号B",
    "cookies": "__Secure-1PSID=g.a000...; __Secure-1PSIDTS=sidts...",
    "auth_user": ""
  }
}
```

**怎么拿 cookie**：浏览器登录 gemini.google.com → F12 → Application → Cookies →
复制 `__Secure-1PSID` 和 `__Secure-1PSIDTS` 两个值，拼成 `key=value; key=value` 格式。

> cookie 会过期。一旦日志出现 `Account status: UNAUTHENTICATED`，响应会变得极慢（库走降级慢路径），
> 需要重新登录、更新 cookie。

### 3. 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `GEMINI_SEEKER_API_KEY` | 空 | 客户端鉴权 key；空则不校验 |
| `GEMINI_SEEKER_HISTORY_TURNS` | 3 | 保留最近几轮 history |
| `GEMINI_POOL_PATH` | `/root/gemini-panel/accounts.json` | 账号池路径 |
| `GEMINI_POOL_DEFAULT` | `A` | 默认用哪个号 |
| `GEMINI_POOL_TTL` | 3 | 账号池缓存秒数 |

### 4. 启动

```bash
.venv/bin/python app.py        # 监听 0.0.0.0:4983
```

或直接用 systemd（见 `deploy/`）。

## 客户端接入（RikkaHub / 任意 OpenAI 客户端）

| 字段 | 值 |
|---|---|
| Base URL | `https://your-domain.example` |
| API 路径 | `/v1/chat/completions` |
| API Key | 你设的 `GEMINI_SEEKER_API_KEY` |
| 模型名 | 任意（服务忽略，如 `gemini-3.8-flash`） |

> 注意路径要带 `/v1`。有的客户端 Base URL 里已含 `/v1`，此时路径填 `/chat/completions`。

Anthropic 协议端点：`/v1/messages`。

## 接口

- `GET /health` — 健康检查，返回当前账号/会话状态
- `POST /v1/chat/completions` — OpenAI 协议（支持 `stream`）
- `POST /v1/messages` — Anthropic 协议

## 已知现象

- **cookie 失效 → 极慢**：库走降级路径，一次要等几十秒。刷新 cookie 即恢复。
- **并发**：同一时刻只允许一个请求进会话（已加锁）；客户端并发多发时其余会排队。
- **usage 字段**：token 统计为 0（未实现），不影响功能。

## License

MIT（`parser.py` 改编自 deeperseeker，发布公开仓库前请确认其 license）。
