"""沙箱兼容补丁（仅本机配置流程用）。

Python 3.14 在 Windows 上会把 os.mkdir(..., 0o700) 转成"仅属主"的 DACL；
在 Codex 沙箱的受限令牌下，子进程建出的临时目录随后不可写（ensurepip / pip 会报
PermissionError）。这里把过窄的 mode 放宽成 0o755，避免锁死。

用法：运行 python / pip 前设置  PYTHONPATH=<repo>/.support
（用户在自己终端操作时无需此补丁，也不会自动加载。）
"""

import os

_orig_mkdir = os.mkdir


def _mkdir(path, mode=0o777, *args, **kwargs):
    try:
        if (int(mode) & 0o077) == 0:  # 0o700 及更窄
            mode = 0o755
    except (TypeError, ValueError):
        pass
    return _orig_mkdir(path, mode, *args, **kwargs)


os.mkdir = _mkdir

