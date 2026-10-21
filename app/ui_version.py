"""Content revision for app-owned resources; independent of the package manifest hash."""
import hashlib
from app.runtime import resource_path, BUILD_ID

WEB_FILES = ('web/index.html','web/css/map.css','web/js/map-osm.js','web/js/app.js','web/js/session.js','web/css/app.css','web/css/ui-shell.css','web/js/ui-shell.js','web/poster.html','web/poster/poster-app.js','web/poster/ui-poster.css','web/assets/ui/maple-hero.webp','web/css/button-feedback.css','web/js/button-feedback.js')
WEB_REVISION = hashlib.sha256(b''.join(resource_path(p).read_bytes() for p in WEB_FILES)).hexdigest()[:16]


def info():
    return {"version":"0.6.2","build_id":BUILD_ID,"web_revision":WEB_REVISION}
