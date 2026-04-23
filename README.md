## protect_zyy
多语种（中/日/韩/英/泰）饭圈社区风控 **Agent Demo**：将“风控决策”映射为前端可见动作（安全放行/警告打码/违规盲盒遮挡），并提供翻译、点赞、回复、简易数据看板。

运行要求
- Python 3.11+


启动后直接打开：
- 页面体验：`http://127.0.0.1:8001/app`
- API 文档：`http://127.0.0.1:8001/docs`

你会看到：
- 打开即有 50 条模拟评论（显得社区真实热闹）
- 风控动作：安全=绿正常显示；警告=黄自动打码；违规=红盲盒遮挡可点开
- 每条评论：点赞 / 回复 / 翻译
- 右下角 AI 助手：可对“当前输入”给出风险判断与发言建议

### 火山引擎（语义风控）
本项目支持接入火山引擎（Ark）让风控不只靠“死词典”，而是能识别变体、隐晦表达和多语种语义。

1. 复制配置文件并填写你的信息：

```bash
copy .env.example .env
```

2. 在 `.env` 里填写：
- `VOLC_API_KEY`
- `VOLC_MODEL`
- （可选）`VOLC_BASE_URL`（默认 `https://ark.cn-beijing.volces.com`）
- （可选）`VOLC_LLM_MODE`：`smart`（默认）/ `always` / `off`（或 `fast_only`）
- （可选）`VOLC_TIMEOUT_S`：接口超时（秒，默认 12）
- （可选）`SEVERITY_LOW_MAX` / `SEVERITY_MED_MAX`：把 0-100 分映射为 **LOW / MED / HIGH** 三档

如果不配置 `.env`，系统会自动降级为“规则版风控”（仍可跑通三振/复核/改判闭环）。



### 指标看板 / API
- 本地看板页面：`http://127.0.0.1:8001/ui`
- 面向用户的清新版界面：`http://127.0.0.1:8001/app`（支持自定义背景）
- 指标 JSON：`http://127.0.0.1:8001/v1/metrics/summary?days=7`
- 在 `POST /v1/comments` 的返回里，你会看到 `moderation.severity`（三档）以及 `moderation.llm_used / llm_model / llm_error`

### 关键 API（便于验收/演示）
- `POST /v1/comments`：发表评论（游客昵称= `username`）
- `GET /v1/comments`：获取帖子列表（默认只取主贴）
- `POST /v1/comments/{id}/like`：点赞
- `GET /v1/comments/{id}/replies`：查看回复
- `POST /v1/comments/{id}/translate`：翻译某条后端评论
- `POST /v1/translate`：翻译任意文本（用于前端模拟评论）
- `POST /v1/agent/advice`：对任意文本给出风险判断与建议（用于右下角 AI 助手）

### 安装依赖
在项目目录下执行：

```bash
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -U pip
pip install -r requirements.txt
```

### 启动服务

```bash
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8001
```

启动后访问：
- API 文档：`http://127.0.0.1:8001/docs`
- 健康检查：`http://127.0.0.1:8001/healthz`


1. 创建/获取用户（自动创建）并发表评论（会触发风控判定）
2. 如果同一用户累计违规达到 3 次，会自动封禁（ban）

你可以在 Swagger (`/docs`) 里按顺序调用：
- `POST /v1/comments` 连续发 3 条明显违规内容（例如英文 `idiot/stupid/trash` 或中文明显辱骂）观察三振封禁
- `GET /v1/comments?limit=20` 查看“历史评论列表”（Swagger 的 Reset/Cancel 只会清空页面输入，不会清空数据库）
- `GET /v1/comments?limit=20&username=test1` 只看某个用户的评论（避免你以为“重复/对称”）
- `GET /v1/users/{user_id}` 查看 strikes 与是否被封禁
- `GET /v1/users/by-username/{username}` 通过用户名查 user_id（复制到上一条）
- `GET /v1/users/{user_id}/penalties` 查看三振过程（STRIKE_ADDED/BANNED 等事件）
- `GET /v1/review-queue` 查看复核队列
- `POST /v1/admin/comments/{id}/override` 运营/管理员改判（从 `GET /v1/review-queue` 或 `GET /v1/comments` 里复制 `id`）

如果你想清空演示数据（避免旧评论干扰），用：
- `POST /v1/admin/demo/reset`



