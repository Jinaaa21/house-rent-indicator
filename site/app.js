"use strict";

// 임대차 2법 지표 테스트: 정적 파일(data/*.json)을 읽어 지도·차트를 SVG로 직접 그린다.
// 데이터는 src/11_build_site.py 가 만든다.

const $ = (id) => document.getElementById(id);
const SVGNS = "http://www.w3.org/2000/svg";
const state = {
  dongs: [], byCd: new Map(), geoDong: null, geoGu: null, S: null,
  mode: "pair", lisaLevel: "fdr", sc: "dlq_rg", box: "dLQ_exist", r: "R_exist", sel: null,
};

// 색: 발산형(파랑 = 감소, 빨강 = 증가, 가운데 회색), 순차형(파랑), 권역(범주 고정 순서)
const DIV = ["#104281", "#1c5cab", "#3987e5", "#86b6ef", "#d4e3f5", "#f0efec", "#f6d3d1", "#e99a97", "#e66767", "#c43c3a", "#a8201f"];
const SEQ = ["#eaf2fc", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#1c5cab", "#104281"];
const NODATA = "#c9c8c2";
const REGION_COLOR = { 도심권: "#2a78d6", 동북권: "#eb6834", 서북권: "#1baf7a", 서남권: "#eda100", 동남권: "#6250d6" };
const LISA_COLOR = { HH: "#a8201f", LL: "#104281", HL: "#e99a97", LH: "#86b6ef", 유의하지_않음: "#f0efec" };
const LIGHT = 0.35; // 90% 구간이 0을 포함하는 동: 같은 색을 흰 바탕과 35%로 섞음

const IND = {
  dLQ_exist: { name: "ΔLQ (준공 2017년 이하 단지)", short: "ΔLQ(기존 단지)", fmt: (v) => signed(v, 2), neg: "전세 쪽", pos: "월세 쪽" },
  dLQ_all: { name: "ΔLQ (전체 계약)", short: "ΔLQ(전체)", fmt: (v) => signed(v, 2), neg: "전세 쪽", pos: "월세 쪽" },
  RG: { name: "RG (순수전세 ㎡당 보증금 상대 상승률)", short: "RG", fmt: (v) => signed(v, 3), neg: "상승 둔화", pos: "상승 가속" },
  U: { name: "갱신요구권 사용률 U", short: "U", fmt: (v) => pct(v), seq: true },
};

init();

async function init() {
  try {
    const [dongs, gd, gg, S] = await Promise.all(
      ["data/dongs.json", "data/admdong.geojson", "data/gu.geojson", "data/summary.json"].map((u) =>
        fetch(u).then((r) => { if (!r.ok) throw new Error(u); return r.json(); })),
    );
    Object.assign(state, { dongs, geoDong: gd, geoGu: gg, S });
    for (const d of dongs) state.byCd.set(d.cd, d);
  } catch (e) {
    $("maps").textContent = "자료를 불러오지 못했습니다. 로컬에서는 site 폴더에서 'python -m http.server'로 연 뒤 접속하세요.";
    return;
  }
  // 인쇄할 때는 접는 상자(7장)를 모두 펼친다
  window.addEventListener("beforeprint", () => { for (const d of document.querySelectorAll("details")) d.open = true; });
  bindSeg("mode", (v) => { state.mode = v; $("lisa-level").hidden = v !== "lisa"; drawMaps(); });
  bindSeg("lisa-level", (v) => { state.lisaLevel = v; drawMaps(); });
  bindSeg("sc-mode", (v) => { state.sc = v; drawScatter(); });
  bindSeg("box-mode", (v) => { state.box = v; drawBox(); });
  bindSeg("r-mode", (v) => { state.r = v; drawR(); });
  renderKpis();
  renderTables();
  drawAll();
  let t, lastW = document.body.clientWidth;
  new ResizeObserver(() => {
    const w = document.body.clientWidth;
    if (w === lastW) return; // 높이만 바뀐 경우(접는 상자 열기 등)는 다시 그리지 않음
    lastW = w; clearTimeout(t); t = setTimeout(drawAll, 120);
  }).observe(document.body);
}

function drawAll() {
  drawMaps(); drawScatter(); drawBox(); drawForest(); drawMonthly(); drawR(); drawHist(); renderPanel();
}

// ---------- 공통 ----------
function el(tag, attrs = {}, ...kids) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) e.setAttribute(k, v);
  for (const c of kids) e.append(c);
  return e;
}
function div(cls, text) { const d = document.createElement("div"); if (cls) d.className = cls; if (text != null) d.textContent = text; return d; }
function span(cls, text) { const s = document.createElement("span"); if (cls) s.className = cls; s.textContent = text; return s; }
function signed(v, d) { return v == null ? "–" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}`; }
function fx(v, d = 2) { return v == null ? "–" : `${v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}`; }
function pct(v, d = 1) { return v == null ? "–" : `${(v * 100).toFixed(d)}%`; }
function fmtInt(n) { return n == null ? "–" : Math.round(n).toLocaleString("ko-KR"); }
function bindSeg(id, cb) {
  $(id).addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    for (const x of $(id).querySelectorAll("button")) x.classList.toggle("on", x === b);
    cb(b.dataset.v);
  });
}
function hexRgb(h) { return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)); }
function ramp(colors, t) {
  const x = Math.min(1, Math.max(0, t)) * (colors.length - 1);
  const i = Math.min(colors.length - 2, Math.floor(x)), f = x - i;
  const a = hexRgb(colors[i]), b = hexRgb(colors[i + 1]);
  return a.map((v, j) => Math.round(v + (b[j] - v) * f));
}
const rgb = (c) => `rgb(${c.join(",")})`;
const lighten = (c) => c.map((v) => Math.round(LIGHT * v + (1 - LIGHT) * 255));
function quantile(arr, q) {
  const s = [...arr].sort((a, b) => a - b); if (!s.length) return null;
  const i = (s.length - 1) * q, lo = Math.floor(i), hi = Math.ceil(i);
  return s[lo] + (s[hi] - s[lo]) * (i - lo);
}
function corr(xs, ys) {
  const n = xs.length, mx = xs.reduce((a, b) => a + b, 0) / n, my = ys.reduce((a, b) => a + b, 0) / n;
  let sxy = 0, sxx = 0, syy = 0;
  for (let i = 0; i < n; i++) { const dx = xs[i] - mx, dy = ys[i] - my; sxy += dx * dy; sxx += dx * dx; syy += dy * dy; }
  return sxy / Math.sqrt(sxx * syy);
}
function rank(a) {
  const idx = a.map((v, i) => [v, i]).sort((x, y) => x[0] - y[0]); const r = new Array(a.length);
  for (let i = 0; i < idx.length;) { let j = i; while (j + 1 < idx.length && idx[j + 1][0] === idx[i][0]) j++; for (let k = i; k <= j; k++) r[idx[k][1]] = (i + j) / 2 + 1; i = j + 1; }
  return r;
}
const spearman = (x, y) => corr(rank(x), rank(y));
function niceStep(raw) { const p = 10 ** Math.floor(Math.log10(raw)), m = raw / p; return (m >= 5 ? 10 : m >= 2 ? 5 : m >= 1 ? 2 : 1) * p; }
function ticks(lo, hi, n = 5) { const s = niceStep((hi - lo) / n); const out = []; for (let v = Math.ceil(lo / s) * s; v <= hi + 1e-9; v += s) out.push(+v.toFixed(10)); return out; }
function tipShow(ev, lines) {
  const tip = $("tip");
  tip.replaceChildren();
  lines.forEach((l, i) => { if (i) tip.append(document.createElement("br")); if (i === 0) { const b = document.createElement("b"); b.textContent = l; tip.append(b); } else tip.append(l); });
  tip.hidden = false;
  const r = tip.getBoundingClientRect();
  let x = ev.clientX + 14, y = ev.clientY + 14;
  if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - 14;
  if (y + r.height > innerHeight - 8) y = ev.clientY - r.height - 14;
  tip.style.left = `${x}px`; tip.style.top = `${y}px`;
}
const tipHide = () => { $("tip").hidden = true; };
function select(cd) { state.sel = state.sel === cd ? null : cd; tipHide(); drawMaps(); drawScatter(); drawBox(); drawR(); renderPanel(); }
function valid(d, key) { return d[key] && d[key].v != null; }
const label = (d) => `${d.gu} ${d.nm}`;
function moranOf(ind, w = "퀸 인접") { return state.S.moran.find((m) => m.ind === ind && m.w.startsWith(w.slice(0, 1))); }

// ---------- 핵심 결과 ----------
function renderKpis() {
  const D = state.dongs.filter((d) => !d.hold);
  const both = D.filter((d) => valid(d, "dLQ_exist") && valid(d, "RG"));
  const r = corr(both.map((d) => d.dLQ_exist.v), both.map((d) => d.RG.v));
  const mE = moranOf("dLQ_exist"), mR = moranOf("RG"), mU = moranOf("U");
  const same = both.filter((d) => (d.dLQ_exist.v > 0) === (d.RG.v > 0)).length;
  const px = both.filter((d) => d.dLQ_exist.v > 0).length / both.length, py = both.filter((d) => d.RG.v > 0).length / both.length;
  const sameExp = both.length * (px * py + (1 - px) * (1 - py));
  const regMed = (rg) => quantile(D.filter((d) => d.region === rg && valid(d, "RG")).map((d) => d.RG.v), 0.5);
  const R = state.S.renewal;
  const cards = [
    ["월세화 지역 × 전세 상승 가속 지역", `r = ${fx(r)}`, `ΔLQ(기존 단지)와 RG의 행정동 상관(${both.length}개 동). 같은 방향으로 움직인 동은 ${same}개로, 두 지표가 무관할 때의 기대 ${Math.round(sameExp)}개보다 조금 많다.`, true],
    ["공간 자기상관(Moran's I)", `${fx(mE.I)} · ${fx(mR.I)}`, `ΔLQ · RG 모두 약한 양의 값(p ≤ 0.001). U는 ${fx(mU.I)}(p = ${mU.p.toFixed(2)})로 없음.`],
    ["갱신요구권 사용률(서울)", pct(R.used / R.renew), `실제 사용률은 U와 U_upper(${pct(R.U_upper_seoul)}) 사이. 공간 패턴과 다른 지표와의 관계는 거의 없음.`],
    ["RG 권역 중위(서북 · 동남)", `${signed(regMed("서북권"), 3)} · ${signed(regMed("동남권"), 3)}`, "서북·서남권에서 높고 동남권에서 낮다. 동남권은 시행 전 상승률이 가장 높았던 곳이라 평균으로의 회귀가 섞였을 수 있다."],
  ];
  $("kpis").replaceChildren(...cards.map(([l, v, s, hero]) => {
    const k = div(`kpi${hero ? " hero" : ""}`); k.append(div("label", l), div(`value${v.length > 14 ? " sm" : ""}`, v), div("sub", s)); return k;
  }));
  $("kpi-note").textContent = "ΔLQ: 월세계약 입지계수(LQ)의 시행 전후 차이, RG: 순수전세 ㎡당 보증금의 시행 후 상승률 − 시행 전 상승률, U: 갱신 계약 중 갱신요구권 '사용' 비율. 정의는 지표 카드와 7장에 있습니다.";
}

// ---------- 지도 ----------
function projector(W, H, pad = 6) {
  const k = Math.cos((37.55 * Math.PI) / 180);
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const f of state.geoGu.features) for (const ring of rings(f.geometry)) for (const [lon, lat] of ring) {
    x0 = Math.min(x0, lon * k); x1 = Math.max(x1, lon * k); y0 = Math.min(y0, lat); y1 = Math.max(y1, lat);
  }
  const s = Math.min((W - 2 * pad) / (x1 - x0), (H - 2 * pad) / (y1 - y0));
  const ox = (W - (x1 - x0) * s) / 2, oy = (H - (y1 - y0) * s) / 2;
  return ([lon, lat]) => [ox + (lon * k - x0) * s, oy + (y1 - lat) * s];
}
function rings(g) { return g.type === "Polygon" ? g.coordinates : g.coordinates.flat(); }
function pathD(g, P) {
  const polys = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
  return polys.map((poly) => poly.map((ring) => ring.map((p, i) => `${i ? "L" : "M"}${P(p).map((v) => v.toFixed(1)).join(",")}`).join("") + "Z").join("")).join("");
}
function centroid(r) {
  let a = 0, x = 0, y = 0;
  for (let i = 0; i < r.length - 1; i++) { const c = r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]; a += c; x += (r[i][0] + r[i + 1][0]) * c; y += (r[i][1] + r[i + 1][1]) * c; }
  return [x / (3 * a), y / (3 * a)];
}
function areaOf(r) { let s = 0; for (let i = 0; i < r.length - 1; i++) s += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]; return Math.abs(s / 2); }

function divLimit(key) {
  const v = state.dongs.filter((d) => valid(d, key) && !d.hold).map((d) => Math.abs(d[key].v));
  const q = quantile(v, 0.97); const s = niceStep(q / 4);
  return Math.ceil(q / s) * s;
}
function seqRange(key) {
  const v = state.dongs.filter((d) => valid(d, key)).map((d) => d[key].v);
  return [Math.floor(quantile(v, 0.02) * 20) / 20, Math.ceil(quantile(v, 0.98) * 20) / 20];
}
function lisaCat(d, key) {
  const L = d[key]; if (!L) return null;
  return L[state.lisaLevel === "fdr" ? 0 : 1];
}
function fillFor(d, key, lim) {
  if (key.startsWith("lisa")) { const c = lisaCat(d, key); return c == null ? NODATA : LISA_COLOR[c.replace(" ", "_")]; }
  if (!valid(d, key)) return NODATA;
  if (IND[key].seq) { const [a, b] = lim; return rgb(ramp(SEQ, (d[key].v - a) / (b - a))); }
  const c = ramp(DIV, (d[key].v + lim) / (2 * lim));
  return rgb(d[key].sig === false ? lighten(c) : c);
}

function drawMaps() {
  const host = $("maps");
  const m = state.mode;
  const views = m === "pair" ? ["dLQ_exist", "RG"] : m === "lisa" ? ["lisa_dLQ", "lisa_RG"] : [m];
  host.className = `maps${views.length > 1 ? " pair" : ""}`;
  const titles = {
    pair: ["월세계약 LQ 변화와 전세 상대 상승률", "색은 값, 옅은 색은 90% 구간이 0을 포함하는 동입니다."],
    dLQ_all: ["ΔLQ (전체 계약)", "신규 단지 계약까지 포함한 값입니다. 기존 단지 기준과 비교해 보세요."],
    U: ["갱신요구권 사용률 U (시행 후 기간, 참고 지표)", "갱신 계약 중 '사용' 비율입니다. 갱신 계약 20건 이상인 동만 표시합니다."],
    lisa: ["국지적 Moran(LISA) 군집", state.lisaLevel === "fdr"
      ? "퀸 인접, 순열 99,999회, FDR 보정 기준입니다. 군집이 없어도 우연히 약 20개·19개(검정 동 수 405·371의 5%)는 p ≤ 0.05로 유의하게 나오며, FDR 보정 후에는 각 1개 동(ΔLQ 광희동, RG 신월5동)만 남습니다."
      : "보정 전 p ≤ 0.05 기준(탐색용)입니다. 군집이 없어도 우연히 약 20개·19개(검정 동 수 405·371의 5%)는 유의하게 나오며, FDR 보정 후에는 각 1개 동(광희동, 신월5동)만 남습니다."],
  };
  $("map-title").textContent = titles[m][0];
  $("map-note").textContent = titles[m][1];
  host.replaceChildren(...views.map((key) => mapBox(key)));
  drawLegend(views);
}

function mapBox(key) {
  const box = div("map-box");
  const isLisa = key.startsWith("lisa");
  const base = isLisa ? (key === "lisa_dLQ" ? "dLQ_exist" : "RG") : key;
  const title = isLisa ? `LISA: ${IND[base].short}` : IND[key].name;
  const mo = moranOf(base), mk = moranOf(base, "k");
  let sub = mo ? `Moran's I ${fx(mo.I, 3)} (퀸 인접, ${mo.p <= 0.001 ? "p ≤ 0.001" : `p = ${mo.p.toFixed(3)}`}) · k=6: ${fx(mk.I, 3)}` : "";
  if (isLisa) {
    const L = state.S.lisa[base], c = state.lisaLevel === "fdr" ? L.fdr : L.p05;
    sub = ["HH", "LL", "HL", "LH"].map((q) => `${q} ${c[q] || 0}`).join(" · ") + ` (${state.lisaLevel === "fdr" ? "FDR 보정" : "p ≤ 0.05"})`;
  }
  const h = document.createElement("h4"); h.textContent = title;
  box.append(h, div("sub", sub));
  const host = div("map"); box.append(host);
  requestAnimationFrame(() => renderMap(host, key));
  return box;
}

function renderMap(host, key) {
  const W = host.clientWidth, H = host.clientHeight; if (!W) return;
  const P = projector(W, H);
  const lim = key.startsWith("lisa") ? null : IND[key].seq ? seqRange(key) : divLimit(key);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": key });
  const defs = el("defs");
  const hid = `hatch-${key}`;
  const pat = el("pattern", { id: hid, width: 5, height: 5, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
  pat.append(el("rect", { width: 5, height: 5, fill: "rgba(255,255,255,.35)" }), el("line", { x1: 0, y1: 0, x2: 0, y2: 5, stroke: "#1d2629", "stroke-width": 1.4 }));
  defs.append(pat); svg.append(defs);
  const holds = [];
  let selPath = null;
  for (const f of state.geoDong.features) {
    const d = state.byCd.get(f.properties.adm_cd); if (!d) continue;
    const p = el("path", { d: pathD(f.geometry, P), fill: fillFor(d, key, lim), class: `dong${state.sel === d.cd ? " sel" : ""}`, tabindex: "0", role: "button", "aria-label": label(d) });
    p.addEventListener("pointermove", (ev) => tipShow(ev, tipLines(d, key)));
    p.addEventListener("pointerleave", tipHide);
    p.addEventListener("click", () => select(d.cd));
    p.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(d.cd); } });
    svg.append(p);
    if (state.sel === d.cd) selPath = p;
    if (d.hold) holds.push(el("path", { d: pathD(f.geometry, P), class: "hold", fill: `url(#${hid})` }));
  }
  const g = el("g");
  for (const f of state.geoGu.features) g.append(el("path", { d: pathD(f.geometry, P), class: "gu" }));
  svg.append(g, ...holds);
  if (selPath) svg.append(selPath);
  const labels = el("g");
  for (const f of state.geoGu.features) {
    const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
    const ring = polys.map((p) => p[0]).reduce((a, b) => (areaOf(b) > areaOf(a) ? b : a));
    const [cx, cy] = P(centroid(ring));
    labels.append(el("text", { x: cx, y: cy, class: "gu-label" }, f.properties.gu.replace(/구$/, "")));
  }
  svg.append(labels);
  host.replaceChildren(svg);
}

function tipLines(d, key) {
  const lines = [`${label(d)} (${d.region})`];
  if (key.startsWith("lisa")) {
    const base = key === "lisa_dLQ" ? "dLQ_exist" : "RG";
    const c = lisaCat(d, key);
    lines.push(c == null ? "LISA 계산 제외(자료 부족·해석 유보)" : `군집: ${c}`);
    if (valid(d, base)) lines.push(`${IND[base].short}: ${IND[base].fmt(d[base].v)}`);
  } else if (valid(d, key)) {
    const x = d[key];
    lines.push(`${IND[key].short}: ${IND[key].fmt(x.v)}`);
    if (x.lo != null) lines.push(`90% 구간: ${IND[key].fmt(x.lo)} ~ ${IND[key].fmt(x.hi)}${x.sig === false ? " (0 포함)" : ""}`);
    if (key === "U") lines.push(`U_upper: ${pct(d.U_upper)} · 갱신 ${fmtInt(d.n_renew)}건`);
    else if (key === "RG") lines.push(`매칭 묶음: 전 ${d.cells[0]} · 후 ${d.cells[1]}`);
    else lines.push(`계약: 전 ${fmtInt(d.N_pre)} · 후 ${fmtInt(d.N_post)}건`);
  } else lines.push("자료 부족(최소 건수 미달)");
  if (d.hold) lines.push("해석 유보");
  return lines;
}

function hatchSwatch() {
  const s = el("svg", { viewBox: "0 0 16 11" });
  const p = el("pattern", { id: "hatch-sw", width: 4, height: 4, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
  p.append(el("line", { x1: 0, y1: 0, x2: 0, y2: 4, stroke: "#1d2629", "stroke-width": 1.2 }));
  s.append(el("defs", {}, p), el("rect", { x: .5, y: .5, width: 15, height: 10, fill: "url(#hatch-sw)", stroke: "#1d2629" }));
  return s;
}
function swatch(color, text) { const s = span("sw", ""); const i = document.createElement("i"); i.style.background = color; s.append(i, text); return s; }

function drawLegend(views) {
  const lg = $("legend"); const items = [];
  const key = views[0];
  if (key.startsWith("lisa")) {
    for (const q of ["HH", "LL", "HL", "LH"]) items.push(swatch(LISA_COLOR[q], q));
    items.push(swatch(LISA_COLOR.유의하지_않음, "유의하지 않음"));
  } else {
    for (const k of views) {
      const box = div("ramp-box");
      const r = div("ramp");
      const cols = IND[k].seq ? SEQ : DIV;
      r.style.background = `linear-gradient(to right, ${cols.join(", ")})`;
      const t = div("ticks");
      if (IND[k].seq) { const [a, b] = seqRange(k); [a, (a + b) / 2, b].forEach((v) => t.append(span("", pct(v, 0)))); }
      else { // 양 끝은 97% 분위로 잘린 값까지 포함
        const L = divLimit(k);
        [-L, -L / 2, 0, L / 2, L].forEach((v, i) => t.append(span("", `${i === 0 ? "≤ " : i === 4 ? "≥ " : ""}${v === 0 ? "0" : IND[k].fmt(v)}`)));
      }
      box.append(span("", IND[k].short), r, t);
      if (!IND[k].seq) { const p = div("poles"); p.append(span("", `◀ ${IND[k].neg}`), span("", `${IND[k].pos} ▶`)); box.append(p); }
      items.push(box);
    }
    if (!IND[key].seq) {
      const c = ramp(DIV, 0.9);
      items.push(swatch(rgb(c), "90% 구간이 0 제외"), swatch(rgb(lighten(c)), "90% 구간이 0 포함"));
    }
  }
  items.push(swatch(NODATA, key.startsWith("lisa") ? "자료 부족(계산 제외)" : "자료 부족"));
  const h = span("sw", ""); h.append(hatchSwatch(), "해석 유보(잠원동·반포3동)"); items.push(h);
  lg.replaceChildren(...items);
}

// ---------- 선택한 동 ----------
function renderPanel() {
  const host = $("panel");
  const d = state.sel && state.byCd.get(state.sel);
  if (!d) { host.replaceChildren(Object.assign(document.createElement("p"), { className: "hint", textContent: "지도나 그래프에서 동을 누르면 이 자리에 그 동의 값이 나옵니다." })); return; }
  const head = div("panel-head");
  const nm = div("name"); nm.textContent = `${label(d)} `; nm.append(span("muted small", d.region));
  if (d.hold) nm.append(span("badge hold", "해석 유보"));
  for (const [k, n] of [["lisa_dLQ", "ΔLQ"], ["lisa_RG", "RG"]]) {
    const L = d[k]; if (L && L[0] !== "유의하지 않음") nm.append(span("badge lisa", `${n} ${L[0]} (FDR)`));
    else if (L && L[1] !== "유의하지 않음") nm.append(span("badge lisa", `${n} ${L[1]} (p≤0.05)`));
  }
  const close = Object.assign(document.createElement("button"), { className: "ghost", type: "button", textContent: "선택 해제" });
  close.addEventListener("click", () => select(d.cd));
  head.append(nm, close);
  const cell = (lab, key, sub) => {
    const c = div("cell"); c.append(div("label", lab));
    const x = d[key];
    const v = div("value", x && x.v != null ? IND[key].fmt(x.v) : "자료 부족");
    if (x && x.v != null && !IND[key].seq) v.classList.add(x.v > 0 ? "pos" : "neg");
    c.append(v, div("sub", x && x.v != null ? sub(x) : ""));
    return c;
  };
  const cells = div("cells");
  cells.append(
    cell("ΔLQ (기존 단지)", "dLQ_exist", (x) => `90% ${IND.dLQ_exist.fmt(x.lo)} ~ ${IND.dLQ_exist.fmt(x.hi)} · LQ ${d.LQ_pre ?? "–"} → ${d.LQ_post ?? "–"}`),
    cell("ΔLQ (전체 계약)", "dLQ_all", (x) => `90% ${IND.dLQ_all.fmt(x.lo)} ~ ${IND.dLQ_all.fmt(x.hi)} · 계약 ${fmtInt(d.N_pre)} → ${fmtInt(d.N_post)}`),
    cell("RG", "RG", (x) => `90% ${IND.RG.fmt(x.lo)} ~ ${IND.RG.fmt(x.hi)} · g ${signed(d.g_pre, 3)} → ${signed(d.g_post, 3)}`),
    cell("갱신요구권 사용률 U", "U", (x) => `90% ${pct(x.lo)} ~ ${pct(x.hi)} · U_upper ${pct(d.U_upper)} · 갱신 ${fmtInt(d.n_renew)}건`),
  );
  host.replaceChildren(head, cells);
}

// ---------- 산점도 ----------
function scatterFrame(host, xd, yd, opts = {}) {
  const W = host.clientWidth, H = host.clientHeight; if (!W) return null;
  const m = { l: 56, r: 16, t: 12, b: 44 };
  const xs = opts.log
    ? (v) => m.l + (Math.log(v) - Math.log(xd[0])) / (Math.log(xd[1]) - Math.log(xd[0])) * (W - m.l - m.r)
    : (v) => m.l + (v - xd[0]) / (xd[1] - xd[0]) * (W - m.l - m.r);
  const ys = (v) => H - m.b - (v - yd[0]) / (yd[1] - yd[0]) * (H - m.t - m.b);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}` });
  const grid = el("g", { class: "grid" }), axis = el("g", { class: "axis" });
  const xt = opts.xticks || ticks(xd[0], xd[1], 6), yt = ticks(yd[0], yd[1], 6);
  for (const v of xt) { grid.append(el("line", { x1: xs(v), x2: xs(v), y1: m.t, y2: H - m.b })); axis.append(el("text", { x: xs(v), y: H - m.b + 16, "text-anchor": "middle" }, (opts.xfmt || String)(v))); }
  for (const v of yt) { grid.append(el("line", { x1: m.l, x2: W - m.r, y1: ys(v), y2: ys(v) })); axis.append(el("text", { x: m.l - 6, y: ys(v) + 4, "text-anchor": "end" }, (opts.yfmt || String)(v))); }
  svg.append(grid, axis);
  svg.append(el("text", { class: "axis-title", x: (m.l + W - m.r) / 2, y: H - 6, "text-anchor": "middle" }, opts.xlab || ""));
  svg.append(el("text", { class: "axis-title", x: 14, y: (m.t + H - m.b) / 2, "text-anchor": "middle", transform: `rotate(-90 14 ${(m.t + H - m.b) / 2})` }, opts.ylab || ""));
  return { svg, xs, ys, W, H, m };
}
const padRange = (v, p = 0.06) => { const a = Math.min(...v), b = Math.max(...v), s = (b - a) * p || 0.01; return [a - s, b + s]; };
const sizeOf = (n) => 2.5 + 9 * Math.sqrt(n / 10000);

function drawScatter() {
  const host = $("scatter");
  const cfg = {
    dlq_rg: { x: "dLQ_exist", y: "RG", title: "행정동별 ΔLQ(기존 단지)와 RG" },
    u_rg: { x: "U", y: "RG", title: "갱신요구권 사용률 U와 RG" },
    u_dlq: { x: "U", y: "dLQ_exist", title: "갱신요구권 사용률 U와 ΔLQ(기존 단지)" },
  }[state.sc];
  $("sc-title").textContent = cfg.title;
  const D = state.dongs.filter((d) => !d.hold && valid(d, cfg.x) && valid(d, cfg.y));
  const X = D.map((d) => d[cfg.x].v), Y = D.map((d) => d[cfg.y].v);
  const xd = padRange(X), yd = padRange(Y);
  const F = scatterFrame(host, xd, yd, {
    xlab: IND[cfg.x].name, ylab: IND[cfg.y].short,
    xfmt: cfg.x === "U" ? (v) => pct(v, 0) : (v) => fx(v, 1), yfmt: (v) => (cfg.y === "RG" ? fx(v, 2) : fx(v, 1)),
  });
  if (!F) return;
  const { svg, xs, ys, W, H, m } = F;
  const xref = cfg.x === "U" ? quantile(X, 0.5) : 0;
  svg.append(el("line", { class: cfg.x === "U" ? "ref" : "zero", x1: xs(xref), x2: xs(xref), y1: m.t, y2: H - m.b }));
  svg.append(el("line", { class: "zero", x1: m.l, x2: W - m.r, y1: ys(0), y2: ys(0) }));
  if (cfg.x === "U") svg.append(el("text", { class: "quad", x: xs(xref) + 4, y: m.t + 12 }, "U 중위"));
  // 사분면 개수
  const q = { pp: 0, pn: 0, np: 0, nn: 0 };
  D.forEach((d) => { q[(d[cfg.x].v > xref ? "p" : "n") + (d[cfg.y].v > 0 ? "p" : "n")]++; });
  const qx = cfg.x === "U" ? ["U 낮음", "U 높음"] : ["전세 쪽", "월세 쪽"];
  const qy = cfg.y === "RG" ? ["상승 둔화", "상승 가속"] : ["전세 쪽", "월세 쪽"];
  // 무관할 때의 기대 수 = n·p_x·p_y
  const n = D.length, px = (q.pp + q.pn) / n, py = (q.pp + q.np) / n;
  const ex = { pp: n * px * py, pn: n * px * (1 - py), np: n * (1 - px) * py, nn: n * (1 - px) * (1 - py) };
  const corner = (x, y, anchor, k, a, b) => {
    const tx = el("text", { class: "quad", x, y, "text-anchor": anchor });
    const lines = narrow ? [`${a} · ${b}`, `${q[k]}개 동`, `(무관할 때 ${Math.round(ex[k])})`]
      : [`${a} · ${b}`, `${q[k]}개 동 (무관할 때 ${Math.round(ex[k])})`];
    lines.forEach((s, i) => tx.append(el("tspan", { x, dy: i ? "1.25em" : null }, s)));
    svg.append(tx);
  };
  const narrow = W < 560, bottomY = H - m.b - (narrow ? 36 : 22);
  corner(m.l + 6, m.t + 12, "start", "np", qx[0], qy[1]);
  corner(W - m.r - 6, m.t + 12, "end", "pp", qx[1], qy[1]);
  corner(m.l + 6, bottomY, "start", "nn", qx[0], qy[0]);
  corner(W - m.r - 6, bottomY, "end", "pn", qx[1], qy[0]);
  const g = el("g");
  [...D].sort((a, b) => b.N_pre + b.N_post - a.N_pre - a.N_post).forEach((d) => {
    const c = el("circle", { cx: xs(d[cfg.x].v), cy: ys(d[cfg.y].v), r: sizeOf(d.N_pre + d.N_post) * Math.min(1, W / 800 + 0.25), fill: REGION_COLOR[d.region], "fill-opacity": .72, class: `dot${state.sel === d.cd ? " sel" : ""}` });
    c.addEventListener("pointermove", (ev) => tipShow(ev, [`${label(d)} (${d.region})`, `${IND[cfg.x].short}: ${IND[cfg.x].fmt(d[cfg.x].v)}`, `${IND[cfg.y].short}: ${IND[cfg.y].fmt(d[cfg.y].v)}`, `계약 ${fmtInt(d.N_pre + d.N_post)}건`]));
    c.addEventListener("pointerleave", tipHide);
    c.addEventListener("click", () => select(d.cd));
    g.append(c);
  });
  svg.append(g);
  const sel = g.querySelector(".sel"); if (sel) g.append(sel);
  host.replaceChildren(svg);
  const r = corr(X, Y), rs = spearman(X, Y);
  $("sc-stat").replaceChildren("행정동 ", Object.assign(document.createElement("b"), { textContent: D.length }), "개 · Pearson r = ",
    Object.assign(document.createElement("b"), { textContent: fx(r) }), " · Spearman ρ = ", Object.assign(document.createElement("b"), { textContent: fx(rs) }),
    " · 점 크기 = 두 기간 계약 수 · 자료 부족·해석 유보 제외");
  $("sc-legend").replaceChildren(...state.S.region_order.map((rg) => { const s = span("", ""); const i = document.createElement("i"); i.style.background = REGION_COLOR[rg]; s.append(i, rg); return s; }));
  const same = q.pp + q.nn, sameExp = Math.round(ex.pp + ex.nn);
  const notes = {
    dlq_rg: `같은 방향(둘 다 양수 또는 둘 다 음수)인 동은 ${same}개로 두 지표가 무관할 때의 기대 ${sameExp}개보다 조금 많지만, 반대 방향인 동도 ${q.pn + q.np}개에 이른다. 월세 쪽으로 기운 동과 전세 상승 속도가 빨라진 동은 일부만 겹친다.`,
    u_rg: "갱신요구권 사용률이 높은 동과 전세 상승 속도가 빨라진 동 사이에 뚜렷한 관계가 없다. 사분면별 동 수도 두 지표가 무관할 때의 기대 수와 비슷하다.",
    u_dlq: "갱신요구권 사용률과 월세 쪽으로 기운 정도 사이에도 관계가 거의 없다. 사분면별 동 수도 무관할 때의 기대 수와 비슷하다.",
  };
  $("sc-note").textContent = notes[state.sc];
}

// ---------- 권역별 분포 ----------
function hashJitter(cd) { let h = 0; for (const c of cd) h = (h * 31 + c.charCodeAt(0)) % 997; return h / 997 - 0.5; }
function drawBox() {
  const key = state.box, host = $("box");
  $("box-title").textContent = `권역별 ${IND[key].short}`;
  const W = host.clientWidth, H = host.clientHeight; if (!W) return;
  const D = state.dongs.filter((d) => !d.hold && valid(d, key));
  const regs = state.S.region_order;
  const m = { l: 52, r: 12, t: 12, b: 62 };
  const vals = D.map((d) => d[key].v), yd = padRange(vals, 0.04);
  const bw = (W - m.l - m.r) / regs.length;
  const xs = (i) => m.l + bw * (i + 0.5);
  const ys = (v) => H - m.b - (v - yd[0]) / (yd[1] - yd[0]) * (H - m.t - m.b);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}` });
  const grid = el("g", { class: "grid" }), axis = el("g", { class: "axis" });
  for (const v of ticks(yd[0], yd[1], 6)) {
    grid.append(el("line", { x1: m.l, x2: W - m.r, y1: ys(v), y2: ys(v) }));
    axis.append(el("text", { x: m.l - 6, y: ys(v) + 4, "text-anchor": "end" }, key === "U" ? pct(v, 0) : key === "RG" ? fx(v, 2) : fx(v, 1)));
  }
  svg.append(grid, axis);
  if (key !== "U") svg.append(el("line", { class: "zero", x1: m.l, x2: W - m.r, y1: ys(0), y2: ys(0) }));
  const meds = [];
  regs.forEach((rg, i) => {
    const pts = D.filter((d) => d.region === rg), v = pts.map((d) => d[key].v);
    const [q1, q2, q3] = [0.25, 0.5, 0.75].map((q) => quantile(v, q)), iqr = q3 - q1;
    const lo = Math.min(...v.filter((x) => x >= q1 - 1.5 * iqr)), hi = Math.max(...v.filter((x) => x <= q3 + 1.5 * iqr));
    const cx = xs(i), w = Math.min(46, bw * 0.45);
    const col = rgb(lighten(hexRgb(REGION_COLOR[rg])));
    svg.append(el("line", { class: "whisk", x1: cx, x2: cx, y1: ys(lo), y2: ys(hi) }));
    svg.append(el("rect", { class: "box", x: cx - w / 2, y: ys(q3), width: w, height: Math.max(1, ys(q1) - ys(q3)), fill: col }));
    pts.forEach((d) => {
      const c = el("circle", { cx: cx + hashJitter(d.cd) * bw * 0.6, cy: ys(d[key].v), r: state.sel === d.cd ? 4.5 : 2.4, fill: REGION_COLOR[rg], "fill-opacity": .7, class: `dot${state.sel === d.cd ? " sel" : ""}` });
      c.addEventListener("pointermove", (ev) => tipShow(ev, [label(d), `${IND[key].short}: ${IND[key].fmt(d[key].v)}`]));
      c.addEventListener("pointerleave", tipHide);
      c.addEventListener("click", () => select(d.cd));
      svg.append(c);
    });
    svg.append(el("line", { class: "med", x1: cx - w / 2, x2: cx + w / 2, y1: ys(q2), y2: ys(q2) }));
    axis.append(el("text", { x: cx, y: H - m.b + 16, "text-anchor": "middle" }, rg));
    if (bw >= 90) axis.append(el("text", { x: cx, y: H - m.b + 31, "text-anchor": "middle" }, `중위 ${IND[key].fmt(q2)}`));
    axis.append(el("text", { x: cx, y: H - m.b + (bw >= 90 ? 46 : 31), "text-anchor": "middle" }, `${pts.length}개 동`));
    meds.push([rg, q2]);
  });
  host.replaceChildren(svg);
  const notes = {
    dLQ_exist: "서북·서남권에서 월세 쪽으로, 도심권에서 전세 쪽으로 기운 동이 많다. 시행 전 LQ와 ΔLQ의 상관은 −0.60이지만, 기준과 변화를 서로 다른 해로 계산하면 −0.37로 약해진다. 남은 음의 상관은 시행 전 월세 비중이 높던 동이 서울 평균 쪽으로 수렴했음을 보여주며, 도심권의 낮은 값도 이 수렴과 겹친다. 수렴의 원인은 이 자료로 알 수 없다.",
    RG: "서북·서남권의 중위값이 높고 동남권은 0 근처이다. 동 단위 RG는 대부분 0과 구별되지 않으므로 권역 비교로 읽는다.",
    U: "권역 사이 차이가 거의 없다.",
  };
  $("box-note").textContent = notes[key];
}

// ---------- 자치구 RG ----------
function drawForest() {
  const host = $("forest"); const W = host.clientWidth, H = host.clientHeight; if (!W) return;
  const rows = [...state.S.gu_rg].sort((a, b) => b.RG - a.RG);
  const m = { l: 74, r: 54, t: 8, b: 34 };
  const lo = Math.min(...rows.map((r) => r.lo)), hi = Math.max(...rows.map((r) => r.hi));
  const xd = padRange([lo, hi], 0.05);
  const xs = (v) => m.l + (v - xd[0]) / (xd[1] - xd[0]) * (W - m.l - m.r);
  const rh = (H - m.t - m.b) / rows.length, ys = (i) => m.t + rh * (i + 0.5);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}` });
  const grid = el("g", { class: "grid" }), axis = el("g", { class: "axis" });
  for (const v of ticks(xd[0], xd[1], 5)) { grid.append(el("line", { x1: xs(v), x2: xs(v), y1: m.t, y2: H - m.b })); axis.append(el("text", { x: xs(v), y: H - m.b + 16, "text-anchor": "middle" }, fx(v, 2))); }
  svg.append(grid, axis, el("line", { class: "zero", x1: xs(0), x2: xs(0), y1: m.t, y2: H - m.b }));
  svg.append(el("text", { class: "axis-title", x: (m.l + W - m.r) / 2, y: H - 2, "text-anchor": "middle" }, "RG (자치구로 모은 묶음의 중위값, 90% 구간)"));
  rows.forEach((r, i) => {
    const y = ys(i), col = REGION_COLOR[r.region], sig = r.lo > 0 || r.hi < 0;
    const g = el("g");
    g.append(el("line", { class: "ci", x1: xs(r.lo), x2: xs(r.hi), y1: y, y2: y, stroke: sig ? col : rgb(lighten(hexRgb(col))) }));
    g.append(el("circle", { cx: xs(r.RG), cy: y, r: 4.2, fill: col, stroke: "#fff", "stroke-width": 1 }));
    g.append(el("text", { class: "row-label", x: m.l - 8, y: y + 4 }, r.gu + (r.note ? " †" : "")));
    g.append(el("text", { class: "row-val", x: W - m.r + 6, y: y + 4 }, signed(r.RG, 3)));
    g.addEventListener("pointermove", (ev) => tipShow(ev, [`${r.gu} (${r.region})`, `RG ${signed(r.RG, 3)} (90% ${signed(r.lo, 3)} ~ ${signed(r.hi, 3)})`,
      `시행 전 상승률 ${signed(r.g_pre, 3)} → 시행 후 ${signed(r.g_post, 3)}`, ...(r.note ? [r.note] : [])]));
    g.addEventListener("pointerleave", tipHide);
    svg.append(g);
  });
  host.replaceChildren(svg);
  const gp = rows.map((r) => r.g_pre), rg = rows.map((r) => r.RG);
  $("forest-stat").textContent = "색은 권역이고, 옅은 선은 90% 구간이 0을 포함하는 구입니다. †는 해석 유보 동(잠원동·반포3동)이 들어 있는 구입니다.";
  $("forest-note").textContent = `시행 전 상승률(g_전)과 RG의 자치구 상관은 r = ${fx(corr(gp, rg))}이다. 시행 전 상승률이 높았던 강남·송파·강서의 RG가 낮게 나온 데에는 평균으로의 회귀가 섞였을 수 있다(RG에는 −g_전이 들어 있어 어느 정도의 음의 상관은 계산상 생긴다).`;
}

// ---------- 월별 추이 ----------
function drawMonthly() {
  const host = $("monthly"); const W = host.clientWidth, H = host.clientHeight; if (!W) return;
  const M = state.S.monthly; const n = M.length;
  const m = { l: 56, r: 14, t: 18, b: 30, gap: 30 };
  const ph = (H - m.t - m.b - m.gap) / 2;
  const xs = (i) => m.l + (i + 0.5) / n * (W - m.l - m.r);
  const idx = (ym) => M.findIndex((x) => x.ym === ym);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}` });
  const iLaw = idx("202008") - 0.5, iRep = idx("202106") - 0.5, g0 = idx("202008") - 0.5, g1 = idx("202207") + 0.5;
  const panels = [
    { key: "n", lab: "월별 계약 수(건)", fmt: (v) => fmtInt(v), col: "#2a78d6", top: m.t },
    { key: "share", lab: "월세 포함 비중(%)", fmt: (v) => `${v.toFixed(0)}%`, col: "#b3261e", top: m.t + ph + m.gap },
  ];
  for (const p of panels) {
    const v = M.map((x) => x[p.key]), yd = padRange(v, 0.08);
    const ys = (val) => p.top + ph - (val - yd[0]) / (yd[1] - yd[0]) * ph;
    svg.append(el("rect", { class: "gap-band", x: xs(g0), y: p.top, width: xs(g1) - xs(g0), height: ph }));
    const grid = el("g", { class: "grid" }), axis = el("g", { class: "axis" });
    for (const t of ticks(yd[0], yd[1], 4)) { grid.append(el("line", { x1: m.l, x2: W - m.r, y1: ys(t), y2: ys(t) })); axis.append(el("text", { x: m.l - 6, y: ys(t) + 4, "text-anchor": "end" }, p.fmt(t))); }
    svg.append(grid, axis);
    svg.append(el("text", { class: "axis-title", x: m.l, y: p.top - 5 }, p.lab));
    for (const [j, [i, t]] of [[iLaw, "법 시행"], [iRep, "신고제 시행"]].entries()) {
      svg.append(el("line", { class: "vline", x1: xs(i), x2: xs(i), y1: p.top, y2: p.top + ph }));
      if (p.key === "n") svg.append(el("text", { class: "vlabel", x: xs(i) + 4, y: p.top + 12 + j * 14 }, t));
    }
    svg.append(el("path", { class: "series", stroke: p.col, d: v.map((val, i) => `${i ? "L" : "M"}${xs(i).toFixed(1)},${ys(val).toFixed(1)}`).join("") }));
    p.ys = ys;
  }
  const axis = el("g", { class: "axis" });
  const narrow = W < 560;
  M.forEach((x, i) => { if (x.ym.endsWith("08") || (!narrow && x.ym.endsWith("02"))) axis.append(el("text", { x: xs(i), y: H - 10, "text-anchor": "middle" }, `${x.ym.slice(2, 4)}.${x.ym.slice(4)}`)); });
  svg.append(axis);
  // 마우스 위치의 달
  const cross = el("line", { class: "cross", y1: m.t, y2: H - m.b, visibility: "hidden" });
  const hit = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" });
  hit.addEventListener("pointermove", (ev) => {
    const r = svg.getBoundingClientRect(); const x = (ev.clientX - r.left) * (W / r.width);
    const i = Math.max(0, Math.min(n - 1, Math.round((x - m.l) / (W - m.l - m.r) * n - 0.5)));
    cross.setAttribute("x1", xs(i)); cross.setAttribute("x2", xs(i)); cross.setAttribute("visibility", "visible");
    tipShow(ev, [`${M[i].ym.slice(0, 4)}.${M[i].ym.slice(4)}`, `계약 ${fmtInt(M[i].n)}건`, `월세 포함 ${M[i].share.toFixed(1)}%`, M[i].seg]);
  });
  hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); tipHide(); });
  svg.append(cross, hit);
  host.replaceChildren(svg);
  const per = state.S.period.filter((p) => p.yr === "전체");
  const pre = per.find((p) => p.period === "시행 전"), post = per.find((p) => p.period === "시행 후");
  $("mon-stat").textContent = `월세 포함 비중: 시행 전 ${pre.share.toFixed(1)}% → 시행 후 ${post.share.toFixed(1)}%. 회색은 진단에만 쓴 사이 기간(2020.8.~2022.7.)입니다.`;
  const pl = state.S.placebo;
  const f = (s) => pl.find((p) => p.name.startsWith(s)).diff;
  $("mon-note").textContent = `월세 포함 비중은 법 시행 직후부터 오르기 시작해 신고제 이전 10개월(2020.8.~2021.5.) 평균이 35.6%였다. 신고제 직전·직후 6개월의 차이는 ${signed(f("신고제 시점"), 1)}%p이나, 같은 계절 구성의 비교 구간에서도 ${signed(f("위약 1"), 1)}%p, ${signed(f("위약 2"), 1)}%p의 변화가 있어 신고제 고유의 변화는 분리하지 못했다.`;
}

// ---------- R – ΔLQ ----------
function drawR() {
  const key = state.r, host = $("rscatter");
  const D = state.dongs.filter((d) => !d.hold && d[key]);
  const X = D.map((d) => d[key][0]), Y = D.map((d) => d[key][1]);
  const xd = [Math.min(0.3, Math.min(...X) * 0.95), Math.max(...X) * 1.08], yd = padRange(Y);
  const xt = [0.3, 0.5, 0.7, 1, 1.5, 2, 3, 5, 10].filter((v) => v >= xd[0] && v <= xd[1]);
  const F = scatterFrame(host, xd, yd, { log: true, xticks: xt, xfmt: (v) => `${v}`, yfmt: (v) => fx(v, 1),
    xlab: "신고 증가배수 R (로그 축, 1 = 서울 평균)", ylab: key === "R_exist" ? "ΔLQ (준공 2017년 이하)" : "ΔLQ (전체 계약)" });
  if (!F) return;
  const { svg, xs, ys, W, H, m } = F;
  svg.append(el("line", { class: "zero", x1: xs(1), x2: xs(1), y1: m.t, y2: H - m.b }), el("line", { class: "zero", x1: m.l, x2: W - m.r, y1: ys(0), y2: ys(0) }));
  D.forEach((d) => {
    const c = el("circle", { cx: xs(d[key][0]), cy: ys(d[key][1]), r: state.sel === d.cd ? 5 : 3, fill: "#2a78d6", "fill-opacity": .65, class: `dot${state.sel === d.cd ? " sel" : ""}` });
    c.addEventListener("pointermove", (ev) => tipShow(ev, [label(d), `R ${d[key][0].toFixed(2)}`, `ΔLQ ${signed(d[key][1], 2)}`]));
    c.addEventListener("pointerleave", tipHide);
    c.addEventListener("click", () => select(d.cd));
    svg.append(c);
  });
  host.replaceChildren(svg);
  const r = corr(X, Y), rs = spearman(X, Y);
  const rr = (k) => { const P = state.dongs.filter((d) => !d.hold && d[k]); return corr(P.map((d) => d[k][0]), P.map((d) => d[k][1])); };
  // 숫자 상자는 선택한 기준의 r, 설명에는 다른 기준의 r을 함께 적는다
  const exist = key === "R_exist";
  $("r-kpi").replaceChildren(div("label", `신고 증가배수 R × ΔLQ (${exist ? "준공 2017년 이하" : "전체 계약"})`), div("value", `r = ${fx(rr(key))}`),
    div("sub", exist
      ? `기존 주택(준공 2017년 이하) 기준. 전체 계약 기준은 r = ${fx(rr("R_all"))}로, 차이는 신축 입주에서 나온다.`
      : `전체 계약 기준. 기존 주택(준공 2017년 이하)만 보면 r = ${fx(rr("R_exist"))}로, 차이는 신축 입주에서 나온다.`));
  $("r-stat").textContent = `${D.length}개 동 · Pearson r = ${fx(r)} · Spearman ρ = ${fx(rs)}`;
  $("r-note").textContent = key === "R_exist"
    ? "기존 주택만 보면 신고가 많이 늘어난 동과 ΔLQ 사이에 관계가 거의 없다. 기존 단지 기준 ΔLQ를 주 지표로 삼은 근거이다."
    : "전체 계약 기준에서는 약한 양의 상관이 보이는데, R이 큰 동(항동, 개포1동 등)은 신축 단지 입주로 계약 수와 월세 비중이 함께 늘어난 곳이다.";
}

// ---------- 인상률 분포 ----------
function drawHist() {
  const host = $("hist"); const W = host.clientWidth, H = host.clientHeight; if (!W) return;
  const Hs = state.S.inc_hist, E = Hs.edges, nb = E.length - 1;
  const dens = (cnt, n) => cnt.map((c) => c / n * 100); // 구간(1%p)당 비율(%)
  const used = dens(Hs.used.counts, Hs.used.n), blank = dens(Hs.blank.counts, Hs.blank.n), over = dens(Hs.used_over5.counts, Hs.used.n);
  const ymax = Math.max(...used, ...blank) * 1.08;
  const m = { l: 48, r: 12, t: 10, b: 40 };
  const xs = (v) => m.l + (v - E[0]) / (E[nb] - E[0]) * (W - m.l - m.r);
  const ys = (v) => H - m.b - v / ymax * (H - m.t - m.b);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}` });
  const grid = el("g", { class: "grid" }), axis = el("g", { class: "axis" });
  for (const v of ticks(0, ymax, 5)) { grid.append(el("line", { x1: m.l, x2: W - m.r, y1: ys(v), y2: ys(v) })); axis.append(el("text", { x: m.l - 6, y: ys(v) + 4, "text-anchor": "end" }, `${v}%`)); }
  const narrow = W < 560; // 좁은 화면은 5% 눈금 생략(세로선에 '5% 상한' 표시)
  for (const v of narrow ? [-0.2, -0.1, 0, 0.1, 0.2, 0.3, 0.4] : [-0.2, -0.1, 0, 0.05, 0.1, 0.2, 0.3, 0.4]) axis.append(el("text", { x: xs(v), y: H - m.b + 16, "text-anchor": "middle" }, `${Math.round(v * 100)}%`));
  svg.append(grid, axis);
  svg.append(el("text", { class: "axis-title", x: (m.l + W - m.r) / 2, y: H - 4, "text-anchor": "middle" }, narrow ? "보증금 인상률(양끝은 끝 구간에 합침)" : "보증금 인상률 (deposit / preDeposit − 1, 양끝은 끝 구간에 합침)"));
  over.forEach((v, i) => { if (v > 0) svg.append(el("rect", { x: xs(E[i]), y: ys(v), width: xs(E[i + 1]) - xs(E[i]), height: ys(0) - ys(v), fill: "#86b6ef" })); });
  const step = (arr) => arr.map((v, i) => `${i ? "L" : "M"}${xs(E[i]).toFixed(1)},${ys(v).toFixed(1)}H${xs(E[i + 1]).toFixed(1)}`).join("");
  svg.append(el("path", { class: "series", stroke: "#eb6834", d: step(blank) }), el("path", { class: "series", stroke: "#2a78d6", d: step(used) }));
  svg.append(el("line", { class: "vline", x1: xs(0.05), x2: xs(0.05), y1: m.t, y2: H - m.b }));
  svg.append(el("text", { class: "vlabel", x: xs(0.05) + 18, y: m.t + 12 }, "5% 상한"));
  const hit = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" });
  hit.addEventListener("pointermove", (ev) => {
    const r = svg.getBoundingClientRect(); const x = E[0] + ((ev.clientX - r.left) * (W / r.width) - m.l) / (W - m.l - m.r) * (E[nb] - E[0]);
    const i = Math.max(0, Math.min(nb - 1, Math.floor((x - E[0]) / 0.01)));
    tipShow(ev, [`인상률 ${Math.round((E[i] + 0.005) * 100)}% 구간`, `사용 ${used[i].toFixed(1)}%`, `빈 값 ${blank[i].toFixed(1)}%`]);
  });
  hit.addEventListener("pointerleave", tipHide);
  svg.append(hit);
  host.replaceChildren(svg);
  $("hist-stat").textContent = `사용 ${fmtInt(Hs.used.n)}건(중위 ${pct(Hs.used.median)}, 5% 초과 ${pct(Hs.used.over5)}, 인하 ${pct(Hs.used.down)}) · 빈 값 ${fmtInt(Hs.blank.n)}건(중위 ${pct(Hs.blank.median)}, 5% 초과 ${pct(Hs.blank.over5)}, 정확히 5% ${pct(Hs.blank.at5)})`;
  const lg = (cls, color, t) => { const s = span("", ""); const i = document.createElement("i"); i.className = cls; if (cls === "line") i.style.borderColor = color; else i.style.background = color; s.append(i, t); return s; };
  $("hist-legend").replaceChildren(lg("line", "#2a78d6", "'사용'"), lg("line", "#eb6834", "'빈 값'"), lg("sq", "#86b6ef", "'사용' 중 5% 초과(원인 확인 필요)"));
  $("hist-note").textContent = "'사용' 계약은 인상이 5%에서 멈추고, '빈 값' 계약은 40% 이상이 5%를 넘는다. 두 분포가 달라 빈 값을 미사용으로 보는 해석과 맞는다. 빈 값 중 정확히 5% 인상은 사용 표시가 빠졌을 수 있어 U_upper에 넣었다. 2023~2024년 전세가 하락기에는 권리를 행사하면서 보증금을 낮춘 갱신도 많다.";
  const R = state.S.renewal;
  const k = (l, v, s) => { const x = div("kpi"); x.append(div("label", l), div("value", v), div("sub", s)); return x; };
  $("u-kpis").replaceChildren(
    k("갱신요구권 사용률 U", pct(R.used / R.renew), `갱신 ${fmtInt(R.renew)}건 중 '사용' ${fmtInt(R.used)}건`),
    k("U_upper", pct(R.U_upper_seoul), "빈 값 중 정확히 5% 인상까지 '사용'으로 본 값"),
    k("갱신 비율 REN", pct(R.renew / (R.renew + R.new)), "계약구분이 확인된 계약 중 갱신"),
    k("계약구분 빈 값", pct(R.blank / R.n), `시행 후 ${fmtInt(R.n)}건 중(공공임대 제외)`),
  );
}

// ---------- 표 ----------
function renderTables() {
  const mt = $("moran-table");
  const inds = ["dLQ_all", "dLQ_exist", "RG", "U"];
  const head = ["지표", "동 수", "I (퀸 인접)", "p", "I (k=6)", "p"];
  const rows = inds.map((k) => { const q = moranOf(k), n = moranOf(k, "k"); return [IND[k].short, q.n, fx(q.I, 3), q.p.toFixed(3), fx(n.I, 3), n.p.toFixed(3)]; });
  fill(mt, head, rows);
  const pt = $("prep-table");
  const P = state.S.preprocess, max = Math.max(...P.map((p) => p.n));
  const prow = P.map((p) => {
    const bar = document.createElement("span"); bar.className = "cellbar"; bar.style.width = `${(p.n / max) * 80}px`;
    const f = p.flag[0] == null ? "" : `${fmtInt(p.flag[0])} / ${fmtInt(p.flag[1])}`;
    return [p.step, { left: true, text: p.rule }, [fmtInt(p.n), bar], f];
  });
  fill(pt, ["단계", "처리 기준", "남은 건수", "표시(시행 전 / 후)"], prow);
  renderStock();
}
function renderStock() {
  const T = state.S.stock_corr.filter((r) => r.ind !== "LQ_pre(참고)");
  const feats = [...new Set(T.map((r) => r.feat))];
  const table = $("stock-table");
  const th = document.createElement("thead"), tr = document.createElement("tr");
  ["재고 특성", "ΔLQ (기존 단지)", "RG"].forEach((h) => { const c = document.createElement("th"); c.textContent = h; tr.append(c); });
  th.append(tr);
  const tb = document.createElement("tbody");
  for (const f of feats) {
    const row = document.createElement("tr");
    const c0 = document.createElement("td"); c0.className = "left"; c0.textContent = f; row.append(c0);
    for (const ind of ["dLQ_exist", "RG"]) {
      const r = T.find((x) => x.feat === f && x.ind === ind);
      const td = document.createElement("td");
      const sig = r.p_lo > 0 || r.p_hi < 0;
      const c = ramp(DIV, (Math.max(-0.7, Math.min(0.7, r.p)) + 0.7) / 1.4);
      td.style.background = rgb(sig ? c : lighten(lighten(c)));
      if (sig && Math.abs(r.p) > 0.4) td.classList.add("dark");
      td.append(Object.assign(document.createElement("b"), { textContent: signed(r.p, 2) }), document.createElement("br"),
        span("ci-txt", `[${signed(r.p_lo, 2)}, ${signed(r.p_hi, 2)}]`));
      // 다른 그림과 같은 툴팁(브라우저 기본 title 툴팁은 늦게 뜨거나 안 뜰 수 있음)
      const lines = [`${f} × ${ind === "RG" ? "RG" : "ΔLQ(기존 단지)"}`,
        `Pearson ${signed(r.p, 2)} [${signed(r.p_lo, 2)}, ${signed(r.p_hi, 2)}]`,
        `Spearman ${signed(r.s, 2)} [${signed(r.s_lo, 2)}, ${signed(r.s_hi, 2)}]`,
        `${r.n}개 동 · 90% 구간이 0을 ${sig ? "포함하지 않음" : "포함"}`];
      td.classList.add("hov");
      td.tabIndex = 0;
      td.addEventListener("pointermove", (ev) => tipShow(ev, lines));
      td.addEventListener("pointerleave", tipHide);
      td.addEventListener("focus", () => { const b = td.getBoundingClientRect(); tipShow({ clientX: b.right, clientY: b.top }, lines); });
      td.addEventListener("blur", tipHide);
      row.append(td);
    }
    tb.append(row);
  }
  table.replaceChildren(th, tb);
}
function fill(table, head, rows) {
  const th = document.createElement("thead"), tr = document.createElement("tr");
  head.forEach((h) => { const c = document.createElement("th"); c.textContent = h; tr.append(c); }); th.append(tr);
  const tb = document.createElement("tbody");
  rows.forEach((r) => {
    const row = document.createElement("tr");
    r.forEach((v) => {
      const td = document.createElement("td");
      if (Array.isArray(v)) td.append(...v);
      else if (v && typeof v === "object") { td.className = "left"; td.textContent = v.text; }
      else td.textContent = v;
      row.append(td);
    });
    tb.append(row);
  });
  table.replaceChildren(th, tb);
}
