/* 构图文法 2 · 卷轴式：左竖栏 + 右大图 + 下方小图（海报办法 §2.5-2） */
(function () {
  const S = (window.PosterSkill = window.PosterSkill || {});
  S.grammars = S.grammars || {};
  S.grammars.scroll = async function scroll(ctx) {
    const { el, textEl, photoEl, hero, subs, spec } = ctx;
    const box = el("div", "grammar grammar-scroll", { position: "absolute", inset: "0" });

    // 左栏
    box.appendChild(textEl("div", "t2 vertical", ctx.title, {
      position: "absolute", left: "3.6%", top: "5%",
      writingMode: "vertical-rl", textOrientation: "upright", height: "44%",
      color: "var(--primary)", letterSpacing: "10px",
    }));
    box.appendChild(textEl("div", "t6 kicker", spec.meta.date, {
      position: "absolute", left: "6.2%", top: "52%",
      writingMode: "vertical-rl", letterSpacing: "6px",
    }));
    box.appendChild(textEl("div", "t6 num", spec.meta.page_no || "", {
      position: "absolute", left: "3.6%", bottom: "8%", opacity: "0.7",
    }));

    // 右大图
    box.appendChild(photoEl(hero, "rect", {
      position: "absolute", left: "15%", top: "4.2%", width: "80%", height: "58%",
    }));
    // 下方两小图
    const layouts = [
      { left: "15%", top: "64.5%", width: "38%", height: "22%" },
      { left: "57%", top: "64.5%", width: "38%", height: "22%" },
    ];
    subs.slice(0, 2).forEach((p, i) => {
      box.appendChild(photoEl(p, "rect", { position: "absolute", ...layouts[i] }));
    });
    const cap = (ctx.caps[0] && ctx.caps[0].text) || "";
    if (cap) {
      box.appendChild(textEl("div", "t5", cap, {
        position: "absolute", left: "15%", top: "88.4%", width: "60%",
      }));
    }
    return box;
  };
})();
