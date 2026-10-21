/* 栖霞山小向导 · 前端（M3/M4）
 * 对话（SSE 流式）+ 示意地图 + 到点自动播报 + 演示控制台 + 剧本模式。
 */
const SID = Qixi.sid;
let uiGeneration = 0;
let stateRequestSequence = 0;
const chats = new Map();
const seenArrivals = new Set();
const $ = (s) => document.querySelector(s);
let DATA = { pois: [], routes: [] };

const TOOL_LABELS = {
  get_location: "位置",
  list_nearby: "周边",
  get_poi: "讲解资料",
  plan_route: "路线",
  navigate_hint: "导航提示",
  save_memory: "记住此刻",
  get_conditions: "天气与红叶",
};

const state = {
  visits: {},      // 此次会话内每点驻足次数（进入 35m 内计数）
  speaking: null,  // 正在播报的信息
  voiceOn: true,   // 游客是否允许开口（"别念了"后置 false）
  scriptRunning: false,
};

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json()).detail || "HTTP " + r.status);
  return r.json();
}

// ---------- 初始化 ----------

async function init() {
  refreshConditions().catch(() => { $("#conditions").textContent = "天气暂不可用";window.QixiUI?.conditionsError(); });
  const core=api('/api/data').then(d=>{DATA=d;fillPoiSelect();return refreshState();});
  const health=api('/api/health').then(h=>setKeyStatus(!!h.key_configured));
  const status=await Promise.allSettled([core,health]);
  status.forEach(x=>{if(x.status==='rejected')addNote('部分数据加载失败：'+x.reason.message);});
  try { await QixiMap.init({data:DATA,refresh:refreshState}); }
  catch(e){const warning=$('#mapLoadError');warning.hidden=false;warning.textContent='地图加载失败：'+e.message+'。请点击重试底图。';}
  await refreshState().catch(e=>addNote('会话暂不可用：'+e.message));
  setInterval(() => refreshState().catch(() => {}), 2000);
  $('#appVersion').textContent=window.QIXI_FRONTEND?.version||'版本待核对';
  $('#reloadVersion').onclick=()=>location.reload();
  async function checkVersion(){try{const current=await api('/api/ui-version');if(current.web_revision!==window.QIXI_FRONTEND?.web_revision||current.build_id!==window.QIXI_FRONTEND?.build_id)$('#versionNotice').hidden=false;}catch{}}
  checkVersion();setInterval(checkVersion,15000);
}

function setKeyStatus(ok) {
  window.QixiUI?.keyStatus(ok);
  const el = $("#keyStatus");
  el.textContent = ok ? "Key 已保存（可测试连接）" : "对话尚未配置";
  el.classList.toggle("ok", ok);
}

function fillPoiSelect() {
  $("#poiSelect").innerHTML = DATA.pois
    .map((p) => `<option value="${p.poi_id}">${p.name}</option>`)
    .join("");
}

async function refreshState() {
  const epoch = uiGeneration;
  const requestSequence = ++stateRequestSequence;
  const st = await api(`/api/state?session_id=${SID}`);
  if (epoch !== uiGeneration || requestSequence !== stateRequestSequence) return st;
  Qixi.generation = st.generation;
  if (st.arrived) onArrive(st.arrived, st.location?.snapped?.poi_distance_m);
  renderMap(st);
  renderStateInfo(st);
  renderTripMini(st);
  window.QixiUI?.snapshot(st);
  return st;
}

function renderStateInfo(st) {
  const loc = st.location || {};
  const snapped = loc.snapped || {};
  const poi = DATA.pois.find((p) => p.poi_id === snapped.poi_id);
  $("#stateInfo").textContent = loc.lat == null ? "尚无真实位置；可手动选起点" : `${loc.source === "sim" ? "模拟位置 · " : loc.source === "manual" ? "手动起点 · " : "设备位置 · "}${Number(loc.lat).toFixed(4)}, ${Number(loc.lng).toFixed(4)}${
    poi ? " · 在" + poi.name : ""
  }`;
}

function renderTripMini(st) {
  const visited = st.visited || [];
  const memories = st.memory || [];
  if (!visited.length) {
    $("#tripMini").textContent = "走到哪儿，这里就记到哪儿。";
    return;
  }
  const names = visited
    .map((v) => ((DATA.pois.find((p) => p.poi_id === v.poi_id) || {}).name || v.poi_id) + (v.source === "sim" ? "（演示）" : ""))
    .map((n) => `<span class="chip">${n}</span>`)
    .join("");
  const mem = memories.length ? `<div class="muted">记下 ${memories.length} 条</div>` : "";
  $("#tripMini").innerHTML = names + mem;
}

// ---------- 地图 ----------

function renderMap(st) {
  if (window.QixiMap && QixiMap.update(st)) return;
  renderDraftMap(st);
}

function renderDraftMap(st) {
  const box = $("#mapBox");
  const pts = [];
  DATA.routes.forEach((r) => (r.geometry || []).forEach((g) => pts.push(g)));
  DATA.pois.forEach((p) => pts.push(p.coord));
  if (!pts.length) return;
  const lats = pts.map((p) => p[0]);
  const lngs = pts.map((p) => p[1]);
  const minLat = Math.min(...lats), maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs), maxLng = Math.max(...lngs);
  const W = 320, H = 360, pad = 26;
  const sx = (lng) => pad + ((lng - minLng) / (maxLng - minLng || 1)) * (W - pad * 2);
  const sy = (lat) => H - pad - ((lat - minLat) / (maxLat - minLat || 1)) * (H - pad * 2);

  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;
  const activeId = (st && st.route && st.route.route_id) || "";
  DATA.routes.forEach((r) => {
    const ptsStr = (r.geometry || [])
      .map((g) => `${sx(g[1]).toFixed(1)},${sy(g[0]).toFixed(1)}`)
      .join(" ");
    svg += `<polyline points="${ptsStr}" class="route ${r.route_id} ${
      r.route_id === activeId ? "active" : ""
    }" />`;
  });
  DATA.pois.forEach((p) => {
    const [lat, lng] = p.coord;
    const x = sx(lng).toFixed(1), y = sy(lat).toFixed(1);
    const visited = (st.visited || []).some((v) => v.poi_id === p.poi_id);
    svg += `<circle cx="${x}" cy="${y}" r="${visited ? 4.2 : 3.2}" class="poi${
      visited ? " visited" : ""
    }" />`;
    svg += `<text x="${Number(x) + 6}" y="${Number(y) + 3}" class="poi-label">${p.name}</text>`;
  });
  if (st && st.location) {
    svg += `<circle cx="${sx(st.location.lng).toFixed(1)}" cy="${sy(st.location.lat).toFixed(
      1
    )}" r="6" class="me" />`;
  }
  svg += "</svg>";
  box.innerHTML = svg;
}

// ---------- 对话 ----------

function addMsg(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  $("#messages").appendChild(div);
  $("#messages").scrollTop = $("#messages").scrollHeight;
  return div;
}

function addNote(text) {
  const div = document.createElement("div");
  div.className = "note";
  div.textContent = text;
  $("#messages").appendChild(div);
  $("#messages").scrollTop = $("#messages").scrollHeight;
  return div;
}

async function sendChat(text) {
  if (!text.trim()) return;
  window.QixiUI?.conversation();
  addMsg("user", text);
  const bubble = addMsg("ai", "");
  let note = null;
  const epoch = uiGeneration;
  const controller = new AbortController();
  const request_id = crypto.randomUUID();
  chats.set(request_id, controller);
  $("#cancelChatBtn").disabled = false;
  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: SID, text, request_id, generation: Qixi.generation }),
      signal: controller.signal,
    });
    if (!resp.ok || !resp.body) {
      bubble.textContent = "服务出问题了，稍后再试。";
      return;
    }
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (epoch !== uiGeneration) return;
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        if (!chunk.startsWith("data:")) continue;
        let ev;
        try {
          ev = JSON.parse(chunk.slice(5).trim());
        } catch {
          continue;
        }
        if (ev.type === "done" && ev.status === "cancelled") bubble.textContent += "（已取消）";
        if (ev.type === "delta") bubble.textContent += ev.text;
        else if (ev.type === "tool_start") {
          note = addNote(`小栖去查一下（${TOOL_LABELS[ev.name] || ev.name}）…`);
        } else if (ev.type === "tool_end" && note) {
          note.textContent = `${ev.ok ? "查好了" : "查询未完成"}（${TOOL_LABELS[ev.name] || ev.name}）`;
          note = null;
        } else if (ev.type === "error") {
          bubble.textContent += (bubble.textContent ? "\n" : "") + ev.message;
          bubble.classList.add("err");
        }
      }
    }
    if (!bubble.textContent) bubble.textContent = "……";
  } catch (e) {
    if (epoch === uiGeneration) bubble.textContent = e.name === "AbortError" ? "已取消" : "网络断了，再试一次。";
  } finally {
    chats.delete(request_id);
    $("#cancelChatBtn").disabled = chats.size === 0;
    if (epoch === uiGeneration) refreshState().catch(() => {});
  }
}

// ---------- 到点自动播报（决策 #17） ----------

let playbackToken = 0;
function speak(text) {
  if (!state.voiceOn) return false;
  const info = state.speaking;
  stopVoice();
  state.speaking = info;
  const token = playbackToken;
  const src = info && info.audio_url;
  if (src) {
    const a = new Audio(src);
    a.play().catch(() => {
      if (token !== playbackToken || !state.voiceOn) return;
      speakBrowser(text);
      promptManualPlay(src);
    });
    state.speaking = { ...(state.speaking || {}), el: a };
    return true;
  }
  return speakBrowser(text);
}

function speakBrowser(text) {
  if (!window.speechSynthesis || !text) return false;
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "zh-CN";
  u.rate = 0.95;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(u);
  return true;
}

function stopVoice() {
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  const el = state.speaking && state.speaking.el;
  if (el && el.pause) {
    el.pause();
    el.currentTime = 0;
  }
  playbackToken++;
  if (state.speaking) delete state.speaking.el;
}

let manualPromptShown = false;
function promptManualPlay(src) {
  if (manualPromptShown) return;
  manualPromptShown = true;
  const n = addNote("浏览器挡了自动播放，点这里播一次：");
  const b = document.createElement("button");
  b.className = "chip-btn";
  b.textContent = "▶ 播放语音";
  b.onclick = () => { state.voiceOn = true; speak(state.speaking?.line || ""); };
  n.appendChild(b);
}

function typeInto(el, text, speed = 30) {
  el.textContent = "";
  const epoch = uiGeneration;
  return new Promise((res) => {
    let i = 0;
    const t = setInterval(() => {
      if (epoch !== uiGeneration) { clearInterval(t); return res(); }
      el.textContent = text.slice(0, ++i);
      if (i >= text.length) {
        clearInterval(t);
        res();
      }
    }, speed);
  });
}

async function showArrival(info, meters) {
  const card = $("#arrivedCard");
  card.style.display = "block";
  $("#arrivedName").textContent = "到点播报 · " + info.name;
  $("#arrivedPoi").textContent = meters != null ? `${meters} 米内` : "";
  state.speaking = info;
  speak(info.line || "");
  typeInto($("#arrivedText"), info.line || info.name, 26);
  addNote(`到点播报｜${info.name}：${info.line || ""}`);
}

async function onArrive(info, meters) {
  if (!info || seenArrivals.has(info.event_id)) return;
  seenArrivals.add(info.event_id);
  state.speaking = info;
  if (!state.voiceOn) {
    $("#arrivedCard").style.display = "block";
    $("#arrivedName").textContent = "到点 · " + info.name;
    $("#arrivedPoi").textContent = "安静模式：不播报";
    $("#arrivedText").textContent = info.name;
    return;
  }
  await showArrival(info, meters);
}

// ---------- 演示控制台 ----------

async function demoCall(path, payload, opts = {}) {
  const epoch = uiGeneration;
  if (!path.endsWith("reset") && window.QixiMap && QixiMap.mode !== "demo") { addNote("这是演示操作。请先明确切换到演示草稿；真实地图不会因跳点而自动隐藏。"); return {}; }
  const r = await api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, generation: Qixi.generation }),
  });
  if (epoch !== uiGeneration) return r;
  if (r.state) Qixi.generation = r.state.generation;
  if (r.error) {
    addNote("控制台：" + r.error);
    return r;
  }
  if (r.state) {
    renderMap(r.state);
    renderStateInfo(r.state);
    renderTripMini(r.state);
  }
  if (r.arrived) {
    const meters = Math.round((r.state.location.snapped || {}).distance_m || 0);
    await onArrive(r.arrived, meters);
  }
  return r;
}

// 剧本模式：一键走 golden path
const SCRIPT = [
  { hint: "行前：小栖给明天上午的半日安排", wait: 6, run: () => sendChat("明天上午到，想看红叶，也看千佛岩，怎么安排？") },
  { hint: "上山：从山门走到明镜湖", wait: 8, run: () => demoCall("/api/demo/goto", { session_id: SID, poi_id: "mingjinghu" }, { immediate: true }) },
  { hint: "继续走到栖霞寺", wait: 8, run: () => demoCall("/api/demo/goto", { session_id: SID, poi_id: "qixiasi" }, { immediate: true }) },
  { hint: "再上石阶，到千佛岩", wait: 8, run: () => demoCall("/api/demo/goto", { session_id: SID, poi_id: "qianfoyan" }, { immediate: true }) },
  { hint: "追问：讲讲最大那尊", wait: 7, run: () => sendChat("讲讲最大那尊") },
  { hint: "累了：结合天气和红叶重规划", wait: 9, run: () => sendChat("我有点累了，想看红叶，今天天气怎么样，怎么走最快？") },
  { hint: "记住此刻", wait: 5, run: () => sendChat("帮我记住这里，风从石缝里过，很凉") },
];

async function runScript() {
  if (state.scriptRunning) return;
  state.scriptRunning = true;
  const epoch = uiGeneration;
  const btn = $("#scriptBtn");
  btn.textContent = "剧本进行中…";
  const hint = $("#scriptHint");
  hint.hidden = false;
  for (let i = 0; i < SCRIPT.length; i++) {
    if (epoch !== uiGeneration || !state.scriptRunning) return;
    const step = SCRIPT[i];
    hint.textContent = `第 ${i + 1}/${SCRIPT.length} 步 · ${step.hint}`;
    try {
      await step.run();
    } catch (e) {
      hint.textContent = `第 ${i + 1} 步出错了：${e.message}`;
      break;
    }
    if (epoch !== uiGeneration) return;
    await new Promise((r) => setTimeout(r, step.wait * 1000));
  }
  if (epoch !== uiGeneration) return;
  hint.textContent = "剧本走完 · 现在去写今天的日记 ";
  const b = document.createElement("button");
  b.className = "chip-btn";
  b.textContent = "打开发日记 →";
  b.onclick = () => (window.QixiUI ? QixiUI.show("poster") : location.href = "/poster.html");
  hint.appendChild(b);
  btn.textContent = "▶ 走一遍剧本（3 分钟）";
  state.scriptRunning = false;
}

// ---------- 天气与红叶 ----------

async function refreshConditions() {
  const c = await api("/api/conditions");
  const w = c.weather || {};
  const now = w.now || {};
  const today = w.today || {};
  const red = c.red_leaf || {};
  if (red.kind === "estimated") red.text = (red.text || "") + " · 算法估计";
  window.QixiUI?.conditions(c);
  $("#conditions").innerHTML = `
    <div class="cond-line"><b>${now.text || ""}</b> ${now.temp_c ?? "-"}°C
      <span class="muted">${now.wind || ""}</span></div>
    <div class="cond-line">今日 ${today.min ?? "-"}~${today.max ?? "-"}°C ·
      雨概率 ${today.rain_prob ?? "-"}% · 落日 ${today.sunset ?? "-"}</div>
    <div class="cond-line red"><b>红叶指数 ${red.score ?? "-"}</b>（${red.text || ""}）</div>
    <ul class="advice">${(c.advice || []).map((a) => `<li>${a}</li>`).join("")}</ul>
    <div class="muted src">来源：${
      c.source === "open-meteo" ? "Open-Meteo" : "本地记录"
    } · 天气数据 © Open-Meteo</div>`;
}

// ---------- 事件 ----------

function bindEvents() {
  $("#cancelChatBtn").addEventListener("click", () => {
    for (const [request_id, controller] of chats) {
      controller.abort();
      api("/api/chat/cancel",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({session_id:SID,request_id})}).catch(e=>addNote(e.message));
    }
  });
  $("#chatForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("#chatInput");
    const text = input.value;
    input.value = "";
    sendChat(text);
  });

  document.querySelectorAll("[data-q]").forEach((b) => {
    b.addEventListener("click", () => sendChat(b.dataset.q));
  });

  document.querySelectorAll("[data-act='advance']").forEach((btn) => {
    btn.addEventListener("click", () =>
      demoCall("/api/demo/advance", {
        session_id: SID,
        meters: Number(btn.dataset.val),
      }).catch(e=>addNote(e.message))
    );
  });

  $("#gotoBtn").addEventListener("click", () =>
    demoCall("/api/demo/goto", { session_id: SID, poi_id: $("#poiSelect").value }).catch(e=>addNote(e.message))
  );

  $("#resetBtn").addEventListener("click", async () => {
    uiGeneration++;
    state.scriptRunning = false;
    for (const [request_id, controller] of chats) { controller.abort(); api("/api/chat/cancel", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({session_id:SID,request_id})}).catch(() => {}); }
    $("#scriptBtn").textContent = "▶ 走一遍剧本（3 分钟）";
    $("#scriptHint").hidden = true;
    stopVoice();
    state.speaking = null;
    let r;
    try { r = await demoCall("/api/demo/reset", { session_id: SID }); }
    catch(e) { addNote("新行程创建失败："+e.message); return; }
    localStorage.setItem("qixi_epoch", crypto.randomUUID());
    window.QixiUI?.resetEpoch();
    seenArrivals.clear();
    state.visits = {};
    state.voiceOn = true;
    $("#arrivedCard").style.display = "none";
    await QixiMap.reset();
    await refreshState();
    addNote(QixiMap.mode === "demo" ? "已重置演示到山门。" : "已开始新行程，请重新选择起点或开启定位。");
    return r;
  });

  $("#scriptBtn").addEventListener("click", runScript);

  $("#playAgainBtn").addEventListener("click", () => {
    state.voiceOn = true;
    if (state.speaking && state.speaking.line) {
      speak(state.speaking.line);
    }
  });
  $("#stopVoiceBtn").addEventListener("click", () => {
    state.voiceOn = false;
    stopVoice();
    addNote("好，安静走。");
  });
  $("#askMoreBtn").addEventListener("click", () => {
    const name = (state.speaking && state.speaking.name) || "这里";
    sendChat(`讲讲${name}`);
  });
  $("#toPosterBtn").addEventListener("click", () => (window.QixiUI ? QixiUI.show("poster") : location.href = "/poster.html"));

  $("#keyBtn").addEventListener("click", () => {
    $("#keyModal").style.display = "flex";
  });
  $("#keyClose").addEventListener("click", () => {
    $("#keyModal").style.display = "none";
  });
  $("#keySave").addEventListener("click", async () => {
    const key = $("#keyInput").value.trim();
    if (!key) return;
    $("#keyMsg").textContent = "保存中…";
    try {
    await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ deepseek_api_key: key }),
    });
    $("#keyMsg").textContent = "测试连接中…";
    const t = await api("/api/config/test", { method: "POST" });
    $("#keyMsg").textContent = t.ok ? "连接正常 ✓" : `连接失败：${t.message}`;
    $("#keyStatus").textContent = t.ok ? "模型已连通" : "Key 已保存，连接未通过";
    window.QixiUI?.keyStatus(true);
    } catch (e) { $("#keyMsg").textContent = e.message; }
  });
}

init().catch((e) => addNote("启动数据加载失败：" + e.message));
bindEvents();

window.QixiAppUI = {refresh:refreshState, tasks:()=>({chat:chats.size,voice:!!(state.voiceOn && ((state.speaking?.el && !state.speaking.el.paused) || window.speechSynthesis?.speaking))})};
