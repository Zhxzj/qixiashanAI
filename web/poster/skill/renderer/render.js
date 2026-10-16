/* 海报渲染引擎：DesignSpec + 照片 → #stage DOM（海报办法 §3.5）。
 * 约束：全部 DOM + class；色值只走 CSS 变量；导出前 document.fonts.ready。
 */
(function () {
  const S = (window.PosterSkill = window.PosterSkill || {});

  const MOTIFS = [
    "maple_leaf_line", "maple_leaf_solid", "sweetgum_line", "leaves_group",
    "mountain_line", "mountain_solid", "stupa_line", "arch_line",
    "buddha_dots", "ripple_line", "cloud_line", "seal_frame",
  ];
  const motifCache = {};

  async function loadMotif(id) {
    if (motifCache[id]) return motifCache[id];
    const r = await fetch(`/poster/skill/motifs/${id}.svg`);
    const text = await r.text();
    motifCache[id] = text;
    return text;
  }

  async function preloadMotifs() {
    await Promise.all(MOTIFS.map((m) => loadMotif(m).catch(() => null)));
  }

  // ---------- 工具 ----------

  function mulberry32(seed) {
    let t = seed >>> 0;
    return function () {
      t += 0x6d2b79f5;
      let r = Math.imul(t ^ (t >>> 15), 1 | t);
      r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
      return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
    };
  }

  function el(tag, cls, style) {
    const d = document.createElement(tag);
    if (cls) d.className = cls;
    if (style) Object.assign(d.style, style);
    return d;
  }

  function textEl(tag, cls, text, style) {
    const d = el(tag, cls, style);
    d.textContent = text;
    d.setAttribute("data-qa", "text");
    return d;
  }

  function verticalTitle(text, cls, style) {
    const box = el("div", cls, style);
    box.setAttribute("data-qa", "text");
    box.style.display = "flex";
    box.style.flexDirection = "column";
    box.style.alignItems = "center";
    for (const ch of String(text).slice(0, 12)) {
      const s = document.createElement("div");
      s.textContent = ch;
      box.appendChild(s);
    }
    return box;
  }

  function photoEl(photo, crop, style) {
    const f = el("div", "pframe " + (crop || "rect"), style);
    f.setAttribute("data-qa", "img");
    const img = document.createElement("img");
    img.src = photo.url;
    img.alt = "";
    f.appendChild(img);
    return f;
  }

  function sealEl(text, style, small) {
    const box = el("div", "seal" + (small ? " small" : ""), style);
    box.setAttribute("data-qa", "text");
    const chars = String(text || "栖霞").slice(0, 4).split("");
    while (chars.length < 4) chars.push("");
    chars.slice(0, 4).forEach((c) => {
      const s = document.createElement("span");
      s.textContent = c;
      box.appendChild(s);
    });
    return box;
  }

  function motifEl(svgText, spec) {
    const d = el("div", "motif", {
      left: (spec.x * 100).toFixed(2) + "%",
      top: (spec.y * 100).toFixed(2) + "%",
      width: (spec.scale * 1080).toFixed(0) + "px",
      height: (spec.scale * 1080 * 0.64).toFixed(0) + "px",
      transform: `rotate(${spec.rot || 0}deg)`,
      color: spec.color === "primary" ? "var(--primary)" : "var(--accent)",
      opacity: spec.opacity == null ? 0.9 : spec.opacity,
    });
    if (spec.scale < 0.2) d.style.height = (spec.scale * 1080).toFixed(0) + "px";
    d.innerHTML = svgText;
    d.setAttribute("data-qa", "motif");
    return d;
  }

  function footerEl(dateText) {
    const f = el("div", "footer-slot");
    const a = textEl("span", "ai-mark t6", `由小栖 AI 辅助生成 · ${dateText}`);
    const b = textEl("span", "t6", "天气数据 © Open-Meteo");
    b.style.opacity = "0.7";
    f.appendChild(a);
    f.appendChild(b);
    return f;
  }

  // ---------- 取色（§3.4） ----------

  function rgb2lab(r, g, b) {
    const f = (v) => {
      v /= 255;
      return v > 0.04045 ? Math.pow((v + 0.055) / 1.055, 2.4) : v / 12.92;
    };
    const R = f(r), G = f(g), B = f(b);
    let x = (R * 0.4124 + G * 0.3576 + B * 0.1805) / 0.95047;
    let y = R * 0.2126 + G * 0.7152 + B * 0.0722;
    let z = (R * 0.0193 + G * 0.1192 + B * 0.9505) / 1.08883;
    const g2 = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
    x = g2(x); y = g2(y); z = g2(z);
    return [116 * y - 16, 500 * (x - y), 200 * (y - z)];
  }

  function extractPalette(photos) {
    return new Promise((resolve) => {
      const hist = new Map();
      let pending = photos.length;
      if (!pending) return resolve(null);
      let settled = false;
      const finishOnce = (val) => { if (!settled) { settled = true; resolve(val); } };
      // 照片解码失败/超时不能让整条渲染管线卡住
      const guard = setTimeout(() => finishOnce(null), 1200);
      photos.forEach((p) => {
        const img = new Image();
        img.onload = () => {
          try {
            const k = 256 / Math.max(img.naturalWidth, img.naturalHeight);
            const c = document.createElement("canvas");
            c.width = Math.max(1, Math.round(img.naturalWidth * Math.min(1, k)));
            c.height = Math.max(1, Math.round(img.naturalHeight * Math.min(1, k)));
            const ctx = c.getContext("2d", { willReadFrequently: true });
            ctx.drawImage(img, 0, 0, c.width, c.height);
            const data = ctx.getImageData(0, 0, c.width, c.height).data;
            for (let i = 0; i < data.length; i += 16) {
              const r = data[i], g = data[i + 1], b = data[i + 2];
              const lum = 0.299 * r + 0.587 * g + 0.114 * b;
              if (lum < 26 || lum > 232) continue;
              const key = `${r >> 5},${g >> 5},${b >> 5}`;
              const e = hist.get(key) || [0, 0, 0, 0];
              e[0] += r; e[1] += g; e[2] += b; e[3] += 1;
              hist.set(key, e);
            }
          } catch (e) { /* 取色失败不影响渲染 */ }
          if (--pending === 0) { clearTimeout(guard); finish(); }
        };
        img.onerror = () => { if (--pending === 0) { clearTimeout(guard); finish(); } };
        img.src = p.url;
      });

      function finish() {
        const top = [...hist.values()].sort((a, b) => b[3] - a[3]).slice(0, 3)
          .map((e) => [e[0] / e[3], e[1] / e[3], e[2] / e[3]].map(Math.round));
        if (!top.length) return resolve(null);
        const labTop = rgb2lab(...top[0]);
        const pal = S.currentPalette ? S.currentPalette() : null;
        let accentOverride = null;
        if (pal && pal.accent) {
          const labAccent = rgb2lab(...pal.accent);
          const dE = Math.sqrt(labAccent.reduce((s, v, i) => s + (v - labTop[i]) ** 2, 0));
          if (dE < 12) accentOverride = top[0];
        }
        resolve({ extracted: top, accent_override: accentOverride });
      }
    });
  }

  const PALETTES = {
    danfeng: { bg: [166, 58, 43], paper: [247, 240, 228], primary: [194, 73, 47], secondary: [110, 42, 32], accent: [217, 164, 65], ink: [46, 38, 34] },
    zhemo: { bg: [243, 237, 224], paper: [251, 247, 239], primary: [140, 90, 43], secondary: [74, 58, 42], accent: [178, 58, 46], ink: [43, 38, 32] },
    yanlan: { bg: [223, 220, 212], paper: [244, 242, 236], primary: [91, 110, 106], secondary: [148, 166, 158], accent: [194, 73, 47], ink: [51, 59, 56] },
    yuebai: { bg: [247, 245, 240], paper: [255, 255, 255], primary: [62, 74, 91], secondary: [168, 176, 189], accent: [217, 164, 65], ink: [38, 44, 54] },
  };
  S.currentPalette = () => PALETTES[document.getElementById("stage").dataset.palette] || PALETTES.danfeng;
  S.PALETTES = PALETTES;

  // ---------- 渲染 ----------

  async function render(stage, spec) {
    stage.dataset.palette = spec.palette;
    stage.innerHTML = "";
    stage.classList.add("poster-stage");

    const grain = el("div", "paper-grain");
    stage.appendChild(grain);
    stage.appendChild(el("div", "paper-base", {
      position: "absolute", inset: "3%", background: "var(--paper)",
      boxShadow: "0 0 0 1px color-mix(in srgb, var(--secondary) 30%, transparent)",
    }));

    const ctx = buildContext(spec);
    const grammar = S.grammars[spec.grammar] || S.grammars.mount;
    const content = await grammar(ctx);
    stage.appendChild(content);

    const hint = await extractPalette(spec.photos);
    spec.palette_hint = hint;
    if (hint && hint.accent_override) {
      stage.style.setProperty("--accent", `rgb(${hint.accent_override.join(",")})`);
    } else {
      stage.style.removeProperty("--accent");
    }
    // 母题（在语法内容之后叠放，z-index 抬升）
    const rnd = mulberry32(spec.seed || 1);
    const chosen = pickMotifs(spec, rnd);
    for (const m of chosen) {
      const svg = await loadMotif(m.id).catch(() => null);
      if (!svg) continue;
      const node = motifEl(svg, m);
      node.style.zIndex = m.z || 2;
      stage.appendChild(node);
    }
    stage.appendChild(footerEl(spec.meta.date));
    if (spec.type.seal) stage.appendChild(sealEl(spec.type.seal, { right: "6%", bottom: "7%" }, spec.grammar === "timeline"));
    return stage;
  }

  function pickMotifs(spec, rnd) {
    const base = spec.motifs && spec.motifs.length ? spec.motifs : [];
    const out = base.slice(0, 3);
    return out;
  }

  function buildContext(spec) {
    const { w, h } = spec.canvas;
    const hero = spec.photos.find((p) => p.role === "hero") || spec.photos[0];
    const subs = spec.photos.filter((p) => p !== hero).slice(0, 5);
    // caption 两种形态都吃：字符串 或 {poi_id, text}（海报办法 §3.2）
    const caps = (spec.type.captions || [])
      .map((c) => (typeof c === "string" ? { text: c } : c))
      .filter((c) => c && c.text);
    return {
      spec, w, h, hero, subs, caps, rnd: mulberry32(spec.seed || 1),
      el, textEl, verticalTitle, photoEl, motifEl,
      title: spec.type.title || "山中一日",
      kicker: spec.type.kicker || spec.meta.date,
    };
  }

  S.render = render;
  S.loadMotif = loadMotif;
  S.preloadMotifs = preloadMotifs;
  S.extractPalette = extractPalette;
})();
