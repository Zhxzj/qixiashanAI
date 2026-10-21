/* Real browser lifecycle + original/new output equivalence. Model/GPS fixtures are explicit. */
const {chromium}=require(process.env.QIXI_PLAYWRIGHT_MODULE||'playwright-core');
const fs=require('fs'),path=require('path'),assert=require('assert/strict'),crypto=require('crypto');
const base=process.env.QIXI_TEST_BASE||'http://127.0.0.1:8041';
const out=process.env.QIXI_UI_REPORTS||'D:/Codex/2026-10-16/bug/work/ui-v4-lifecycle';fs.mkdirSync(out,{recursive:true});
const backup=process.env.QIXI_UI_BASELINE||'D:/Codex/2026-10-16/bug/work/ui-v4-production-backup';
const checks=[],errors=[];let browser;
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const blank=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=','base64');
async function config(ctx){
 await ctx.route('https://tile.openstreetmap.org/**',r=>r.fulfill({contentType:'image/png',body:blank}));
 await ctx.route('**/api/recap',async r=>{const photos=r.request().postDataJSON().photos;await r.fulfill({contentType:'application/json',body:JSON.stringify({visited:[],conditions:{red_leaf:{text:'秋日'}},replay_lines:['今天走进山林。'],diary:{title:'山中一日',kicker:'2026.10.21 · 栖霞山',paragraphs:['今天在栖霞山走了一段，留下这些照片。'],captions:photos.map(p=>({photo_id:p.id,text:'山间留影'})),seal:'栖霞'}})});});
}
async function generate(frame){
 await frame.locator('#samplesBtn').evaluate(b=>b.click());await frame.locator('#photoGrid img').nth(3).waitFor();
 await frame.locator('#genBtn').click();await frame.locator('#candRow .cand').nth(2).waitFor({timeout:90000});
 await frame.locator('#genBtn').waitFor({state:'visible'});
 await frame.locator('#stageEmpty').waitFor({state:'hidden'});
 return frame.locator('#candRow img').evaluateAll(imgs=>imgs.map(i=>i.src));
}
(async()=>{
 browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 const ctx=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce',acceptDownloads:true});await config(ctx);
 await ctx.addInitScript(()=>{window.__watchCount=0;window.__clearCount=0;let ok;Object.defineProperty(navigator,'geolocation',{value:{watchPosition(fn){window.__watchCount++;ok=fn;setTimeout(()=>ok?.({coords:{latitude:32.1538504,longitude:118.9550305,accuracy:10},timestamp:Date.now()}),20);return 1;},clearWatch(){window.__clearCount++;ok=null;}}});});
 const p=await ctx.newPage();p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.accept());let childStateRequests=0,chatRequests=0,cancels=0,recaps=0;
 p.on('request',r=>{if(r.url().includes('/api/state') && r.frame()!==p.mainFrame())childStateRequests++;if(r.url().includes('/api/recap'))recaps++;});
 await p.goto(base);await p.waitForFunction(()=>QixiMap.inspect().initialized);assert.equal(await p.locator('#view-chat').isVisible(),true);assert.equal(await p.locator('.brand,.brand-mark').count(),0);checks.push('AI default; requested logo/name/subtitle absent');
 await p.fill('#chatInput','保留这条草稿');const id=await p.evaluate(()=>document.querySelector('#realMap')._leaflet_id);
 await p.click('.ui-nav [data-view=map]');await p.waitForTimeout(100);assert.ok((await p.evaluate(()=>QixiMap.inspect())).markers.every(m=>m.inBounds));checks.push('first hidden-map reveal fits all 12 toilets and 2 gates');
 await p.click('#startLocation');await p.waitForFunction(()=>QixiMap.inspect().locating);await p.waitForFunction(()=>document.querySelector('#locationStatus').textContent.includes('可做实时判断'));
 const frameEl=await p.locator('#posterFrame').elementHandle();await p.click('.ui-nav [data-view=poster]');const f=p.frameLocator('#posterFrame');await f.locator('#tripInfo').waitFor();await p.waitForTimeout(500);
 for(const v of ['chat','map','poster','chat'])await p.click('.ui-nav [data-view='+v+']');
 assert.equal(await p.inputValue('#chatInput'),'保留这条草稿');assert.equal(await p.evaluate(()=>document.querySelector('#realMap')._leaflet_id),id);assert.equal(await p.evaluate(()=>__watchCount),1);assert.equal(await p.evaluate(()=>__clearCount),0);assert.equal(await p.locator('#uiStopLocation').isVisible(),true);await p.click('#uiStopLocation');await p.waitForFunction(()=>!QixiMap.inspect().locating);checks.push('draft, Leaflet identity and one GPS subscription survive tab changes; global stop works');
 assert.equal(recaps,0);assert.equal(childStateRequests,0);checks.push('tab/iframe init makes no model request; poster never consumes arrival state endpoint');
 await p.route('**/api/chat',r=>{chatRequests++;return new Promise(resolve=>setTimeout(async()=>{try{await r.fulfill({contentType:'text/event-stream',body:'data: {"type":"delta","text":"测试回答"}\n\ndata: {"type":"done"}\n\n'});}catch{}resolve();},2000));});
 await p.route('**/api/chat/cancel',async r=>{cancels++;await r.fulfill({contentType:'application/json',body:'{}'});});
 await p.locator('#chatForm').evaluate(f=>f.requestSubmit());await p.fill('#chatInput','第二条');await p.locator('#chatForm').evaluate(f=>f.requestSubmit());await p.click('.ui-nav [data-view=map]');await p.waitForFunction(()=>!document.querySelector('#uiCancel').hidden);await p.click('#uiCancel');await p.waitForTimeout(2200);assert.equal(chatRequests,2);assert.equal(cancels,2);assert.equal(await p.locator('#messages .msg.user').count(),2);checks.push('two in-flight chats retained across view switch and both cancelled without re-send');
 await p.unroute('**/api/chat');await p.unroute('**/api/chat/cancel');await p.click('.ui-nav [data-view=poster]');
 const thumbs=await generate(f);const photoCount=await f.locator('#photoGrid img').count();const candidateHTML=await f.locator('#candRow').innerHTML();
 await p.click('.ui-nav [data-view=chat]');await p.fill('#chatInput','1');await p.keyboard.press('2');await p.click('.ui-nav [data-view=poster]');
 assert.equal(await f.locator('#photoGrid img').count(),photoCount);assert.equal(await f.locator('#candRow').innerHTML(),candidateHTML);assert.equal(await p.locator('#posterFrame').evaluate((node,old)=>node===old,frameEl),true);checks.push('real decoded photos, three candidates, active selection and iframe persist; hidden keyboard does not select');
 // Original UI, same data/model fixture/browser/seed/date; compare the actual PNG candidate bytes.
 const oldCtx=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});await config(oldCtx);
 for(const rel of ['poster.html','poster/poster-app.js'])await oldCtx.route('**/'+rel,r=>r.fulfill({contentType:rel.endsWith('.html')?'text/html':'text/javascript',body:fs.readFileSync(path.join(backup,'web',rel))}));
 const old=await oldCtx.newPage();await old.goto(base+'/poster.html');const oldThumbs=await generate(old);
 assert.deepEqual(thumbs.map(hash),oldThumbs.map(hash));checks.push('all three original/new rendered candidate PNGs are byte-identical with fixed recap and seed');
 const fullPNG=async frame=>frame.locator('#stage').evaluate(async stage=>htmlToImage.toPng(stage,{pixelRatio:1,width:1080,height:1620,style:{position:'relative',transform:'none',insetBlock:'0 auto',insetInline:'0 auto',left:'0',top:'0',right:'auto',bottom:'auto'}}));
 const fullNew=await fullPNG(f),fullOld=await fullPNG(old);assert.equal(hash(fullNew),hash(fullOld));checks.push('1080x1620 rendered PNG bytes equal original UI');
 await oldCtx.close();
 for(let i=0;i<3 && await f.locator('#pngBtn').isDisabled();i++){await f.locator('#candRow .cand').nth(i).click();await p.waitForTimeout(500);}
 assert.equal(await f.locator('#pngBtn').isDisabled(),false);const dl=p.waitForEvent('download');await f.locator('#pngBtn').click();const download=await dl;const file=await download.path();const png=fs.readFileSync(file);assert.equal(png.readUInt32BE(16),1080);assert.equal(png.readUInt32BE(20),1620);await download.saveAs(out+'/海报实际导出.png');checks.push('real iframe download passes original QA and exports 1080x1620 PNG');
 // Unknown message cannot invalidate album/candidates.
 await p.evaluate(()=>postMessage({channel:'qixi-ui-v1',type:'epoch',sid:Qixi.sid,epoch:'spoof'},location.origin));await p.waitForTimeout(50);assert.equal(await f.locator('#candRow .cand').count(),3);checks.push('unknown message source rejected');
 await p.click('#uiMore summary');await p.click('#resetBtn');await p.waitForFunction(()=>document.querySelector('#messages').textContent.includes('已开始新行程'));await p.waitForTimeout(250);assert.equal(await f.locator('#candRow .cand').count(),0);assert.equal(await f.locator('#photoGrid img').count(),photoCount);assert.equal(await f.locator('#pngBtn').isDisabled(),true);assert.equal(childStateRequests,0);checks.push('new trip invalidates stale candidates/tasks without deleting photos; child still no arrival reads');
 await p.click('.ui-nav [data-view=map]');await p.click('#startLocation');await p.waitForFunction(()=>QixiMap.inspect().locating);await p.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));});await p.waitForFunction(()=>!QixiMap.inspect().locating);checks.push('actual background visibility handler stops GPS');
 assert.deepEqual(errors,[]);checks.push('no page JavaScript exceptions');
 fs.writeFileSync(out+'/lifecycle.json',JSON.stringify({passed:checks.length,checks,errors,childStateRequests,modelFixture:true,gpsFixture:true,realPhotos:true,realPNG:true,thumbnailHashes:thumbs.map(hash),fullPngHash:hash(fullNew)},null,2));console.log(JSON.stringify({passed:checks.length,checks},null,2));await ctx.close();
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();});
