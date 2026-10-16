# qixi-guide · 编码代理约定（M3/M4/M6 已实现）

## 这是什么
「栖霞山小向导」——枫客松黑客松赛道二作品。本地 H5（PC 优先）：游客对话向导 + 示意地图 + 游后日记海报。
当前阶段：**M0–M4 + M6 主链路已跑通**（对话、地图、到点自动播报+语音、剧本演示、海报生成三候选+质检+导出）。
数据仍是骨架（10 点位 M5 补齐）；M8 视觉识别接了口，参考图库待用真实照片替换。

## 单一事实来源（SSOT）
动手前先读（按需）：
- 总纲（SSOT）：`docs/指导文件/《栖霞山小向导项目开发总体方案（2026年10月修订）》.md`（内部版本 v1.2，含七工具接口、数据模型、模块任务卡、API 备忘）
- 海报办法：`docs/指导文件/《小栖海报生成工作管理办法（试行）》.md`（v0.1）
- 语言守则：`docs/指导文件/《小栖人设与语言风格工作守则》.md`（v2.1）
- 文件体系说明：`docs/指导文件/《关于项目指导文件体系的通知》.md`；备赛与参考资料在 `docs/参考文件/`

## 冻结接口（不要擅自改，改要先改规格）
- 端口：`127.0.0.1:8017`（打包版自动回退 8018/8019）
- SSE 事件名：`delta` / `tool_start` / `tool_end` / `done` / `error`（`app/agent/loop.py`）
- 工具注册方式：`app/tools/<name>.py` 里 `SCHEMA`（OpenAI function schema）+ `async def run(args, ctx)`，由 `app/tools/__init__.py` 汇总
- 数据文件：`app/data/poi.json`、`app/data/routes.json`、`app/data/manual_conditions.json`（schema 见规格 §4）
- 会话状态：`app/services/session.py`（结构见规格 §3.0）

## 运行与自测
```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
scripts\start_dev.bat
.venv\Scripts\python scripts\smoke.py
.venv\Scripts\python scripts\boot_check.py
node tools\test_poster_dom.mjs        :: 海报渲染 72 组合无头自测（需先在 tools/ 里 npm i）
```
没有 DeepSeek Key 时，对话接口应返回友好报错（不是崩溃）；页面右上角可填 Key 并"测试连接"。

> 沙箱内建 venv / pip 若报 PermissionError：先 `$env:PYTHONPATH="<repo>/.support"` 再执行（Python 3.14 的 0o700 目录 ACL 在受限令牌下会被锁死，`.support/sitecustomize.py` 做过兼容）。

## 分工（双 AI 协作）
- Codex（后端）：`app/**`、`scripts/**`、`tools/**`
- Claude Code（前端）：`web/**`（含海报 `web/poster/**`；海报规范实现见 `web/poster/skill/SKILL.md`）
- 同一时间只改自己目录；跨目录改动先在 `docs/` 留一条接口变更记录。

## 海报与语音（新增约定）
- 海报渲染契约：`PosterSkill.render(stage, spec)`；`spec.type.captions` 允许字符串或 `{text}`；
  导出前把 `#stage` 的 transform 复位为 `none`（`poster-app.js` 已处理）。
- 质检契约：`PosterSkill.qa.run(document, stage, {})`；改渲染器必须跑 `tools/test_poster_dom.mjs`。
- 到点播报音频：`scripts/make_audio.py`（edge-tts，构建期）；文件在 `app/audio/poi/`，
  接口 `/audio/poi/<id>.mp3`；缺失时前端回退浏览器 TTS，不能因此报错。
- 示例照片与参考图：`scripts/make_samples.py` → `app/data/samples/`、`app/data/refs/`；
  真实采集后 refs 可替换（文件名随意，目录名=poi_id）。
- 照片合规（决策 #23）：不落盘、不落图床；只在内存与 LLM 请求间流转。

## 编码规则
- 不为"栖霞山"写死逻辑：景点/路线全部走数据文件（可换皮引擎）。
- LLM 调用：主循环 `thinking: disabled`（延迟优先）；带 tools 时若开 thinking 必须回传 `reasoning_content`（否则 400）；图片只能放在 `user` 消息里。
- 文案输出一律遵循系统提示词文风；不确定的事实说不确定。
- 提交前跑 `scripts/smoke.py`，全绿再提交。
- **.bat 文件只写 ASCII**：cmd 按本地 ANSI 代码页逐字节解析 bat，UTF-8 的中文会把字符串拆成乱码命令
  （2026-10-15 实际踩坑）。面向用户的中文提示一律放 Python 输出；bat 只负责 `chcp 65001` 与调用。

## 版本管理与推送（2026-10-16 起）
- 远程仓库：`https://github.com/joeyl3526-cloud/qixi-guide`（**私有**），分支 `main`；
  协作者：zhxzj、lisirui330-oss。三人协作流程见 `docs/协作指南.md`。
- 仓库已排除 `dist/`、`.venv/`、`node_modules/`、日志等大文件（见 `.gitignore`），不要 `git add -f` 强行提交。
- 本机普通终端推送：首次会弹 Git Credential Manager 浏览器登录；或先 `gh auth login` 一次。
- Codex 沙箱内推送（schannel 与 `!` 凭证助手不可用，用下面配方）：
  ```powershell
  $env:GH_CONFIG_DIR='C:\Users\COLORFUL-Joey\Documents\Codex\.gh-cli'
  $tok = gh auth token; $b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$tok"))
  git -c http.sslBackend=openssl -c credential.helper= -c http.extraheader="AUTHORIZATION: basic $b64" push -u origin main
  ```

