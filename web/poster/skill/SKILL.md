# 小栖海报生成 Skill（v0.1 实现说明）

> 规范来源：《小栖海报生成工作管理办法（试行）》v0.1（SSOT）。本目录是它的**可执行实现**。
> 一句话：LLM 只出文字（标题/导语/图注/落款），几何与色由渲染器与色板决定，质检层守住底线。

## 目录

```
skill/
├─ SKILL.md                  # 本文件（给编码代理与维护者）
├─ css/palettes.css          # 四套色板（CSS 变量，仅 --accent 可被取色覆盖）
├─ css/type.css               # 6 级字号阶梯（96/72/52/36/28/20 @1080）
├─ css/base.css               # 舞台、相框、印章、footer、纹理
├─ motifs/*.svg               # 12 枚母题（线稿 + 实心，24px 网格）
└─ renderer/
   ├─ render.js               # 入口：DesignSpec + 照片 → #stage DOM（含取色）
   ├─ grammar-mount.js        # 山门式
   ├─ grammar-scroll.js       # 卷轴式
   ├─ grammar-timeline.js     # 时间轴式
   ├─ grammar-collage.js      # 拼贴式
   ├─ grammar-poem.js         # 诗笺式
   ├─ grammar-map.js          # 地图式
   └─ poster-qa.js            # 质检：H1/H2/H3/H4/H7/H9/H11 + 重叠
```

## 渲染契约

```js
await PosterSkill.render(stageEl, spec);
```

- `spec`（DesignSpec）字段见《海报办法》§3.2；`type.captions` 支持字符串或 `{text}`。
- 舞台固定 1080×1620；预览用 `transform: scale()`；导出前由调用方把 transform 复位为 `none`。
- 渲染器自己决定母题位置（`spec.motifs` 给出 id/位置/缩放入口），**LLM 不写 CSS/HTML**。
- 取色：`extractPalette(photos)` 在渲染末尾自动执行，命中（ΔE<12）时覆盖 `--accent`，并把结果写到 `spec.palette_hint`。

## 质检契约

```js
const qa = PosterSkill.qa.run(document, stageEl, {});
// { ok, pass, total, results: [{name, ok, detail}] }
```

- `H1` 溢出 / `H2` 对比度 / `H3` 边距（含印章 6%） / `H4` 字号阶梯 / `H7` 照片短边≥600
  / `H11` AI 标注 / 文本与文本、文本与图片重叠。
- `H9` 留白在 `poster-app.js` 中用缩略图取样补测（浏览器端）。
- 浏览器直接打开页面即可看到逐条质检结果；改渲染器后跑 `node tools/test_poster_dom.mjs`（72 组合）。

## 字体说明

demo 用系统字体栈（标题 楷体 / 正文 宋体 / 数字 Garamond 系）。发布版如需嵌入
霞鹜文楷与思源宋体，用 fonttools 子集化后放 `css/fonts/`，在 `type.css` 里加 `@font-face`，
并在导出前 `await document.fonts.ready`（渲染器已保证这一步）。

## 升级路径

- 新母题：按 24px 网格画 SVG 放 `motifs/`，在 `render.js` 的 `MOTIFS` 里登记。
- 新语法：加 `grammar-<name>.js`（导出 `S.grammars.<name>`），在 `poster.html` 里挂一个 `<script>`。
- 参考样本：`app/data/refs/<poi_id>/` 放真实照片后，无 GPS 识别会自动用上（Vision 直比）。
