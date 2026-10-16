/* 构图文法 5 · 诗笺式：大量留白 + 居中竖排短句（≤16 字）+ 小图/印章（§2.5-5） */
(function () {
  const S = (window.PosterSkill = window.PosterSkill || {});
  S.grammars = S.grammars || {};
  S.grammars.poem = async function poem(ctx) {
    const { el, textEl, photoEl, hero, caps } = ctx;
    const box = el("div", "grammar grammar-poem", { position: "absolute", inset: "0" });

    const line = (ctx.spec.type.quote || ctx.title || "").slice(0, 16);
    box.appendChild(textEl("div", "t2 vertical", line, {
      position: "absolute", right: "14%", top: "8%", height: "48%",
      writingMode: "vertical-rl", textOrientation: "upright", letterSpacing: "14px",
      color: "var(--primary)",
    }));
    box.appendChild(textEl("div", "t6 kicker", ctx.kicker, {
      position: "absolute", right: "20%", top: "58%",
      writingMode: "vertical-rl", letterSpacing: "4px",
    }));
    box.appendChild(photoEl(hero, "rect", {
      position: "absolute", left: "9%", top: "24%", width: "44%", height: "44%",
    }));
    const cap = (caps[0] && caps[0].text) || "";
    if (cap) {
      box.appendChild(textEl("div", "t5", cap, {
        position: "absolute", left: "9%", top: "70.5%", width: "44%",
      }));
    }
    return box;
  };
})();
