/* Real map: official GCJ-02 only; browser WGS84 converted exactly once. */
window.QixiMap = (() => {
  "use strict";
  const $ = s => document.querySelector(s);
  const xy = p => [Number(p.getLat ? p.getLat() : p.lat), Number(p.getLng ? p.getLng() : p.lng)];
  const lnglat = p => [p[1], p[0]];
  const within = p => p[0] >= 32.12 && p[0] <= 32.20 && p[1] >= 118.91 && p[1] <= 119.01;
  const centre = [118.963, 32.156];
  let deps, mode = "real", map, A, config, origin, destination, via = [], places = [], facilities = [];
  let routeLine, pointLayers = [], toiletLayers = [], userMarker, accuracyCircle, endpoints = [];
  let selected, pick = null, loading = false, loadingSDK, action = Date.now()*1000, searchAction = 0;
  let watch = null, token = null, locateEpoch = 0, sequence = 0, processing = false, queued = null;
  let routeKey = "", intentSeen = "", lastState, follow = false, lastSample = 0, working = false, planningCount = 0, locationStarting = false;
  let modeQueue = Promise.resolve();

  function status(text) { $("#mapStatus").textContent = text; }
  function message(text) {
    $("#mapMessage").textContent = text;
    if (!$("#mapConfigModal").hidden) $("#mapConfigMessage").textContent=text;
    if (!$("#facilitiesModal").hidden) $("#facilitiesPreviewText").textContent=text;
  }
  function run(fn) { return (...args) => Promise.resolve().then(() => fn(...args)).catch(e => message(e.message || "操作未完成，请重试")); }
  async function request(path, body, signal) {
    const bounded = signal || AbortSignal.timeout(20000);
    const response = await fetch(path, body === undefined ? {signal:bounded} : {method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify(body), signal:bounded});
    const out = await response.json();
    if (!response.ok) {const error=new Error(typeof out.detail === "string" ? out.detail : "输入或状态无效，请刷新重试");error.status=response.status;throw error;}
    return out;
  }
  const session = () => ({session_id: Qixi.sid, generation: Qixi.generation});
  const post = (path, body = {}) => request(path, {...session(), ...body});
  function button(text, fn, className = "ghost") {
    const b = document.createElement("button"); b.type = "button"; b.textContent = text; b.className = className;
    b.onclick = run(fn); return b;
  }
  function distance(a, b) {
    const r = Math.PI / 180, dlat = (b[0]-a[0])*r, dlng = (b[1]-a[1])*r;
    return 12742000 * Math.asin(Math.sqrt(Math.sin(dlat/2)**2 + Math.cos(a[0]*r)*Math.cos(b[0]*r)*Math.sin(dlng/2)**2));
  }
  function sdkCall(fn, timeout = 20000) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("高德服务超时，请重试")), timeout);
      fn((state, result) => { clearTimeout(timer); state === "complete" ? resolve(result) : reject(new Error("高德未返回可用结果，请检查权限、网络或更换地点")); });
    });
  }
  async function load() {
    if (map) return map;
    if (loadingSDK) return loadingSDK;
    loadingSDK = (async () => {
      config = await request("/api/map/config");
      if (!config.configured) throw new Error("请先点“地图设置”，填写高德 Web端(JS API) Key 和安全密钥");
      status("正在连接高德地图…");
      window._AMapSecurityConfig = {serviceHost:location.origin + "/_AMapService"};
      if (!window.AMapLoader) await new Promise((resolve, reject) => {
        const script = document.createElement("script"); script.src = "https://webapi.amap.com/loader.js";
        const timer = setTimeout(() => { script.remove(); reject(new Error("地图脚本加载超时，请检查网络")); }, 15000);
        script.onload = () => {clearTimeout(timer); resolve();};
        script.onerror = () => {clearTimeout(timer); script.remove(); reject(new Error("地图脚本无法加载，请检查网络"));};
        document.head.appendChild(script);
      });
      A = await Promise.race([window.AMapLoader.load({key:config.js_key, version:"2.0", plugins:["AMap.ToolBar","AMap.Scale","AMap.PlaceSearch","AMap.Walking"]}),
        new Promise((_,reject) => setTimeout(() => reject(new Error("地图初始化超时，请重试或重新打开页面")),20000))]);
      map = new A.Map("realMap", {viewMode:"2D", zoom:15, center:centre, resizeEnable:true});
      map.addControl(new A.ToolBar()); map.addControl(new A.Scale());
      map.on("click", e => {
        if (!pick || mode !== "real") return;
        const coord = xy(e.lnglat); if (!within(coord)) return message("请选择栖霞山工作范围内的地点");
        assign(pick, {name:"地图选点（入口待现场核对）", coord}); pick = null;
      });
      map.on("dragstart", () => { follow = false; });
      if(mode === "real") status("高德真实地图 · 景区道路开放情况需现场核对");
      $("#mapEmpty").hidden = true;
      await loadFacilities();
      return map;
    })();
    try { return await loadingSDK; }
    catch(e) { status(e.message); throw e; }
    finally { loadingSDK = null; }
  }
  function remove(layer) { if (layer && map) map.remove(layer); }
  function refreshEndpoints() {
    endpoints.forEach(remove); endpoints = [];
    if (!map) return;
    [origin, ...via, destination].filter(Boolean).forEach((p, i) => {
      const label = p === origin ? "起" : p === destination ? "终" : String(i);
      const marker = new A.Marker({position:lnglat(p.coord), label:{content:label, direction:"top"}});
      map.add(marker); endpoints.push(marker);
    });
  }
  function assign(kind, place) {
    if (kind === "origin") origin = place; else if (kind === "destination") destination = place;
    else { if (via.length >= 5) throw new Error("最多5个途经点"); via.push(place); }
    action++; // a changed endpoint also invalidates any in-flight plan
    invalidateSelection();
    $("#routeOrigin").textContent = origin?.name || "未选起点";
    $("#routeDestination").textContent = destination?.name || "未选终点";
    $("#routeVia").textContent = via.length ? "途经：" + via.map(p => p.name).join(" → ") : "未设置途经点";
    refreshEndpoints(); message("起终点已更新，请点“规划步行路线”；旧路线仅作上次结果参考。");
  }
  function invalidateSelection() {
    const request_id=lastState?.route?.request_id;
    if(request_id) post("/api/map/route/cancel",{request_id}).catch(e=>message(e.message));
    if(lastState)lastState.route=null;
    remove(routeLine);routeLine=null;routeKey="";
    stopLocation().catch(e=>message(e.message));
  }
  function drawPlaces() {
    pointLayers.forEach(remove); pointLayers = [];
    if (!map || !$("#showPois").checked) return;
    places.forEach(p => {
      const symbol=document.createElement("span");symbol.className="map-poi-symbol";symbol.textContent="景";
      const m = new A.Marker({position:lnglat(p.coord), title:p.name,content:symbol});
      m.on("click", () => showPlace(p)); map.add(m); pointLayers.push(m);
    });
  }
  function showPlace(place) {
    selected = place;
    const box = $("#poiDetail"); box.replaceChildren();
    const title = document.createElement("strong"); title.textContent = place.name; box.append(title);
    const info = document.createElement("p"); info.textContent = `${place.address || "入口位置需现场核对"} · 来源：高德 POI · GCJ-02`;
    box.append(info, button("设为起点", () => assign("origin", place)), button("设为终点", () => assign("destination", place)), button("添加途经", () => assign("via", place)));
    if (map) map.panTo(lnglat(place.coord));
  }
  async function find(keyword) {
    await load();
    const search = new A.PlaceSearch({city:"南京", citylimit:true, pageSize:20, pageIndex:1, extensions:"base"});
    const result = await sdkCall(cb => search.searchInBounds(keyword, new A.Bounds([118.91,32.12],[119.01,32.20]), cb));
    return (result.poiList?.pois || []).filter(p => p.location).map(p => ({id:p.id, name:String(p.name), address:String(p.address || ""), coord:xy(p.location)})).filter(p => within(p.coord));
  }
  async function search() {
    const query = $("#mapSearchInput").value.trim(); if (!query) return;
    const version = ++searchAction; message("正在查询高德景点…");
    const found = await find(query); if (version !== searchAction || mode !== "real") return;
    places = found; drawPlaces(); const list = $("#mapResults"); list.replaceChildren();
    found.forEach(p => list.append(button(`${p.name} · ${p.address}`, () => showPlace(p), "map-result")));
    message(found.length ? `高德返回 ${found.length} 个范围内候选，请核对名称和入口。` : "没有查到范围内结果；请换关键词，不使用草稿坐标补点。");
  }
  async function majorPlaces() {
    await load();
    const names=[...new Set(deps.data.pois.map(p=>p.name))].slice(0,20);
    if(!confirm(`向高德查询 ${names.length} 个主要景点候选吗？将使用账号查询额度，只显示名称唯一匹配的服务坐标，不使用旧草稿坐标。`))return;
    const version=++searchAction,generation=Qixi.generation;$("#majorPois").disabled=true;
    const matched=[],unresolved=[];
    try {
      for(const name of names) {
        if(version!==searchAction||generation!==Qixi.generation||mode!=="real")return;
        message(`正在核对主要景点：${name}`);
        try{const result=(await find(name)).filter(p=>p.name===name);if(result.length===1)matched.push(result[0]);else unresolved.push(name);}
        catch(e){unresolved.push(name);}
        await new Promise(r=>setTimeout(r,250));
      }
      if(version!==searchAction||generation!==Qixi.generation||mode!=="real")return;
      places=[...new Map(matched.map(p=>[p.id,p])).values()];drawPlaces();$("#mapResults").replaceChildren();
      places.forEach(p=>$("#mapResults").append(button(p.name,()=>showPlace(p),"map-result")));
      if(pointLayers.length)map.setFitView(pointLayers,false,[60,60,60,60]);
      message(`高德名称唯一匹配 ${places.length} 个；待核对：${unresolved.join("、")||"无"}。匹配不代表现场开放核实。`);
    } finally {$("#majorPois").disabled=false;}
  }
  async function plan() {
    if (working) action++; // latest request wins, server request_id is the second barrier
    await load(); if (!origin || !destination) throw new Error("请先搜索或地图点选起点和终点");
    await stopLocation();
    const version = ++action, generation = Qixi.generation;
    const selection = [origin, ...via, destination].map(p => ({...p, coord:[...p.coord]}));
    working = true; planningCount++; $("#startLocation").disabled=true; message("正在向高德请求完整步行路线…");
    let ticket;
    let geometry = [], steps = [], walked = 0, duration = 0;
    try {
      ticket=await post("/api/map/route/start", {sequence:version, origin:selection[0].coord, destination:selection.at(-1).coord, via:selection.slice(1,-1).map(p=>p.coord)});
      if(version!==action||generation!==Qixi.generation)return;
      for (let i=1;i<selection.length;i++) {
        const walking = new A.Walking({hideMarkers:true});
        const result = await sdkCall(cb => walking.search(lnglat(selection[i-1].coord), lnglat(selection[i].coord), cb));
        if (version !== action || generation !== Qixi.generation || mode !== "real") return;
        const route = result.routes?.[0]; if (!route?.steps?.length) throw new Error("高德未覆盖该步行路段，不以直线补齐");
        duration += Number(route.time || 0);
        for (const step of route.steps) {
          const path = (step.path || []).map(xy); if (path.length < 2) throw new Error("服务路线缺少几何，无法显示");
          if (geometry.length && distance(geometry.at(-1), path[0]) > 50) throw new Error("服务分段存在断点，请核对园内道路覆盖");
          if (geometry.length && distance(geometry.at(-1),path[0]) > 0.1) { walked += distance(geometry.at(-1),path[0]); geometry.push(path[0]); }
          for (let j=geometry.length ? 1 : 0;j<path.length;j++) { if (geometry.length) walked+=distance(geometry.at(-1),path[j]); geometry.push(path[j]); }
          steps.push({instruction:String(step.instruction || "沿高德推荐步道行进").slice(0,300), at_m:walked, poi_id:null});
        }
      }
      const matches = selection.filter(p => p.id).map(p => {
        const internal = deps.data.pois.find(x => x.name === p.name);
        return internal ? {poi_id:internal.poi_id, amap_id:p.id, name:p.name, coord:p.coord} : null;
      }).filter(Boolean);
      if (version !== action || generation !== Qixi.generation) return;
      const route = await post("/api/map/route/commit", {request_id:ticket.request_id, geometry, steps, matches,
        duration_min:Math.round(duration/6)/10, name:selection.at(-1).name});
      if (version !== action || generation !== Qixi.generation) return;
      renderRoute(route, true); message("路线已同步到当前行程。请核对现场通行情况；开始定位后才进行实时判断。");
    } catch(e) {
      if (version === action && generation === Qixi.generation) {
        if(ticket) await post("/api/map/route/commit", {request_id:ticket.request_id, error:true}).catch(()=>post("/api/map/route/cancel",{request_id:ticket.request_id}).catch(()=>{}));
        remove(routeLine); routeLine=null; routeKey=""; throw e;
      }
    } finally {
      if(ticket && (version!==action || generation!==Qixi.generation)) await post("/api/map/route/cancel",{request_id:ticket.request_id}).catch(()=>{});
      planningCount--; working=planningCount>0; $("#startLocation").disabled=working;
    }
  }
  function renderRoute(route, fit = false) {
    if (!map) return;
    const key = route?.status === "ready" && route.provider === "amap" ? route.request_id : "";
    if (key !== routeKey) {
      remove(routeLine); routeLine=null; routeKey=key;
      if (key) { routeLine=new A.Polyline({path:route.geometry.map(lnglat), strokeColor:"#a63a2b", strokeWeight:6, outlineColor:"#fff", isOutline:true, showDir:true}); map.add(routeLine); }
    }
    if (routeLine) $("#showRoute").checked ? routeLine.show() : routeLine.hide();
    if (fit && routeLine) map.setFitView([routeLine], false, [60,60,60,60]);
    const box=$("#routeSummary"); box.replaceChildren();
    if (!key) {box.textContent=route?.status === "pending" ? "正在规划，请稍候…" : route?.error?.message || "选择起终点后规划；路线以高德返回的实际步行路径为准。"; return;}
    const h=document.createElement("strong"); h.textContent=`至 ${route.name} · ${(route.total_m/1000).toFixed(2)} 公里 · 约 ${route.duration_min} 分钟`;
    box.append(h);
    const note=document.createElement("p"); note.textContent="高德推荐步行路线 · 未经现场通行核实 · 不保证最短、无台阶或主题优化";box.append(note);
    const details=document.createElement("details"), summary=document.createElement("summary");summary.textContent=`查看 ${route.steps.length} 段说明`;details.append(summary);
    const ol=document.createElement("ol");route.steps.forEach(s=>{const li=document.createElement("li");li.textContent=s.instruction;ol.append(li);});details.append(ol);box.append(details);
  }
  async function stopLocation() {
    locateEpoch++; follow=false; queued=null;
    if (watch !== null) navigator.geolocation.clearWatch(watch); watch=null;
    const old=token; token=null;
    remove(userMarker);remove(accuracyCircle);userMarker=null;accuracyCircle=null;
    if (old) await post("/api/map/stop",{token:old}).catch(()=>{});
    $("#locationStatus").textContent="定位未开启 · 手动起点仅用于路线预览";
  }
  async function startLocation() {
    if(working)throw new Error("正在规划，请完成后再开始定位");
    if(locationStarting)return;locationStarting=true;
    try {
    await load();
    if(working)throw new Error("正在规划，请完成后再开始定位");
    if (!window.isSecureContext || !navigator.geolocation) throw new Error("当前浏览器不能定位，请通过本机启动器打开，或手动选择起点");
    if (!confirm("允许浏览器获取这台电脑的位置吗？原始坐标将发送至高德进行坐标转换，用于地图显示与步行导航；聊天时当前位置信息也会发往所配置的模型用于问答。电脑定位可能不够精确。")) return;
    await stopLocation(); const epoch=++locateEpoch;
    const generation=Qixi.generation, result=await post("/api/map/location/start");
    if (epoch!==locateEpoch || generation!==Qixi.generation || document.hidden) {
      await post("/api/map/stop",{token:result.token}).catch(()=>{});return;
    }
    token=result.token; sequence=0; follow=true;
    $("#locationStatus").textContent="等待真实位置…请允许浏览器和 Windows 定位权限";
    watch=navigator.geolocation.watchPosition(p=>{
      if(epoch!==locateEpoch)return;queued={p,epoch,generation,token};processLocation();
    }, e=>{if(epoch===locateEpoch){message(e.code===1 ? "定位权限被拒绝，可继续手动选起点" : "本机定位不可用或超时，可继续手动选起点");stopLocation();}},
    {enableHighAccuracy:true, maximumAge:0, timeout:15000});
    } finally {locationStarting=false;}
  }
  async function processLocation() {
    if(processing)return;processing=true;
    try { while(queued) {
      const item=queued;queued=null;const {p,epoch,generation}=item;
      if(epoch!==locateEpoch || document.hidden)continue;
      try {
        const raw=[p.coords.latitude,p.coords.longitude], sample_at=p.timestamp/1000;
        if(!Number.isFinite(p.coords.accuracy)||p.coords.accuracy<=0)throw new Error("浏览器未提供可靠精度");
        const converted=await sdkCall(cb=>A.convertFrom(lnglat(raw),"gps",cb));
        if(epoch!==locateEpoch || generation!==Qixi.generation)continue;
        if(!converted.locations?.length)throw new Error("高德坐标转换未完成，不能把原始坐标直接叠加");
        const coord=xy(converted.locations[0]);
        const result=await post("/api/map/location",{token:item.token,sequence:++sequence,lat:coord[0],lng:coord[1],raw_wgs84:raw,
          coordinate_system:"GCJ-02",accuracy_m:p.coords.accuracy,sample_at});
        if(epoch!==locateEpoch)continue;
        if(result.accepted){lastSample=sample_at;showDevice(coord,p.coords.accuracy);}
        $("#locationStatus").textContent=`设备定位 · 精度约 ${Math.round(p.coords.accuracy)} 米 · ${new Date(p.timestamp).toLocaleTimeString()} · ${result.eligible ? "可进行实时判断" : result.reason || "等待稳定定位"}`;
        await deps.refresh();
      } catch(e) { if(epoch===locateEpoch){if(e.status===409)await stopLocation();message(e.status===409 ? "导航状态已更新，定位已停止；请重新开始定位" : e.message);} }
    }} finally {processing=false;}
  }
  function showDevice(coord, accuracy) {
    remove(userMarker);remove(accuracyCircle);
    userMarker=new A.Marker({position:lnglat(coord),title:"设备位置（以精度圈为准）"});
    accuracyCircle=new A.Circle({center:lnglat(coord),radius:accuracy,strokeColor:"#2773a5",strokeOpacity:0.5,fillColor:"#83bbdc",fillOpacity:0.18});
    map.add([accuracyCircle,userMarker]);if(follow)map.panTo(lnglat(coord));
  }
  async function loadFacilities() {
    const result=await request("/api/map/facilities");facilities=result.items;
    $("#facilityStatus").textContent=facilities.length ? `已导入 ${facilities.length} 个用户提供厕所点位` : "厕所位置待补充；底图自带标注不等于本项目核实数据。";
    drawFacilities();
  }
  function drawFacilities() {
    toiletLayers.forEach(remove);toiletLayers=[];
    if(!map||!$("#showToilets").checked)return;
    facilities.forEach(p=>{
      const symbol=document.createElement("span");symbol.className="map-toilet-symbol";symbol.textContent="厕";
      const marker=new A.Marker({position:[p.lng,p.lat],title:p.name,content:symbol});
      marker.on("click",()=>{
        const box=$("#poiDetail");box.replaceChildren();const t=document.createElement("p");
        t.textContent=`厕所：${p.name} · 来源 ${p.source} · 核实 ${p.verified_at} · 开放 ${p.opening_hours||"未知"} · 无障碍 ${p.accessible===null ? "未知" : p.accessible ? "是" : "否"}`;
        const place={name:p.name,coord:[p.lat,p.lng]};box.append(t,button("设为终点",()=>assign("destination",place)));
      });map.add(marker);toiletLayers.push(marker);
    });
  }
  function setMode(next) {
    const change=async()=>{
    $("#mapMode").disabled=true;
    try {
    action++;searchAction++;await stopLocation();await post("/api/map/mode",{mode:next});mode=next;
    $("#realMapWrap").hidden=next!=="real";$("#mapBox").hidden=next!=="demo";$("#mapMode").value=next;
    $("#mapRealTools").hidden=next!=="real";
    if(next==="real") {await load();status("高德真实地图 · 景区道路开放情况需现场核对");} else status("演示草稿模式 · 位置与路线均不是真实 GPS 导航");
    await deps.refresh();
    } finally {$("#mapMode").value=mode;$("#mapMode").disabled=false;}
    };
    modeQueue=modeQueue.catch(()=>{}).then(change);return modeQueue;
  }
  async function intent(st) {
    const value=st.map_intent;if(!value||value.id===intentSeen||loading)return;intentSeen=value.id;loading=true;
    try {
      const targets=[...(value.via||[]),value.to];const result=[];
      for(const target of targets) {
        const internal=deps.data.pois.find(p=>p.poi_id===target||p.name===target);if(!internal)throw new Error("未识别路线目标，请在地图搜索并选择");
        const found=(await find(internal.name)).filter(p=>p.name===internal.name);
        if(found.length!==1)throw new Error(`“${internal.name}”存在缺失或歧义，请在地图搜索核对`);result.push(found[0]);
      }
      if(mode!=="real"||Qixi.generation!==st.generation)return;
      via=result.slice(0,-1);destination=result.at(-1);assign("destination",destination);
      message("已按对话查询高德目标；请核对起点和目标，点击“规划步行路线”。主题和天气未自动改变官方算路。");
    } catch(e){message(e.message);}finally{loading=false;}
  }
  function update(st) {
    lastState=st;if(mode!=="real")return false;
    if(!deps)return true;
    renderRoute(st.route);
    const names={on_route:"沿路线行进",off_route:"可能偏离路线，请核对",checking_deviation:"正在核对偏离",destination_nearby:"接近目的地，请核对入口",waiting_location:"实时判断暂停：等待合格位置",stopped:"路线预览：定位未开启",no_route:"尚无当前路线"};
    $("#navigationStatus").textContent=names[st.navigation?.status]||"";
    if(st.navigation?.eligible)$("#navigationStatus").textContent+=` · 路线剩余约 ${st.route?.remaining_m??"—"} 米`;
    if(token&&Date.now()/1000-lastSample>15)$("#locationStatus").textContent="定位已陈旧或尚未取得，实时判断暂停；请检查本机定位";
    intent(st);return true;
  }
  async function init(options) {
    deps=options;
    $("#mapMode").onchange=run(e=>setMode(e.target.value));
    $("#mapRetry").onclick=run(load);
    $("#mapConfigOpen").onclick=()=>{$("#mapConfigMessage").textContent="";$("#mapConfigModal").hidden=false;};
    $("#mapConfigClose").onclick=()=>{$("#mapConfigModal").hidden=true;};
    $("#mapConfigSave").onclick=run(async()=>{
      await request("/api/map/config",{js_key:$("#mapJsKey").value.trim(),security_code:$("#mapSecurity").value.trim()});
      $("#mapSecurity").value="";message("地图配置已保存，正在重新打开页面…");location.reload();
    });
    $("#mapSearchForm").onsubmit=e=>{e.preventDefault();run(search)();};
    $("#majorPois").onclick=run(majorPlaces);
    $("#pickOrigin").onclick=()=>{pick="origin";message("请点击地图上的起点");};
    $("#pickDestination").onclick=()=>{pick="destination";message("请点击地图上的终点");};
    $("#clearVia").onclick=()=>{via=[];action++;invalidateSelection();$("#routeVia").textContent="未设置途经点";refreshEndpoints();};
    $("#planWalking").onclick=run(plan);$("#startLocation").onclick=run(startLocation);$("#stopLocation").onclick=run(stopLocation);
    $("#useDeviceOrigin").onclick=()=>{
      const loc=lastState?.location;
      if(!loc||loc.source!=="device"||!lastState.navigation?.eligible)return message("先开启定位，取得新鲜且精度合格的位置");
      if(!within([loc.lat,loc.lng]))return message("当前设备不在景区工作范围，请手动选择起点");
      assign("origin",{name:"本次设备位置",coord:[loc.lat,loc.lng]});
    };
    $("#fitRoute").onclick=()=>{if(map&&routeLine)map.setFitView([routeLine],false,[60,60,60,60]);};
    $("#homeMap").onclick=()=>{if(map)map.setZoomAndCenter(15,centre);};
    $("#showPois").onchange=drawPlaces;$("#showToilets").onchange=drawFacilities;
    $("#showRoute").onchange=()=>renderRoute(lastState?.route);
    $("#facilitiesOpen").onclick=()=>{$("#facilitiesModal").hidden=false;};
    $("#facilitiesClose").onclick=()=>{$("#facilitiesModal").hidden=true;};
    $("#facilitiesPreview").onclick=run(async()=>{
      const body={items:JSON.parse($("#facilitiesInput").value)};
      const out=await request("/api/map/facilities/preview",body);
      $("#facilitiesPreviewText").textContent=JSON.stringify(out.items,null,2);
      $("#facilitiesSave").disabled=false;$("#facilitiesSave").dataset.body=JSON.stringify(body);
    });
    $("#facilitiesInput").oninput=()=>{$("#facilitiesSave").disabled=true;};
    $("#facilitiesSave").onclick=run(async()=>{
      const body=JSON.parse($("#facilitiesSave").dataset.body);if(!confirm(`确认用这 ${body.items.length} 个自有厕所点位替换当前设施数据？`))return;
      await request("/api/map/facilities/import",body);await loadFacilities();$("#facilitiesModal").hidden=true;
    });
    document.addEventListener("visibilitychange",()=>{if(document.hidden)stopLocation();});
    window.addEventListener("pagehide",()=>{if(token){navigator.sendBeacon("/api/map/stop",new Blob([JSON.stringify({...session(),token})],{type:"application/json"}));}});
    await post("/api/map/mode",{mode:"real"});
    try{await load();}catch(e){message(e.message);}
  }
  return {init,update,setMode,stop:stopLocation,get mode(){return mode;},async reset(){
    action++;intentSeen="";searchAction++;await stopLocation();origin=null;destination=null;via=[];pick=null;selected=null;
    endpoints.forEach(remove);endpoints=[];remove(routeLine);routeLine=null;routeKey="";places=[];drawPlaces();
    $("#routeOrigin").textContent="未选起点";$("#routeDestination").textContent="未选终点";$("#routeVia").textContent="未设置途经点";
    $("#mapResults").replaceChildren();$("#poiDetail").replaceChildren();$("#mapMessage").textContent="";
    await post("/api/map/mode",{mode});
  }};
})();
