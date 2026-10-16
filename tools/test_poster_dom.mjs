/* 海报渲染无头自测（jsdom）：6 构图 × 4 色板 × 1/3/6 张照片
 * 校验：渲染不抛错、关键槽位存在、footer AI 标注、QA 可运行、取色接口可调用。
 *
 * 用法： node tools/test_poster_dom.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const SKILL = path.join(ROOT, "web", "poster", "skill");

const RENDERER_FILES = [
  "render.js", "grammar-mount.js", "grammar-scroll.js", "grammar-timeline.js",
  "grammar-collage.js", "grammar-poem.js", "grammar-map.js", "poster-qa.js",
];
const CSS_FILES = ["css/palettes.css", "css/type.css", "css/base.css"];
const GRAMMARS = ["mount", "scroll", "timeline", "collage", "poem", "map"];
const PALETTES = ["danfeng", "zhemo", "yanlan", "yuebai"];

// jsdom 不加载外部资源：母题用备用 SVG，图片用 data URL（1×1 GIF），保证流程可跑
const GIF = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";
const MOTIF_AS_FALLBACK = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96"><circle cx="48" cy="48" r="40" fill="currentColor"/></svg>';

function buildDom() {
  const css = CSS_FILES.map((f) => fs.readFileSync(path.join(SKILL, f), "utf8")).join("\n");
  const dom = new JSDOM(
    `<!doctype html><html><head><style>${css}</style></head><body><div id="stage"></div></body></html>`,
    { pretendToBeVisual: true, runScripts: "outside-only" }
  );
  const { window } = dom;
  // 近似浏览器行为：外部资源不实际加载，fetch 直接给母题占位
  window.fetch = async () => ({ text: async () => MOTIF_AS_FALLBACK });
  window.PosterSkill = undefined;
  for (const f of RENDERER_FILES) {
    const code = fs.readFileSync(path.join(SKILL, "renderer", f), "utf8");
    window.eval(code);
  }
  if (!window.PosterSkill || !window.PosterSkill.render) {
    throw new Error("renderer 没有挂上 window.PosterSkill.render");
  }
  return dom;
}

function makeSpec(grammar, palette, nPhotos, seed) {
  const photos = [];
  for (let i = 0; i < nPhotos; i++) {
    photos.push({ file: `p${i}.jpg`, url: GIF, role: i === 0 ? "hero" : "sub", crop: "rect", slot: i === 0 ? "top" : "mid" });
  }
  return {
    canvas: { w: 1080, h: 1620 },
    grammar, palette,
    motifs: [{ id: "maple_leaf_line", style: "line", x: 0.05, y: 0.04, scale: 0.12, rot: -12 }],
    photos,
    type: {
      title: "山中一日", kicker: "2026.10.31 · 晴",
      captions: ["明镜湖的水面", "千佛岩的石阶", "霜红苑的一片坡", "舍利塔的影子", "枫林湖的倒影", "凤翔峰的晚霞"],
      quote: "霜叶红于二月花", seal: "栖霞",
    },
    meta: { date: "2026-10-31", poi_count: nPhotos, route_m: 1680, page_no: "No.001" },
    seed,
  };
}

const results = [];
const fail = (msg) => { results.push(["FAIL", msg]); };
const pass = (msg) => { results.push(["PASS", msg]); };

async function main() {
  let combo = 0, errs = 0;
  for (let n of [1, 3, 6]) {
    for (const g of GRAMMARS) {
      for (const p of PALETTES) {
        combo++;
        const dom = buildDom();
        const { window } = dom;
        const stage = window.document.getElementById("stage");
        const spec = makeSpec(g, p, n, 20261031 + combo * 13);
        try {
          await window.PosterSkill.render(stage, spec);
        } catch (e) {
          errs++;
          fail(`渲染 ${g}/${p}/${n}张：${e.message}`);
          continue;
        }
        // 结构断言
        const footer = stage.querySelector(".footer-slot .ai-mark");
        if (!footer || !/AI 辅助生成/.test(footer.textContent)) fail(`${g}/${p}/${n}：缺 AI 标注`);
        if (!stage.querySelector('.pframe[data-qa="img"]')) fail(`${g}/${p}/${n}：没有照片槽`);
        const textCount = stage.querySelectorAll('[data-qa="text"]').length;
        if (textCount < 3) fail(`${g}/${p}/${n}：文本槽过少 (${textCount})`);
        if (stage.dataset.palette !== p) fail(`${g}/${p}/${n}：色板没写进 data-palette`);
        // 取色接口
        const hint = await window.PosterSkill.extractPalette(spec.photos);
        if (hint === undefined) fail(`${g}/${p}/${n}：取色接口返回 undefined`);
        // QA（jsdom 里部分项会标记 unknown，只要不抛错即可）
        try {
          const qa = window.PosterSkill.qa.run(window.document, stage, {});
          if (typeof qa.ok !== "boolean" || !Array.isArray(qa.results)) {
            fail(`${g}/${p}/${n}：QA 返回结构不对`);
          }
        } catch (e) {
          fail(`${g}/${p}/${n}：QA 抛错 ${e.message}`);
        }
      }
    }
  }
  pass(`全组合渲染：${combo} 组（6 构图 × 4 色板 × 1/3/6 张），渲染异常 ${errs} 组`);

  // 单点深查：山门式 + 丹枫 + 3 张，检查槽位细节
  const dom = buildDom();
  const { window } = dom;
  const stage = window.document.getElementById("stage");
  const spec = makeSpec("mount", "danfeng", 3, 42);
  await window.PosterSkill.render(stage, spec);
  const texts = [...stage.querySelectorAll('[data-qa="text"]')].map((n) => n.textContent);
  const hasTitle = texts.some((t) => t.includes("山中"));
  const hasKicker = texts.some((t) => t.includes("2026.10.31"));
  const hasCaption = texts.some((t) => t.includes("明镜湖"));
  if (!hasTitle) fail("山门式：标题没渲染");
  if (!hasKicker) fail("山门式：kicker 没渲染");
  if (!hasCaption) fail("山门式：caption 没渲染");
  const imgs = stage.querySelectorAll('.pframe[data-qa="img"]').length;
  if (imgs < 2) fail(`山门式：照片槽只有 ${imgs} 个（应有主图 + 小图）`);
  const motif = stage.querySelector(".motif");
  if (!motif) fail("山门式：母题没渲染");
  if (hasTitle && hasKicker && hasCaption && imgs >= 2 && motif) pass("山门式单点深查（标题/kicker/caption/照片/母题）");

  const bad = results.filter((r) => r[0] === "FAIL");
  for (const [mark, msg] of results) console.log(`[${mark}] ${msg}`);
  console.log("-".repeat(56));
  console.log(`共 ${results.length} 项，失败 ${bad.length} 项`);
  return bad.length ? 1 : 0;
}

const code = await main();
process.exit(code);
