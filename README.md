# 栖霞山小向导（qixi-guide）

枫客松黑客松赛道二作品 · 本地 H5 · 当前已跑通主链路：
对话向导 → 到点自动讲解（含语音）→ 天气/红叶 → 游后日记海报（三候选 + 质检 + 导出）。

上手最快的方式：看 [docs/DEMO使用说明.md](docs/DEMO使用说明.md)（含三分钟演示剧本与自测命令）。
三人协作分工与同步流程：看 [docs/协作指南.md](docs/协作指南.md)。
要发给没有 Python 的机器：看 [docs/打包与分发调研.md](docs/打包与分发调研.md)（便携 Python 免安装版）。

## 快速开始（Windows）

```bat
cd <本仓库所在目录>\qixi-guide
start.bat
```

`start.bat` 会自动找 Python、建环境、装依赖、挑端口、开浏览器（首次约 1 分钟，之后几秒）。
排错或开发时用 `scripts\start_dev.bat`（前台 + reload）。

首次使用：页面右上角填入 DeepSeek API Key（保存后可"测试连接"）。不填 Key 时页面可以看地图、走演示、看天气，只有对话会提示配置。

## 自测

```bat
.venv\Scripts\python scripts\smoke.py
.venv\Scripts\python scripts\boot_check.py
```

分发前的两条回归（“发给别人之前跑这个”）：

```bat
.venv\Scripts\python scripts\selftest_fresh.py --in-repo   :: 新电脑首次安装链路（切换解释器等）
.venv\Scripts\python scripts\selftest_portable.py          :: 免安装包：导入探针 + start.bat 真链路
```

全链路排查与修复记录见 [docs/稳定性审计报告.md](docs/稳定性审计报告.md)。

## 目录

- `app/` 后端（FastAPI + Agent 循环 + 七工具 + 服务 + 预生成语音 + 示例/参考图）
- `web/` 前端（原生 JS；对话 / 地图 / 控制台 / 海报工作台）
- `web/poster/skill/` 海报生成 Skill（渲染器 + 6 构图 + 4 色板 + 12 母题 + 质检）
- `scripts/` 启动、素材生成与自测脚本
- `tools/` 无头渲染自测（jsdom，仅开发用）
- `docs/` 演示与使用文档

说明：`config.json`、`.venv/`、`logs/` 不入库。

