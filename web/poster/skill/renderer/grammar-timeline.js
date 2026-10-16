/* 构图文法 3 · 时间轴式：竖轴 + 3–5 节点（点位名 + 一句话 + 小图）（海报办法 §2.5-3） */
(function () {
  const S = (window.PosterSkill = window.PosterSkill || {});
  S.grammars = S.grammars || {};
  S.grammars.timeline = async function timeline(ctx) {
    const { el, textEl, photoEl, hero, subs, caps } = ctx;
    const box = el("div", "grammar grammar-timeline", { position: "absolute", inset: "0" });

    box.appendChild(textEl("div", "t2", ctx.title, {
      position: "absolute", left: "6%", top: "4%", color: "var(--primary)",
    }));
    box.appendChild(textEl("div", "t6 kicker", ctx.kicker, {
      position: "absolute", left: "6.4%", top: "10.6%",
    }));

    const axX = 27;
    box.appendChild(el("div", "hairline", {
      position: "absolute", left: axX + "%", top: "15%", width: "2px", height: "66%",
    }));

    const photos = [hero, ...subs].slice(0, 4);
    const n = photos.length;
    photos.forEach((p, i) => {
      const top = 17 + i * (60 / Math.max(1, n));
      const right = i % 2 === 0;
      // 节点圆点
      const dot = el("div", "dot", {
        position: "absolute", left: `calc(${axX}% - 7px)`, top: (top + 6) + "%",
        width: "16px", height: "16px",
      });
      box.appendChild(dot);
      const w = 30;
      const left = right ? axX + 4 : axX - 4 - w;
      box.appendChild(photoEl(p, "rect", {
        position: "absolute", left: left + "%", top: top + "%",
        width: w + "%", height: "13.4%",
      }));
      const cap = (caps[i] && caps[i].text) || "";
      if (cap) {
        box.appendChild(textEl("div", "t6", cap, {
          position: "absolute",
          left: (right ? left : left + 2) + "%", top: (top + 14.4) + "%",
          width: (w - 2) + "%",
        }));
      }
    });
    return box;
  };
})();
