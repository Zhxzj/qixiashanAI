/* Independent acceptance page against the running service. Never attaches to a user browser. */
const {chromium}=require(process.env.QIXI_PLAYWRIGHT_MODULE||'playwright-core');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base=process.env.QIXI_TEST_BASE||'http://127.0.0.1:8017',out=process.env.QIXI_MAP_REPORTS||path.resolve('dist/visibility-exe-reports');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1500,height:1050},reducedMotion:'reduce'}),errors=[],tiles=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.url().startsWith('https://tile.openstreetmap.org/'))tiles.push(r.status());});
  await page.goto(base);await page.locator('#mapEmpty[hidden]').waitFor({state:'attached'});await page.click('#homeMap');await page.waitForTimeout(4000);
  const data=await page.evaluate(()=>QixiMap.inspect());assert.equal(data.markers.length,14);assert.ok(data.markers.every(p=>p.onMap&&p.inBounds));
  assert.deepEqual(data.markers.filter(p=>p.id.startsWith('gate_')).map(p=>p.id).sort(),['gate_marked_south','gate_marked_west']);
  assert.equal(await page.locator('#mapStatus,#viewAllToilets,#viewAllFacilities,#facilityVisibility,#facilityStatus,#showPublicToilets').count(),0);
  assert.ok((await page.locator('.facility-label').allTextContents()).every(t=>t==='厕所'||t==='大门'));
  assert.ok((await page.evaluate(()=>fetch('/api/map/osm/data').then(r=>r.json()))).pois.every(p=>p.category!=='toilet_candidate'));
  const rect=await page.locator('#realMap').boundingBox();const pixelIds=[];
  for(const el of await page.locator('[data-annotation-id]').all()){const b=await el.boundingBox();assert.ok(b.x>=rect.x&&b.y>=rect.y&&b.x+b.width<=rect.x+rect.width&&b.y+b.height<=rect.y+rect.height);pixelIds.push(await el.getAttribute('data-annotation-id'));}
  assert.equal(pixelIds.length,14);assert.equal(errors.length,0);await page.locator('#mapWorkspace').screenshot({path:path.join(out,'actual-service-live-map.png')});
  await page.fill('#mapSearchInput','栖霞寺');await page.click('#mapSearchForm button[type=submit]');await page.locator('#mapResults button').first().click();await page.locator('.place-summary').waitFor();await page.waitForFunction(()=>document.querySelector('.place-photo-button img')?.naturalWidth>0);assert.equal(await page.locator('.place-credit').isVisible(),false);await page.locator('#mapWorkspace').screenshot({path:path.join(out,'actual-service-place-photo.png')});
  async function search(q,n=0){await page.fill('#mapSearchInput',q);await page.click('#mapSearchForm button[type=submit]');await page.locator('#mapResults button').nth(n).click();}
  await search('千佛岩');await page.getByRole('button',{name:'设为起点',exact:true}).click();
  const gateRoutes=[];
  for(const [n,id] of [[0,'gate_marked_west'],[1,'gate_marked_south']]){
   await search('大门',n);await page.getByRole('button',{name:'设为终点（附近道路）',exact:true}).click();await page.click('#planWalking');
   await page.waitForFunction(async id=>{const s=await fetch('/api/state?session_id='+Qixi.sid).then(r=>r.json());return s.route?.status==='ready'&&s.route.annotation_targets?.some(p=>p.id===id);},id);
   const route=await page.evaluate(()=>fetch('/api/state?session_id='+Qixi.sid).then(r=>r.json()).then(s=>s.route));
   const target=route.annotation_targets.find(p=>p.id===id);assert.equal(target.access_verified,false);assert.deepEqual(target.road_endpoint,route.geometry.at(-1));assert.ok(route.geometry.length>2);
   gateRoutes.push({id,geometryVertices:route.geometry.length,target});
  }
  await page.locator('#mapWorkspace').screenshot({path:path.join(out,'actual-service-gate-route.png')});
  assert.deepEqual(errors,[]);
  const version=await page.evaluate(()=>fetch('/api/ui-version').then(r=>r.json()));const report={...version,port:Number(new URL(base).port),liveTileStatuses:tiles,errors,visibleIds:pixelIds,visibleMarkerCount:14,gateRoutes,removedRegionAbsent:true,toiletNumbersAbsent:true,publicCandidatesAbsent:true,originalUserWindowCaptured:false,independentAcceptancePage:true,photoAttributionCollapsed:true};
  fs.writeFileSync(path.join(out,'actual-service-visible-verification.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
