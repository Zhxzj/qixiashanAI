"""构建期语音预生成（决策 #17：到点播报用预生成音频）。

文本 = 首句"到点开场白"（poi.text_short 首句）+ 一句邀请，遵循《语言守则》文风。
语音 = edge-tts（微软神经网络语音，免费）；生成失败不影响主流程（前端回退浏览器 TTS）。

用法：
    .venv\\Scripts\\python scripts\\make_audio.py
    .venv\\Scripts\\python scripts\\make_audio.py --voice zh-CN-XiaoxiaoNeural
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "app" / "data"
OUT = ROOT / "app" / "audio" / "poi"


def announce_text(poi: dict) -> str:
    text = poi.get("text_short", "").strip()
    first = re.split(r"[。！？]", text)[0].strip()
    if not first:
        first = f"这里就是{poi['name']}"
    return f"前面就是{poi['name']}。{first}。想细听就说一声。"


async def synth(text: str, out_path: Path, voice: str, rate: str) -> None:
    import edge_tts

    tts = edge_tts.Communicate(text, voice, rate=rate)
    await tts.save(str(out_path))


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    parser.add_argument("--rate", default="-4%")
    parser.add_argument("--only", default="", help="只生成某个 poi_id（调试用）")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    pois = json.loads((DATA / "poi.json").read_text(encoding="utf-8"))
    manifest = []
    failed = []
    for poi in pois:
        if args.only and poi["poi_id"] != args.only:
            continue
        text = announce_text(poi)
        out = OUT / f"{poi['poi_id']}.mp3"
        try:
            await synth(text, out, args.voice, args.rate)
            manifest.append(
                {"poi_id": poi["poi_id"], "name": poi["name"], "text": text,
                 "file": f"/audio/poi/{poi['poi_id']}.mp3", "bytes": out.stat().st_size}
            )
            print(f"[OK] {poi['poi_id']:14s} {text[:28]}… {out.stat().st_size//1024}KB")
        except Exception as e:  # 网络/服务异常：跳过，前端会回退
            failed.append(poi["poi_id"])
            print(f"[SKIP] {poi['poi_id']}: {type(e).__name__} {e}")

    # 全部失败时别把已有的 manifest 覆盖成空（保护仓库里的构建产物）
    if manifest or not (OUT / "manifest.json").exists():
        (OUT / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"完成：{len(manifest)} 条，跳过 {len(failed)} 条")
    return 1 if failed and len(failed) == len(pois) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
