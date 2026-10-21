const {chromium}=require(process.env.QIXI_PLAYWRIGHT_MODULE||'playwright-core');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
let browser;const checks=[],errors=[];
(async()=>{
 browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
 await context.route('https://tile.openstreetmap.org/**',r=>r.abort());
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));let chats=0;
 page.on('request',r=>{if(new URL(r.url()).pathname==='/api/chat')chats++;});
 await page.goto(process.env.QIXI_TEST_BASE);await page.waitForFunction(()=>QixiMap.inspect().initialized);
 assert.equal(await page.locator('#uiHome').isVisible(),false);assert.equal(await page.locator('#messages .msg').count(),0);checks.push('actual homepage hides Home with empty history');
 for(const selector of ['.ui-nav [data-view=chat]','.guide-item[data-view=chat]']){
  await page.click(selector);assert.equal(await page.getAttribute('body','data-conversation'),'true');assert.equal(await page.locator('#uiHome').isVisible(),true);
  assert.equal(await page.locator('.scenic').isVisible(),false);assert.ok((await page.locator('.chat-panel').boundingBox()).height>650);
  await page.fill('#chatInput','尚未发送的草稿');await page.click('#uiHome');assert.equal(await page.inputValue('#chatInput'),'尚未发送的草稿');assert.equal(await page.locator('#uiHome').isVisible(),false);
 }checks.push('both AI entries open full-height empty conversation and Home preserves draft');assert.equal(chats,0);checks.push('entering AI never sends a model request');
 await page.click('.ui-nav [data-view=map]');await page.click('#majorPois');assert.equal(await page.locator('#mapResults button').count(),14);checks.push('14 main places visible, with original graph positions');
 for(const [query,title] of [['如来堂','如来堂'],['如來堂','如来堂'],['读枫','读枫阁'],['读枫阁','读枫阁']]){
  await page.fill('#mapSearchInput',query);await page.locator('#mapSearchForm').evaluate(f=>f.requestSubmit());await page.locator('#mapResults button').first().click();
  await page.waitForFunction(t=>document.querySelector('#poiDetail h3')?.textContent===t&&document.querySelector('.place-summary'),title);
  assert.ok((await page.locator('.place-detail-text').innerText()).length<=200);
 }checks.push('simplified/traditional and pavilion aliases select matching enriched content');
 const items=await page.evaluate(()=>fetch('/api/map/places').then(r=>r.json()).then(r=>r.items));
 const excluded=new Set(['栖霞寺','千佛岩','何家山','九乡河']);
 for(const p of items.filter(p=>!excluded.has(p.name))){
  const d=await page.evaluate(id=>fetch('/api/map/place?place_id='+encodeURIComponent(id)).then(r=>r.json()),p.place_id);
  assert.ok(d.summary&&!d.summary.includes('正在核对'));assert.ok(d.detail.length<=200&&d.sources.length);assert.ok(!d.detail.includes(d.summary));
 }checks.push('all 12 requested places have two distinct text layers and provenance');
 for(const place of items.filter(p=>!excluded.has(p.name))){
  await page.fill('#mapSearchInput',place.name);await page.locator('#mapSearchForm').evaluate(f=>f.requestSubmit());await page.locator('#mapResults button').first().click();
  await page.waitForFunction(n=>document.querySelector('#poiDetail h3')?.textContent===n&&document.querySelector('.place-photo-button img')?.complete&&document.querySelector('.place-photo-button img')?.naturalWidth>0,place.name);
  assert.equal(await page.locator('.place-credit').isVisible(),false);
  await page.locator('.place-photo-button').click();await page.locator('#placePhotoDialog[open]').waitFor();
  await page.waitForFunction(()=>document.querySelector('#placePhotoFull').naturalWidth>0);await page.keyboard.press('Escape');
 }checks.push('all 12 user photos load locally, open at full size, with credits folded');

 assert.equal(await page.locator('#poiDetail details').getAttribute('open'),null);checks.push('source and editorial status folded by default');
 await page.screenshot({path:path.join(process.env.QIXI_UI_REPORTS,'十二景资料与别名.png'),fullPage:true});
 await page.click('#uiHome');await page.click('.ui-nav [data-view=chat]');await page.screenshot({path:path.join(process.env.QIXI_UI_REPORTS,'空记录完整AI界面.png'),fullPage:true});
 assert.deepEqual(errors,[]);checks.push('no browser exceptions');
 fs.writeFileSync(path.join(process.env.QIXI_UI_REPORTS,'home-places-update.json'),JSON.stringify({passed:checks.length,checks,errors,realModelRequests:chats},null,2));console.log('Home/12-place checks:',checks.length);
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();});
