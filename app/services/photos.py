"""照片能力（M8 + 海报素材）：

1. `match_photo` —— 无 GPS 照片场景识别（本地直方图粗排 → Vision 两轮直比，见规格 §3.9）；
2. `build_recap` —— 回放小传 + 日记文案（海报管线，见海报办法 §3.1）。

合规（决策 #23）：用户照片只用于当次识别与海报生成，不落盘、不落图床、不他传。
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import httpx
from PIL import Image

try:  # 可选：装了 pillow-heif 就能直接读 iPhone 的 HEIC/HEIF；没有也不影响 JPG/PNG
    from pillow_heif import register_heif_opener  # type: ignore

    register_heif_opener()
except Exception:
    pass

API_URL = "https://api.deepseek.com/chat/completions"
MAX_SIDE = 1024  # Vision 计费上限：单图约 1024 tokens（规格 §3.9）

_HEIF_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"avif")


def _looks_like_heif(data: bytes) -> bool:
    """ISO-BMFF 开头 + HEIC/HEIF/AVIF 品牌 → 大概率是 iPhone 相册原图。"""
    return len(data) > 12 and data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS


def _squash(data: bytes, max_side: int = MAX_SIDE) -> str:
    """缩到 max_side 内，返回 base64（不带 data: 前缀）。"""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _histogram(data: bytes, bins: int = 4) -> list[float]:
    """4×4×4 RGB 直方图（归一化），用于本地粗排。"""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((256, 256), Image.LANCZOS)
    px = list(img.getdata())
    hist = [0.0] * (bins**3)
    step = 256 // bins
    for r, g, b in px:
        idx = (r // step) * bins * bins + (g // step) * bins + (b // step)
        hist[idx] += 1.0
    total = max(1.0, float(len(px)))
    return [v / total for v in hist]


def _chi2(a: list[float], b: list[float]) -> float:
    s = 0.0
    for x, y in zip(a, b):
        m = x + y
        if m > 0:
            s += (x - y) ** 2 / m
    return s


class PhotoService:
    def __init__(self, data_dir: Path, cfg: dict):
        self.data_dir = Path(data_dir)
        self.cfg = cfg
        self.refs_dir = self.data_dir / "refs"
        self.pois = json.loads((self.data_dir / "poi.json").read_text(encoding="utf-8"))
        self.poi_by_id = {p["poi_id"]: p for p in self.pois}
        self._ref_hist: dict[str, list[list[float]]] = {}

    # ---------- 参考图 ----------

    def ref_images(self, poi_id: str, limit: int = 2) -> list[Path]:
        d = self.refs_dir / poi_id
        if not d.exists():
            return []
        files = sorted(p for p in d.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
        return files[:limit]

    def ref_pool(self) -> list[str]:
        if not self.refs_dir.exists():
            return []
        return sorted(p.name for p in self.refs_dir.iterdir() if p.is_dir())

    def _hists_for(self, poi_id: str) -> list[list[float]]:
        if poi_id not in self._ref_hist:
            hists = []
            for p in self.ref_images(poi_id, limit=6):
                try:
                    hists.append(_histogram(p.read_bytes()))
                except Exception:
                    continue
            self._ref_hist[poi_id] = hists
        return self._ref_hist[poi_id]

    # ---------- 场景识别 ----------

    def coarse_rank(self, photo_bytes: bytes, top_k: int = 6) -> list[dict]:
        """本地直方图粗排；参考图库为空的点位不参与（升级路径：collect_refs.py）。"""
        try:
            h = _histogram(photo_bytes)
        except Exception as e:
            if _looks_like_heif(photo_bytes):
                msg = (
                    "这看起来是 iPhone 的 HEIC/HEIF 照片，本机暂未装解码插件。"
                    "请先导出为 JPG（手机相册→分享→存储为 JPG）再上传。"
                )
            else:
                msg = f"这张图片读不出来（{type(e).__name__}）：可能格式不支持或文件损坏，换 JPG/PNG 再试。"
            return [{"error": {"code": "bad_image", "message": msg}}]
        scored = []
        for poi in self.pois:
            hists = self._hists_for(poi["poi_id"])
            if not hists:
                continue
            d = min(_chi2(h, rh) for rh in hists)
            scored.append(
                {
                    "poi_id": poi["poi_id"],
                    "name": poi["name"],
                    "one_liner": poi.get("text_short", ""),
                    "score": round(1.0 / (1.0 + d), 3),
                }
            )
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    async def match_photo(
        self,
        photo_bytes: bytes,
        candidates: list[dict] | None = None,
        top_k: int = 3,
    ) -> dict:
        """两轮直比：① 文字候选清单 → 报 top-3；② 照片+参考图 → 给结论。

        没有 Key 或没有参考图时返回 coarse_only，前端弹手动确认。
        """
        ranked = self.coarse_rank(photo_bytes, top_k=6)
        if ranked and "error" in ranked[0]:
            return {"ok": False, "mode": "error", "message": ranked[0]["error"]["message"]}
        if not ranked:
            return {
                "ok": False,
                "mode": "no_refs",
                "message": "参考图库还没建（先跑 scripts/make_samples.py 或 collect_refs.py）",
                "candidates": [],
            }
        top = ranked[:top_k]
        if not self.cfg.get("deepseek_api_key"):
            return {"ok": False, "mode": "no_key", "candidates": top,
                    "message": "未配置 DeepSeek Key，先用本地颜色相似度给了候选"}

        try:
            guess = await self._vision_pick(photo_bytes, ranked)
        except Exception as e:
            return {"ok": False, "mode": "vision_failed", "candidates": top,
                    "message": f"视觉识别失败（{type(e).__name__}），先用候选兜底"}
        # 候选确认：top-3 由视觉得分与本地得分合并
        merged = {c["poi_id"]: dict(c) for c in top}
        for it in guess.get("candidates", []):
            pid = it.get("poi_id")
            if pid in merged:
                merged[pid]["reason"] = it.get("reason", "")
                merged[pid]["vision_score"] = it.get("score")
            elif pid in self.poi_by_id:
                p = self.poi_by_id[pid]
                merged[pid] = {
                    "poi_id": pid, "name": p["name"],
                    "one_liner": p.get("text_short", ""),
                    "score": 0.0,
                    "reason": it.get("reason", ""),
                    "vision_score": it.get("score"),
                }
        items = list(merged.values())
        items.sort(key=lambda x: (x.get("vision_score") or 0, x["score"]), reverse=True)
        return {
            "ok": True,
            "mode": "vision",
            "best": items[0] if items else None,
            "candidates": items[:top_k],
            "note": guess.get("note", ""),
        }

    async def _vision_pick(self, photo_bytes: bytes, ranked: list[dict]) -> dict:
        """一次请求：用户照片 + 前 3 个候选点位的参考图（≤4 张，规格 §3.9 第②轮）。"""
        content: list[dict] = [
            {
                "type": "text",
                "text": (
                    "这是游客在栖霞山拍的照片。下面跟着 1–3 个候选点位的参考图（每张前会用文字标注点位名）。"
                    "请判断这张照片最可能拍自哪个点位，按可能性从高到低给最多 3 个候选。"
                    '只输出 JSON：{"candidates":[{"poi_id":"...","score":0.0-1.0,"reason":"一句中文理由"}],"note":"可选一句提醒"}'
                    "。候选必须从这些 poi_id 里选：" + "、".join(c["poi_id"] for c in ranked) + "。"
                ),
            },
            {
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + _squash(photo_bytes)},
            },
        ]
        for c in ranked[:3]:
            for ref in self.ref_images(c["poi_id"], limit=1):
                content.append({"type": "text", "text": f"参考图（{c['name']}）："})
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + _squash(ref.read_bytes())},
                    }
                )
        body = {
            "model": self.cfg.get("model", "deepseek-flash"),
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.2,
            "max_tokens": 500,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        headers = {
            "Authorization": f"Bearer {self.cfg.get('deepseek_api_key', '')}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15)) as client:
            resp = await client.post(API_URL, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        text = data["choices"][0]["message"]["content"]
        return json.loads(text)

    # ---------- 回放小传 + 日记 ----------

    def replay_lines(self, state: dict) -> list[str]:
        """三行白描（规则兜底版；有 Key 时由 LLM 润色）。"""
        locator = None  # 只用到名称，从 poi_by_id 取
        visited = state.get("visited") or []
        names = [self.poi_by_id.get(v["poi_id"], {}).get("name", v["poi_id"]) for v in visited]
        route = state.get("route") or {}
        memories = state.get("memory") or []

        if not names:
            names = ["山门"]
        first, last = names[0], names[-1]
        line1 = f"今天你从{first}走到{last}，{len(names)} 个地方"
        if route.get("remaining_m") is not None:
            total_m = route.get("total_m") or 0
            if total_m:
                line1 += f"，{total_m / 1000:.1f} 公里"
        line1 += "。"

        mid = names[1:-1] or names[:1]
        line2 = f"在{mid[0]}停了一会儿" if mid else "沿路慢慢走"
        notes = [m.get("note") for m in memories if m.get("note")]
        if notes:
            line2 = f"你说：“{notes[-1]}”。"
        else:
            line2 += "。"

        cond = state.get("_conditions") or {}
        red = (cond.get("red_leaf") or {}).get("text")
        if red:
            line3 = f"今天红叶{red}，山里的光不燥。"
        else:
            line3 = "下山的路上，风从林子里过。"
        return [line1, line2, line3]

    def diary_fallback(self, state: dict) -> dict:
        """无 Key 时的日记文案兜底（模板拼接，仍遵循文风规范）。"""
        visited = state.get("visited") or []
        names = [self.poi_by_id.get(v["poi_id"], {}).get("name", v["poi_id"]) for v in visited]
        memories = [m for m in (state.get("memory") or []) if m.get("note")]
        title = "山里的这半天"
        if names:
            title = f"{names[-1]}的这一程"
        paras = []
        if names:
            paras.append("从" + names[0] + "进来，" + "、".join(names[1:4] or names[:1]) + "，一路没赶时间。")
        for m in memories[:2]:
            poi = self.poi_by_id.get(m.get("poi_id") or "", {}).get("name", "")
            paras.append((poi + "。" if poi else "") + f"你说：“{m['note']}”。")
        paras.append("回去的路上把照片翻了一遍，红的黄的都还在。")

        captions = []
        for i, n in enumerate(names[:4]):
            captions.append({"poi_id": None, "text": f"{n}，到了"})
        while len(captions) < 3:
            captions.append({"poi_id": None, "text": "山里的光"})
        return {
            "title": title,
            "kicker": None,
            "paragraphs": paras[:4],
            "captions": captions,
            "quote": None,
            "seal": "栖霞",
            "source": "fallback",
        }

    async def build_recap(self, state: dict) -> dict:
        """海报管线入口：call 一次 LLM 产出日记文案 + 落 DesignSpec 文本部分。"""
        lines = self.replay_lines(state)
        diary = self.diary_fallback(state)
        if self.cfg.get("deepseek_api_key"):
            try:
                diary = await self._diary_llm(state, diary)
            except Exception:
                pass  # 保底：模板版
        return {"replay_lines": lines, "diary": diary}

    async def _diary_llm(self, state: dict, base: dict) -> dict:
        visited = state.get("visited") or []
        visiting_txt = "、".join(
            f"{self.poi_by_id.get(v['poi_id'], {}).get('name', v['poi_id'])}"
            for v in visited
        ) or "山门附近"
        memories = [
            m for m in (state.get("memory") or []) if m.get("note")
        ]
        mem_txt = "；".join(
            f"在{self.poi_by_id.get(m.get('poi_id') or '', {}).get('name', '半路')}说“{m['note']}”"
            for m in memories[:3]
        ) or "无"
        cond = state.get("_conditions") or {}
        weather = ((cond.get("weather") or {}).get("now") or {}).get("text", "")
        red = (cond.get("red_leaf") or {}).get("text", "")
        prompt = f"""你在帮一位游客整理他今天在南京栖霞山的行程，写一段日记式的短文（给他生成纪念海报用）。

行程：{visiting_txt}
游客原话：{mem_txt}
天气：{weather or '不明'}；红叶：{red or '不明'}

要求：
- 中文，白描，短句；只写他今天做过的事和看到的东西，不抒情不说教。
- 标题 ≤ 10 字；正文 2–3 段，每段 ≤ 60 字；不要"欢迎""感谢"这类词。
- 另外给 3–4 条照片说明（caption），每条 ≤ 12 字，配得上照片。
- 如果标题或句子能用上红叶/秋色，就用，但不要堆词。
- 严格输出 JSON：{{"title":"…","kicker":"日期·天气（≤12字）","paragraphs":["…"],"captions":[{{"poi_id":null,"text":"…"}}],"quote":null,"seal":"2–4字"}}"""
        body = {
            "model": self.cfg.get("model", "deepseek-flash"),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8,
            "max_tokens": 700,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        headers = {
            "Authorization": f"Bearer {self.cfg.get('deepseek_api_key', '')}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15)) as client:
            resp = await client.post(API_URL, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        out = json.loads(data["choices"][0]["message"]["content"])
        merged = {**base, **{k: v for k, v in out.items() if v}}
        merged["source"] = "llm"
        return merged
