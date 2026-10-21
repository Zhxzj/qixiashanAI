"""Page-scoped credentials, exclusively in process memory. Never log their values."""
from contextvars import ContextVar
import time
from uuid import UUID

request_key = ContextVar("qixi_request_model_key", default=None)
request_page = ContextVar("qixi_request_page", default="")
_pages = {}
IDLE_TTL = 12 * 60 * 60

def valid_page(value):
    try:
        return str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False

def get_key(page):
    now = time.monotonic()
    for identifier, (_, touched) in list(_pages.items()):
        if now - touched > IDLE_TTL:
            _pages.pop(identifier, None)
    item = _pages.get(page)
    if not item:
        return ""
    _pages[page] = (item[0], now)
    return item[0]

def set_key(page, key):
    if not valid_page(page):
        raise ValueError("请刷新页面后重新输入 Key")
    get_key(page)
    if not key:
        _pages.pop(page, None)
    else:
        if page not in _pages and len(_pages) >= 256:
            raise ValueError("打开的页面较多，请关闭不用的页面后重试")
        _pages[page] = (key, time.monotonic())
    request_key.set(key)

def forget(page):
    _pages.pop(page, None)
