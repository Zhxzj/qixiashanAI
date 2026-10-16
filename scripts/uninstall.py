"""卸载：停服务 + 删桌面/开始菜单快捷方式（中文提示都在这里）。

用法：uninstall.bat（仓库根）→ python scripts\\uninstall.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    print("=" * 46)
    print("  栖霞山小向导 · 卸载")
    print("=" * 46)
    print("将停止后台服务，并删除桌面 / 开始菜单里的快捷方式。")
    if IS_FROZEN() is False:
        print(f"程序文件夹：{ROOT}")
    try:
        ans = input("确认卸载吗？(Y/N)：").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n（没有交互终端，已取消）")
        return 0
    if ans != "y":
        print("已取消。")
        return 0

    # 1) 停服务
    try:
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "stop_service.py")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
        print((r.stdout or "").strip() or "（服务未运行）")
    except Exception as e:
        print(f"停服务失败（忽略）：{type(e).__name__}")

    # 2) 快捷方式
    targets = [
        Path(os.environ.get("USERPROFILE", "")) / "Desktop" / "栖霞山小向导.lnk",
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "栖霞山小向导.lnk",
    ]
    for t in targets:
        try:
            if t and t.exists():
                t.unlink()
                print(f"已删除：{t}")
        except Exception as e:
            print(f"删除失败（可手动删）：{t}（{type(e).__name__}）")

    # 3) 说明
    print()
    print("程序本体是绿色文件夹，卸载就是删掉整个文件夹；")
    print("用户数据在 %LOCALAPPDATA%\\QixiGuide（打包版配置），需要的话一并删除。")
    print("没有注册表项、没有系统服务、没有开机启动。")
    return 0


def IS_FROZEN() -> bool:
    from app.runtime import IS_FROZEN as frozen

    return frozen


if __name__ == "__main__":
    sys.exit(main())
