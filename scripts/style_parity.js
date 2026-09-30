#!/usr/bin/env node
'use strict';
/* 标准稿逐组件渲染差异比对（style parity）。
 * 标准 = docs/reference/style-draft-2026-09-27.html（Ray 指定的 html）；线上 = 本机 aistudy。
 * 对每屏逐组件比对计算样式 + 几何；差异 != 0 则 exit 1。
 * 用法： node scripts/style_parity.js [--base http://127.0.0.1:5003] [--draft /path/draft.html] [--verbose]
 */
const { execFileSync } = require('child_process');
const fs = require('fs'); const os = require('os'); const path = require('path');
const ROOT = path.resolve(__dirname, '..');
const AB = process.env.AGENT_BROWSER || '/Users/xicheng/.nvm/versions/node/v22.22.0/bin/agent-browser';
const argv = process.argv.slice(2);
const argOf = (k, d) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : d; };
const BASE = argOf('--base', process.env.UI_AUDIT_BASE || 'http://127.0.0.1:5003').replace(/\/$/, '');
const DRAFT = argOf('--draft', path.join(ROOT, 'docs/reference/style-draft-2026-09-27.html'));
const VERBOSE = argv.includes('--verbose');
const SESSION = 'style-parity-' + process.pid;
const PROFILE = fs.mkdtempSync(path.join(os.tmpdir(), 'ab-parity-'));
const W = 390, H = 900;
function ab(a) { return execFileSync(AB, ['--session', SESSION, '--profile', PROFILE, ...a], { encoding: 'utf8', maxBuffer: 1 << 24, env: { ...process.env, HOME: process.env.HOME || '/Users/xicheng' } }); }
function sleepMs(ms) { const t = Date.now(); while (Date.now() - t < ms) {} }
function ev(expr) { const out = String(ab(['eval', expr])).trim(); try { return JSON.parse(out.replace(/^"|"$/g, '').replace(/\\"/g, '"').replace(/\\\\n/g, '\n')); } catch (e) { return null; } }
/* 组件映射：屏 → [说明, 标准稿选择器, 线上选择器] */
const MAP = {
  progress: [
    ['学科掌握度标签', '.feature .mlabel', '.dcard .hero .k'],
    ['学科掌握度数字', '.bignum', '.dcard .hero .v'],
    ['三格容器', '.stats', '.dcard .grid'],
    ['三格单元', '.stats>div', '.dcard .grid>div'],
    ['区块小标题', '.sectitle', '.sec-title'],
    ['章节行', '.progline', '.chapter'],
    ['章节标题', '.progline .nm', '.chapter .nm'],
    ['章节名副行', '.progline .nm em', '.chapter .nm em'],
    ['章节进度条', '.progline .bar', '.chapter-bar'],
    ['章节条标签', '.progline .mname', '.chapter-bar-row>span'],
  ],
  quiz: [
    ['区块小标题', '.sectitle', '.sec-title'],
    ['行块', '.row', '.qcard'],
    ['行标题', '.row b', '.qcard .meta .t'],
    ['行副标题', '.row .l span', '.qcard .meta .s'],
    ['主按钮', '.primary', 'text=一键生成巩固练习'],
  ],
  knowledge: [
    ['闪卡外框', '.kc-card', '.kc-card'],
    ['卡面', '.kc-face', '.kc-face'],
    ['提示行', '.kc-hint', '.kc-hint'],
    ['主按钮', '.btn', 'text=继续'],
  ],
  learn: [
    ['任务行', '.task', '.task-row'],
    ['任务名', '.task b', '.task-label'],
    ['入口卡', '.row', '.home-card'],
    ['主按钮', '.primary', 'text=继续复习'],
  ],
  class: [
    ['打卡行', '.row', '.checkin-row'],
    ['排名行', '.row', '.rank-row'],
    ['排名数字', '.pos', '.rank-num'],
    ['徽章/达标', '.tick', '.checkin-done'],
  ],
};
const ROUTES = [['progress', 0], ['quiz', 1], ['knowledge', 2], ['learn', 3], ['class', 4]]; // 帧序：1 进度 2 测评 3 知识卡片 4 学习 5 班级
const PROPS = ['fontSize', 'fontWeight', 'lineHeight', 'color', 'backgroundColor', 'backgroundImage', 'boxShadow', 'borderTopWidth', 'borderLeftWidth', 'borderBottomWidth', 'borderTopColor', 'borderTopStyle', 'borderRadius', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'gap', 'textAlign', 'letterSpacing', 'textTransform', 'justifyContent', 'alignItems', 'minHeight'];
const PROBE = (sel) => `(()=>{const s=${JSON.stringify(sel)};const e=s.startsWith('text=')?[...document.querySelectorAll('button,.btn,.primary')].find(x=>(x.innerText||'').includes(s.slice(5))):document.querySelector(s);if(!e)return 'null';const c=getComputedStyle(e);const r=e.getBoundingClientRect();const o={__rect:[Math.round(r.width),Math.round(r.height)],__text:[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim().length>0),__display:c.display};${JSON.stringify(PROPS)}.forEach(p=>o[p]=c[p]);return JSON.stringify(o);})()`;
function measure(sel) { const r = ev(PROBE(sel)); return (r && r.__rect) ? r : null; }
function token() {
  const f = '/tmp/tok-JWT_SECRET-file.txt';
  if (fs.existsSync(f)) return fs.readFileSync(f, 'utf8').trim();
  const t = fs.readFileSync(path.join(ROOT, '.env'), 'utf8').split('\n').map(l => l.trim()).filter(l => l.startsWith('JWT_SECRET='));
  process.env.JWT_SECRET = (t[0] ? t[0].slice('JWT_SECRET='.length).replace(/^["']|["']$/g, '') : '');
  return execFileSync(process.execPath, ['/tmp/mktoken.py'], { encoding: 'utf8', env: process.env }).trim();
}
function norm(v, draft) {
  if (v == null) return 'MISSING';
  if (typeof v === 'number') return String(v);
  return String(v).replace(/\s+/g, ' ').trim();
}
function closeFail(a, b) {
  const na = parseFloat(a), nb = parseFloat(b);
  const sa = String(a), sb = String(b);
  // 语义等价：normal ≡ 0px（gap/letterSpacing 等的默认值写法差异），不算差异
  const zeroish = (s) => s === 'normal' || s === '0px' || s === '0' || s === '0s';
  if (zeroish(sa) && zeroish(sb)) return true;
  if (!isNaN(na) && !isNaN(nb) && /^-?\d+(\.\d+)?(px)?$/.test(sa) && /^-?\d+(\.\d+)?(px)?$/.test(sb)) return Math.abs(na - nb) <= 1.01;
  return sa === sb;
}
fs.writeFileSync('/tmp/style-parity-out.txt', '');
const diffs = [];
function record(screen, comp, prop, d, l) {
  if (closeFail(d, l)) return;
  diffs.push({ screen, comp, prop, draft: d, live: l });
}
try {
  ab(['set', 'viewport', String(W), String(H)]);
  ab(['open', 'file://' + DRAFT]); sleepMs(1200);
  const draftData = {};
  for (const [screen, fi] of ROUTES) {
    ab(['eval', `document.querySelectorAll('.frame')[${fi}].scrollIntoView({block:'start'})`]); sleepMs(200);
    draftData[screen] = {};
    for (const [name, dsel] of MAP[screen]) draftData[screen][name] = measure(dsel);
  }
  ab(['open', BASE + '/?cb=' + Date.now() + '#learn']);
  const tk = token();
  ab(['eval', 'localStorage.setItem("aistudy_token",' + JSON.stringify(tk) + '),location.reload()']);
  ab(['wait', '--fn', '!document.querySelector(".loading")']);
  const liveData = {};
  for (const [screen] of ROUTES) {
    ab(['open', `${BASE}/?cb=${Date.now()}#${screen}`]);
    ab(['wait', '--fn', '(()=>{const c=document.querySelector(".content");return !document.querySelector(".loading") && !!c && c.children.length>2})()']);
    liveData[screen] = {};
    for (const [name, dsel, lsel] of MAP[screen]) liveData[screen][name] = measure(lsel);
  }
  const lines = [];
  lines.push('屏'.padEnd(12) + '组件'.padEnd(18) + '属性'.padEnd(17) + '标准稿'.padEnd(20) + '线上');
  lines.push('-'.repeat(96));
  for (const [screen] of ROUTES) {
    for (const [name, dsel, lsel] of MAP[screen]) {
      const d = draftData[screen][name], l = liveData[screen][name];
      if (!d) { lines.push(screen.padEnd(12) + name.padEnd(18) + '标准稿选择器未命中 ' + dsel); continue; }
      if (!l) { record(screen, name, '组件', '存在', 'MISSING(' + lsel + ')'); lines.push(screen.padEnd(12) + name.padEnd(18) + '线上未命中 ' + lsel); continue; }
      const TEXT_PROPS = ['fontSize', 'fontWeight', 'lineHeight', 'color', 'letterSpacing', 'textAlign'];
      const bothText = !!d.__text && !!l.__text;
      const flexy = /flex|grid/.test(d.__display) && /flex|grid/.test(l.__display);
      for (const p of ['__rect', ...PROPS]) {
        if (TEXT_PROPS.includes(p) && !bothText) continue;   // 无直接文字的容器不比对文字属性
        if (p === 'gap' && !flexy) continue;                  // 非 flex/grid 不比对 gap
        const dv = norm(d[p]), lv = norm(l[p]);
        if (dv === lv) continue;
        record(screen, name, p, dv, lv);
        if (VERBOSE || diffs.length <= 80) lines.push(screen.padEnd(12) + name.padEnd(18) + p.padEnd(17) + dv.padEnd(20) + lv);
      }
    }
  }
  console.log(lines.join('\n'));
  console.log('\n差异总数: ' + diffs.length);
  fs.writeFileSync('/tmp/style-parity-diffs.json', JSON.stringify(diffs, null, 1));
  console.log('差异清单: /tmp/style-parity-diffs.json');
} catch (e) {
  console.error('parity 运行异常: ' + (e.message || '').split('\n')[0]);
  process.exit(1);
} finally { try { ab(['close']); } catch (_) {} }
if (diffs.length) { console.log('\n✗ 标准稿 vs 线上存在 ' + diffs.length + ' 处渲染差异'); process.exit(2); }
console.log('\n✓ 逐组件渲染差异 0');
