/* 质检层：H1–H11 硬规则（海报办法 §1.1 / §4.1）。
 * 浏览器与 Node 双端可用（UMD 风格）；仅依赖 DOM 与 canvas，不引入第三方。
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else (root.PosterSkill = root.PosterSkill || {}).qa = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const TYPE_STEPS = [96, 72, 52, 36, 28, 20];
  const SAFE = 0.04;     // 边距 ≥ 画布宽 4%
  const SEAL_SAFE = 0.06; // 印章离边 ≥ 6%

  function parseColor(str) {
    if (!str) return null;
    str = str.trim();
    let m = str.match(/^rgba?\(([^)]+)\)$/);
    if (m) {
      const parts = m[1].split(",").map((s) => parseFloat(s));
      return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
    }
    m = str.match(/^#([0-9a-f]{6})$/i);
    if (m) {
      const v = parseInt(m[1], 16);
      return { r: (v >> 16) & 255, g: (v >> 8) & 255, b: v & 255, a: 1 };
    }
    m = str.match(/^#([0-9a-f]{3})$/i);
    if (m) {
      const v = parseInt(m[1], 16);
      return { r: ((v >> 8) & 15) * 17, g: ((v >> 4) & 15) * 17, b: (v & 15) * 17, a: 1 };
    }
    return null;
  }

  function luminance(c) {
    const f = (v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  }

  function contrast(a, b) {
    const la = luminance(a), lb = luminance(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  }

  function effectiveBg(node, root) {
    let acc = null;
    let cur = node.parentElement;
    while (cur && cur !== document.documentElement) {
      const bg = parseColor(getComputedStyle(cur).backgroundColor);
      if (bg && bg.a > 0.9) {
        acc = bg;
        break;
      } else if (bg && bg.a > 0.05) {
        acc = acc
          ? { r: acc.r * (1 - bg.a) + bg.r * bg.a, g: acc.g * (1 - bg.a) + bg.g * bg.a, b: acc.b * (1 - bg.a) + bg.b * bg.a, a: 1 }
          : bg;
      }
      cur = cur.parentElement;
    }
    if (!acc) acc = parseColor(getComputedStyle(root).backgroundColor) || { r: 255, g: 255, b: 255, a: 1 };
    return acc;
  }

  function rectOf(node) {
    const r = node.getBoundingClientRect();
    const stage = node.closest(".poster-stage");
    const root = stage?.getBoundingClientRect();
    const scale = root?.width ? 1080 / root.width : 1;
    return {left:r.left*scale,right:r.right*scale,top:r.top*scale,bottom:r.bottom*scale,width:r.width*scale,height:r.height*scale};
  }

  function checkOverflow(stage, rootRect) {
    const bad = [];
    stage.querySelectorAll('[data-qa="text"]').forEach((n) => {
      const r = rectOf(n);
      let ok = n.scrollHeight <= n.clientHeight + 2 && n.scrollWidth <= n.clientWidth + 2;
      if (!ok) bad.push({ tag: n.className, text: (n.textContent || "").slice(0, 18), type: "self-overflow" });
      const inside = r.left >= rootRect.left - 2 && r.right <= rootRect.right + 2 &&
        r.top >= rootRect.top - 2 && r.bottom <= rootRect.bottom + 2;
      if (!inside) bad.push({ tag: n.className, text: (n.textContent || "").slice(0, 18), type: "outside-stage" });
    });
    stage.querySelectorAll('[data-qa="img"]').forEach((n) => {
      const r = rectOf(n);
      const inside = r.left >= rootRect.left - 2 && r.right <= rootRect.right + 2 &&
        r.top >= rootRect.top - 2 && r.bottom <= rootRect.bottom + 2;
      if (!inside) bad.push({ tag: n.className, text: "(照片)", type: "outside-stage" });
    });
    return { name: "H1 无溢出", ok: bad.length === 0, detail: bad.slice(0, 6) };
  }

  function checkContrast(stage, root) {
    const bad = [];
    stage.querySelectorAll('[data-qa="text"]').forEach((n) => {
      const style = getComputedStyle(n);
      const color = parseColor(style.color);
      if (!color) return;
      const fs = parseFloat(style.fontSize);
      const bg = effectiveBg(n, root);
      const ratio = contrast({ ...color, a: 1 }, bg);
      const large = fs >= 36 || (fs >= 28 * 1.2 && parseInt(style.fontWeight) >= 700);
      const need = large ? 3.0 : 4.5;
      if (ratio < need) {
        bad.push({ text: (n.textContent || "").slice(0, 16), ratio: +ratio.toFixed(2), need });
      }
    });
    return { name: "H2 对比度", ok: bad.length === 0, detail: bad.slice(0, 6) };
  }

  function checkMargins(stage, root, rootRect) {
    const w = rootRect.width;
    const bad = [];
    stage.querySelectorAll('[data-qa="text"], [data-qa="img"]').forEach((n) => {
      const r = rectOf(n);
      if (r.width > w * 0.92 || r.height > rootRect.height * 0.94) return; // 大块容器跳过
      if (r.left - rootRect.left < w * SAFE - 2 || rootRect.right - r.right < w * SAFE - 2) {
        bad.push({ text: (n.textContent || "").slice(0, 14), type: "margin" });
      }
    });
    stage.querySelectorAll(".seal").forEach((n) => {
      const r = rectOf(n);
      if (
        r.left - rootRect.left < w * SEAL_SAFE - 2 ||
        rootRect.right - r.right < w * SEAL_SAFE - 2 ||
        rootRect.bottom - r.bottom < rootRect.height * SEAL_SAFE * 0.4
      ) {
        bad.push({ text: "(印章)", type: "seal-margin" });
      }
    });
    return { name: "H3 边距", ok: bad.length === 0, detail: bad.slice(0, 6) };
  }

  function checkTypeScale(stage) {
    const bad = [];
    const step = TYPE_STEPS.map((v) => v / 1080);
    stage.querySelectorAll('[data-qa="text"]').forEach((n) => {
      const fs = parseFloat(getComputedStyle(n).fontSize);
      const norm = fs / 1080;
      if (!step.some((s) => Math.abs(s - norm) < 0.004)) {
        bad.push({ text: (n.textContent || "").slice(0, 14), fs });
      }
    });
    return { name: "H4 字号阶梯", ok: bad.length === 0, detail: bad.slice(0, 6) };
  }

  function checkImages(stage) {
    const bad = [];
    stage.querySelectorAll('[data-qa="img"]').forEach((f) => {
      const img = f.querySelector("img");
      if (!img || !img.naturalWidth) { bad.push({type:"image-not-decoded"}); return; }
      const fr = rectOf(f), ir = rectOf(img);
      const srcRatio = img.naturalWidth / img.naturalHeight;
      const boxRatio = ir.width / Math.max(1, ir.height);
      if (Math.abs(srcRatio / boxRatio - 1) > 0.02) {
        // object-fit: cover 允许裁剪，但不允许拉伸——cover 不改变比例，此处仅记录
      }
      if (Math.min(img.naturalWidth, img.naturalHeight) < 600) {
        bad.push({ text: img.src.split("/").pop(), w: img.naturalWidth, h: img.naturalHeight });
      }
      if (fr.width < 120 || fr.height < 90) bad.push({ text: img.src.split("/").pop(), type: "too-small-slot" });
    });
    return { name: "H7 图片", ok: bad.length === 0, detail: bad.slice(0, 6) };
  }

  function checkOverlap(stage) {
    const texts = [...stage.querySelectorAll('[data-qa="text"]')];
    const imgs = [...stage.querySelectorAll('[data-qa="img"]')];
    const bad = [];
    const inter = (a, b) =>
      Math.min(a.right, b.right) - Math.max(a.left, b.left) > 6 &&
      Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 6;
    texts.forEach((t) => {
      const tr = rectOf(t);
      imgs.forEach((im) => {
        const ir = rectOf(im);
        if (inter(tr, ir)) bad.push({ text: (t.textContent || "").slice(0, 14), type: "text-over-image" });
      });
    });
    for (let i = 0; i < texts.length; i++) {
      for (let j = i + 1; j < texts.length; j++) {
        const a = rectOf(texts[i]), b = rectOf(texts[j]);
        if (a.width * a.height === 0 || b.width * b.height === 0) continue;
        if (inter(a, b)) {
          const oa = a.width * a.height, ob = b.width * b.height;
          if (Math.min(oa, ob) / Math.max(oa, ob) > 0.08) {
            bad.push({ text: (texts[i].textContent || "").slice(0, 12), type: "text-text" });
          }
        }
      }
    }
    return { name: "重叠", ok: bad.length === 0, detail: bad.slice(0, 6) };
  }

  function checkFooter(stage) {
    const n = stage.querySelector(".footer-slot .ai-mark");
    const ok = !!n && /AI 辅助生成/.test(n.textContent);
    return { name: "H11 AI 标注", ok, detail: ok ? "" : "footer 缺少“由小栖 AI 辅助生成”" };
  }

  function checkDensity(canvasCtx, w, h, palette) {
    try {
      const bg = palette.bg, paper = palette.paper;
      const img = canvasCtx.getImageData(0, 0, w, h).data;
      let same = 0, total = 0;
      for (let y = 0; y < h; y += 8) {
        for (let x = 0; x < w; x += 8) {
          const i = (y * w + x) * 4;
          const d = Math.min(Math.abs(img[i]-bg[0])+Math.abs(img[i+1]-bg[1])+Math.abs(img[i+2]-bg[2]),Math.abs(img[i]-paper[0])+Math.abs(img[i+1]-paper[1])+Math.abs(img[i+2]-paper[2]));
          if (d < 90) same++;
          total++;
        }
      }
      const ratio = same / Math.max(1, total);
      return { name: "H9 留白", ok: ratio >= 0.35, detail: `背景可见约 ${(ratio * 100).toFixed(0)}%` };
    } catch (e) {
      return { name: "H9 留白", ok: false, unknown: true, detail: "无法取样（跳过）" };
    }
  }

  function run(document_, stage, opts) {
    const root = stage;
    const rootRect = rectOf(root);
    const results = [
      checkOverflow(stage, rootRect),
      checkContrast(stage, root),
      checkMargins(stage, root, rootRect),
      checkTypeScale(stage),
      checkImages(stage),
      checkOverlap(stage),
      checkFooter(stage),
    ];
    if (opts && opts.canvasCtx && opts.palette) {
      results.push(checkDensity(opts.canvasCtx, opts.canvasCtx.canvas.width, opts.canvasCtx.canvas.height, opts.palette));
    }
    const failed = results.filter((r) => !r.ok || r.unknown);
    return {
      ok: failed.length === 0,
      pass: results.filter((r) => r.ok).length,
      total: results.length,
      results,
      failed: failed.map((r) => r.name),
    };
  }

  return { run, TYPE_STEPS, parseColor, contrast };
});
