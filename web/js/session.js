/* Shared identity across guide and poster pages; never reuse the old demo id. */
(function () {
  let sid = localStorage.getItem("qixi_sid");
  if (!sid || sid === "demo") sid = crypto.randomUUID();
  localStorage.setItem("qixi_sid", sid);
  window.Qixi = { sid, generation: null };
  window.Qixi.escape = (s) => String(s ?? "").replace(/[&<>"']/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  window.Qixi.exit = async () => {
    const r = await fetch("/api/app");
    const info = await r.json();
    const stop = await fetch("/api/app/control", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:info.control_token,action:"exit"})});
    if (!stop.ok) throw new Error("退出失败，请重试");
    document.body.textContent = "应用已退出，可以关闭此页面。";
  };
})();
