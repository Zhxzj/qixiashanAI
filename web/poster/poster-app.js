/* 游后日记 · 海报工作台（M6）
 * 流程：上传照片 → EXIF/视觉点位核对 → 回放小传 → 三候选渲染 → 质检 → 导出 PNG。
 * 合规：照片仅在本机内存与本产品调用的 LLM 之间流转；导出图 footer 固定 AI 标注。
 */
(function () {
  const $ = (s) => document.querySelector(s);
  const SID = Qixi.sid;
  const embedded = window.parent !== window && new URLSearchParams(location.search).get('embedded') === '1';
  let hostActive = !embedded, hostReady = false, hostGeneration = null, hostVisits = null;
  let hostEpoch = localStorage.getItem('qixi_epoch') || '';
  let resolveHost;
  const hostState = new Promise(resolve => { resolveHost = resolve; });
  const tellHost = (type, data = {}) => { if(embedded) parent.postMessage({channel:'qixi-ui-v1',type,sid:SID,...data},location.origin); };
  if (embedded) document.body.classList.add('embedded');
  function applyEpoch(next) {
    if(typeof next !== 'string' || next === hostEpoch) return;
    hostEpoch = next; hostGeneration = null; albumEpoch++; detects.forEach(c=>c.abort()); invalidate();
  }
  window.addEventListener('message', e => {
    if(!embedded || e.origin !== location.origin || e.source !== parent || e.data?.channel !== 'qixi-ui-v1' || e.data.sid !== SID) return;
    const d=e.data;
    if(d.type === 'active' && typeof d.active === 'boolean') {
      hostActive=d.active; if(hostActive) requestAnimationFrame(fitStage);
    } else if(d.type === 'epoch') applyEpoch(d.epoch);
    else if(d.type === 'snapshot' && Number.isInteger(d.generation) && Array.isArray(d.visited)) {
      const changed=hostReady && hostGeneration !== null && hostGeneration !== d.generation;
      const epochChanged=d.epoch !== hostEpoch;
      applyEpoch(d.epoch);
      if(changed && !epochChanged) {albumEpoch++;detects.forEach(c=>c.abort());invalidate();}
      hostGeneration=d.generation;Qixi.generation=d.generation;hostReady=true;
      const visits=JSON.stringify(d.visited);
      if(hostVisits!==null && hostVisits!==visits && state.trip) {
        $('#hostTripNotice').hidden=false;
        $('#hostTripNotice').textContent='游览记录已更新。需要使用最新记录时，请在日记工具中刷新文案后重新生成。';
      }
      hostVisits=visits;
      if(!state.trip) {
        $('#tripInfo').textContent=d.visited.length ? d.visited.map(v=>state.poiById[v.poi_id]?.name || v.poi_id).join(' · ') : '还没有游踪。先到地图走一段，再来生成日记。';
      }
      resolveHost(d);
    } else if(d.type === 'unavailable') { $('#tripInfo').textContent='行程暂不可用，请返回问答检查服务后重试。'; }
  });
  const esc = Qixi.escape;
  let revision = 0, albumEpoch = 0, rendering = 0;
  let tripPending = null;
  const detects = new Map();
  let detectChain = Promise.resolve();
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


  function invalidate() {
    revision++;
    rendering++;
    replayRun++;
    state.trip = null;
    state.candidates = [];
    state.active = 0;
    if (tripPending) tripPending.controller.abort();
    tripPending = null;
    $("#candRow").replaceChildren();
    $("#stage").replaceChildren();
    $("#stageEmpty").hidden = false;
    $("#pngBtn").disabled = true;
    $("#diaryBody").textContent = "输入已更新，请重新生成日记。";
    $("#candHint").textContent = "输入已更新，旧海报已失效。";
    if($('#hostTripNotice')) $('#hostTripNotice').hidden=true;
  }

  function removePhoto(item) {
    detects.get(item.id)?.abort();
    if (item.url.startsWith("blob:")) URL.revokeObjectURL(item.url);
  }

  function makeStage() {
    const stage = document.createElement("div");
    stage.className = "poster-stage";
    Object.assign(stage.style, {position:"absolute",left:"-20000px",top:"0",width:STAGE_W+"px",height:STAGE_H+"px",transform:"none"});
    document.body.appendChild(stage);
    return stage;
  }

  async function prepareStage(spec) {
    const stage = makeStage();
    try {
      const rendered = structuredClone(spec);
      await S.render(stage, rendered);
      spec.palette_hint = rendered.palette_hint;
      await waitImages(stage);
      await Promise.race([document.fonts.ready,new Promise((_,reject)=>setTimeout(()=>reject(new Error("字体准备超时")),10000))]);
      return stage;
    } catch (e) { stage.remove(); throw e; }
  }

  async function inferenceURL(item) {
    const image = await loadImg(item.url);
    const ratio = Math.min(1, 1024 / Math.max(image.naturalWidth,image.naturalHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(image.naturalWidth*ratio); canvas.height = Math.round(image.naturalHeight*ratio);
    canvas.getContext("2d").drawImage(image,0,0,canvas.width,canvas.height);
    return canvas.toDataURL("image/jpeg",0.88);
  }
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
  async function addPhotoFromURL(url, name, file, samplePoi = null) {
    const epoch = albumEpoch;
    if (state.photos.length >= 12) throw new Error("一次最多 12 张照片");
    const decoded = await loadImg(url);
    if (decoded.naturalWidth * decoded.naturalHeight > 40000000) throw new Error("照片超过 4000 万像素，请缩小后再试");
    const id = "p" + Math.random().toString(36).slice(2, 8);
    const item = { id, url, name: name || id, file, gps: null, poi_id: null, poi_name: null, source: "unknown" };
    if (window.exifr && file) {
      try {
        const ex = await window.exifr.parse(file);
        if (ex && Number.isFinite(ex.latitude) && Number.isFinite(ex.longitude) && Math.abs(ex.latitude) <= 90 && Math.abs(ex.longitude) <= 180) {
          item.gps = [ex.latitude, ex.longitude];
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
    if (epoch !== albumEpoch) { if (url.startsWith("blob:")) URL.revokeObjectURL(url); return; }
    if (samplePoi) { const p = state.poiById[samplePoi]; item.poi_id = p.poi_id; item.poi_name = p.name; item.source = "sample"; }
    state.photos.push(item);
    invalidate();
    renderPhotoGrid();
    renderPhotoList();
    if (!item.poi_id) { detectChain = detectChain.then(() => scheduleDetect(item)).catch(() => {}); }
  }


  async function scheduleDetect(item) {
    if (!state.photos.includes(item) || ["manual","sample","gps"].includes(item.source)) return;
    const controller = new AbortController();
    const source = item.source;
    const epoch = albumEpoch;
    detects.set(item.id, controller);
    try {
      const data_url = await inferenceURL(item);
      if (controller.signal.aborted) return;
      const r = await api("/api/photo/detect", {
        method:"POST",headers:{"Content-Type":"application/json"},signal:controller.signal,
        body:JSON.stringify({session_id:SID,data_url,photo_id:item.id,allow_cloud:$("#cloudDetect").checked}),
      });
      if (epoch !== albumEpoch || !state.photos.includes(item) || item.source !== source || controller.signal.aborted) return;
      item.detect = r;
      const best = r.best || r.candidates?.[0];
      if (best && state.poiById[best.poi_id]) {
        item.poi_id = best.poi_id; item.poi_name = state.poiById[best.poi_id].name;
        item.source = r.mode === "vision" ? "vision" : "coarse";
        item.confidence = best.vision_score;
        item.candidates = r.candidates;
      }
      item.detect_note = r.message || "识别建议，请修改或手动确认后使用地点";
      invalidate();
      renderPhotoList();
    } catch(e) {
      if (e.name !== "AbortError" && state.photos.includes(item)) { item.detect_note = "识别未完成，请手动选择地点"; renderPhotoList(); }
    } finally { detects.delete(item.id); }
  }

  async function onFiles(files) {
    const epoch = albumEpoch;
    for (const f of files) {
      let url;
      try {
        if (epoch !== albumEpoch) break;
        if (!/\.(jpe?g|png|webp)$/i.test(f.name)) throw new Error("请将 HEIC 等格式转换为 JPG/PNG/WEBP 后选择");
        if (f.size > 25000000) throw new Error("每张原图最多 25MB");
        url = URL.createObjectURL(f);
        await addPhotoFromURL(url,f.name,f);
      } catch(e) { if (url) URL.revokeObjectURL(url); $("#photoError").textContent = f.name + "：" + e.message; }
    }
  }

  async function loadSamples() {
    const epoch = albumEpoch;
    const r = await api("/api/samples");
    const pick = r.items.slice(0, 4);
    const poiCycle = ["qianfoyan", "shuanghongyuan", "mingjinghu", "qixiasi"];
    for (let i = 0; i < pick.length; i++) {
      const s = pick[i];
      const resp = await fetch(s.url);
      const blob = await resp.blob();
      const file = new File([blob], s.name + ".jpg", { type: "image/jpeg" });
      const url = await fileToDataURL(file);
      if (epoch !== albumEpoch) return;
      await addPhotoFromURL(url, s.name, null, poiCycle[i % poiCycle.length]);
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
        const item = state.photos.find((p) => p.id === b.dataset.rm);
        if (item) removePhoto(item);
        state.photos = state.photos.filter((p) => p.id !== b.dataset.rm);
        invalidate();
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
            <div class="poi-name">${esc(p.poi_name || "还没认出在哪")}</div>
            <div class="muted">${sourceLabel(p)}${
          p.confidence != null ? " · 置信 " + Math.round(p.confidence * 100) + "%" : ""
        }</div>
            ${p.detect_note ? `<div class="muted">⚠ ${esc(p.detect_note)}</div>` : ""}
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
        detects.get(p.id)?.abort();
        invalidate();
        $("#pickPanel").hidden = true;
        renderPhotoList();
      })
    );
  }

  // ---------- 游踪 / 回放小传 ----------

  async function refreshTrip() {
    if (state.trip) return state.trip;
    if (tripPending && tripPending.revision === revision) return tripPending.promise;
    const rev = revision;
    const controller = new AbortController();
    const promise = (async () => {
      const r = await api("/api/recap",{method:"POST",headers:{"Content-Type":"application/json"},signal:controller.signal,
        body:JSON.stringify({session_id:SID,photos:state.photos.map((p)=>({id:p.id,poi_id:p.poi_id,source:p.source,ts:p.ts || null}))})});
      if (rev !== revision) throw new Error("输入已更新，请重新生成");
      state.trip = r;
      renderTrip();
      $("#diaryBody").textContent = (r.diary?.paragraphs || []).join("\n\n") + (r.diary?.source === "fallback" ? "\n\n（记录模板）" : "");
      return r;
    })();
    tripPending = {revision:rev,controller,promise};
    try { return await promise; } finally { if (tripPending?.promise === promise) tripPending = null; }
  }

  function renderTrip() {
    const t = state.trip || {};
    const visited = t.visited || [];
    $("#tripInfo").innerHTML = visited.length
      ? visited.map((v, i) => `<span class="chip">${i + 1}. ${esc(v.name)}</span>`).join("")
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
      d.className = "replay-line replaying";
      box.appendChild(d);
      if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {d.textContent=line;d.classList.remove("replaying");continue;}
      for (const ch of line) {
        if (myRun !== replayRun) return;
        d.textContent += ch;
        await new Promise((r) => setTimeout(r, 46));
      }
      d.classList.remove("replaying");
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
    const byId = new Map((diary.captions || []).map((c) => [c.photo_id, c]));
    const caps = state.photos.map((p) => byId.get(p.id) || {photo_id:p.id,text:"地点待确认"});
    const dateStr = new Intl.DateTimeFormat("sv-SE", {timeZone:"Asia/Shanghai"}).format(new Date()).replace(/-/g,".");
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
    if (!state.photos.length) { $("#candHint").textContent = "先放一张照片再生成。"; return; }
    const token = ++rendering;
    const rev = revision;
    const btn = $("#genBtn"); btn.disabled = true; btn.textContent = "生成中…";
    try {
      await refreshTrip();
      if (token !== rendering || rev !== revision) return;
      if (bumpSeed) state.seed = Math.floor(Math.random()*1e8);
      const grammars = pickGrammars(state.photos.length);
      const palettes = pickPalettes(moodOf(state.photos,state.trip));
      const next = [];
      for (let i = 0; i < grammars.length; i++) {
        const spec = buildSpec(grammars[i],palettes[i],state.seed+i*7919);
        applyMotifs(spec,spec.seed);
        const stage = await prepareStage(spec);
        try {
          const qa = await runQA(stage,spec);
          const thumb = await snapshot(stage,0.22);
          if (token !== rendering || rev !== revision) return;
          next.push({grammar:grammars[i],palette:palettes[i],spec:structuredClone(spec),qa,thumb,revision:rev});
        } finally { stage.remove(); }
      }
      state.candidates = next; state.active = 0;
      renderCandidates();
      await showCandidate(0);
    } catch(e) { $("#candHint").textContent = "生成未完成："+e.message; }
    finally { btn.disabled = false; btn.textContent = "生成三张候选"; }
  }

  function waitImages(scope) {
    return Promise.all([...scope.querySelectorAll("img")].map((img)=>new Promise((resolve,reject)=>{
      const finish = (error) => { clearTimeout(timer); img.removeEventListener("load",loaded); img.removeEventListener("error",failed); error ? reject(error) : resolve(); };
      const loaded = () => finish(img.naturalWidth ? null : new Error("照片解码失败"));
      const failed = () => finish(new Error("照片加载失败，请重新选择"));
      const timer = setTimeout(()=>finish(new Error("照片加载超时")),15000);
      if (img.complete) return loaded();
      img.addEventListener("load",loaded,{once:true}); img.addEventListener("error",failed,{once:true});
    })));
  }

  async function snapshot(stage,ratio) {
    if (!window.htmlToImage) throw new Error("导出组件未就绪");
    let timer;
    // Computed logical insets also contain the offscreen position. Reset both
    // logical and physical coordinates on the exported clone.
    const task = window.htmlToImage.toPng(stage,{pixelRatio:ratio,width:STAGE_W,height:STAGE_H,style:{position:"relative",transform:"none",insetBlock:"0 auto",insetInline:"0 auto",left:"0",top:"0",right:"auto",bottom:"auto"}});
    let url;
    try { url = await Promise.race([task,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error("图片导出超时，请重试")),30000);})]); }
    finally { clearTimeout(timer); }
    if (!url || !url.startsWith("data:image/png")) throw new Error("未生成有效 PNG");
    return url;
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
      const bg = pal.bg, paper = pal.paper;
      let same = 0, total = 0;
      for (let y = 0; y < c.height; y += 4) {
        for (let x = 0; x < c.width; x += 4) {
          const i = (y * c.width + x) * 4;
          const d = Math.min(Math.abs(data[i]-bg[0])+Math.abs(data[i+1]-bg[1])+Math.abs(data[i+2]-bg[2]), Math.abs(data[i]-paper[0])+Math.abs(data[i+1]-paper[1])+Math.abs(data[i+2]-paper[2]));
          if (d < 90) same++;
          total++;
        }
      }
      const ratio = same / Math.max(1, total);
      qa.results.push({ name: "H9 留白", ok: ratio >= 0.35, detail: `背景可见约 ${(ratio * 100).toFixed(0)}%` });
      qa.total += 1;
      if (ratio >= 0.35) qa.pass += 1;
      else qa.ok = false;
    } catch (e) { qa.results.push({name:"H9 留白",ok:false,unknown:true,detail:"取样未完成"}); qa.total++; }
    qa.ok = qa.results.every((r) => r.ok && !r.unknown);
    return qa;
  }

  function loadImg(url) {
    return new Promise((res, rej) => {
      const i = new Image();
      const timer = setTimeout(() => rej(new Error("图片解码超时")),15000);
      i.onload = () => { clearTimeout(timer); res(i); };
      i.onerror = () => { clearTimeout(timer); rej(new Error("图片无法解码")); };
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
      b.addEventListener("click", () => showCandidate(Number(b.dataset.i)).catch(e => $("#candHint").textContent=e.message))
    );
    if (state.candidates.length) $("#candHint").textContent = "点缩略图切换；不确定就选 A。";
  }

  const GRAMMAR_NAMES = { mount: "山门式", scroll: "卷轴式", timeline: "时间轴式", collage: "拼贴式", poem: "诗笺式", map: "地图式" };
  const PALETTE_NAMES = { danfeng: "丹枫", zhemo: "赭墨", yanlan: "烟岚", yuebai: "月白" };
  const grammarName = (g) => GRAMMAR_NAMES[g] || g;
  const paletteName = (p) => PALETTE_NAMES[p] || p;


  async function showCandidate(i) {
    const c = state.candidates[i];
    if (!c || c.revision !== revision) return;
    const token = ++rendering;
    state.active = i;
    const prepared = await prepareStage(c.spec);
    try {
      if (token !== rendering || c.revision !== revision) return;
      const stage = $("#stage");
      stage.replaceChildren(...prepared.childNodes);
      stage.dataset.palette = prepared.dataset.palette;
      stage.style.setProperty("--accent",prepared.style.getPropertyValue("--accent"));
      renderCandidates(); renderQABox(c.qa); renderHint(c.spec); fitStage();
      $("#stageEmpty").hidden = true;
      $("#pngBtn").disabled = !c.qa.ok;
    } finally { prepared.remove(); }
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
    const candidate = state.candidates[state.active];
    if (!candidate || candidate.revision !== revision) return;
    const rev = revision;
    const spec = structuredClone(candidate.spec);
    const button = $("#pngBtn"); button.disabled = true;
    let stage;
    try {
      stage = await prepareStage(spec);
      const qa = await runQA(stage,spec);
      if (!qa.ok) throw new Error("质检未通过，请选择其他候选或调整照片后重试");
      const data = await snapshot(stage,1);
      const image = await loadImg(data);
      if (image.naturalWidth !== STAGE_W || image.naturalHeight !== STAGE_H) throw new Error("导出尺寸校验失败");
      if (rev !== revision) throw new Error("输入已更新，请重新生成");
      const blob = await (await fetch(data)).blob();
      if (!blob.size) throw new Error("导出文件为空");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = `栖霞日记_${candidate.palette}_${Date.now()}.png`; a.click();
      setTimeout(()=>URL.revokeObjectURL(url),30000);
    } catch(e) { $("#candHint").textContent = "导出失败："+e.message; }
    finally { stage?.remove(); button.disabled = !state.candidates[state.active]?.qa.ok; }
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
    $("#samplesBtn").addEventListener("click", () => loadSamples().catch(e => $("#photoError").textContent=e.message));
    $("#clearBtn").addEventListener("click", () => {
      albumEpoch++;
      state.photos.forEach(removePhoto);
      state.photos = [];
      invalidate();
      renderPhotoGrid();
      renderPhotoList();
    });
    $("#replayBtn").addEventListener("click", () => playReplay().catch(e => $("#photoError").textContent=e.message));
    $("#recapBtn").addEventListener("click", async () => {
      invalidate();
      try { await refreshTrip(); } catch(e) { $("#photoError").textContent=e.message; return; }
      $("#recapBtn").textContent = "已刷新";
      setTimeout(() => ($("#recapBtn").textContent = "刷新文案"), 900);
    });
    $("#genBtn").addEventListener("click", () => generate(false));
    $("#redrawBtn").addEventListener("click", () => generate(true));
    $("#pngBtn").disabled = true;
    $("#pngBtn").addEventListener("click", exportPNG);
    $("#copyDiary").addEventListener("click", async () => { try { await navigator.clipboard.writeText((state.trip?.diary?.paragraphs || []).join("\n\n")); $("#copyDiary").textContent="已复制"; } catch(e) { $("#copyDiary").textContent="请选中正文复制"; } });
    window.addEventListener("storage", (e) => { if (e.key === "qixi_epoch") applyEpoch(e.newValue || ""); });
    window.addEventListener("resize", fitStage);
    document.addEventListener("keydown", (e) => {
      if(!hostActive || /INPUT|TEXTAREA|SELECT/.test(e.target.tagName) || e.target.isContentEditable) return;
      if (e.key === "1" || e.key === "2" || e.key === "3") showCandidate(Number(e.key) - 1).catch(e => $("#candHint").textContent=e.message);
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
    if(embedded) {
      document.querySelector('.topnav a').onclick=e=>{e.preventDefault();tellHost('back');};
      tellHost('ready');
      const retry=setInterval(()=>{if(!hostReady)tellHost('request-state');else clearInterval(retry);},5000);
      new MutationObserver(()=>tellHost('busy',{busy:!!tripPending || $('#genBtn').disabled || detects.size>0})).observe(document.querySelector('.poster-layout'),{subtree:true,attributes:true,childList:true});
    }
    const st = embedded ? await hostState : await api(`/api/state?session_id=${SID}`);
    Qixi.generation = st.generation;
    state.trip = {visited:st.visited.map(v=>({poi_id:v.poi_id,name:state.poiById[v.poi_id]?.name || v.poi_id}))};
    renderTrip();
    state.trip = null;
  }

  init();
})();
