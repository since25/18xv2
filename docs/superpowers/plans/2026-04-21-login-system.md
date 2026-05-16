# 域名访问登录系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为当前 18x_v2 系统增加一个单管理员登录系统，支持通过 Lucky 反向代理后的域名安全访问，避免未登录状态下暴露管理页面、115 token/cookies 相关接口和敏感操作。

**Architecture:** 采用“单管理员账号 + 服务端会话 Cookie + FastAPI 鉴权依赖/中间件 + 前端登录页”的方案。管理员用户名从 `.env` 读取；首次启动时若未初始化密码，则自动生成随机密码、只在容器日志打印一次，并将密码哈希持久化到 `data/`。Lucky 负责 HTTPS 与域名反代，应用自身负责登录态校验与受保护 API 拦截。

**Tech Stack:** FastAPI, SQLAlchemy (existing), Pydantic Settings, secure password hashing (`pwdlib` or `passlib[bcrypt]`), signed session cookie, React + Vite frontend, Nginx, Lucky reverse proxy

---

## 文件清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `app/core/config.py` | 修改 | 增加认证与代理相关配置 |
| `app/core/auth.py` | 新增 | 认证配置、密码生成、哈希校验、Cookie 工具 |
| `app/services/auth/bootstrap.py` | 新增 | 首次启动初始化管理员密码并持久化 |
| `app/services/auth/session_store.py` | 新增 | 登录会话读写与校验 |
| `app/services/auth/user_store.py` | 新增 | 单管理员凭据持久化到 `data/auth.json` |
| `app/api/deps.py` | 修改 | 增加“当前登录用户”依赖 |
| `app/api/routes/auth.py` | 新增 | `login/logout/me` 接口 |
| `app/main.py` | 修改 | 注册认证路由；在启动阶段执行认证初始化；加入代理信任与鉴权中间层 |
| `frontend/src/api/types.ts` | 修改 | 增加认证相关响应类型 |
| `frontend/src/api/client.ts` | 修改 | 请求默认带 cookie；统一处理 401 |
| `frontend/src/pages/LoginPage.tsx` | 新增 | 登录页 |
| `frontend/src/App.tsx` | 修改 | 增加登录路由、登录守卫、退出入口 |
| `frontend/src/utils/format.ts` | 如需 | 仅在登录页或会话页需要额外格式化时调整 |
| `docker/README.md` | 修改 | 增加首次启动密码、Lucky 配置、域名访问说明 |
| `.env.example` | 修改 | 增加认证配置项示例 |
| `tests/auth/test_bootstrap.py` | 新增 | 首次启动初始化与“只打印一次”行为测试 |
| `tests/auth/test_auth_routes.py` | 新增 | 登录/登出/会话校验测试 |
| `tests/auth/test_protected_routes.py` | 新增 | 未登录禁止访问敏感接口测试 |

---

### Task 1：补齐认证配置与持久化设计

**Files:**
- Modify: `app/core/config.py`
- Create: `app/core/auth.py`
- Create: `app/services/auth/user_store.py`
- Create: `app/services/auth/bootstrap.py`
- Modify: `.env.example`

- [ ] **Step 1：在配置中增加认证项**

在 `app/core/config.py` 的 `Settings` 中增加以下配置：

```python
    auth_enabled: bool = Field(default=True, alias="AUTH_ENABLED")
    auth_username: str = Field(default="wang", alias="AUTH_USERNAME")
    auth_session_secret: str = Field(default="change-me-in-env", alias="AUTH_SESSION_SECRET")
    auth_cookie_name: str = Field(default="18x_session", alias="AUTH_COOKIE_NAME")
    auth_cookie_secure: bool = Field(default=True, alias="AUTH_COOKIE_SECURE")
    auth_cookie_samesite: str = Field(default="lax", alias="AUTH_COOKIE_SAMESITE")
    auth_session_ttl_hours: int = Field(default=24, alias="AUTH_SESSION_TTL_HOURS")
    auth_trust_proxy: bool = Field(default=True, alias="AUTH_TRUST_PROXY")
    auth_store_path: str = Field(default="data/auth.json", alias="AUTH_STORE_PATH")
```

- [ ] **Step 2：在 `.env.example` 中补充认证配置示例**

追加类似内容：

```env
AUTH_ENABLED=true
AUTH_USERNAME=wang
AUTH_SESSION_SECRET=replace-with-a-long-random-secret
AUTH_COOKIE_NAME=18x_session
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=lax
AUTH_SESSION_TTL_HOURS=24
AUTH_TRUST_PROXY=true
AUTH_STORE_PATH=data/auth.json
```

- [ ] **Step 3：设计 `data/auth.json` 持久化格式**

在 `app/services/auth/user_store.py` 中约定存储格式：

```json
{
  "username": "wang",
  "password_hash": "<hash>",
  "password_initialized_at": "2026-04-21T12:00:00+08:00",
  "password_printed_once": true
}
```

要求：
- 文件不存在时视为未初始化
- 文件存在但用户名与 `.env` 不一致时，保留现有 hash，但记录 warning
- 只支持单管理员，不支持多用户列表

- [ ] **Step 4：实现首次启动密码初始化器**

在 `app/services/auth/bootstrap.py` 中实现：

```python
def ensure_admin_password_initialized() -> None:
    """
    如果 data/auth.json 不存在：
    1. 生成随机密码
    2. 计算密码哈希
    3. 写入 auth.json
    4. 仅打印一次明文密码到日志
    如果已存在：
    1. 不再打印密码
    2. 直接跳过
    """
```

行为要求：
- 首次启动打印类似：

```text
[auth-init] admin username: wang
[auth-init] initial password (shown only once): <generated-password>
```

- 后续启动只打印：

```text
[auth-init] admin password already initialized; skip password generation
```

- [ ] **Step 5：实现密码生成与哈希工具**

在 `app/core/auth.py` 中实现：
- 高强度随机密码生成
- 密码哈希
- 密码校验

推荐接口：

```python
def generate_initial_password(length: int = 20) -> str: ...
def hash_password(password: str) -> str: ...
def verify_password(password: str, password_hash: str) -> bool: ...
```

密码要求：
- 长度至少 20
- 含大小写字母与数字
- 避免容易混淆字符可选

- [ ] **Step 6：为首次启动逻辑写测试**

在 `tests/auth/test_bootstrap.py` 中覆盖：
- 首次启动会创建 `auth.json`
- 首次启动会生成 hash 且可校验
- 第二次启动不会覆盖已有 hash
- 第二次启动不会重复输出明文密码

- [ ] **Step 7：运行测试**

Run:

```bash
pytest tests/auth/test_bootstrap.py -v
```

Expected:

```text
PASS
```

- [ ] **Step 8：commit**

```bash
git add app/core/config.py app/core/auth.py app/services/auth/user_store.py app/services/auth/bootstrap.py .env.example tests/auth/test_bootstrap.py
git commit -m "feat(auth): add single-admin bootstrap config and password initialization"
```

---

### Task 2：实现服务端登录会话

**Files:**
- Create: `app/services/auth/session_store.py`
- Create: `app/api/routes/auth.py`
- Modify: `app/api/deps.py`
- Modify: `app/main.py`
- Test: `tests/auth/test_auth_routes.py`

- [ ] **Step 1：定义会话数据模型与存储方式**

会话存储采用服务器本地持久化文件或内存+签名 Cookie 两种里更简单的一种。为降低复杂度，优先实现：
- Cookie 中只保存随机 session id
- 服务端将 session 映射写入 `data/auth_sessions.json`

建议结构：

```json
{
  "sessions": [
    {
      "session_id": "uuid",
      "username": "wang",
      "created_at": "2026-04-21T12:00:00+08:00",
      "expires_at": "2026-04-22T12:00:00+08:00"
    }
  ]
}
```

- [ ] **Step 2：实现登录接口**

在 `app/api/routes/auth.py` 中新增：

```python
@router.post("/login")
def login(...): ...
```

行为：
- 校验用户名必须等于 `.env` 中 `AUTH_USERNAME`
- 校验密码哈希
- 登录成功后：
  - 创建 session
  - 通过 `response.set_cookie(...)` 写入 HttpOnly Cookie
- 登录失败返回 401

- [ ] **Step 3：实现登出与当前用户接口**

新增：

```python
@router.post("/logout")
def logout(...): ...

@router.get("/me")
def me(...): ...
```

要求：
- `/me` 用于前端判断是否已登录
- `logout` 删除服务端 session 并清 Cookie

- [ ] **Step 4：增加鉴权依赖**

在 `app/api/deps.py` 增加：

```python
def require_authenticated_user(request: Request) -> str:
    """返回当前管理员用户名；未登录则抛 401。"""
```

并提供：

```python
def optional_authenticated_user(request: Request) -> str | None:
    ...
```

- [ ] **Step 5：在 `app/main.py` 中挂载认证路由并执行启动初始化**

要求：
- `lifespan` 中在 115 client 初始化前后调用 `ensure_admin_password_initialized()`
- 注册 `auth.router`

- [ ] **Step 6：保护敏感 API**

对以下路由逐步接入 `Depends(require_authenticated_user)`：
- plans 写操作
- jobs/tasks 写操作
- imports/cleanup/extractor 等管理型接口
- `/tools/auth-code`
- `/tools/qr-login`
- `/system-status`

说明：
- `/healthz` 保持公开
- 前端静态资源保持公开

- [ ] **Step 7：写认证接口测试**

在 `tests/auth/test_auth_routes.py` 覆盖：
- 正确用户名+密码可登录
- 错误密码返回 401
- `/me` 未登录返回 401
- 登录后 `/me` 返回 `wang`
- 登出后 `/me` 再次返回 401

- [ ] **Step 8：运行测试**

Run:

```bash
pytest tests/auth/test_auth_routes.py -v
```

Expected:

```text
PASS
```

- [ ] **Step 9：commit**

```bash
git add app/services/auth/session_store.py app/api/routes/auth.py app/api/deps.py app/main.py tests/auth/test_auth_routes.py
git commit -m "feat(auth): add single-admin session login routes"
```

---

### Task 3：前端接入登录页与登录守卫

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/pages/LoginPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/index.css`（若需要）

- [ ] **Step 1：补充认证接口类型**

在 `frontend/src/api/types.ts` 中新增：

```ts
export interface AuthMeResponse {
  username: string
}

export interface LoginResponse {
  success: boolean
  username: string
}
```

- [ ] **Step 2：让 fetch 默认携带 cookie**

在 `frontend/src/api/client.ts` 中为请求增加：

```ts
credentials: 'include'
```

并在 401 时抛出可识别错误，供页面跳转登录。

- [ ] **Step 3：新增登录页**

创建 `frontend/src/pages/LoginPage.tsx`，包含：
- 用户名输入框（默认可预填 `wang`）
- 密码输入框
- 登录按钮
- 登录失败提示

登录成功后跳转到首页或来源页。

- [ ] **Step 4：在 App 中增加登录态检查**

在 `frontend/src/App.tsx` 中：
- 增加 `/login` 路由
- 应用加载时请求 `/api/auth/me`
- 未登录访问管理页时跳转到 `/login`
- 右上角增加当前用户与“退出登录”按钮

- [ ] **Step 5：保护现有页面**

保护这些前端页面：
- 授权中心
- 计划页
- 执行页
- 导入页
- 关键词页
- 设置页

未登录时不允许直接进入。

- [ ] **Step 6：前端本地验证**

Run:

```bash
cd frontend
npm run build
```

Expected:

```text
vite build 成功
```

- [ ] **Step 7：commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/pages/LoginPage.tsx frontend/src/App.tsx frontend/src/index.css
git commit -m "feat(auth): add login page and frontend auth guard"
```

---

### Task 4：Lucky 反代与代理信任收口

**Files:**
- Modify: `app/main.py`
- Modify: `docker/README.md`

- [ ] **Step 1：确保应用信任反向代理头**

应用需要正确识别 Lucky 透传的：
- `X-Forwarded-Proto`
- `X-Forwarded-Host`

要求：
- 生产 Cookie 在域名 HTTPS 下使用 `Secure`
- 后端不要把自身误判成 `http://127.0.0.1:8010`

- [ ] **Step 2：在部署文档中加入 Lucky 配置说明**

在 `docker/README.md` 中增加：
- Lucky 反代到 `http://<server-ip>:8010`
- 域名必须启用 HTTPS
- 反代时保留 `Host`
- 传递 `X-Forwarded-Proto=https`

- [ ] **Step 3：补充首次启动密码说明**

文档明确写出：
- 首次启动会在容器日志打印一次初始密码
- 记录后需自行保存
- 后续不会再次显示
- 如需重置密码，删除 `data/auth.json` 后重建容器

- [ ] **Step 4：commit**

```bash
git add app/main.py docker/README.md
git commit -m "docs(auth): document lucky reverse proxy and one-time password bootstrap"
```

---

### Task 5：保护敏感接口并补回归测试

**Files:**
- Modify: `app/api/routes/auth_code.py`
- Modify: `app/api/routes/qr_login.py`
- Modify: `app/api/routes/plans.py`
- Modify: `app/api/routes/imports.py`
- Modify: `app/api/routes/keywords.py`
- Test: `tests/auth/test_protected_routes.py`

- [ ] **Step 1：梳理敏感接口列表**

最少保护：
- `/api/plans/batch-execute`
- `/api/plans/batch-delete`
- `/api/tools/auth-code`
- `/api/tools/qr-login/*`
- `/api/imports/*`
- `/api/keywords/*` 的写接口

- [ ] **Step 2：为这些接口加统一鉴权依赖**

要求：
- 未登录返回 401 JSON
- 登录后正常访问
- 公开接口仅保留：
  - `/api/healthz`
  - `/api/auth/login`
  - `/api/auth/logout`
  - `/api/auth/me`

- [ ] **Step 3：写保护接口测试**

在 `tests/auth/test_protected_routes.py` 中覆盖：
- 未登录调用批量执行返回 401
- 未登录访问授权码接口返回 401
- 登录后可访问

- [ ] **Step 4：运行测试**

Run:

```bash
pytest tests/auth/test_protected_routes.py -v
```

Expected:

```text
PASS
```

- [ ] **Step 5：跑完整关键测试**

Run:

```bash
pytest tests/auth tests/client_115 tests/planner -v
cd frontend && npm run build
```

Expected:

```text
后端测试通过，前端构建通过
```

- [ ] **Step 6：commit**

```bash
git add app/api/routes/auth_code.py app/api/routes/qr_login.py app/api/routes/plans.py app/api/routes/imports.py app/api/routes/keywords.py tests/auth/test_protected_routes.py
git commit -m "feat(auth): protect sensitive management and 115 credential routes"
```

---

### Task 6：容器与域名联调验收

**Files:**
- Modify: `docker/README.md`（如联调后需补充）

- [ ] **Step 1：重建容器**

Run:

```bash
cd docker
docker compose up -d --build --force-recreate
```

- [ ] **Step 2：检查首次启动日志**

Run:

```bash
docker logs --tail 200 docker-app-1
```

Expected:
- 首次部署时看到一次初始密码打印
- 二次重启后不再打印

- [ ] **Step 3：联调 Lucky 域名**

验证：
- 使用域名访问首页会进入登录页
- 登录成功后能进入前端
- `/api/healthz` 正常
- 未登录无法访问敏感接口

- [ ] **Step 4：记录上线结果**

在 `docker/README.md` 或 `PROGRESS.md` 增加一条上线记录，说明：
- 已启用单管理员登录
- Lucky 域名接入完成
- 首次密码生成流程验证通过

- [ ] **Step 5：commit**

```bash
git add docker/README.md PROGRESS.md
git commit -m "chore(auth): verify domain login flow behind lucky proxy"
```

---

## 风险与注意事项

- 单管理员密码只打印一次，任何能查看 Docker 日志的人都能看到初始密码；需要控制服务器与日志权限。
- Lucky 反代必须是 HTTPS，否则 `Secure` Cookie 在生产模式下不会回传。
- 如果 SQLite 对 `DateTime(timezone=True)` 仍返回无时区字符串，前端或 API 层需保持统一时区处理，避免登录审计时间混乱。
- `data/auth.json` 属于敏感文件，应和 `data/tokens.json` 一样纳入持久化但避免公开下载或暴露。
- 后续若需要二次验证、IP 白名单、密码重置页，应另开计划，不要在本期里扩大范围。

---

## 验收标准

- 未登录时，域名访问系统只能进入登录页。
- 登录成功后，可正常访问前端与受保护 API。
- 115 token/cookies 相关接口不会在未登录状态下暴露。
- 管理员用户名来自 `.env`，密码首次启动随机生成并只打印一次。
- Lucky 反代下 Cookie 可正常工作，且为 `HttpOnly + Secure + SameSite`。
- 容器重启后，管理员密码与登录系统状态保持不变。
