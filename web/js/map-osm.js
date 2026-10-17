/* Leaflet + OSM. WGS84 end to end; local graph routing; no map key or CDN. */
window.QixiMap = (() => {
  "use strict";
  const $=s=>document.querySelector(s);
  let deps,data,map,tiles,roadGroup,areaGroup,poiGroup,toiletGroup,publicGroup,endpointGroup;
  let mode="real",modeQueue=Promise.resolve(),routeLine,deviceMarker,accuracyCircle;
  let origin,destination,via=[],pick=null,lastState,routeKey="",action=Date.now()*1000,planning=0;
  let watch=null,token=null,locationEpoch=0,locationStarting=false,processing=false,queued=null,sequence=0,lastSample=0;
  let follow=false,facilityData=[],tileLoads=0,tileErrors=0;
  const session=()=>({session_id:Qixi.sid,generation:Qixi.generation});
  function message(text){$("#mapMessage").textContent=text;if(!$("#facilitiesModal").hidden)$("#facilitiesPreviewText").textContent=text;}
  function run(fn){return (...args)=>Promise.resolve().then(()=>fn(...args)).catch(e=>message(e.message||"操作未完成，请重试"));}
  async function request(url,body){
    const options={signal:AbortSignal.timeout(20000)};
    if(body!==undefined)Object.assign(options,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    const r=await fetch(url,options),out=await r.json();
    if(!r.ok){const e=new Error(typeof out.detail==="string"?out.detail:"输入或状态无效，请核对后重试");e.status=r.status;throw e;}
    return out;
  }
  const post=(url,body={})=>request(url,{...session(),...body});
  function button(text,fn,className="ghost") {const b=document.createElement("button");b.type="button";b.textContent=text;b.className=className;b.onclick=run(fn);return b;}
  function paragraph(text){const p=document.createElement("p");p.textContent=text;return p;}
  function inside(p){return data&&p[0]>=data.bounds[1]&&p[0]<=data.bounds[3]&&p[1]>=data.bounds[0]&&p[1]<=data.bounds[2];}
  function icon(text,className){const el=document.createElement("span");el.className=className;el.textContent=text;return L.divIcon({html:el,className:"qixi-marker",iconSize:[28,28],iconAnchor:[14,14]});}
  const roadNames={path:"山间小径",footway:"步道",steps:"台阶",pedestrian:"步行道路",service:"园内/服务道路"};
  function tileStatus(){
    if(mode!=="real")return;
    $("#mapStatus").textContent=tileLoads ? `Leaflet＋OSM · 本地路网可用 · 底图已加载${tileErrors?"（部分瓦片未完成）":""}` : "本地道路与地标已就绪；在线背景尚未加载，可继续本地算路";
  }
  function layerToggle(group,checked){if(!group)return;checked?group.addTo(map):map.removeLayer(group);}
  function showPlace(p){
    const box=$("#poiDetail");box.replaceChildren();const title=document.createElement("strong");title.textContent=p.name;box.append(title);
    box.append(paragraph(`${p.category==="toilet_candidate"?"公开厕所候选 · 未核实开放情况 · ":""}来源：${p.source||"OpenStreetMap"} · WGS84${p.position_kind==="polygon_representative"?" · 面状地物代表点，不等于入口":""}`));
    box.append(button("设为起点",()=>assign("origin",p)),button("设为终点",()=>assign("destination",p)),button("添加途经",()=>assign("via",p)));
    if(p.id&&/^(node|way|relation)\/\d+$/.test(p.id)){const link=document.createElement("a");link.href="https://www.openstreetmap.org/"+p.id;link.target="_blank";link.rel="noopener noreferrer";link.textContent="查看OSM来源";box.append(link);}
    map.panTo(p.coord);
  }
  function drawPois(list){
    poiGroup.clearLayers();
    list.filter(p=>p.category==="poi").forEach(p=>{
      const marker=L.marker(p.coord,{title:p.name,icon:icon("景","map-poi-symbol")});
      const label=document.createElement("span");label.textContent=p.name;
      marker.bindTooltip(label,{direction:"top"});marker.on("click",()=>showPlace(p));poiGroup.addLayer(marker);
    });
    layerToggle(poiGroup,$("#showPois").checked);
  }
  function drawResults(list){const box=$("#mapResults");box.replaceChildren();list.forEach(p=>box.append(button(p.name,()=>showPlace(p),"map-result")));}
  function drawFacilities(){
    toiletGroup.clearLayers();publicGroup.clearLayers();
    facilityData.filter(p=>p.coordinate_system==="WGS84").forEach(p=>{
      const place={...p,coord:[p.lat,p.lng],source:p.source,category:"user_toilet"};
      const marker=L.marker(place.coord,{title:p.name,icon:icon("厕","map-toilet-symbol")});marker.on("click",()=>{
        showPlace(place);$("#poiDetail").append(paragraph(`用户核实日期：${p.verified_at} · 开放：${p.opening_hours||"未知"} · 无障碍：${p.accessible===null?"未知":p.accessible?"是":"否"}`));
      });toiletGroup.addLayer(marker);
    });
    data.pois.filter(p=>p.category==="toilet_candidate").forEach((p,i)=>{
      const place={...p,name:`公开厕所候选 ${i+1}（未现场核实）`};const m=L.marker(p.coord,{title:place.name,icon:icon("?厕","map-toilet-candidate")});m.on("click",()=>showPlace(place));publicGroup.addLayer(m);
    });
    layerToggle(toiletGroup,$("#showToilets").checked);layerToggle(publicGroup,$("#showPublicToilets").checked);
    const valid=facilityData.filter(p=>p.coordinate_system==="WGS84").length;
    $("#facilityStatus").textContent=`用户WGS84厕所 ${valid} 个；OSM公开候选 ${data.pois.filter(p=>p.category==="toilet_candidate").length} 个（默认隐藏，未保证开放）。${facilityData.length>valid?"旧GCJ-02设施未叠加，需先核实转换。":""}`;
  }
  function drawReference(){
    const box=$("#photoReference");box.replaceChildren();
    (data.photo_reference?.items||[]).forEach(ref=>{
      const poi=data.pois.find(p=>p.id===ref.osm_id),row=document.createElement("div");row.className="reference-row";
      row.append(document.createTextNode(ref.photo_name+"："));
      if(poi)row.append(button("OSM同名（未现场核实）",()=>showPlace(poi),"map-result"));
      else row.append(document.createTextNode(ref.status==="name_difference"?"名称有差异：OSM为“读枫”，待核对":"当前数据未匹配，暂不补点"));
      box.append(row);
    });
  }
  async function initMap(){
    data=await request("/api/map/osm/data");if(!window.L)throw new Error("本地Leaflet资源缺失，请重新展开程序");
    map=L.map("realMap",{center:data.view_center,zoom:16,minZoom:13,maxZoom:19,maxBounds:[[data.bounds[1],data.bounds[0]],[data.bounds[3],data.bounds[2]]],maxBoundsViscosity:.7});
    L.control.scale({imperial:false}).addTo(map);
    map.attributionControl.addAttribution('<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a> · <a href="/api/map/osm/database">ODbL本地数据</a>');
    areaGroup=L.layerGroup().addTo(map);roadGroup=L.layerGroup().addTo(map);poiGroup=L.layerGroup().addTo(map);toiletGroup=L.layerGroup().addTo(map);publicGroup=L.layerGroup();endpointGroup=L.layerGroup().addTo(map);
    data.areas.forEach(a=>L.polygon(a.geometry,{color:a.kind==="water"?"#78aebd":"#7a9a6f",fillColor:a.kind==="water"?"#a6ced5":"#b7cca9",weight:1,fillOpacity:.18,interactive:false}).addTo(areaGroup));
    data.roads.forEach(r=>{
      const pedestrian=["path","footway","steps","pedestrian"].includes(r.highway);
      const line=L.polyline(r.geometry,{color:r.highway==="steps"?"#a96c3e":pedestrian?"#3b7457":"#7e8074",weight:pedestrian?2.5:1.5,opacity:.65,dashArray:r.highway==="steps"?"3 4":null});
      const title=document.createElement("span");title.textContent=(r.name||roadNames[r.highway]||"已知道路")+" · OSM";line.bindTooltip(title);roadGroup.addLayer(line);
    });
    // Retain browser caching. Never prefetch or create an offline tile archive.
    tiles=L.tileLayer(data.tile_url,{maxZoom:19,updateWhenIdle:true,keepBuffer:1});
    tiles.on("tileload",()=>{tileLoads++;tileStatus();});tiles.on("tileerror",()=>{tileErrors++;tileStatus();});tiles.addTo(map);
    map.on("dragstart",()=>{follow=false;});
    map.on("click",e=>{if(!pick||mode!=="real")return;const coord=[e.latlng.lat,e.latlng.lng];if(!inside(coord))return message("请选择本地路网范围内地点");const kind=pick;pick=null;assign(kind,{name:"地图选点（入口待核对）",coord});});
    drawPois(data.pois);drawResults(data.pois.filter(p=>p.category==="poi"));drawReference();
    try{facilityData=(await request("/api/map/facilities")).items;}catch(e){message(e.message);}drawFacilities();
    $("#mapEmpty").hidden=true;tileStatus();
    $("#mapDataInfo").replaceChildren(paragraph(`数据获取：${data.retrieved_at.slice(0,10)} · WGS84 · ${data.roads.length}段道路 / ${data.pois.filter(p=>p.category==="poi").length}个地标（含周边）`),paragraph("OSM数据是开放编辑数据；同名匹配不等于现场测绘核实。定位精度以系统返回值为准。"));
  }
  function refreshEndpoints(){
    if(!map)return;endpointGroup.clearLayers();
    [origin,...via,destination].filter(Boolean).forEach((p,i)=>L.marker(p.coord,{title:p.name,icon:icon(p===origin?"起":p===destination?"终":String(i),"map-endpoint-symbol")}).addTo(endpointGroup));
    $("#routeOrigin").textContent=origin?.name||"未选起点";$("#routeDestination").textContent=destination?.name||"未选终点";$("#routeVia").textContent=via.length?"途经："+via.map(p=>p.name).join(" → "):"未设置途经点";
  }
  function invalidateSelection(){
    const id=lastState?.route?.request_id;if(id)post("/api/map/route/cancel",{request_id:id}).catch(e=>message(e.message));
    if(lastState)lastState.route=null;if(routeLine)map.removeLayer(routeLine);routeLine=null;routeKey="";stopLocation();
  }
  function assign(kind,p){
    if(kind==="origin")origin=p;else if(kind==="destination")destination=p;else{if(via.length>=5)throw new Error("最多5个途经点");via.push(p);}
    action++;invalidateSelection();refreshEndpoints();message("已更新选择，请规划步行路线；不使用照片或草稿坐标补路。");
  }
  function renderRoute(route,fit=false){
    if(!map)return;const key=route?.provider==="osm"&&route.status==="ready"?route.request_id:"";
    if(key!==routeKey){
      if(routeLine)map.removeLayer(routeLine);routeLine=null;routeKey=key;
      if(key){routeLine=L.polyline(route.geometry,{color:"#ae3d2c",weight:6,opacity:.95}).addTo(map);fit=true;}
    }
    if(routeLine){$("#showRoute").checked?routeLine.addTo(map):map.removeLayer(routeLine);if(fit)map.fitBounds(routeLine.getBounds(),{padding:[45,45],maxZoom:17});}
    const box=$("#routeSummary");box.replaceChildren();
    if(!key){box.textContent=route?.error?.message||"本地步行算路已就绪，选择起终点即可使用，无需地图Key。";return;}
    const h=document.createElement("strong");h.textContent=`至 ${route.name} · ${(route.total_m/1000).toFixed(2)} 公里 · 估计 ${route.duration_min} 分钟`;box.append(h);
    box.append(paragraph("沿OSM已知道路计算 · 未核实现场开放/入口 · 估计时间随体力和台阶变化"));
    (route.access_notes||[]).forEach(n=>box.append(paragraph(n)));
    const details=document.createElement("details"),summary=document.createElement("summary");summary.textContent=`查看 ${route.steps.length} 段说明`;details.append(summary);
    const ol=document.createElement("ol");route.steps.forEach((s,i)=>{const li=document.createElement("li");li.textContent=s.instruction;if(i===route.current_step)li.className="current-step";ol.append(li);});details.append(ol);box.append(details);
  }
  async function plan(){
    if(!origin||!destination)throw new Error("请先选择起点和终点");if(mode!=="real")throw new Error("请切回OSM真实地图");
    await stopLocation();const version=++action,generation=Qixi.generation;
    const selection=[origin,...via,destination].map(p=>({...p,coord:[...p.coord]}));planning++;$("#startLocation").disabled=true;message("正在本地计算步行路线…");
    try{
      const route=await post("/api/map/osm/plan",{sequence:version,origin:selection[0].coord,destination:selection.at(-1).coord,via:selection.slice(1,-1).map(p=>p.coord),name:selection.at(-1).name,avoid_steps:$("#avoidSteps").checked});
      if(version!==action||generation!==Qixi.generation){await post("/api/map/route/cancel",{request_id:route.request_id}).catch(()=>{});return;}
      renderRoute(route,true);message("本地路线已生成并同步行程。定位合格后才做实时进度/偏离判断，请核对现场通行。");await deps.refresh();
    }finally{planning--;$("#startLocation").disabled=planning>0;}
  }
  async function stopLocation(){
    locationEpoch++;queued=null;follow=false;
    if(watch!==null)navigator.geolocation.clearWatch(watch);watch=null;
    if(deviceMarker)map?.removeLayer(deviceMarker);if(accuracyCircle)map?.removeLayer(accuracyCircle);deviceMarker=null;accuracyCircle=null;
    const old=token;token=null;if(old)await post("/api/map/stop",{token:old}).catch(()=>{});
    $("#locationStatus").textContent="定位未开启 · 手动起点只用于路线预览";
  }
  async function startLocation(){
    if(planning)throw new Error("正在规划，请稍后开始定位");if(locationStarting)return;locationStarting=true;
    try{
      if(!window.isSecureContext||!navigator.geolocation)throw new Error("当前浏览器不能定位，请用本机启动器或手动选择起点");
      if(!confirm("允许获取这台电脑的位置用于本机导航吗？不再调用高德转换。在线底图会向OSM请求当前视野瓦片；聊天时位置信息会发送至配置模型。电脑不一定有GPS，精度以实际结果为准。"))return;
      await stopLocation();const epoch=++locationEpoch,generation=Qixi.generation;const result=await post("/api/map/location/start");
      if(epoch!==locationEpoch||generation!==Qixi.generation||document.hidden){await post("/api/map/stop",{token:result.token}).catch(()=>{});return;}
      token=result.token;sequence=0;lastSample=0;follow=true;$("#locationStatus").textContent="等待设备定位…请允许浏览器和Windows定位权限";
      watch=navigator.geolocation.watchPosition(p=>{if(epoch===locationEpoch){queued={p,epoch,generation,token};processLocation();}},e=>{
        if(epoch===locationEpoch){stopLocation();message(e.code===1?"定位权限被拒绝，可继续手动选起点":"定位不可用或超时，可继续手动选起点");}
      },{enableHighAccuracy:true,maximumAge:0,timeout:15000});
    }finally{locationStarting=false;}
  }
  async function processLocation(){
    if(processing)return;processing=true;
    try{while(queued){const item=queued;queued=null;const {p,epoch,generation}=item;if(epoch!==locationEpoch||document.hidden)continue;
      try{
        const coord=[p.coords.latitude,p.coords.longitude],sample_at=p.timestamp/1000;
        if(sample_at<=lastSample)continue;
        const result=await post("/api/map/location",{token:item.token,sequence:++sequence,lat:coord[0],lng:coord[1],raw_wgs84:coord,coordinate_system:"WGS84",accuracy_m:p.coords.accuracy,sample_at});
        if(epoch!==locationEpoch||generation!==Qixi.generation)continue;
        if(result.accepted){lastSample=sample_at;if(deviceMarker)map.removeLayer(deviceMarker);if(accuracyCircle)map.removeLayer(accuracyCircle);
          deviceMarker=L.circleMarker(coord,{radius:7,color:"#fff",weight:2,fillColor:"#246eaf",fillOpacity:1}).addTo(map);
          accuracyCircle=L.circle(coord,{radius:p.coords.accuracy,color:"#448ac0",fillOpacity:.12,weight:1}).addTo(map);if(follow&&inside(coord))map.panTo(coord);
        }
        $("#locationStatus").textContent=`设备定位 · 精度约 ${Math.round(p.coords.accuracy)} 米 · ${new Date(p.timestamp).toLocaleTimeString()} · ${result.eligible?"可做实时判断":result.reason||"等待稳定样本"}${inside(coord)?"":" · 位于路网范围外，请手动选起点"}`;
        await deps.refresh();
      }catch(e){if(epoch===locationEpoch){if(e.status===409)await stopLocation();message(e.message);}}
    }}finally{processing=false;}
  }
  function setMode(next){
    const change=async()=>{$("#mapMode").disabled=true;try{
      action++;await stopLocation();await post("/api/map/mode",{mode:next,provider:"osm"});mode=next;
      $("#realMapWrap").hidden=next!=="real";$("#mapBox").hidden=next!=="demo";$("#mapRealTools").hidden=next!=="real";
      if(next==="real"){map?.invalidateSize();tileStatus();}else $("#mapStatus").textContent="演示草稿 · 不是设备GPS或真实步行路线";
      await deps.refresh();
    }finally{$("#mapMode").value=mode;$("#mapMode").disabled=false;}};
    modeQueue=modeQueue.catch(()=>{}).then(change);return modeQueue;
  }
  function update(st){
    const previousKey=lastState?.route?.request_id;lastState=st;if(mode!=="real")return false;if(!deps||!map)return true;
    if(token&&previousKey&&st.route?.request_id!==previousKey&&!st.navigation?.active)stopLocation();
    renderRoute(st.route);
    const labels={no_route:"请先规划路线",stopped:"路线预览：定位未开启",waiting_location:"实时判断暂停：等待合格位置",on_route:"沿已知路线行进",off_route:"可能偏离路线，请核对",checking_deviation:"正在核对偏离",destination_nearby:"接近目的地，请核对实际入口"};
    $("#navigationStatus").textContent=labels[st.navigation?.status]||"";
    if(st.navigation?.eligible&&st.route?.provider==="osm")$("#navigationStatus").textContent+=` · 路线剩余约 ${st.route.remaining_m} 米`;
    if(token&&Date.now()/1000-lastSample>15)$("#locationStatus").textContent="定位已陈旧或尚未取得，实时判断暂停；请检查本机定位";
    return true;
  }
  async function reset(){
    action++;await stopLocation();origin=null;destination=null;via=[];pick=null;routeKey="";
    if(routeLine)map.removeLayer(routeLine);routeLine=null;endpointGroup?.clearLayers();refreshEndpoints();
    $("#poiDetail").replaceChildren();$("#mapMessage").textContent="";await post("/api/map/mode",{mode,provider:"osm"});
  }
  async function init(options){
    deps=options;
    $("#mapMode").onchange=run(e=>setMode(e.target.value));
    $("#mapRetry").onclick=run(async()=>{if(!map)await initMap();else{tileLoads=0;tileErrors=0;tiles.redraw();tileStatus();}});
    $("#mapConfigOpen").onclick=()=>{$("#mapConfigModal").hidden=false;};$("#mapConfigClose").onclick=()=>{$("#mapConfigModal").hidden=true;};
    $("#mapSearchForm").onsubmit=e=>{e.preventDefault();if(!data)return message("地图数据未就绪，请重试");const q=$("#mapSearchInput").value.trim();const result=data.pois.filter(p=>p.name.includes(q));drawResults(result);drawPois(result);message(result.length?`本地匹配 ${result.length} 个OSM地物，请核对名称和入口。`:"本地数据没有该名称；可在图上已知道路选点，不猜坐标补点。");};
    $("#majorPois").onclick=()=>{if(!data)return;drawResults(data.pois.filter(p=>p.category==="poi"));drawPois(data.pois);message("显示本地OSM地标（含周边），不代表景区完整名录或现场核实。");};
    $("#pickOrigin").onclick=()=>{pick="origin";message("请点击地图上的已知道路附近作为起点");};$("#pickDestination").onclick=()=>{pick="destination";message("请点击地图终点；离已知道路过远会拒绝算路");};
    $("#clearVia").onclick=()=>{via=[];action++;invalidateSelection();refreshEndpoints();};$("#avoidSteps").onchange=()=>{action++;invalidateSelection();};
    $("#planWalking").onclick=run(plan);$("#startLocation").onclick=run(startLocation);$("#stopLocation").onclick=run(stopLocation);
    $("#useDeviceOrigin").onclick=()=>{const loc=lastState?.location;if(loc?.source!=="device"||!lastState.navigation?.eligible||!inside([loc.lat,loc.lng]))return message("需要景区范围内、新鲜且精度合格的设备位置，否则请手动选起点");assign("origin",{name:"本次设备位置",coord:[loc.lat,loc.lng]});};
    $("#fitRoute").onclick=()=>{if(routeLine)map.fitBounds(routeLine.getBounds(),{padding:[45,45],maxZoom:17});};$("#homeMap").onclick=()=>map?.setView(data.view_center,16);
    $("#showPois").onchange=()=>layerToggle(poiGroup,$("#showPois").checked);$("#showRoads").onchange=()=>layerToggle(roadGroup,$("#showRoads").checked);$("#showRoute").onchange=()=>renderRoute(lastState?.route);
    $("#showToilets").onchange=drawFacilities;$("#showPublicToilets").onchange=drawFacilities;
    $("#facilitiesOpen").onclick=()=>{$("#facilitiesModal").hidden=false;};$("#facilitiesClose").onclick=()=>{$("#facilitiesModal").hidden=true;};
    $("#facilitiesInput").oninput=()=>{$("#facilitiesSave").disabled=true;};
    $("#facilitiesPreview").onclick=run(async()=>{const body={items:JSON.parse($("#facilitiesInput").value)};if(!Array.isArray(body.items)||body.items.some(p=>p.coordinate_system!=="WGS84"))throw new Error("仅接受明确标注WGS84的厕所坐标，请先核实坐标系。");const out=await request("/api/map/facilities/preview",body);$("#facilitiesPreviewText").textContent=JSON.stringify(out.items,null,2);$("#facilitiesSave").dataset.body=JSON.stringify(body);$("#facilitiesSave").disabled=false;});
    $("#facilitiesSave").onclick=run(async()=>{const body=JSON.parse($("#facilitiesSave").dataset.body);if(!confirm(`确认用${body.items.length}个点位替换用户厕所数据？坐标必须是WGS84。`))return;await request("/api/map/facilities/import",body);facilityData=(await request("/api/map/facilities")).items;drawFacilities();$("#facilitiesModal").hidden=true;});
    document.addEventListener("visibilitychange",()=>{if(document.hidden)stopLocation();});
    window.addEventListener("pagehide",()=>{if(token)navigator.sendBeacon("/api/map/stop",new Blob([JSON.stringify({...session(),token})],{type:"application/json"}));});
    await post("/api/map/mode",{mode:"real",provider:"osm"});await initMap();
  }
  return {init,update,setMode,reset,stop:stopLocation,get mode(){return mode;}};
})();
