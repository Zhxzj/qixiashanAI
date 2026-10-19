/* Leaflet + OSM. WGS84 end to end; local graph routing; no map key or CDN. */
window.QixiMap = (() => {
  "use strict";
  const $=s=>document.querySelector(s);
  let deps,data,map,tiles,roadGroup,areaGroup,poiGroup,toiletGroup,endpointGroup,annotationGroup,gateGroup,previewGroup,roadEndGroup;
  let mode="real",modeQueue=Promise.resolve(),routeLine,deviceMarker,accuracyCircle;
  let origin,destination,via=[],pick=null,lastState,routeKey="",action=Date.now()*1000,planning=0;
  let watch=null,token=null,locationEpoch=0,locationStarting=false,processing=false,queued=null,sequence=0,lastSample=0;
  let follow=false,facilityData=[],tileLoads=0,tileErrors=0;
  let selectedPlaceId=null,selectedRaw=null,selectionEpoch=0,detailAbort=null;
  let annotations={items:[],revision:0,warnings:[],writable:false},editPicking=false,editPreview=null,editEpoch=0,editSaving=false;
  const annotationMarkers=new Map();
  const placeByOsm=new Map(),contentCache=new Map(),markers=new Map();
  const reducedMotion=()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function highlight(){
    new Map([...markers,...annotationMarkers]).forEach((m,id)=>m.getElement()?.classList.toggle('selected-place',id===selectedRaw?.id));
    document.querySelectorAll('#mapResults button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.osmId===selectedRaw?.id)));
  }
  function syncFollow(){ $('#mapFollowStatus').hidden=watch===null||follow; }
  function closeDetails(){
    selectionEpoch++;detailAbort?.abort();selectedPlaceId=null;selectedRaw=null;
    $('#poiDetail').hidden=true;$('#poiDetail').replaceChildren();$('#mapWorkspace').classList.remove('has-place');highlight();
    if($('#placePhotoDialog').open)$('#placePhotoDialog').close();
  }
  function sourceLink(title,url){
    const a=document.createElement('a');a.textContent=title;
    if(typeof url==='string'&&/^https:\/\//.test(url)){a.href=url;a.target='_blank';a.rel='noopener noreferrer';}
    return a;
  }
  function photoCredit(photo){return `${photo.title} · ${photo.author} · ${photo.license} · 拍摄：${photo.captured_at} · 历史照片，不代表当前状态`;}
  function renderPlace(p,item){
    const box=$('#poiDetail');box.replaceChildren();box.scrollTop=0;
    box.append(button('关闭详情',closeDetails,'ghost close-place'));
    const title=document.createElement('h3');title.textContent=p.name;box.append(title);
    if(item){
      if(item.photo){
        const photo=item.photo,open=button('',()=>{const img=$('#placePhotoFull');img.src=photo.src;img.alt=photo.title;$('#placePhotoDialog').showModal();},'place-photo-button');
        open.setAttribute('aria-label','放大'+photo.title);const img=document.createElement('img');img.src=photo.src;img.alt=photo.title;img.decoding='async';
        img.onerror=()=>{open.replaceChildren(paragraph('照片加载失败，可继续阅读介绍'));open.disabled=true;};open.append(img);box.append(open);
      }else box.append(paragraph('照片待补充'));
      const summary=paragraph(item.summary),detail=paragraph(item.detail);summary.className='place-summary';detail.className='place-detail-text';box.append(summary,detail);
      if(item.status!=='reviewed')box.append(paragraph('介绍待核实；当前仅可确认本地OSM记录。'));
      const sources=document.createElement('details'),head=document.createElement('summary');head.textContent='资料来源与核实状态';sources.append(head);
      if(item.photo){const credit=paragraph(photoCredit(item.photo));credit.className='place-credit';credit.append(' ',sourceLink('照片来源',item.photo.source_url),' · ',sourceLink('许可',item.photo.license_url));sources.append(credit);}
      item.sources.forEach(x=>{const row=paragraph('');row.append(sourceLink(x.title,x.url));sources.append(row);});
      sources.append(paragraph('位置：OSM快照；现场位置、通行与开放状态未核实。'));box.append(sources);
    }else if(p.annotation){
      box.append(paragraph(p.position_status==='user_confirmed'?'用户校对位置，未现场测量':p.position_status==='osm_record'?'OSM门的位置记录；未证明是西门/南门游客入口':'用户截图标注，位置近似，未现场测量'));
      if(p.source_record?.url)box.append(sourceLink('查看门的OSM原始记录',p.source_record.url));
      box.append(paragraph('开放时间、无障碍与实际入口未知。路线只到已有道路附近，不保证精确到门。'));
      box.append(button('在地图校对此位置',()=>openEditor(p.id),'ghost'));
    }else box.append(paragraph(p.category?.includes('toilet')?'厕所位置/接入或开放状态尚未完整核实。':'该地标暂无经核实的景点图文。'));
    box.append(paragraph(`来源：${p.annotation?(p.position_status==='osm_record'?'OSM门的位置记录':'2026-10-19用户标注/校对'):p.source||'OpenStreetMap'} · WGS84${p.position_kind==='polygon_representative'?' · 面状代表点，不等于入口':''}`));
    const allow=p.annotation||!p.category?.includes('toilet')||p.access_verified===true;
    for(const [label,kind] of [['设为起点','origin'],['设为终点','destination'],['添加途经','via']]){
      const target=p.access_verified?{...p,name:p.name+'（核实接入点）',coord:p.entrance_coord}:p;const b=button(p.annotation?label+'（附近道路）':label,()=>assign(kind,target));b.disabled=!allow;b.title=allow?'':'厕所接入点未核实，暂不作为导航目标';box.append(b);
    }
    if(p.id&&/^(node|way|relation)\/\d+$/.test(p.id))box.append(sourceLink('查看OSM来源','https://www.openstreetmap.org/'+p.id));
    highlight();
  }
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
  function layerToggle(group,checked){if(!group)return;checked?group.addTo(map):map.removeLayer(group);}
  async function showPlace(p){
    const wasSelected=selectedRaw?.id===p.id,epoch=++selectionEpoch;detailAbort?.abort();
    selectedRaw=p;selectedPlaceId=placeByOsm.get(p.id)?.place_id||null;follow=false;syncFollow();
    $('#poiDetail').hidden=false;$('#mapWorkspace').classList.add('has-place');renderPlace(p,null);
    requestAnimationFrame(()=>{if(epoch!==selectionEpoch)return;map.invalidateSize({pan:false});map.setView(p.coord,Math.min(map.getMaxZoom(),Math.max(map.getZoom(),18)),{animate:!wasSelected&&!reducedMotion()});});
    if(!selectedPlaceId)return;
    const id=selectedPlaceId;
    try{
      let item=contentCache.get(id);
      if(!item){detailAbort=new AbortController();const r=await fetch('/api/map/place?place_id='+encodeURIComponent(id),{signal:AbortSignal.any([detailAbort.signal,AbortSignal.timeout(20000)])});if(!r.ok)throw new Error('详情暂时不可用，请重新选择');item=await r.json();contentCache.set(id,item);}
      if(epoch===selectionEpoch&&id===selectedPlaceId)renderPlace(p,item);
    }catch(e){if(e.name!=='AbortError'&&epoch===selectionEpoch)$('#poiDetail').append(paragraph(e.message));}
  }
  function drawPois(list){
    poiGroup.clearLayers();markers.clear();
    list.filter(p=>p.category==="poi").forEach(p=>{
      const marker=L.marker(p.coord,{title:p.name,icon:icon("景","map-poi-symbol")});
      const label=document.createElement("span");label.textContent=p.name;
      marker.bindTooltip(label,{direction:"top"});marker.on("click",()=>showPlace(p));poiGroup.addLayer(marker);markers.set(p.id,marker);
    });
    layerToggle(poiGroup,$("#showPois").checked);highlight();
  }
  function drawResults(list){const box=$('#mapResults');box.replaceChildren();list.forEach(p=>{const b=button(p.name,()=>showPlace(p),'map-result');b.dataset.osmId=p.id;box.append(b);});highlight();}
  function annotationPlaces(){return annotations.items.filter(p=>p.coord).map(p=>({...p,annotation:true,source_record:p.source,source:p.position_status==='osm_record'?'OpenStreetMap原始门记录':'用户截图标注/校对'}));}
  function drawAnnotations(){
    annotationGroup.clearLayers();gateGroup.clearLayers();annotationMarkers.clear();
    annotationPlaces().forEach(p=>{
      const m=L.marker(p.coord,{title:p.name+'（用户位置，未现场测量）',icon:icon(p.category==='gate'?'门':'厕',p.category==='gate'?'map-gate-symbol':'map-user-toilet-symbol')});
      const label=document.createElement('span');label.textContent=p.category==='toilet'?'厕所':p.name;m.bindTooltip(label,{permanent:true,direction:'right',offset:[12,0],className:'facility-label'});m.on('click',()=>showPlace(p));
      m.on('add',()=>{if(m.getElement())m.getElement().dataset.annotationId=p.id;});
      (p.category==='gate'?gateGroup:annotationGroup).addLayer(m);annotationMarkers.set(p.id,m);
    });
    layerToggle(annotationGroup,$('#showToilets').checked);layerToggle(gateGroup,$('#showGates').checked);highlight();
  }
  function overview(kind='all'){
    if(!map||!data)return;
    const facilities=annotationPlaces().filter(p=>kind!=='toilets'||p.category==='toilet');
    const positions=(kind==='toilets'?facilities:[...data.pois.filter(p=>placeByOsm.get(p.id)?.major),...facilities]).map(p=>p.coord);
    if(!positions.length){map.setView(data.view_center,15);return;}
    map.invalidateSize({pan:false});map.fitBounds(L.latLngBounds(positions),{paddingTopLeft:[48,48],paddingBottomRight:[125,48],maxZoom:16,animate:false,reset:true});
    
  }
  function mapError(text){$('#mapLoadError').hidden=!text;$('#mapLoadError').textContent=text;}
  async function loadExtras(){
    const result=await Promise.allSettled([request('/api/map/places'),request('/api/map/annotations'),request('/api/map/facilities')]);
    const errors=[];
    if(result[0].status==='fulfilled'){placeByOsm.clear();result[0].value.items.forEach(p=>placeByOsm.set(p.osm_id,p));}else errors.push('景点介绍暂不可用');
    if(result[1].status==='fulfilled')annotations=result[1].value;else errors.push('厕所和大门加载失败，点击重试底图重新加载');
    if(result[2].status==='fulfilled')facilityData=result[2].value.items;else errors.push('旧版已核实厕所数据不可用');
    drawPois(data.pois);drawFacilities();drawResults(data.pois.filter(p=>placeByOsm.get(p.id)?.major));
    mapError([...errors,...annotations.warnings].join('；'));
  }
  function editorMessage(text){$('#annotationPreview').textContent=text;}
  function editorBusy(busy){editSaving=busy;for(const id of ['annotationSelect','annotationPick','annotationReset','annotationCancel'])$('#'+id).disabled=busy;$('#annotationSave').disabled=busy||!editPreview;}
  function clearPreview(){editEpoch++;editPreview=null;editPicking=false;previewGroup?.clearLayers();$('#annotationSave').disabled=true;}
  function cancelEditor(){if(editSaving)return;clearPreview();$('#annotationEditor').hidden=true;}
  function editorSelection(){
    clearPreview();const p=annotations.items.find(x=>x.id===$('#annotationSelect').value);
    editorMessage(p?.coord?`${p.name}：${p.coord[0].toFixed(6)}, ${p.coord[1].toFixed(6)}；位置确认不代表实地测量。`:`${p?.name||'设施'}尚未定位，请在地图点选确认。`);
  }
  function openEditor(id){
    if(editSaving)return;
    pick=null;follow=false;syncFollow();$('#annotationEditor').hidden=false;
    const select=$('#annotationSelect');select.replaceChildren();
    [...annotations.items].sort((a,b)=>Number(a.category!=='gate')-Number(b.category!=='gate')).forEach(p=>{
      const option=document.createElement('option');option.value=p.id;option.textContent=p.name+(p.coord?'':'（待确认位置）');select.append(option);
    });
    if(id)select.value=id;editorSelection();
    $('#annotationPick').disabled=!annotations.writable;$('#annotationReset').disabled=!annotations.writable;
    if(!annotations.writable)editorMessage(annotations.warnings.join('；'));
  }
  async function previewPosition(coord){
    if(editSaving||!editPicking)return;
    const id=$('#annotationSelect').value,epoch=++editEpoch;editPreview=null;$('#annotationSave').disabled=true;
    previewGroup.clearLayers();L.marker(coord,{title:'未保存的预览位置',icon:icon('预览','map-preview-symbol')}).addTo(previewGroup);
    editorMessage('正在检查预览位置…');
    try{
      const result=await request('/api/map/annotations/preview',{id,coord,revision:annotations.revision});
      if(epoch!==editEpoch||!editPicking)return;
      editPreview=result;$('#annotationSave').disabled=false;editorMessage(`预览：${coord[0].toFixed(6)}, ${coord[1].toFixed(6)}。未保存；请核对后确认。`);
    }catch(e){if(epoch===editEpoch){
      if(e.status===409){const out=await request('/api/map/annotations');if(epoch!==editEpoch)return;applyAnnotations(out,id);clearPreview();editorMessage(e.message+'；已刷新，请重新点选。');}
      else editorMessage(e.message);
    }}
  }
  function applyAnnotations(out,id){
    const changed=new Set(out.items.filter(p=>annotations.items.find(x=>x.id===p.id)?.position_revision!==p.position_revision).map(p=>p.id));
    annotations=out;const current=out.items.find(p=>p.id===id);
    if(lastState?.route?.annotation_targets?.some(p=>changed.has(p.id)))invalidateSelection();
    const replacement=p=>{if(!p?.annotation||!changed.has(p.id))return p;const updated=out.items.find(x=>x.id===p.id);return updated?.coord?{...updated,annotation:true}:null;};
    origin=replacement(origin);destination=replacement(destination);via=via.map(replacement).filter(Boolean);refreshEndpoints();
    for(const option of $('#annotationSelect').options){const p=out.items.find(x=>x.id===option.value);if(p)option.textContent=p.name+(p.coord?'':'（待确认位置）');}
    drawFacilities();if(selectedRaw?.id===id){if(current?.coord)showPlace({...current,annotation:true});else closeDetails();}
  }
  function bindEditor(){
    $('#annotationsOpen').onclick=()=>openEditor();$('#annotationSelect').onchange=editorSelection;
    $('#annotationPick').onclick=()=>{clearPreview();editPicking=true;pick=null;editorMessage('现在请点击地图；可以再次点击调整预览，确认保存前不会更改设施。');};
    $('#annotationCancel').onclick=cancelEditor;
    $('#annotationSave').onclick=run(async()=>{
      if(!editPreview||editSaving)return;const preview=editPreview;editorBusy(true);
      try{const out=await request('/api/map/annotations/save',preview);applyAnnotations(out,preview.id);clearPreview();editorMessage('已保存至本机，重启后保留；入口及通行仍未核实。');message('设施位置已保存。若此位置用于当前路线，请重新规划。');}
      catch(e){editorMessage(e.message);if(e.status===409){applyAnnotations(await request('/api/map/annotations'),preview.id);clearPreview();}throw e;}
      finally{editorBusy(false);}
    });
    $('#annotationReset').onclick=run(async()=>{
      if(editSaving)return;const id=$('#annotationSelect').value,p=annotations.items.find(p=>p.id===id);
      if(!confirm(p.category==='gate'?'确认将此大门恢复为未定位？':'确认恢复此厕所的截图标注位置？'))return;
      editorBusy(true);try{applyAnnotations(await request('/api/map/annotations/reset',{id,revision:annotations.revision}),id);clearPreview();editorMessage('已恢复此点默认状态，其他设施保留。');}
      catch(e){if(e.status===409){applyAnnotations(await request('/api/map/annotations'),id);clearPreview();}throw e;}
      finally{editorBusy(false);}
    });
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#placePhotoDialog').open)cancelEditor();});
  }
  function drawFacilities(){
    toiletGroup.clearLayers();
    facilityData.filter(p=>p.coordinate_system==="WGS84").forEach(p=>{
      const place={...p,name:"公共厕所",coord:[p.lat,p.lng],source:p.source,category:"user_toilet",access_verified:p.access_verified===true};
      const marker=L.marker(place.coord,{title:place.name,icon:icon("厕","map-toilet-symbol")});marker.on("click",()=>{
        showPlace(place);$("#poiDetail").append(paragraph(`用户核实日期：${p.verified_at} · 开放：${p.opening_hours||"未知"} · 无障碍：${p.accessible===null?"未知":p.accessible?"是":"否"}`));
      });toiletGroup.addLayer(marker);
    });
    layerToggle(toiletGroup,$("#showToilets").checked);
    drawAnnotations();

  }
  async function initMap(){
    data=await request('/api/map/osm/data');
    $('#showToilets').checked=true;$('#showGates').checked=true;
    if(!window.L)throw new Error("本地Leaflet资源缺失，请重新展开程序");
    map=L.map("realMap",{zoomAnimation:!reducedMotion(),fadeAnimation:!reducedMotion(),center:data.view_center,zoom:16,minZoom:13,maxZoom:19,maxBounds:[[data.bounds[1],data.bounds[0]],[data.bounds[3],data.bounds[2]]],maxBoundsViscosity:.7});
    L.control.scale({imperial:false}).addTo(map);
    map.attributionControl.addAttribution('<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a> · <a href="/api/map/osm/database">ODbL本地数据</a>');
    areaGroup=L.layerGroup().addTo(map);roadGroup=L.layerGroup().addTo(map);poiGroup=L.layerGroup().addTo(map);toiletGroup=L.layerGroup().addTo(map);endpointGroup=L.layerGroup().addTo(map);annotationGroup=L.layerGroup().addTo(map);gateGroup=L.layerGroup().addTo(map);previewGroup=L.layerGroup().addTo(map);roadEndGroup=L.layerGroup().addTo(map);
    data.areas.forEach(a=>L.polygon(a.geometry,{color:a.kind==="water"?"#78aebd":"#7a9a6f",fillColor:a.kind==="water"?"#a6ced5":"#b7cca9",weight:1,fillOpacity:.18,interactive:false}).addTo(areaGroup));
    data.roads.forEach(r=>{
      const pedestrian=["path","footway","steps","pedestrian"].includes(r.highway);
      const line=L.polyline(r.geometry,{color:r.highway==="steps"?"#a96c3e":pedestrian?"#3b7457":"#7e8074",weight:pedestrian?2.5:1.5,opacity:.65,dashArray:r.highway==="steps"?"3 4":null});
      const title=document.createElement("span");title.textContent=(r.name||roadNames[r.highway]||"已知道路")+" · OSM";line.bindTooltip(title);roadGroup.addLayer(line);
    });
    // Retain browser caching. Never prefetch or create an offline tile archive.
    overview();
    tiles=L.tileLayer(data.tile_url,{maxZoom:19,updateWhenIdle:true,keepBuffer:1});
    tiles.on("tileload",()=>{tileLoads++;});tiles.on("tileerror",()=>{tileErrors++;});tiles.addTo(map);
    map.on("dragstart",()=>{follow=false;syncFollow();});
    map.on("click",e=>{if(editPicking){previewPosition([e.latlng.lat,e.latlng.lng]).catch(e=>message(e.message));return;}if(!pick||mode!=="real")return;const coord=[e.latlng.lat,e.latlng.lng];if(!inside(coord))return message("请选择本地路网范围内地点");const kind=pick;pick=null;assign(kind,{name:"地图选点（入口待核对）",coord});});
    drawPois(data.pois);drawResults(data.pois.filter(p=>placeByOsm.get(p.id)?.major));
    await loadExtras();overview();
    $("#mapEmpty").hidden=true;if(annotations.warnings.length)message(annotations.warnings.join("；"));
    $("#mapDataInfo").replaceChildren(paragraph(`数据获取：${data.retrieved_at.slice(0,10)} · WGS84 · ${data.roads.length}段道路 / ${data.pois.filter(p=>p.category==="poi").length}个地标（含周边）`),paragraph("OSM数据是开放编辑数据；同名匹配不等于现场测绘核实。定位精度以系统返回值为准。"));
  }
  function refreshEndpoints(){
    if(!map)return;endpointGroup.clearLayers();
    [origin,...via,destination].filter(Boolean).forEach((p,i)=>L.marker(p.coord,{title:p.name,icon:icon(p===origin?"起":p===destination?"终":String(i),"map-endpoint-symbol")}).addTo(endpointGroup));
    $("#routeOrigin").textContent=origin?.name||"未选起点";$("#routeDestination").textContent=destination?.name||"未选终点";$("#routeVia").textContent=via.length?"途经："+via.map(p=>p.name).join(" → "):"未设置途经点";
  }
  function invalidateSelection(){
    const id=lastState?.route?.request_id;if(id)post("/api/map/route/cancel",{request_id:id}).catch(e=>message(e.message));
    if(lastState)lastState.route=null;if(routeLine)map.removeLayer(routeLine);routeLine=null;routeKey="";roadEndGroup?.clearLayers();stopLocation();
  }
  function assign(kind,p){
    if(kind==="origin")origin=p;else if(kind==="destination")destination=p;else{if(via.length>=5)throw new Error("最多5个途经点");via.push(p);}
    action++;invalidateSelection();refreshEndpoints();message("已更新选择，请规划步行路线；不使用照片或草稿坐标补路。");
  }
  function renderRoute(route,fit=false){
    if(!map)return;const explicitFit=fit;const key=route?.provider==="osm"&&route.status==="ready"?route.request_id:"";
    if(key!==routeKey){
      roadEndGroup.clearLayers();
      if(routeLine)map.removeLayer(routeLine);routeLine=null;routeKey=key;
      if(key){(route.annotation_targets||[]).filter(p=>p.role==="destination").forEach(p=>L.marker(p.road_endpoint,{title:"路网终点：设施入口待确认",icon:icon("路终","map-road-end-symbol")}).addTo(roadEndGroup));routeLine=L.polyline(route.geometry,{color:"#ae3d2c",weight:6,opacity:.95}).addTo(map);fit=true;}
    }
    layerToggle(roadEndGroup,$("#showRoute").checked);
    if(routeLine){$("#showRoute").checked?routeLine.addTo(map):map.removeLayer(routeLine);if(fit&&(!selectedRaw||explicitFit))map.fitBounds(routeLine.getBounds(),{padding:[45,45],maxZoom:17});}
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
      const route=await post("/api/map/osm/plan",{sequence:version,origin:selection[0].coord,destination:selection.at(-1).coord,via:selection.slice(1,-1).map(p=>p.coord),name:selection.at(-1).name,avoid_steps:$("#avoidSteps").checked,annotation_targets:selection.flatMap((p,i)=>p.annotation?[{id:p.id,position_revision:p.position_revision,role:i===0?"origin":i===selection.length-1?"destination":"via:"+(i-1)}]:[])});
      if(version!==action||generation!==Qixi.generation){await post("/api/map/route/cancel",{request_id:route.request_id}).catch(()=>{});return;}
      renderRoute(route,true);message("本地路线已生成并同步行程。定位合格后才做实时进度/偏离判断，请核对现场通行。");await deps.refresh();
    }finally{planning--;$("#startLocation").disabled=planning>0;}
  }
  async function stopLocation(){
    locationEpoch++;queued=null;follow=false;
    if(watch!==null)navigator.geolocation.clearWatch(watch);watch=null;
    if(deviceMarker)map?.removeLayer(deviceMarker);if(accuracyCircle)map?.removeLayer(accuracyCircle);deviceMarker=null;accuracyCircle=null;
    syncFollow();const old=token;token=null;if(old)await post("/api/map/stop",{token:old}).catch(()=>{});
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
      },{enableHighAccuracy:true,maximumAge:0,timeout:15000});syncFollow();
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
      cancelEditor();closeDetails();action++;await stopLocation();await post("/api/map/mode",{mode:next,provider:"osm"});mode=next;
      $("#mapWorkspace").hidden=next!=="real";$("#realMapWrap").hidden=next!=="real";$("#mapBox").hidden=next!=="demo";$("#mapRealTools").hidden=next!=="real";
      if(next==="real"){map?.invalidateSize({pan:false,animate:false});requestAnimationFrame(()=>overview());}
      $("#mapModeNotice").hidden=next==="real";await deps.refresh();
    }finally{$("#mapMode").value=mode;$("#mapMode").disabled=false;}};
    modeQueue=modeQueue.catch(()=>{}).then(change);return modeQueue;
  }
  function update(st){
    const previousKey=lastState?.route?.request_id;lastState=st;if(mode!=="real")return false;if(!deps||!map)return true;
    if(token&&previousKey&&st.route?.request_id!==previousKey&&!st.navigation?.active)stopLocation();
    renderRoute(st.route);
    const labels={no_route:"请先规划路线",stopped:"路线预览：定位未开启",waiting_location:"实时判断暂停：等待合格位置",on_route:"沿已知路线行进",off_route:"可能偏离路线，请核对",checking_deviation:"正在核对偏离",destination_nearby:"接近目的地，请核对实际入口",road_endpoint_nearby:"接近本路线的路网终点，设施入口待确认"};
    $("#navigationStatus").textContent=labels[st.navigation?.status]||"";
    if(st.navigation?.eligible&&st.route?.provider==="osm")$("#navigationStatus").textContent+=` · 路线剩余约 ${st.route.remaining_m} 米`;
    if(token&&Date.now()/1000-lastSample>15)$("#locationStatus").textContent="定位已陈旧或尚未取得，实时判断暂停；请检查本机定位";
    return true;
  }
  async function reset(){
    cancelEditor();action++;await stopLocation();origin=null;destination=null;via=[];pick=null;routeKey="";
    if(routeLine)map.removeLayer(routeLine);routeLine=null;endpointGroup?.clearLayers();refreshEndpoints();
    closeDetails();$("#mapMessage").textContent="";await post("/api/map/mode",{mode,provider:"osm"});
  }
  async function init(options){
    deps=options;
    bindEditor();
    $('#returnRealMap').onclick=run(async()=>{await setMode('real');$('#showToilets').checked=true;$('#showGates').checked=true;drawAnnotations();overview();});
    $('#placePhotoClose').onclick=()=>$('#placePhotoDialog').close();
    $('#placePhotoDialog').addEventListener('close',()=>{$('#placePhotoFull').removeAttribute('src');});
    $('#resumeFollow').onclick=()=>{if(watch===null||!deviceMarker)return message('请先取得设备位置');const loc=lastState?.location;if(!loc||!inside([loc.lat,loc.lng]))return message('当前设备位置不在本地范围');follow=true;syncFollow();map.panTo(deviceMarker.getLatLng(),{animate:!reducedMotion()});};
    new ResizeObserver(entries=>{const box=$('#mapWorkspace');box.classList.toggle('stacked',entries[0].contentRect.width<720);if(map&&mode==="real"&&entries[0].contentRect.width>0)map.invalidateSize({pan:false,animate:false});}).observe($('#mapWorkspace'));

    $("#mapMode").onchange=run(e=>setMode(e.target.value));
    $("#mapRetry").onclick=run(async()=>{try{if(!map)await initMap();else{await loadExtras();overview();tileLoads=0;tileErrors=0;tiles.redraw();}}catch(e){mapError("地图加载失败："+e.message);throw e;}});
    $("#mapConfigOpen").onclick=()=>{$("#mapConfigModal").hidden=false;};$("#mapConfigClose").onclick=()=>{$("#mapConfigModal").hidden=true;};
    $("#mapSearchForm").onsubmit=e=>{e.preventDefault();if(!data)return message("地图数据未就绪，请重试");const q=$("#mapSearchInput").value.trim();const result=[...data.pois,...annotationPlaces()].filter(p=>p.name.includes(q));drawResults(result);drawPois(data.pois);message(result.length?`本地匹配 ${result.length} 个地标或设施，请核对名称和入口。`:"本地数据没有该名称；可在图上已知道路选点，不猜坐标补点。");};
    $("#majorPois").onclick=()=>{if(!data)return;drawResults(data.pois.filter(p=>placeByOsm.get(p.id)?.major));drawPois(data.pois);message("主要景点目录；图文待补项单独标明，不代表全园名录或现场核实。");};
    $("#pickOrigin").onclick=()=>{cancelEditor();pick="origin";message("请点击地图上的已知道路附近作为起点");};$("#pickDestination").onclick=()=>{cancelEditor();pick="destination";message("请点击地图终点；离已知道路过远会拒绝算路");};
    $("#clearVia").onclick=()=>{via=[];action++;invalidateSelection();refreshEndpoints();};$("#avoidSteps").onchange=()=>{action++;invalidateSelection();};
    $("#planWalking").onclick=run(plan);$("#startLocation").onclick=run(startLocation);$("#stopLocation").onclick=run(stopLocation);
    $("#useDeviceOrigin").onclick=()=>{const loc=lastState?.location;if(loc?.source!=="device"||!lastState.navigation?.eligible||!inside([loc.lat,loc.lng]))return message("需要景区范围内、新鲜且精度合格的设备位置，否则请手动选起点");assign("origin",{name:"本次设备位置",coord:[loc.lat,loc.lng]});};
    $("#fitRoute").onclick=()=>{if(routeLine)map.fitBounds(routeLine.getBounds(),{padding:[45,45],maxZoom:17});};$("#homeMap").onclick=()=>{if(map)overview();};
    $("#showPois").onchange=()=>layerToggle(poiGroup,$("#showPois").checked);$("#showRoads").onchange=()=>layerToggle(roadGroup,$("#showRoads").checked);$("#showRoute").onchange=()=>renderRoute(lastState?.route);
    $("#showGates").onchange=drawAnnotations;$("#showToilets").onchange=drawFacilities;
    $("#facilitiesOpen").onclick=()=>{$("#facilitiesModal").hidden=false;};$("#facilitiesClose").onclick=()=>{$("#facilitiesModal").hidden=true;};
    $("#facilitiesInput").oninput=()=>{$("#facilitiesSave").disabled=true;};
    $("#facilitiesPreview").onclick=run(async()=>{const body={items:JSON.parse($("#facilitiesInput").value)};if(!Array.isArray(body.items)||body.items.some(p=>p.coordinate_system!=="WGS84"))throw new Error("仅接受明确标注WGS84的厕所坐标，请先核实坐标系。");const out=await request("/api/map/facilities/preview",body);$("#facilitiesPreviewText").textContent=JSON.stringify(out.items,null,2);$("#facilitiesSave").dataset.body=JSON.stringify(body);$("#facilitiesSave").disabled=false;});
    $("#facilitiesSave").onclick=run(async()=>{const body=JSON.parse($("#facilitiesSave").dataset.body);if(!confirm(`确认用${body.items.length}个点位替换用户厕所数据？坐标必须是WGS84。`))return;await request("/api/map/facilities/import",body);facilityData=(await request("/api/map/facilities")).items;drawFacilities();$("#facilitiesModal").hidden=true;});
    document.addEventListener("visibilitychange",()=>{if(document.hidden)stopLocation();});
    window.addEventListener("pagehide",()=>{if(token)navigator.sendBeacon("/api/map/stop",new Blob([JSON.stringify({...session(),token})],{type:"application/json"}));});
    try{await post("/api/map/mode",{mode:"real",provider:"osm"});}catch(e){message("会话暂不可用，仍可查看地图："+e.message);}await initMap();
  }
  function inspect(){return {mode,initialized:!!map,showToilets:$('#showToilets').checked,showGates:$('#showGates').checked,markers:[...annotationMarkers].map(([id,m])=>({id,coord:[m.getLatLng().lat,m.getLatLng().lng],onMap:map.hasLayer(m),inBounds:map.getBounds().contains(m.getLatLng())}))};}
  return {init,update,setMode,reset,stop:stopLocation,inspect,get mode(){return mode;}};
})();
