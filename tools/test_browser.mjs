/* Real Edge layout/export regression tests, using the actual portable EXE. */
import fs from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {spawn} from "node:child_process";
import {randomUUID,createHash} from "node:crypto";
const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"..");
const work=path.join(ROOT,".tmp","browser-"+randomUUID());
await fs.mkdir(work,{recursive:true});
const cache=path.join(work,"用户 缓存");
const profile=path.join(work,"edge-profile");
const downloads=path.join(work,"downloads");
await fs.mkdir(downloads,{recursive:true});
const executable=process.env.QIXI_TEST_EXE || path.join(ROOT,"dist","栖霞山小向导.exe");
const host=spawn(process.env.QIXI_TEST_PYTHON || executable,process.env.QIXI_TEST_PYTHON ? ["-B",path.join(ROOT,"launcher.py")] : [],{env:{...process.env,QIXI_USER_DIR:cache,QIXI_NO_BROWSER:"1"},windowsHide:true,stdio:"ignore"});
let edge,socket,instance;
const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
const errors=[];
const pending=new Map();let sequence=0;
function cdp(method,params={}) {
  const id=++sequence;
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error("CDP timeout: "+method));},120000);
    pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));
  });
}
async function evaluate(expression) {
  const result=await cdp("Runtime.evaluate",{expression,awaitPromise:true,returnByValue:true,userGesture:true});
  if(result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result?.value;
}
async function waitFor(expression,timeout=45000) {
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline) {if(await evaluate(expression)) return;await sleep(100);}
  throw new Error("页面等待超时："+expression+"; "+await evaluate("document.body.innerText.slice(-1500)"));
}
async function go(url) {
  await cdp("Page.navigate",{url});
  await waitFor("document.readyState==='complete'");
}
async function request(pathname,body) {
  const response=await fetch(`http://127.0.0.1:${instance.port}${pathname}`,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  if(!response.ok) throw new Error("API "+response.status);
  return response.json();
}
const checks=[];
function check(name,condition) {if(!condition) throw new Error(name);checks.push(name);console.log("[PASS]",name);}
try {
  let deadline=Date.now()+45000;
  while(Date.now()<deadline) {
    try {instance=JSON.parse(await fs.readFile(path.join(cache,"instance/current.json"),"utf8"));if((await request("/api/health")).instance_id===instance.instance_id) break;} catch {}
    await sleep(100);
  }
  if(!instance) throw new Error("成品未就绪");
  const edgePath=process.env.QIXI_EDGE || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
  edge=spawn(edgePath,["--headless=new","--disable-gpu","--no-first-run","--no-default-browser-check","--remote-debugging-port=0","--user-data-dir="+profile,"about:blank"],{windowsHide:true,stdio:"ignore"});
  let port;
  deadline=Date.now()+30000;
  while(Date.now()<deadline) {try {port=(await fs.readFile(path.join(profile,"DevToolsActivePort"),"utf8")).split("\n")[0];break;} catch {} await sleep(100);}
  if(!port) throw new Error("Edge 调试端口未就绪");
  const tabs=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket=new WebSocket(tabs.find(t=>t.type==="page").webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.addEventListener("open",resolve,{once:true});socket.addEventListener("error",reject,{once:true});});
  socket.addEventListener("message",(event)=>{
    const message=JSON.parse(event.data);
    if(message.id && pending.has(message.id)) {const p=pending.get(message.id);pending.delete(message.id);clearTimeout(p.timer);message.error?p.reject(new Error(message.error.message)):p.resolve(message.result);}
    else if(message.method==="Runtime.exceptionThrown") errors.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
  });
  await cdp("Page.enable");await cdp("Runtime.enable");
  await cdp("Emulation.setDeviceMetricsOverride",{width:1600,height:1000,deviceScaleFactor:1,mobile:false});
  await cdp("Browser.setDownloadBehavior",{behavior:"allow",downloadPath:downloads});
  const base=`http://127.0.0.1:${instance.port}`;
  await go(base);
  await waitFor("document.querySelector('#poiSelect').options.length===10");
  check("向导首屏就绪，无 Key 有明确状态",await evaluate("document.querySelector('#keyStatus').textContent.includes('尚未配置')"));
  const sid=await evaluate("localStorage.getItem('qixi_sid')");
  check("随机独立会话",sid && sid!=="demo");
  await go(base+"/poster.html");
  await waitFor("window.Qixi && document.querySelector('#samplesBtn')");
  await evaluate("document.querySelector('#samplesBtn').click()");
  await waitFor("document.querySelectorAll('#photoGrid img').length===4");
  check("照片示例正确入列",await evaluate("document.querySelectorAll('#photoList .photo-row').length===4"));
  await evaluate("document.querySelector('#genBtn').click()");
  await waitFor("document.querySelectorAll('#candRow .cand').length===3",60000);
  check("三候选与日记正文实际交付",await evaluate("document.querySelector('#diaryBody').textContent.length>20"));
  const qa=await evaluate("document.querySelector('#qaBox').innerText");
  console.log("Candidate QA:",qa);
  const thumb=await evaluate("document.querySelector('#candRow img').src");
  await fs.writeFile(path.join(ROOT,"dist/browser-candidate.png"),Buffer.from(thumb.split(",")[1],"base64"));
  const shot=await cdp("Page.captureScreenshot",{format:"png"});
  await fs.writeFile(path.join(ROOT,"dist/browser-page.png"),Buffer.from(shot.data,"base64"));
  // Exercise all renderer combinations with real decoded images/layout. Failures are returned, never counted as passes.
  const matrix=await evaluate(`(async()=>{
    const images=[...document.querySelectorAll('#photoGrid img')].map(i=>i.src);
    const results=[];
    const stage=document.createElement('div');stage.className='poster-stage';Object.assign(stage.style,{position:'absolute',left:'-20000px',top:'0',transform:'none'});document.body.append(stage);
    for(const n of [1,3,6]) for(const grammar of ['mount','scroll','timeline','collage','poem','map']) for(const palette of ['danfeng','zhemo','yanlan','yuebai']) {
      const spec={canvas:{w:1080,h:1620},grammar,palette,motifs:[],photos:Array.from({length:n},(_,i)=>({file:'p'+i,url:images[i%images.length],role:i?'sub':'hero'})),type:{title:'山中影记',kicker:'2026.10.16',captions:Array.from({length:n},(_,i)=>({photo_id:'p'+i,text:'地点待确认'})),seal:'栖霞'},meta:{date:'2026.10.16',poi_count:n},seed:42};
      await PosterSkill.render(stage,spec);await Promise.all([...stage.querySelectorAll('img')].map(i=>i.decode()));
      const canvas=await htmlToImage.toCanvas(stage,{pixelRatio:0.12,width:1080,height:1620,style:{position:'relative',transform:'none',insetBlock:'0 auto',insetInline:'0 auto',left:'0',top:'0',right:'auto',bottom:'auto'}});
      const qa=PosterSkill.qa.run(document,stage,{canvasCtx:canvas.getContext('2d'),palette:PosterSkill.PALETTES[palette]});results.push({n,grammar,palette,ok:qa.ok,failed:qa.results.filter(r=>!r.ok)});
    }
    stage.remove();return results;
  })()`);
  await fs.writeFile(path.join(ROOT,"dist/browser-layout-results.json"),JSON.stringify(matrix,null,2));
  const failed=matrix.filter(r=>!r.ok);
  console.log("Real layout matrix:",matrix.length-failed.length,"/",matrix.length,"; failures:",JSON.stringify(failed).slice(0,5000));
  // Choose an exportable candidate, verify the real downloaded PNG signature and dimensions.
  for(let i=0;i<3 && await evaluate("document.querySelector('#pngBtn').disabled");i++) {
    await evaluate(`document.querySelectorAll('#candRow .cand')[${i}].click()`);await sleep(800);
  }
  check("至少一个候选通过完整质检",!await evaluate("document.querySelector('#pngBtn').disabled"));
  await evaluate("document.querySelector('#pngBtn').click()");
  deadline=Date.now()+45000;let png;
  while(Date.now()<deadline) {png=(await fs.readdir(downloads)).find(n=>n.endsWith('.png'));if(png) break;await sleep(150);}
  check("真实浏览器完成 PNG 下载",!!png);
  const data=await fs.readFile(path.join(downloads,png));
  check("PNG 内容与 1080×1620 尺寸有效",data.subarray(1,4).toString()==="PNG" && data.readUInt32BE(16)===1080 && data.readUInt32BE(20)===1620);
  await evaluate("document.querySelector('#clearBtn').click()");
  check("清空撤销候选与导出资格",await evaluate("document.querySelectorAll('#candRow .cand').length===0 && document.querySelector('#pngBtn').disabled"));
  check("浏览器无未处理 JavaScript 异常",errors.length===0);
  check("真实布局矩阵全部通过",failed.length===0);
  await fs.writeFile(path.join(ROOT,"dist/browser-test-results.json"),JSON.stringify({checks,errors,matrix_pass:matrix.length-failed.length,matrix_total:matrix.length,build_id:(await request('/api/health')).build_id,exe_sha256:process.env.QIXI_TEST_PYTHON?null:createHash('sha256').update(await fs.readFile(executable)).digest('hex'),download:path.join(downloads,png)},null,2));
} finally {
  if(socket) {try {await cdp("Browser.close");}catch{} socket.close();}
  if(edge && edge.exitCode===null) edge.kill();
  if(instance) {try {await request("/api/app/control",{token:instance.token,action:"exit"});}catch{}}
  if(host.exitCode===null) {await Promise.race([new Promise(r=>host.once("exit",r)),sleep(15000)]);if(host.exitCode===null) host.kill();}
}
