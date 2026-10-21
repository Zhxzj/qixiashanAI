/* Actual app layout, focus and motion checks; no live model requests. */
const {chromium}=require(process.env.QIXI_PLAYWRIGHT_MODULE||'playwright-core');
const fs=require('fs'),assert=require('assert/strict'),path=require('path');
const base=process.env.QIXI_TEST_BASE||'http://127.0.0.1:8041',out=process.env.QIXI_UI_REPORTS||'D:/Codex/2026-10-16/bug/work/ui-v4-final';fs.mkdirSync(out,{recursive:true});
let browser;const checks=[],errors=[],sizes=[],performance=[];
(async()=>{
 browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 const ctx=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});const p=await ctx.newPage();p.on('pageerror',e=>errors.push(e.message));
 await p.route('**/api/conditions',r=>r.fulfill({contentType:'application/json',body:JSON.stringify({weather:{status:'unknown',now:{text:'天气暂不可用'},today:{},advice:[],source:'测试空态'},red_leaf:{text:'暂无实测数据'}})}));
 await p.goto(base);await p.waitForFunction(()=>QixiMap.inspect().initialized);await p.waitForTimeout(350);
 assert.equal(await p.locator('#uiKeyMissing').isVisible(),true);await p.click('#uiConfigureModel');await p.waitForFunction(()=>document.activeElement.id==='keyInput');await p.keyboard.press('Escape');await p.waitForFunction(()=>getComputedStyle(document.querySelector('#keyModal')).display==='none');checks.push('unconfigured-model shortcut, modal initial focus, Escape and return focus');
 await p.click('#uiMore summary');await p.keyboard.press('Escape');assert.equal(await p.locator('#uiMore').evaluate(e=>e.open),false);assert.equal(await p.evaluate(()=>document.activeElement.tagName),'SUMMARY');checks.push('More menu Escape restores trigger focus');
 const geom=await p.evaluate(()=>{
 const box=s=>{const r=document.querySelector(s).getBoundingClientRect();return{x:r.x,y:r.y,width:r.width,bottom:r.bottom};};return{header:box('.ui-header-inner'),nav:box('.ui-nav'),guide:box('.function-guide'),chat:box('.chat-panel'),today:box('.ui-today'),icons:[...document.querySelectorAll('.guide-icon')].map(e=>{const r=e.getBoundingClientRect();return{x:r.x,y:r.y,w:r.width,h:r.height};})};});
 assert.equal(geom.header.x,geom.guide.x);assert.equal(geom.chat.x,geom.guide.x);assert.ok(Math.abs(geom.nav.x+geom.nav.width/2-720)<1);assert.equal(geom.chat.y,geom.today.y);assert.ok(Math.abs(geom.chat.bottom-geom.today.bottom)<1);assert.ok(geom.icons.every(i=>i.w===52&&i.h===52&&i.y===geom.icons[0].y));checks.push('1440px shared 80px edge, centered nav, aligned card top/bottom and six 52px icons');
 await p.screenshot({path:out+'/首页-实际成品.png',fullPage:true});
 await p.route('**/api/chat',r=>r.fulfill({contentType:'text/event-stream',body:'data: {"type":"delta","text":"这是界面验收用的固定回答。实际问答继续连接原模型服务。"}\n\ndata: {"type":"done"}\n\n'}));
 await p.fill('#chatInput','今天想去看看千佛岩');await p.locator('#chatForm').evaluate(e=>e.requestSubmit());await p.waitForFunction(()=>document.querySelectorAll('.msg.ai')[0]?.textContent.includes('固定回答'));await p.screenshot({path:out+'/问答-实际界面-固定响应.png',fullPage:true});
 await p.click('.ui-nav [data-view=map]');await p.click('#homeMap');await p.waitForTimeout(200);await p.screenshot({path:out+'/地图-实际成品.png',fullPage:true});
 await p.fill('#mapSearchInput','栖霞寺');await p.locator('#mapSearchForm').evaluate(e=>e.requestSubmit());await p.locator('#mapResults button').first().click();await p.waitForFunction(()=>document.querySelector('.place-photo-button img')?.naturalWidth>0);await p.screenshot({path:out+'/景点详情-实际成品.png',fullPage:true});
 await p.locator('.place-photo-button').focus();await p.keyboard.press('Enter');assert.equal(await p.locator('#placePhotoDialog').evaluate(e=>e.open),true);assert.equal(await p.locator('#placePhotoDialog').evaluate(e=>e.getAnimations().filter(a=>a.playState==='running').length),0);await p.keyboard.press('Escape');assert.equal(await p.locator('.place-photo-button').evaluate(e=>e===document.activeElement),true);checks.push('keyboard/reduced-motion photo immediate, Escape closes and returns focus');
 const cdp=await ctx.newCDPSession(p);await cdp.send('Emulation.setCPUThrottlingRate',{rate:4});await p.emulateMedia({reducedMotion:'no-preference'});
 await p.evaluate(()=>{window.__uiLong=[];new PerformanceObserver(list=>__uiLong.push(...list.getEntries().map(e=>({start:e.startTime,duration:e.duration})))).observe({type:'longtask'});});
 for(let i=0;i<20;i++) {const start=Date.now();await p.locator('.place-photo-button').click();await p.waitForTimeout(220);await p.click('#placePhotoClose');await p.waitForTimeout(190);performance.push(Date.now()-start);}
 await p.locator('.place-photo-button').click();await p.click('#placePhotoClose');await p.keyboard.press('Escape');assert.equal(await p.locator('#placePhotoDialog').evaluate(e=>e.open),false);checks.push('20 photo open/close cycles at 4x CPU and Escape interrupts close animation');
 const longtasks=await p.evaluate(()=>__uiLong);await cdp.send('Emulation.setCPUThrottlingRate',{rate:1});await p.emulateMedia({reducedMotion:'reduce'});
 await p.click('.ui-nav [data-view=poster]');const f=p.frameLocator('#posterFrame');await f.locator('#tripInfo').waitFor();await p.waitForTimeout(300);await p.screenshot({path:out+'/海报-实际成品.png',fullPage:true});
 for(const width of [1920,1440,1366,1280,1024,800,640,390,320]) {
   await p.setViewportSize({width,height:1000});for(const view of ['chat','map','poster']){await p.evaluate(v=>QixiUI.show(v,false),view);await p.waitForTimeout(40);const parent=await p.evaluate(()=>({inner:innerWidth,scroll:document.documentElement.scrollWidth}));const child=view==='poster'?await f.locator('body').evaluate(()=>({inner:innerWidth,scroll:document.documentElement.scrollWidth})):null;assert.ok(parent.scroll<=parent.inner,JSON.stringify({width,view,parent}));if(child)assert.ok(child.scroll<=child.inner);sizes.push({width,view,parent,child});}
 }
 checks.push('9 widths x 3 views, including iframe content, have no horizontal overflow');
 for(const [width,height] of [[1280,720],[1366,768]]) {await p.setViewportSize({width,height});for(const view of ['chat','map','poster']){await p.evaluate(v=>QixiUI.show(v,false),view);assert.ok(await p.locator('#exitApp').isVisible());}}
 checks.push('1280x720 and 1366x768 essential navigation/exit accessible');
 await p.setViewportSize({width:1440,height:1000});await p.addStyleTag({content:'.ui-app{font-size:30px}'});await p.evaluate(()=>QixiUI.show('chat',false));assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));checks.push('200% body text size has no horizontal overflow');
 await p.setViewportSize({width:390,height:1000});await p.reload();await p.waitForFunction(()=>QixiMap.inspect().initialized);await p.waitForTimeout(400);await p.screenshot({path:out+'/首页-窄窗口实际成品.png',fullPage:true});
 assert.deepEqual(errors,[]);checks.push('no unhandled page errors');
 fs.writeFileSync(path.join(out,'visual-results.json'),JSON.stringify({passed:checks.length,checks,errors,sizes,geometry:geom,motion:{cpuThrottle:4,cycles:20,wallTimesMs:performance,longTasks:longtasks,hardwareGpuVerified:false},model:'fixed response fixture',weather:'unavailable fixture',tiles:'live public tile requests; no guaranteed availability'},null,2));console.log(JSON.stringify({passed:checks.length,longTasks:longtasks.length},null,2));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();});
