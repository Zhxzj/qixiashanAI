"""生成演示用示例照片与参考图库（合成图，无真人肖像，合规）。

用途：
1. `.tmp/synthetic-fixtures/samples/` —— 海报测试样本；
2. `.tmp/synthetic-fixtures/refs/<poi_id>/` —— 合成测试参考图。

说明：合成图为程序绘制的风格化风景，不含任何第三方肖像或版权素材；
赛前可用公开图库/现场拍摄替换 `app/data/refs/`，脚本接口不变。

用法：
    .venv\\Scripts\\python scripts\\make_samples.py
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / ".tmp" / "synthetic-fixtures" / "samples"
REFS = ROOT / ".tmp" / "synthetic-fixtures" / "refs"

W, H = 1600, 1200

PALETTES = {
    "autumn": [(196, 60, 40), (214, 116, 52), (232, 176, 96), (120, 56, 44), (248, 238, 214)],
    "stone": [(122, 116, 106), (156, 148, 134), (94, 88, 80), (188, 178, 160), (222, 214, 198)],
    "lake": [(86, 118, 110), (54, 82, 86), (142, 168, 150), (176, 196, 176), (232, 240, 232)],
    "temple": [(166, 58, 43), (198, 142, 74), (86, 62, 54), (232, 216, 178), (120, 108, 92)],
    "ridge": [(214, 128, 62), (232, 176, 110), (128, 96, 84), (238, 208, 168), (170, 120, 96)],
    "tea": [(94, 110, 78), (130, 146, 102), (70, 84, 60), (206, 206, 176), (44, 56, 44)],
    "night": [(60, 68, 92), (96, 104, 132), (158, 132, 108), (216, 186, 140), (32, 36, 52)],
}


def _soft_gradient(img: Image.Image, c1, c2, vertical: bool = True) -> None:
    d = ImageDraw.Draw(img)
    n = H if vertical else W
    for i in range(n):
        t = i / max(1, n - 1)
        col = tuple(int(c1[k] + (c2[k] - c1[k]) * t) for k in range(3))
        if vertical:
            d.line([(0, i), (W, i)], fill=col)
        else:
            d.line([(i, 0), (i, H)], fill=col)


def _ridge(d: ImageDraw.ImageDraw, y0: int, amp: int, col, seed: int, alpha_img=None) -> None:
    rnd = random.Random(seed)
    pts = [(0, y0 + rnd.randint(-amp // 3, amp // 3))]
    x = 0
    while x < W:
        x += rnd.randint(140, 260)
        pts.append((x, y0 + rnd.randint(-amp, amp)))
    pts += [(W, y0 + rnd.randint(-amp // 2, amp // 2)), (W, H), (0, H)]
    d.polygon(pts, fill=col)


def _blob(img: Image.Image, cx: int, cy: int, r: int, col, steps: int = 26) -> None:
    d = ImageDraw.Draw(img)
    for i in range(steps, 0, -1):
        t = i / steps
        rr = r * t
        c = tuple(int(col[k] + (238 - col[k]) * (1 - t) * 0.25) for k in range(3))
        d.ellipse([cx - rr, cy - rr * 0.78, cx + rr, cy + rr * 0.78], fill=c)


def make_scene(kind: str, seed: int) -> Image.Image:
    rnd = random.Random(seed)
    img = Image.new("RGB", (W, H), (240, 240, 240))
    pal = PALETTES[kind]

    if kind == "autumn":          # 红叶山坡：多层暖色
        _soft_gradient(img, pal[4], (255, 214, 168))
        for i, p in enumerate([pal[2], pal[1], pal[0], pal[3]]):
            _ridge(ImageDraw.Draw(img), 380 + i * 170, 70 + i * 20, p, seed + i)
        for _ in range(230):      # 叶点
            x, y = rnd.randint(0, W), rnd.randint(300, H - 40)
            r = rnd.randint(6, 22)
            col = pal[rnd.choice([0, 1, 2])]
            _blob(img, x, y, r, col, steps=6)

    elif kind == "stone":         # 石阶与崖壁
        _soft_gradient(img, pal[4], pal[1])
        d = ImageDraw.Draw(img)
        for i in range(18):       # 石阶
            y = 320 + i * 46
            d.polygon([(60 + i * 8, y), (W - 80, y - 30), (W - 80, y + 16), (60 + i * 8, y + 46)], fill=pal[1 if i % 2 else 3])
        for _ in range(70):       # 崖壁斑驳
            x, y = rnd.randint(0, W), rnd.randint(240, H)
            _blob(img, x, y, rnd.randint(18, 60), pal[rnd.choice([0, 2, 4])], steps=8)

    elif kind == "lake":          # 湖面与倒影
        _soft_gradient(img, (232, 240, 236), pal[2], vertical=True)
        d = ImageDraw.Draw(img)
        d.rectangle([0, 560, W, H], fill=pal[1])
        for i in range(90):       # 波纹
            y = 570 + i * 7
            x0 = rnd.randint(-80, W)
            d.line([(x0, y), (x0 + rnd.randint(120, 460), y)], fill=pal[3 if i % 3 else 4], width=2)
        for _ in range(40):       # 岸边树丛倒影
            x = rnd.randint(0, W)
            _blob(img, x, 540, rnd.randint(30, 90), pal[2], steps=10)

    elif kind == "temple":        # 古寺红墙金瓦
        _soft_gradient(img, (238, 226, 196), (226, 196, 160))
        d = ImageDraw.Draw(img)
        d.rectangle([150, 430, W - 150, H - 60], fill=pal[0])
        d.rectangle([150, 430, W - 150, 476], fill=pal[1])
        d.polygon([(90, 456), (W - 90, 456), (W, 380), (0, 380)], fill=pal[2])  # 屋檐
        d.polygon([(0, 380), (W, 380), (W - 40, 350), (40, 350)], fill=(54, 40, 36))
        for i in range(6):        # 门钉
            d.ellipse([300 + i * 180, 640, 340 + i * 180, 680], fill=pal[3])
        for _ in range(60):       # 树影
            _blob(img, rnd.randint(0, W), rnd.randint(200, 430), rnd.randint(26, 70), pal[4], steps=8)

    elif kind == "ridge":         # 山脊晚霞
        _soft_gradient(img, pal[3], pal[1])
        for i, p in enumerate([(238, 208, 168), pal[0], pal[2], (96, 72, 66)]):
            _ridge(ImageDraw.Draw(img), 400 + i * 165, 80 + i * 26, p, seed + 7 * i)
        sun = ImageDraw.Draw(img)
        sun.ellipse([W - 520, 200, W - 320, 400], fill=(250, 214, 150))
        d2 = ImageDraw.Draw(img)
        for i in range(5):        # 雾带
            y = 520 + i * 90
            d2.rectangle([0, y, W, y + rnd.randint(10, 26)], fill=(246, 230, 206))

    elif kind == "tea":           # 茶园小院
        _soft_gradient(img, (226, 232, 210), pal[1])
        d = ImageDraw.Draw(img)
        for i in range(26):       # 茶垄
            y = 380 + i * 30
            d.line([(0, y), (W, y - 40)], fill=pal[0 if i % 2 else 2], width=8)
        d.rectangle([980, 380, 1380, 760], fill=pal[3])       # 小屋
        d.polygon([(940, 392), (1420, 392), (1360, 300), (1000, 300)], fill=(72, 60, 48))
        for _ in range(50):
            _blob(img, rnd.randint(0, 260), rnd.randint(340, H), rnd.randint(20, 60), pal[2], steps=8)

    else:                          # night：暮色山影
        _soft_gradient(img, pal[4], pal[1])
        for i, p in enumerate([pal[0], pal[2], pal[3]]):
            _ridge(ImageDraw.Draw(img), 430 + i * 190, 76 + i * 22, p, seed + 3 * i)
        d = ImageDraw.Draw(img)
        for _ in range(140):
            x, y = rnd.randint(0, W), rnd.randint(0, 420)
            d.point((x, y), fill=(240, 232, 210))

    # 统一后期：轻噪点（Alpha 混合，只加一点胶片感）+ 轻模糊 + 暖偏
    img = img.filter(ImageFilter.GaussianBlur(0.8))
    noise = Image.effect_noise((W, H), 18).convert("L")
    grain = Image.merge("RGB", (noise, noise, noise))
    img = Image.blend(img, grain, 0.05)
    # 顶部薄雾（空气感）
    haze = Image.new("RGB", (W, H), (252, 244, 226))
    mask = Image.linear_gradient("L").resize((W, H))
    img = Image.composite(haze, img, mask.point(lambda v: int(v * 0.22)))
    r, g, b = img.split()
    r = r.point(lambda v: min(255, int(v * 1.05)))
    b = b.point(lambda v: int(v * 0.95))
    img = Image.merge("RGB", (r, g, b))
    return ImageEnhance.Color(img).enhance(1.12)


# 文件名 -> (场景, 种子)：覆盖 4 个点位的参考图 + 演示照片
REFS_MAP = {
    "autumn_01": ("autumn", 11), "autumn_02": ("autumn", 23), "autumn_03": ("autumn", 37),
    "stone_01": ("stone", 51), "stone_02": ("stone", 67),
    "lake_01": ("lake", 83), "lake_02": ("lake", 97),
    "temple_01": ("temple", 113), "temple_02": ("temple", 131),
    "ridge_01": ("ridge", 149), "ridge_02": ("ridge", 167),
    "tea_01": ("tea", 181), "night_01": ("night", 199),
}

POI_REFS = {
    "shuanghongyuan": ["autumn_01", "autumn_02", "autumn_03"],
    "qianfoyan": ["stone_01", "stone_02"],
    "mingjinghu": ["lake_01", "lake_02"],
    "qixiasi": ["temple_01", "temple_02"],
    "fengxiangfeng": ["ridge_01", "ridge_02"],
    "luyuchazhuang": ["tea_01"],
    "fenglinhu": ["night_01"],
}

SAMPLE_PICKS = ["autumn_02", "stone_01", "lake_01", "temple_01", "ridge_01", "tea_01"]


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    REFS.mkdir(parents=True, exist_ok=True)

    made: dict[str, Image.Image] = {}
    for name, (kind, seed) in REFS_MAP.items():
        img = make_scene(kind, seed)
        made[name] = img
        (REFS / f"{name}.jpg").parent.mkdir(parents=True, exist_ok=True)
        img.save(REFS / f"{name}.jpg", quality=88)

    for poi, names in POI_REFS.items():
        d = REFS / poi
        d.mkdir(parents=True, exist_ok=True)
        for i, n in enumerate(names, 1):
            made[n].save(d / f"{i:02d}_{n}.jpg", quality=88)

    for i, n in enumerate(SAMPLE_PICKS, 1):
        made[n].save(SAMPLES / f"sample_{i:02d}_{n}.jpg", quality=90)

    print(f"refs -> {REFS}")
    print(f"samples -> {SAMPLES}")
    print(f"共 {len(made)} 张参考图，{len(SAMPLE_PICKS)} 张演示照片")


if __name__ == "__main__":
    main()
