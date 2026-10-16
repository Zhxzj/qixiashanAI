/* 构图文法 1 · 山门式：大图 55–60% 高 + 竖排大标题 + 印章（海报办法 §2.5-1） */
(function () {
  const S = (window.PosterSkill = window.PosterSkill || {});
  S.grammars = S.grammars || {};
  S.grammars.mount = async function mount(ctx) {
    const { el, textEl, verticalTitle, photoEl, hero, subs } = ctx;
    const box = el("div", "grammar grammar-mount", { position: "absolute", inset: "0" });

    box.appendChild(photoEl(hero, "rect", {
      position: "absolute", left: "5%", top: "3.4%", width: "90%", height: "57%",
    }));
    box.appendChild(textEl("div", "kicker t6", ctx.kicker, {
      position: "absolute", left: "5.6%", top: "61.6%",
    }));
    box.appendChild(textEl("div", "t3", "栖霞山纪游", {
      position: "absolute", left: "5.6%", top: "63.6%", opacity: "0.78",
    }));
    box.appendChild(verticalTitle(ctx.title, "t2", {
      position: "absolute", right: "6.4%", top: "61%", color: "var(--primary)",
    }));
    const cap = (ctx.caps[0] && ctx.caps[0].text) || "";
    if (cap) {
      box.appendChild(textEl("div", "t5", cap, {
        position: "absolute", left: "5.6%", top: "70.4%", width: "52%", opacity: "0.92",
      }));
    }
    // 底部一条照片（如果有）
    if (subs[0]) {
      box.appendChild(photoEl(subs[0], "polaroid", {
        position: "absolute", right: "7%", top: "73%", width: "30%", height: "20%",
        transform: "rotate(2.5deg)",
      }));
    }
    box.appendChild(el("div", "hairline", {
      position: "absolute", left: "5.6%", top: "79%", width: "44%", height: "2px",
    }));
    const cap2 = (ctx.caps[1] && ctx.caps[1].text) || "";
    if (cap2) {
      box.appendChild(textEl("div", "t6 cap-small", cap2, {
        position: "absolute", left: "5.6%", top: "80.6%", width: "44%",
      }));
    }
    return box;
  };
})();
