import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";
import assert from "node:assert/strict";
import {JSDOM} from "jsdom";
const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"..");
let passed=0;
const check=(name,fn)=>Promise.resolve().then(fn).then(()=>{passed++;console.log("[PASS]",name);});
function windowFor(page) {
  const dom=new JSDOM(fs.readFileSync(path.join(ROOT,"web",page),"utf8"),{url:"http://127.0.0.1:8017",runScripts:"outside-only",pretendToBeVisual:true});
  const w=dom.window;w.Qixi={sid:"isolated-test",generation:0,escape:s=>String(s)};w.structuredClone=structuredClone;
  return dom;
}
const guide=windowFor("index.html");
const g=guide.window;
const audio=[];
g.Audio=class {constructor(src){this.src=src;audio.push(this);} play(){this.played=true;return Promise.resolve();} pause(){this.paused=true;}};
let tts=0;g.speechSynthesis={cancel(){},speak(){tts++;}};g.SpeechSynthesisUtterance=class {};
let code=fs.readFileSync(path.join(ROOT,"web/js/app.js"),"utf8").replace(/init\(\)\.catch\(.*\);\n/,'').replace(/\nbindEvents\(\);/,'');
g.eval(code+'\nwindow.test={state,speak,stopVoice,onArrive,typeInto,bindEvents,bump:()=>uiGeneration++};');
await check("预生成 MP3 优先且内容保留",()=>{
  g.test.state.speaking={name:"千佛岩",line:"测试",audio_url:"/audio/poi/test.mp3"};
  g.test.speak("测试");assert.equal(audio.length,1);assert.equal(tts,0);assert.equal(g.test.state.speaking.name,"千佛岩");
});
await check("停止会暂停同一个播放器并保留重播内容",()=>{g.test.stopVoice();assert.equal(audio[0].paused,true);assert.equal(g.test.state.speaking.line,"测试");});
await check("语音先于打字完成开始",async()=>{
  await g.test.onArrive({event_id:"e",name:"点位",line:"这是长一点的讲解",audio_url:"/test.mp3"},1);
  assert.equal(audio.length,2);assert.notEqual(g.document.querySelector('#arrivedText').textContent,"这是长一点的讲解");
});
await check("到点事件幂等消费",async()=>{await g.test.onArrive({event_id:"e",name:"点位",line:"x",audio_url:"/test.mp3"},1);assert.equal(audio.length,2);});
await check("旧打字任务取消后不继续渲染",async()=>{const el=g.document.createElement('div');const p=g.test.typeInto(el,'旧文本',1);g.test.bump();await p;assert.equal(el.textContent,'');});
guide.window.close();

const poster=windowFor("poster.html");const w=poster.window;
w.PosterSkill={};
w.Image=class {set src(value){this.naturalWidth=1600;this.naturalHeight=1200;queueMicrotask(()=>this.onload?.());}};
w.HTMLCanvasElement.prototype.getContext=()=>({drawImage(){}});
w.HTMLCanvasElement.prototype.toDataURL=()=>"data:image/jpeg;base64,test";
code=fs.readFileSync(path.join(ROOT,"web/poster/poster-app.js"),"utf8").replace('  init();','  window.test={state,addPhotoFromURL,scheduleDetect,waitImages,invalidate,buildSpec,bind};');
w.eval(code);
const t=w.test;
t.state.poiById={qixiasi:{poi_id:"qixiasi",name:"栖霞寺",coord:[32.1505,118.9575]}};
await check("EXIF 使用十进制坐标而非 DMS 数组",async()=>{
  w.exifr={parse:async()=>({GPSLatitude:[32,9,1.8],GPSLongitude:[118,57,27],latitude:32.1505,longitude:118.9575})};
  await t.addPhotoFromURL('data:test','照片',{});
  assert.equal(t.state.photos[0].source,'gps');assert.equal(t.state.photos[0].gps[0],32.1505);
});
await check("迟到识别不会覆盖人工指定",async()=>{
  let resolve;
  w.fetch=()=>new Promise(r=>{resolve=r;});
  const item={id:'race',url:'data:test',source:'unknown'};t.state.photos.push(item);
  const task=t.scheduleDetect(item);
  for(let i=0;i<20&&!resolve;i++) await new Promise(r=>setTimeout(r,0));
  assert.ok(resolve);item.source='manual';item.poi_id='qixiasi';
  resolve({ok:true,json:async()=>({ok:true,mode:'vision',best:{poi_id:'other',name:'别的地点'}})});
  await task;assert.equal(item.source,'manual');assert.equal(item.poi_id,'qixiasi');
});
await check("已失败的图片立即拒绝，不永久等待",async()=>{
  const image={complete:true,naturalWidth:0,removeEventListener(){},addEventListener(){}};
  await assert.rejects(t.waitImages({querySelectorAll:()=>[image]}),/解码失败/);
});
await check("输入变更撤销候选和导出资格",()=>{t.state.candidates=[{}];t.state.trip={};t.invalidate();assert.equal(t.state.candidates.length,0);assert.equal(t.state.trip,null);assert.equal(w.document.querySelector('#pngBtn').disabled,true);});
await check("图注按 photo_id 绑定，重排后仍正确",()=>{
  t.state.photos=[{id:'b',url:'b'},{id:'a',url:'a'}];
  t.state.trip={diary:{title:'影记',captions:[{photo_id:'a',text:'A'},{photo_id:'b',text:'B'}]}};
  const spec=t.buildSpec('map','yuebai',1);assert.equal(spec.type.captions[0].text,'B');assert.equal(spec.type.captions[1].text,'A');
});
poster.window.close();
console.log(`前端行为回归 ${passed}/${passed}`);
