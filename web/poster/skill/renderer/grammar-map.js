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
      const t = i / (n - 1);
      const x = 180 + 720 * t + Math.sin(t * Math.PI * 1.3) * 90;
      const y = 1290 - 820 * t + Math.cos(t * Math.PI) * 60;
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
    const st = nodes[0], en = nodes[nodes.length - 1];
    box.appendChild(textEl("div", "t6", "起点", {
      position: "absolute", left: (st[0] / 1080 * 100 - 2) + "%", top: (st[1] / 1620 * 100 + 2) + "%",
      color: "var(--primary)",
    }));
    box.appendChild(textEl("div", "t6", (spec.meta.poi_count ? spec.meta.poi_count + " 站" : "终点"), {
      position: "absolute", left: (en[0] / 1080 * 100 - 2) + "%", top: (en[1] / 1620 * 100 - 6) + "%",
      color: "var(--primary)",
    }));

    // 照片锚点
    photos.forEach((p, i) => {
      const [x, y] = nodes[Math.min(i, nodes.length - 1)];
      const left = i % 2 === 0 ? x + 60 : x - 340;
      const top = y - 190 + (i % 2) * 40;
      box.appendChild(photoEl(p, "polaroid", {
        position: "absolute", left: Math.min(640, Math.max(60, left)) + "px",
        top: Math.max(220, Math.min(1180, top)) + "px",
        width: "26%", height: "15%",
        transform: `rotate(${i % 2 === 0 ? -2 : 2.4}deg)`,
      }));
      const cap = (caps[i] && caps[i].text) || "";
      if (cap) {
        box.appendChild(textEl("div", "t6", cap, {
          position: "absolute",
          left: Math.min(640, Math.max(60, left)) + "px",
          top: Math.max(220, Math.min(1180, top)) + 260 + "px",
          width: "26%",
        }));
      }
    });
    return box;
  };
})();
