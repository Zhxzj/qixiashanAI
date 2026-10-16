/* 游后日记 · 海报工作台（M6）
 * 流程：上传照片 → EXIF/视觉点位核对 → 回放小传 → 三候选渲染 → 质检 → 导出 PNG。
 * 合规：照片仅在本机内存与本产品调用的 LLM 之间流转；导出图 footer 固定 AI 标注。
 */
(function () {
  const $ = (s) => document.querySelector(s);
  const SID = localStorage.getItem("qixi_sid") || "demo";
  const STAGE_W = 1080, STAGE_H = 1620;
  const S = window.PosterSkill;

  const state = {
    photos: [],        // {id, url, file, gps, poi_id, poi_name, source, stay_s}
    poiById: {},
    trip: null,        // /api/recap 返回
    candidates: [],    // {grammar, palette, spec, qa, thumb}
    active: 0,
    seed: 20261031,
  };

  // ---------- 基础 ----------
  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  function fileToDataURL(file) {
    return new Promise((res, rej) => {
      const fr = new FileReader();
      fr.onload = () => res(fr.result);
      fr.onerror = rej;
      fr.readAsDataURL(file);
    });
  }

  function haversine(a, b) {
    const R = 6371000, r = Math.PI / 180;
    const dp = (b[0] - a[0]) * r, dl = (b[1] - a[1]) * r;
    const h = Math.sin(dp / 2) ** 2 + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(dl / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }

  function nearestPoi(lat, lng) {
    let best = null;
    for (const p of Object.values(state.poiById)) {
      const d = haversine([lat, lng], p.coord);
      if (!best || d < best.d) best = { id: p.poi_id, name: p.name, d };
    }
    return best && best.d < 400 ? best : null;
  }

  // ---------- 照片入列 ----------
  async function addPhotoFromURL(url, name, file) {
    const id = "p" + Math.random().toString(36).slice(2, 8);
    const item = { id, url, name: name || id, file, gps: null, poi_id: null, poi_name: null, source: "unknown" };
    if (window.exifr && file) {
      try {
        const ex = await window.exifr.parse(file, ["GPSLatitude", "GPSLongitude", "DateTimeOriginal"]);
        if (ex && ex.GPSLatitude != null && ex.GPSLongitude != null) {
          item.gps = [ex.GPSLatitude, ex.GPSLongitude];
          item.ts = ex.DateTimeOriginal ? new Date(ex.DateTimeOriginal).getTime() : Date.now();
          const near = nearestPoi(item.gps[0], item.gps[1]);
          if (near) {
            item.poi_id = near.id;
            item.poi_name = near.name;
            item.source = "gps";
          }
        }
      } catch (e) { /* 无 EXIF 不报错 */ }
    }
    state.photos.push(item);
    renderPhotoGrid();
    renderPhotoList();
    if (!item.poi_id) scheduleDetect(item);
  }

  function scheduleDetect(item) {
    // 无 GPS：调用后台视觉识别（无 Key 时返回本地候选，界面照样可点选）
    api("/api/photo/detect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: SID, data_url: item.url, photo_id: item.id }),
    })
      .then((r) => {
        item.detect = r;
        if (r.ok && r.best) {
          item.poi_id = r.best.poi_id;
          item.poi_name = r.best.name;
          item.source = "vision";
          item.confidence = r.best.vision_score;
        } else if (r.candidates && r.candidates[0]) {
          item.poi_id = r.candidates[0].poi_id;
          item.poi_name = r.candidates[0].name;
          item.source = "coarse";
          item.candidates = r.candidates;
          if (!r.ok && r.message) item.detect_note = r.message;
        } else if (r.message) {
          item.detect_note = r.message;
        }
        renderPhotoList();
      })
      .catch(() => {});
  }

  async function onFiles(files) {
    for (const f of files) {
      if (!f.type.startsWith("image/")) continue;
      const url = await fileToDataURL(f);
      await addPhotoFromURL(url, f.name, f);
    }
  }

  async function loadSamples() {
    const r = await api("/api/samples");
    const pick = r.items.slice(0, 4);
    const poiCycle = ["qianfoyan", "shuanghongyuan", "mingjinghu", "qixiasi"];
    for (let i = 0; i < pick.length; i++) {
      const s = pick[i];
      const resp = await fetch(s.url);
      const blob = await resp.blob();
      const file = new File([blob], s.name + ".jpg", { type: "image/jpeg" });
      const url = await fileToDataURL(file);
      await addPhotoFromURL(url, s.name, null);
      const item = state.photos[state.photos.length - 1];
      const p = state.poiById[poiCycle[i % poiCycle.length]];
      if (p) {
        item.poi_id = p.poi_id;
        item.poi_name = p.name;
        item.source = "sample";
      }
    }
    renderPhotoList();
  }

  // ---------- 界面：照片网格与点位核对 ----------
  function renderPhotoGrid() {
    const g = $("#photoGrid");
    g.innerHTML = state.photos
      .map(
        (p) => `<figure class="thumb" data-id="${p.id}">
          <img src="${p.url}" alt="">
          <button class="thumb-x" data-rm="${p.id}" title="移除">×</button>
        </figure>`
      )
      .join("");
    g.querySelectorAll("[data-rm]").forEach((b) =>
      b.addEventListener("click", (e) => {
        e.stopPropagation();
        state.photos = state.photos.filter((p) => p.id !== b.dataset.rm);
        renderPhotoGrid();
        renderPhotoList();
      })
    );
  }

  function sourceLabel(p) {
    if (p.source === "gps") return "GPS 匹配";
    if (p.source === "vision") return "视觉识别";
    if (p.source === "coarse") return "颜色相似（待确认）";
    if (p.source === "manual") return "手动指定";
    if (p.source === "sample") return "示例";
    return "待识别";
  }

  function renderPhotoList() {
    const box = $("#photoList");
    if (!state.photos.length) {
      box.innerHTML = '<div class="muted">还没有照片。上传或点「示例照片」。</div>';
      return;
    }
    box.innerHTML = state.photos
      .map(
        (p) => `<div class="photo-row" data-id="${p.id}">
          <img src="${p.url}" alt="">
          <div class="photo-meta">
            <div class="poi-name">${p.poi_name || "还没认出在哪"}</div>
            <div class="muted">${sourceLabel(p)}${
          p.confidence != null ? " · 置信 " + Math.round(p.confidence * 100) + "%" : ""
        }</div>
            ${p.detect_note ? `<div class="muted">⚠ ${p.detect_note}</div>` : ""}
          </div>
          <button class="ghost sm" data-pick="${p.id}">修改</button>
        </div>`
      )
      .join("");
    box.querySelectorAll("[data-pick]").forEach((b) =>
      b.addEventListener("click", () => openPick(b.dataset.pick))
    );
  }

  let pickingId = null;
  function openPick(id) {
    pickingId = id;
    const p = state.photos.find((x) => x.id === id);
    $("#pickPanel").hidden = false;
    $("#pickHint").textContent = `给「${p.name}」指定点位（点一下即选中）：`;
    const grid = $("#pickGrid");
    grid.innerHTML = Object.values(state.poiById)
      .map(
        (poi) =>
          `<button class="pick ${p.poi_id === poi.poi_id ? "on" : ""}" data-poi="${poi.poi_id}">${poi.name}</button>`
      )
      .join("");
    grid.querySelectorAll("[data-poi]").forEach((b) =>
      b.addEventListener("click", () => {
        const poi = state.poiById[b.dataset.poi];
        p.poi_id = poi.poi_id;
        p.poi_name = poi.name;
        p.source = "manual";
        $("#pickPanel").hidden = true;
        renderPhotoList();
      })
    );
  }

  // ---------- 游踪 / 回放小传 ----------
  async function refreshTrip() {
    try {
      state.trip = await api("/api/recap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: SID, photos: state.photos.map((p) => ({ id: p.id, poi_id: p.poi_id })) }),
      });
    } catch (e) {
      state.trip = { replay_lines: ["服务没连上，先检查后端是不是开着。"], diary: null, visited: [] };
    }
    renderTrip();
    return state.trip;
  }

  function renderTrip() {
    const t = state.trip || {};
    const visited = t.visited || [];
    $("#tripInfo").innerHTML = visited.length
      ? visited.map((v, i) => `<span class="chip">${i + 1}. ${v.name}</span>`).join("")
      : "还没有游踪。先回向导页走一段，再来生成日记。";
  }

  let replayRun = 0;
  async function playReplay() {
    if (!state.trip) await refreshTrip();
    const lines = (state.trip && state.trip.replay_lines) || [];
    const box = $("#replayBox");
    box.hidden = false;
    const myRun = ++replayRun;
    box.innerHTML = "";
    for (const line of lines) {
      const d = document.createElement("div");
      d.className = "replay-line";
      box.appendChild(d);
      for (const ch of line) {
        if (myRun !== replayRun) return;
        d.textContent += ch;
        await new Promise((r) => setTimeout(r, 46));
      }
      await new Promise((r) => setTimeout(r, 320));
    }
  }

  // ---------- 候选与生成 ----------
  function moodOf(photos, trip) {
    const red = ((trip.conditions || {}).red_leaf || {}).text || "";
    const day = photos.some((p) => {
      if (!p.ts) return false;
      const h = new Date(p.ts).getHours();
      return h >= 16 || h < 7;
    });
    if (day) return "dusk";
    if (/红|正红|七成/.test(red)) return "autumn";
    return "day";
  }

  const GRAMMAR_POOLS = {
    one: [["mount", "poem", "scroll"], "mount"],
    few: [["timeline", "map", "collage"], "timeline"],
    many: [["collage", "map", "timeline"], "collage"],
  };

  function pickGrammars(nPhotos) {
    const pool = nPhotos <= 1 ? GRAMMAR_POOLS.one : nPhotos <= 5 ? GRAMMAR_POOLS.few : GRAMMAR_POOLS.many;
    return pool[0];
  }

  function pickPalettes(mood) {
    if (mood === "autumn") return ["danfeng", "zhemo", "yanlan"];
    if (mood === "dusk") return ["zhemo", "yuebai", "danfeng"];
    return ["yuebai", "danfeng", "yanlan"];
  }

  function buildSpec(grammar, palette, seed) {
    const diary = (state.trip && state.trip.diary) || {};
    const caps = (diary.captions || []).map((c) => (typeof c === "string" ? { text: c } : c));
    const dateStr = new Date().toISOString().slice(0, 10).replace(/-/g, ".");
    const photos = state.photos.map((p, i) => ({
      file: p.id,
      url: p.url,
      role: i === 0 ? "hero" : "sub",
      crop: grammar === "collage" ? "polaroid" : grammar === "poem" ? "rect" : "rect",
      slot: i === 0 ? "top" : "mid",
    }));
    return {
      canvas: { w: STAGE_W, h: STAGE_H },
      grammar,
      palette,
      motifs: [],
      photos,
      type: {
        title: (diary.title || "山中一日").slice(0, 12),
        kicker: (diary.kicker || `${dateStr} · 栖霞山`).slice(0, 18),
        captions: caps.slice(0, 6),
        quote: diary.quote || null,
        seal: (diary.seal || "栖霞").slice(0, 4),
      },
      meta: {
        date: dateStr,
        poi_count: new Set(state.photos.map((p) => p.poi_id).filter(Boolean)).size,
        route_m: null,
        page_no: "No." + String(100 + (seed % 900)),
      },
      seed,
    };
  }

  function applyMotifs(spec, seed) {
    const r = mulberry(seed);
    const fav = spec.grammar === "map" ? "leaves_group" : spec.grammar === "poem" ? "sweetgum_line" : "maple_leaf_line";
    const motifs = [{ id: fav, style: "line", x: 0.03 + r() * 0.05, y: 0.02 + r() * 0.05, scale: 0.11 + r() * 0.05, rot: -20 + r() * 40, z: 2 }];
    if (r() > 0.4) {
      motifs.push({ id: "seal_frame", style: "line", x: 0.86, y: 0.86, scale: 0.09, rot: 0, z: 3, opacity: 0.5 });
    }
    spec.motifs = motifs.slice(0, 3);
  }

  function mulberry(seed) {
    let t = seed >>> 0;
    return function () {
      t += 0x6d2b79f5;
      let r = Math.imul(t ^ (t >>> 15), 1 | t);
      r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
      return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
    };
  }

  async function generate(bumpSeed) {
    if (!state.photos.length) {
      $("#candHint").textContent = "先放一张照片再生成。";
      return;
    }
    const btn = $("#genBtn");
    btn.disabled = true;
    btn.textContent = "生成中…";
    try {
      if (!state.trip) await refreshTrip();
      if (bumpSeed) state.seed = Math.floor(Math.random() * 1e8);
      const grammars = pickGrammars(state.photos.length);
      const palettes = pickPalettes(moodOf(state.photos, state.trip || {}));
      // 换一批：保住用户当前选中的那张，另外两张重排（海报办法 §3.3）
      const keep = bumpSeed ? state.candidates[state.active] : null;
      const next = [];
      const stage = $("#stage");
      for (let i = 0; i < grammars.length; i++) {
        if (keep && i === state.active) {
          next[i] = keep;
          continue;
        }
        const spec = buildSpec(grammars[i], palettes[i], state.seed + i * 7919);
        applyMotifs(spec, spec.seed);
        await S.render(stage, spec);
        await waitImages(stage);
        await document.fonts.ready.catch(() => {});
        const qa = await runQA(stage, spec);
        const thumb = await snapshot(stage, 0.22);
        next[i] = { grammar: grammars[i], palette: palettes[i], spec, qa, thumb };
      }
      state.candidates = next;
      if (!bumpSeed) state.active = 0;
      renderCandidates();
      await showCandidate(state.active);
      $("#stageEmpty").hidden = true;
    } catch (e) {
      $("#candHint").textContent = "出错了：" + e.message;
    } finally {
      btn.disabled = false;
      btn.textContent = "生成三张候选";
    }
  }

  function waitImages(scope) {
    const imgs = [...scope.querySelectorAll("img")];
    return Promise.all(
      imgs.map(
        (img) =>
          new Promise((res) => {
            if (img.complete && img.naturalWidth) return res();
            img.onload = img.onerror = () => res();
          })
      )
    );
  }

  async function snapshot(stage, ratio) {
    if (!window.htmlToImage) return null;
    try {
      return await window.htmlToImage.toPng(stage, {
        pixelRatio: ratio, width: STAGE_W, height: STAGE_H,
        style: { transform: "none" },
      });
    } catch (e) {
      return null;
    }
  }

  async function runQA(stage, spec) {
    const qa = window.PosterSkill.qa.run(document, stage, {});
    // 留白密度：用缩略图取样
    try {
      const url = await snapshot(stage, 0.16);
      const img = await loadImg(url);
      const c = document.createElement("canvas");
      c.width = img.naturalWidth; c.height = img.naturalHeight;
      const ctx = c.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0);
      const pal = S.PALETTES[spec.palette];
      // 复用 QA 里的密度思路（缩略图上取样，够稳）
      const data = ctx.getImageData(0, 0, c.width, c.height).data;
      const bg = pal.bg;
      let same = 0, total = 0;
      for (let y = 0; y < c.height; y += 4) {
        for (let x = 0; x < c.width; x += 4) {
          const i = (y * c.width + x) * 4;
          const d = Math.abs(data[i] - bg[0]) + Math.abs(data[i + 1] - bg[1]) + Math.abs(data[i + 2] - bg[2]);
          if (d < 90) same++;
          total++;
        }
      }
      const ratio = same / Math.max(1, total);
      qa.results.push({ name: "H9 留白", ok: ratio >= 0.3, detail: `背景可见约 ${(ratio * 100).toFixed(0)}%` });
      qa.total += 1;
      if (ratio >= 0.3) qa.pass += 1;
      else qa.ok = false;
    } catch (e) { /* 抽样失败不阻塞 */ }
    qa.ok = qa.results.every((r) => r.ok || r.unknown);
    return qa;
  }

  function loadImg(url) {
    return new Promise((res, rej) => {
      const i = new Image();
      i.onload = () => res(i);
      i.onerror = rej;
      i.src = url;
    });
  }

  function renderCandidates() {
    const row = $("#candRow");
    const labels = ["A", "B", "C"];
    row.innerHTML = state.candidates
      .map(
        (c, i) => `<button class="cand ${i === state.active ? "on" : ""}" data-i="${i}">
          <img src="${c.thumb || ""}" alt="">
          <span>${labels[i]} · ${grammarName(c.grammar)}<br><i>${paletteName(c.palette)}</i></span>
        </button>`
      )
      .join("");
    row.querySelectorAll("[data-i]").forEach((b) =>
      b.addEventListener("click", () => showCandidate(Number(b.dataset.i)))
    );
    if (state.candidates.length) $("#candHint").textContent = "点缩略图切换；不确定就选 A。";
  }

  const GRAMMAR_NAMES = { mount: "山门式", scroll: "卷轴式", timeline: "时间轴式", collage: "拼贴式", poem: "诗笺式", map: "地图式" };
  const PALETTE_NAMES = { danfeng: "丹枫", zhemo: "赭墨", yanlan: "烟岚", yuebai: "月白" };
  const grammarName = (g) => GRAMMAR_NAMES[g] || g;
  const paletteName = (p) => PALETTE_NAMES[p] || p;

  async function showCandidate(i) {
    const c = state.candidates[i];
    if (!c) return;
    state.active = i;
    const stage = $("#stage");
    await S.render(stage, { ...c.spec, motifs: c.spec.motifs });
    await waitImages(stage);
    await document.fonts.ready.catch(() => {});
    const qa = await runQA(stage, c.spec);
    c.qa = qa;
    renderCandidates();
    renderQABox(qa);
    renderHint(c.spec);
    fitStage();
  }

  function renderQABox(qa) {
    const badge = $("#qaBadge");
    badge.textContent = qa.ok ? `质检通过 ${qa.pass}/${qa.total}` : `有 ${qa.total - qa.pass} 项要改`;
    badge.classList.toggle("ok", qa.ok);
    badge.classList.toggle("bad", !qa.ok);
    $("#qaBox").innerHTML = qa.results
      .map((r) => {
        const mark = r.unknown ? "…" : r.ok ? "✓" : "✗";
        const detail = r.detail && r.detail.length
          ? `<span class="muted">${typeof r.detail === "string" ? r.detail : JSON.stringify(r.detail)}</span>`
          : "";
        return `<div class="qa-line ${r.ok ? "ok" : r.unknown ? "" : "bad"}">${mark} ${r.name} ${detail}</div>`;
      })
      .join("");
  }

  function renderHint(spec) {
    const h = spec.palette_hint;
    if (!h) {
      $("#hintBox").textContent = "没有取到照片主色（照片可能太暗或太亮）。";
      return;
    }
    const sw = h.extracted
      .map((c) => `<span class="sw" style="background:rgb(${c.join(",")})"></span>`)
      .join("");
    $("#hintBox").innerHTML = `照片主色：${sw} ${
      h.accent_override ? "命中点睛色，已替换 --accent。" : "和色板点睛色差得远，保留原色板。"
    }`;
  }

  async function exportPNG() {
    const c = state.candidates[state.active];
    if (!c) return;
    const stage = $("#stage");
    const prev = stage.style.transform;
    stage.style.transform = "none";
    try {
      const url = await snapshot(stage, 2);
      const a = document.createElement("a");
      a.href = url;
      a.download = `栖霞日记_${c.palette}_${Date.now()}.png`;
      a.click();
    } finally {
      stage.style.transform = prev;
    }
  }

  // ---------- 舞台缩放 ----------
  function fitStage() {
    const wrap = $("#stageWrap");
    const pad = 28;
    const scale = Math.min((wrap.clientWidth - pad * 2) / STAGE_W, (wrap.clientHeight - pad * 2) / STAGE_H);
    const stage = $("#stage");
    stage.style.transform = `scale(${Math.max(0.12, scale)})`;
    stage.style.transformOrigin = "top left";
    stage.style.position = "absolute";
    stage.style.left = ((wrap.clientWidth - STAGE_W * scale) / 2) + "px";
    stage.style.top = ((wrap.clientHeight - STAGE_H * scale) / 2) + "px";
  }

  // ---------- 事件 ----------
  function bind() {
    $("#pickBtn").addEventListener("click", () => $("#fileInput").click());
    $("#fileInput").addEventListener("change", (e) => onFiles([...e.target.files]));
    const dz = $("#dropZone");
    dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("on"); });
    dz.addEventListener("dragleave", () => dz.classList.remove("on"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault();
      dz.classList.remove("on");
      onFiles([...e.dataTransfer.files]);
    });
    $("#samplesBtn").addEventListener("click", loadSamples);
    $("#clearBtn").addEventListener("click", () => {
      state.photos = [];
      renderPhotoGrid();
      renderPhotoList();
    });
    $("#replayBtn").addEventListener("click", playReplay);
    $("#recapBtn").addEventListener("click", async () => {
      state.trip = null;
      await refreshTrip();
      $("#recapBtn").textContent = "已刷新";
      setTimeout(() => ($("#recapBtn").textContent = "刷新文案"), 900);
    });
    $("#genBtn").addEventListener("click", () => generate(false));
    $("#redrawBtn").addEventListener("click", () => generate(true));
    $("#pngBtn").addEventListener("click", exportPNG);
    window.addEventListener("resize", fitStage);
    document.addEventListener("keydown", (e) => {
      if (e.key === "1" || e.key === "2" || e.key === "3") showCandidate(Number(e.key) - 1);
    });
  }

  async function init() {
    try {
      const d = await api("/api/data");
      d.pois.forEach((p) => (state.poiById[p.poi_id] = p));
    } catch (e) {
      $("#tripInfo").textContent = "后端没起来？先运行 scripts\\start_dev.bat";
    }
    if (S && S.preloadMotifs) S.preloadMotifs();
    bind();
    fitStage();
    refreshTrip();
  }

  init();
})();
