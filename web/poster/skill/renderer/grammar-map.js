/* 构图文法 6 · 地图式：路线线稿贯穿全页 + 照片锚在点位 + 起终点标记（§2.5-6） */
(function () {
  const S = (window.PosterSkill = window.PosterSkill || {});
  S.grammars = S.grammars || {};
  S.grammars.map = async function mapGrammar(ctx) {
    const { el, textEl, photoEl, hero, subs, caps, spec } = ctx;
    const box = el("div", "grammar grammar-map", { position: "absolute", inset: "0" });

    box.appendChild(textEl("div", "t2", ctx.title, {
      position: "absolute", left: "6%", top: "4%", color: "var(--primary)",
    }));
    box.appendChild(textEl("div", "t6 kicker", ctx.kicker, {
      position: "absolute", left: "6.4%", top: "10.4%",
    }));

    // 用点位照片顺序拼一条"路"——从照片数量推节点
    const photos = [hero, ...subs].slice(0, 4);
    const n = Math.max(2, photos.length);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 1080 1620");
    svg.setAttribute("data-qa", "route");
    svg.style.cssText = "position:absolute;inset:0;width:100%;height:100%";
    const nodes = [];
    for (let i = 0; i < n; i++) {
      const x = i % 2 === 0 ? 450 : 560;
      const y = i < 2 ? 1000 : 510;
      nodes.push([x, y]);
    }
    let d = `M ${nodes[0][0]} ${nodes[0][1]}`;
    for (let i = 1; i < nodes.length; i++) {
      const [x0, y0] = nodes[i - 1];
      const [x1, y1] = nodes[i];
      const mx = (x0 + x1) / 2 + 60;
      d += ` Q ${mx} ${(y0 + y1) / 2} ${x1} ${y1}`;
    }
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "var(--secondary)");
    path.setAttribute("stroke-width", "4");
    path.setAttribute("stroke-dasharray", "12 10");
    path.setAttribute("opacity", "0.8");
    svg.appendChild(path);
    nodes.forEach(([x, y], i) => {
      const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      c.setAttribute("cx", x); c.setAttribute("cy", y); c.setAttribute("r", i === 0 || i === n - 1 ? 12 : 7);
      c.setAttribute("fill", "var(--accent)");
      svg.appendChild(c);
    });
    box.appendChild(svg);

    // 起点 / 终点标记
    box.appendChild(textEl("div", "t6", "起点", {
      position: "absolute", left: "44%", top: "78%",
      color: "var(--ink)",
    }));
    box.appendChild(textEl("div", "t6", (spec.meta.poi_count ? spec.meta.poi_count + " 站" : "终点"), {
      position: "absolute", left: "44%", top: "16%",
      color: "var(--ink)",
    }));

    // 照片锚点
    photos.forEach((p, i) => {
      const left = i % 2 === 0 ? 100 : 600;
      const top = i < 2 ? 820 : 330;
      box.appendChild(photoEl(p, "polaroid", {
        position: "absolute", left: left + "px", top: top + "px",
        width: "300px", height: "300px",
        transform: `rotate(${i % 2 === 0 ? -2 : 2.4}deg)`,
      }));
      const cap = ctx.captionFor(p, i).text || "";
      if (cap) {
        box.appendChild(textEl("div", "t6", cap, {
          position: "absolute",
          left: left + "px", top: top + 330 + "px", width: "300px",
        }));
      }
    });
    return box;
  };
})();
