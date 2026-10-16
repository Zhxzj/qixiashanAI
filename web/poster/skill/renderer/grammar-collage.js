/* 构图文法 4 · 拼贴式：3–6 张照片散置（拍立得白边 + 手写感标注）+ 枫叶点缀（§2.5-4） */
(function () {
  const S = (window.PosterSkill = window.PosterSkill || {});
  S.grammars = S.grammars || {};
  S.grammars.collage = async function collage(ctx) {
    const { el, textEl, photoEl, hero, subs, caps, rnd } = ctx;
    const box = el("div", "grammar grammar-collage", { position: "absolute", inset: "0" });

    box.appendChild(textEl("div", "t2", ctx.title, {
      position: "absolute", left: "6%", top: "4%", color: "var(--primary)",
    }));
    box.appendChild(textEl("div", "t6 kicker", ctx.kicker, {
      position: "absolute", left: "6.4%", top: "10.4%",
    }));

    const photos = [hero, ...subs].slice(0, 6);
    const slots = [
      { left: 6, top: 14, w: 44, h: 24, rot: -2.2 },
      { left: 55, top: 13, w: 39, h: 21, rot: 2.6 },
      { left: 8, top: 42, w: 37, h: 21, rot: 1.6 },
      { left: 50, top: 38, w: 44, h: 25, rot: -2.8 },
      { left: 12, top: 66, w: 35, h: 20, rot: -1.4 },
      { left: 54, top: 65, w: 40, h: 22, rot: 2.2 },
    ];
    photos.forEach((p, i) => {
      const s = slots[i % slots.length];
      const jx = (rnd() - 0.5) * 1.6;
      const jy = (rnd() - 0.5) * 1.6;
      const f = photoEl(p, "polaroid", {
        position: "absolute", left: (s.left + jx) + "%", top: (s.top + jy) + "%",
        width: s.w + "%", height: s.h + "%",
        transform: `rotate(${s.rot + (rnd() - 0.5) * 1.2}deg)`,
      });
      box.appendChild(f);
      const cap = (caps[i] && caps[i].text) || "";
      if (cap) {
        box.appendChild(textEl("div", "t6", cap, {
          position: "absolute", left: (s.left + jx + 1) + "%", top: (s.top + jy + s.h + 0.4) + "%",
          width: (s.w - 4) + "%", transform: "rotate(-0.6deg)",
          fontFamily: "var(--font-title)", opacity: "0.9",
        }));
      }
    });
    return box;
  };
})();
