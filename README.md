# 栖霞山小向导（qixi-guide）

当前电脑地图默认 Leaflet＋OpenStreetMap，无需地图 Key；内置路网提供本地步行规划，在线底图需要联网。详见 [OSM电脑版使用说明](docs/OSM电脑版使用说明.md)。旧高德说明保留作历史参考，当前默认入口不加载高德。

枫客松黑客松赛道二作品 · 本地 H5 · 当前已跑通主链路：
对话向导 → 到点自动讲解（含语音）→ 天气/红叶 → 游后日记海报（三候选 + 质检 + 导出）。

上手最快的方式：看 [docs/DEMO使用说明.md](docs/DEMO使用说明.md)（含三分钟演示剧本与自测命令）。
三人协作分工与同步流程：看 [docs/协作指南.md](docs/协作指南.md)。
发给普通收件人：提供 `dist/栖霞山小向导.exe`，双击即可，无需安装 Python、管理员权限或手工解压。构建和验收见 [单文件便携 EXE](docs/便携EXE构建与验收.md)。历史打包调研不代表当前交付方式。

配置、文字行程及有上限的日志位于 `%LOCALAPPDATA%/QixiGuide/`。页面“退出应用”停止宿主，关闭浏览器仅关闭页面。没有 Key 时地图、模拟游览、手工照片点位和模板日记可用；Key 与费用方案由项目方配置。原有讲解资料、演示路线和图库仍待权威核验；当前真实地图使用OSM路网快照，尚未完成现场通行与定位精度验收。

## 源码开发（Windows、Python 3.14 x64）

```bat
cd <本仓库所在目录>\qixi-guide
start.bat
```

`start.bat` 会找 Python 3.14 x64、建环境、按 requirements.lock 校验安装依赖，并交给统一启动器开页面。首次耗时取决于开发机网络。
排错或开发时用 `scripts\start_dev.bat`（前台 + reload）。

首次使用：页面右上角填入 DeepSeek API Key（保存后可"测试连接"）。不填 Key 时页面可以看地图、走演示、看天气，只有对话会提示配置。

## 自测

```bat
.venv\Scripts\python scripts\smoke.py
.venv\Scripts\python scripts\boot_check.py
```

分发前的两条回归（“发给别人之前跑这个”）：

```bat
.venv\Scripts\python scripts\selftest_portable.py          :: 实测最终 EXE、隔离缓存、生命周期
node tools\test_browser.mjs                                 :: Edge 实际布局、完整质检、PNG 下载
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

构建不会生成或覆盖正式 refs/samples/音频。`scripts/make_samples.py` 只向 `.tmp/synthetic-fixtures/` 输出合成测试素材。

# 电脑真实地图更新（2026-10-17）

真实地图已接入高德 JS API 2.0，使用前在页面「地图设置」填写 Web端（JS API）Key 及对应安全密钥。支持景点查询、起终点/途经点选择、完整步行路径、电脑定位精度显示及降级；演示草稿另有明确模式，不与真实坐标混用。

配置方法及验收边界见 [电脑真实地图使用与配置](docs/电脑真实地图使用与配置.md)。本次真实高德账号/园内覆盖/现场定位仍待配置后验收，构建成功和模拟测试不等于精准实地导航验收。厕所等用户提供坐标后导入。

