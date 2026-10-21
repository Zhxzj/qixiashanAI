/* Shared identity across guide and poster pages; never reuse the old demo id. */
(function () {
  let sid = localStorage.getItem("qixi_sid");
  if (!sid || sid === "demo") sid = crypto.randomUUID();
  localStorage.setItem("qixi_sid", sid);
  window.Qixi = { sid, generation: null };
  const embedded = window.parent !== window && new URLSearchParams(location.search).get('embedded') === '1';
  // Share only the current page's random capability with its same-origin workspace.
  // The model Key itself is never put into browser storage or a URL.
  Qixi.pageId = embedded ? window.parent.Qixi.pageId : crypto.randomUUID();
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = new URL(input instanceof Request ? input.url : input, location.href);
    if(url.origin !== location.origin || !url.pathname.startsWith('/api/')) return nativeFetch(input,init);
    const headers = new Headers(init?.headers || (input instanceof Request ? input.headers : undefined));
    headers.set('X-Qixi-Page',Qixi.pageId);
    return nativeFetch(input,{...init,headers});
  };
  if(!embedded) window.addEventListener('pagehide',()=>navigator.sendBeacon('/api/config/forget',new Blob([JSON.stringify({page_id:Qixi.pageId})],{type:'application/json'})));
  if(!embedded) window.addEventListener('pageshow',event=>{if(event.persisted){Qixi.pageId=crypto.randomUUID();window.QixiUI?.keyStatus(false);const status=document.querySelector('#keyStatus');if(status)status.textContent='本次进入需重新输入 Key';}});
  window.Qixi.escape = (s) => String(s ?? "").replace(/[&<>"']/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  window.Qixi.exit = async () => {
    const r = await fetch("/api/app");
    const info = await r.json();
    const stop = await fetch("/api/app/control", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:info.control_token,action:"exit"})});
    if (!stop.ok) throw new Error("退出失败，请重试");
    document.body.textContent = "应用已退出，可以关闭此页面。";
  };
})();
