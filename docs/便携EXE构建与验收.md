# 单文件便携 EXE：构建与验收

收件人只需双击 `栖霞山小向导.exe`，无需 Python、管理员权限或手工安装。首次按版本展开到当前用户缓存，之后校验复用。关闭页面不停止后台，请点击“退出应用”。无 Key 时本地导览、手工照片点位、模板日记可用；云对话需在设置页配置并测试。费用和额度仍由项目方决定。

构建机：Windows x64、Python 3.14、MinGW-w64 GCC 和 windres（无需收件人安装）。固定 CPython 3.14.8 官方 embeddable、23 个 wheel 的版本、URL 和 SHA256 见 `build-inputs.lock.json`；完整 Python 包锁见 `requirements.lock`。构建不生成/覆盖 refs、samples、音频，不复制开发 venv，不分发配置或 Key。产品图标和版本信息由 `native/guide.rc` 嵌入；图标可用纯标准库脚本 `packaging/make_icon.py` 重建。

```powershell
.venv\Scripts\python scripts\smoke.py
.venv\Scripts\python scripts\boot_check.py
.venv\Scripts\python scripts\build_portable.py
.venv\Scripts\python scripts\selftest_portable.py
node tools\test_poster_dom.mjs
node tools\test_browser.mjs
```

默认下载缓存 `.tmp/portable-v2`；可用 `--cache <绝对目录> --skip-download` 从已校验输入离线重建。`scripts/make_portable.py` 是同一构建的兼容入口，不再另行组装。产物为 `dist/栖霞山小向导.exe`、`dist/QixiGuide-portable.zip`、`SHA256SUMS.txt`，构建清单在内部负载 `manifest.json`。

原生壳只依赖 Windows 自带 Win32、BCrypt、Compression API；XPRESS Huffman 解包，逐文件 SHA256、版本缓存锁、staging 原子切换。宿主持有用户实例锁，并使用随机实例凭证退出。旧版本运行时新版本提示先退出；不强杀、不自动覆盖用户状态。缓存清理：全部退出后，命令行运行 EXE `--clean-cache`，保留 config/state/logs。

源码启动仍可用 `start.bat`，不属于收件人交付。配置已统一到 `%LOCALAPPDATA%/QixiGuide/config/config.json`；旧项目根配置不自动迁移，避免误读取或分发开发者 Key。若要使用，请由项目方在新设置入口自行填写。

`selftest_portable.py` 测的是最终 EXE，使用隔离用户目录和失效 Python 环境，检验热缓存、端口冲突、单实例、退出、缓存修复及清理。`test_browser.mjs` 使用独立隐藏 Edge 配置，测试真实布局、质检、PNG 下载和清空失效。测试结果写入 dist JSON；不是干净 Win10/Win11 或真实供应商性能评测的替代。

发布前仍需：凭证和费用决策、POI/路线/图库的权威校对、签名与实际下载信誉、目标干净机器测试、同模型任务集的事实与延迟配对评测。首段有效内容 3s/5s P95 是待验证目标，不是已经达到的结果。
