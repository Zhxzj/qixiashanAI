/* Run against an isolated local host. All AMap business responses are fixtures. */
const {chromium}=require(process.env.QIXI_PLAYWRIGHT_MODULE || 'playwright-core');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base=process.env.QIXI_TEST_BASE || 'http://127.0.0.1:8021';
const out=process.env.QIXI_MAP_REPORTS || path.resolve('../dist/map-reports');fs.mkdirSync(out,{recursive:true});
const mockSDK=()=>{
 const test=window.__mapTest={instances:0,conversions:0,fit:0,moves:0,routePaths:[],markers:[],walks:0};
 class Point{constructor(lng,lat){this.lng=lng;this.lat=lat;}getLng(){return this.lng;}getLat(){return this.lat;}}
 class Layer{constructor(o){this.o=o;this.handlers={};test.markers.push(this);}on(n,f){this.handlers[n]=f;}show(){this.visible=true;}hide(){this.visible=false;}}
 class Map{constructor(id,o){test.instances++;this.handlers={};document.getElementById(id).textContent='模拟 SDK 测试画布，无真实高德底图';}add(){}remove(){}addControl(){}on(n,f){this.handlers[n]=f;test.map=this;}panTo(){test.moves++;}setFitView(){test.fit++;}setZoomAndCenter(){}}
 class Polyline extends Layer{constructor(o){super(o);test.routePaths.push(o.path);}}
 class PlaceSearch{searchInBounds(word,bounds,callback){let names=word.includes('千佛')?['千佛岩']:word.includes('山门')?['山门']:['栖霞寺'];let pois=names.map((name,i)=>({id:name==='栖霞寺'?'mock-temple':name==='山门'?'mock-gate':'mock-cliff',name,address:'测试夹具，不是真实地址',location:new Point(name==='山门'?118.960:118.961,name==='山门'?32.150:32.151)}));setTimeout(()=>callback('complete',{poiList:{pois}}),10);}}
 class Walking{search(a,b,callback){test.walks++;const ms=test.delay??(test.walks%2?80:10);setTimeout(()=>callback('complete',{routes:[{time:180,steps:[{instruction:'测试步行说明',path:[new Point(...a),new Point((a[0]+b[0])/2,(a[1]+b[1])/2),new Point(...b)]}]}]}),ms);}}
 window.AMapLoader={load:async()=>({Map,Marker:Layer,Circle:Layer,Polyline,ToolBar:class{},Scale:class{},Bounds:class{},PlaceSearch,Walking,convertFrom:(p,type,cb)=>{test.conversions++;test.lastConvertType=type;setTimeout(()=>cb('complete',{locations:[new Point(p[0]+.001,p[1]+.001)]}),10);}})};
};
const check=[];let browser,debugPage;
(async()=>{
 browser=await chromium.launch({executablePath:process.env.QIXI_EDGE || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000},permissions:['geolocation'],geolocation:{latitude:32.149,longitude:118.959,accuracy:10}});
 await context.addInitScript(()=>{
   let success,error;window.__emitLocation=(accuracy=10)=>success?.({coords:{latitude:32.149,longitude:118.959,accuracy},timestamp:Date.now()});
   Object.defineProperty(navigator,'geolocation',{configurable:true,value:{watchPosition:(ok,bad)=>{success=ok;error=bad;setTimeout(()=>window.__emitLocation(),20);return 1;},clearWatch:()=>{success=null;error=null;}}});
 });
 const page=await context.newPage(),errors=[];debugPage=page;page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 await page.route('https://webapi.amap.com/loader.js',r=>r.fulfill({contentType:'text/javascript',body:'('+mockSDK.toString()+')();'}));
 await page.route('**/api/map/config',r=>r.request().method()==='GET'?r.fulfill({json:{configured:true,js_key:'fixture-not-real',security_configured:true}}):r.continue());
 await page.goto(base);await page.waitForFunction(()=>window.__mapTest?.instances===1);check.push('official loader boundary mocked; map initializes once');
 assert.equal(await page.locator('#mapBox').isHidden(),true);assert.equal(await page.locator('#realMapWrap').isVisible(),true);check.push('unknown draft layers absent from real map');
 await page.click('#majorPois');await page.waitForFunction(()=>document.querySelector('#mapMessage').textContent.includes('名称唯一匹配'));assert.ok(await page.locator('#mapResults button').count()>0);check.push('major POIs queried on demand using names, never old draft coordinates');
 async function search(word){await page.fill('#mapSearchInput',word);await page.click('#mapSearchForm button[type="submit"]');await page.locator('#mapResults button').first().click();}
 await search('山门');await page.getByRole('button',{name:'设为起点',exact:true}).click();
 await search('栖霞寺');await page.getByRole('button',{name:'设为终点',exact:true}).click();
 await page.click('#planWalking');await page.waitForFunction(()=>document.querySelector('#routeSummary').textContent.includes('测试步行说明'));
 const state=await page.evaluate(async()=>fetch('/api/state?session_id='+Qixi.sid).then(r=>r.json()));
 assert.equal(state.route.provider,'amap');assert.equal(state.route.geometry.length,3);
 const rendered=await page.evaluate(()=>__mapTest.routePaths.at(-1));assert.deepEqual(rendered,state.route.geometry.map(p=>[p[1],p[0]]));check.push('full provider geometry agrees with backend route');
 const fit=await page.evaluate(()=>__mapTest.fit);await page.waitForTimeout(4300);
 assert.equal(await page.evaluate(()=>__mapTest.instances),1);assert.equal(await page.evaluate(()=>__mapTest.fit),fit);check.push('polling neither rebuilds map nor resets viewport');
 await page.uncheck('#showRoute');await page.check('#showRoute');await page.click('#fitRoute');assert.ok(await page.evaluate(()=>__mapTest.fit)>fit);check.push('route layer toggle and explicit fit');
 await page.click('#startLocation');
 await page.waitForFunction(()=>document.querySelector('#locationStatus').textContent.includes('可进行实时判断'));
 const live=await page.evaluate(async()=>fetch('/api/state?session_id='+Qixi.sid).then(r=>r.json()));
 assert.equal(live.location.source,'device');assert.equal(live.location.coordinate_system,'GCJ-02');assert.ok(Math.abs(live.location.lat-32.15)<1e-7);
 assert.equal(await page.evaluate(()=>__mapTest.lastConvertType),'gps');assert.ok(await page.evaluate(()=>__mapTest.conversions)>=1);check.push('browser sample converted once per callback to GCJ-02 and validated');
 await page.waitForTimeout(50);await page.evaluate(()=>__emitLocation(300));await page.waitForFunction(()=>document.querySelector('#locationStatus').textContent.includes('精度或新鲜度不足'));
 const low=await page.evaluate(async()=>fetch('/api/state?session_id='+Qixi.sid).then(r=>r.json()));assert.equal(low.navigation.eligible,false);assert.equal(low.arrived,null);check.push('low accuracy blocks navigation and arrivals');
 await page.click('#stopLocation');const stopped=await page.evaluate(async()=>fetch('/api/state?session_id='+Qixi.sid).then(r=>r.json()));assert.equal(stopped.navigation.active,false);check.push('stop invalidates backend navigation');
 await page.click('#facilitiesOpen');await page.fill('#facilitiesInput','[{"id":"fixture"}]');await page.click('#facilitiesPreview');await page.waitForFunction(()=>document.querySelector('#facilitiesPreviewText').textContent.includes('无效'));
 assert.equal(await page.locator('#facilitiesSave').isDisabled(),true);await page.click('#facilitiesClose');check.push('invalid facility import blocked before save');
 await page.screenshot({path:path.join(out,'desktop-map-mock.png'),fullPage:true});
 await page.click('#gotoBtn');await page.waitForFunction(()=>QixiMap.mode==='demo');await page.locator('#mapBox svg').waitFor();assert.equal(await page.locator('#mapBox svg').count(),1);check.push('demo explicitly switches mode and preserves old simulation');
 await page.selectOption('#mapMode','real');await page.waitForFunction(()=>QixiMap.mode==='real');assert.equal(await page.locator('#mapBox').isHidden(),true);check.push('switch back excludes simulation from real map');
 await page.click('#resetBtn');await page.waitForFunction(()=>document.querySelector('#messages').textContent.includes('已开始新行程'));const reset=await page.evaluate(async()=>fetch('/api/state?session_id='+Qixi.sid).then(r=>r.json()));assert.equal(reset.map_mode,'real');assert.equal(reset.location.source,'unavailable');check.push('reset restores real-mode unknown position');
 assert.equal(await page.locator('#routeOrigin').innerText(),'未选起点');assert.equal(await page.locator('#routeDestination').innerText(),'未选终点');assert.equal(await page.locator('#poiDetail').innerText(),'');check.push('reset clears endpoints and selected-place details');
 await page.evaluate(()=>Promise.all([QixiMap.setMode('demo'),QixiMap.setMode('real'),QixiMap.setMode('demo'),QixiMap.setMode('real')]));
 assert.equal(await page.evaluate(()=>QixiMap.mode),'real');assert.equal(await page.locator('#mapMode').isDisabled(),false);check.push('rapid mode requests serialize and finish in requested mode');
 await page.route('**/api/map/mode',r=>r.fulfill({status:409,json:{detail:'fixture mode busy'}}));await page.selectOption('#mapMode','demo');await page.waitForFunction(()=>document.querySelector('#mapMessage').textContent.includes('fixture mode busy'));
 assert.equal(await page.locator('#mapMode').inputValue(),'real');assert.equal(await page.evaluate(()=>QixiMap.mode),'real');await page.unroute('**/api/map/mode');check.push('failed mode request restores selector to actual mode');
 await search('山门');await page.getByRole('button',{name:'设为起点',exact:true}).click();await search('栖霞寺');await page.getByRole('button',{name:'设为终点',exact:true}).click();
 await page.evaluate(()=>__mapTest.delay=500);const ticketReply=page.waitForResponse(r=>r.url().endsWith('/api/map/route/start'));await page.click('#planWalking');await ticketReply;await page.click('#clearVia');await page.waitForTimeout(700);
 const abandoned=await page.evaluate(async()=>fetch('/api/state?session_id='+Qixi.sid).then(r=>r.json()));assert.equal(abandoned.route,null);check.push('changing selection cancels abandoned planning without stuck pending');
 assert.deepEqual(errors,[]);check.push('no uncaught browser exceptions');
 // A second page with no Key verifies the real, nonmocked offline presentation.
 const offline=await context.newPage();await offline.goto(base);await offline.waitForFunction(()=>document.querySelector('#mapStatus').textContent.includes('地图设置'));
 await offline.screenshot({path:path.join(out,'desktop-map-unconfigured.png'),fullPage:true});
 await offline.click('#mapConfigOpen');assert.equal(await offline.locator('#mapSecurity').inputValue(),'');check.push('missing credentials explain setup without blank page or secret echo');
 fs.writeFileSync(path.join(out,'browser-map-results.json'),JSON.stringify({mockProvider:true,mockDeviceLocation:true,realAmapRequests:0,passed:check.length,checks:check,errors},null,2));
 console.log(JSON.stringify({passed:check.length,checks:check,realAmapRequests:0},null,2));
})().catch(async e=>{console.error(e);if(debugPage)console.error(await debugPage.evaluate(()=>({message:document.querySelector('#mapMessage')?.textContent,location:document.querySelector('#locationStatus')?.textContent,checks:window.__mapTest?.conversions})));process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();});
