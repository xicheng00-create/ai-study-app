#!/usr/bin/env node
'use strict';
/* PROG-015：学生进度/测评页 UI 机械断言。
 *
 * 运行方式（Ray 2026-09-27 铁律：审计必须打库副本，不得打生产库）：
 *   make ui-audit                        → 自举（复制生产库 → 5098 起一次性实例，跑完收摊）
 *   UI_AUDIT_BASE=http://127.0.0.1:5003 node scripts/ui_audit.js
 *                                        → 显式打真实服务（只读用途；含写入的断言会落到生产库）
 */
const { execFileSync, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');
const AB = process.env.AGENT_BROWSER || '/Users/xicheng/.nvm/versions/node/v22.22.0/bin/agent-browser';
// 默认端口 = 本 app 的 launchd 服务端口 5003（曾误配 5004＝个人复习 app → 审计打错 app 必红）
let BASE = (process.env.UI_AUDIT_BASE || 'http://127.0.0.1:5003').replace(/\/$/, '');
const SESSION = `ui-audit-${process.pid}`;
// 每次跑审计用**全新浏览器 profile**：否则旧 Service Worker / HTTP 缓存会把上一版页面喂给断言，
// 让「已上线的旧 UI」冒充通过（本 app 曾因此被 CC 误判为「服务是旧版」）。
const PROFILE = process.env.AGENT_BROWSER_PROFILE || fs.mkdtempSync(path.join(require('os').tmpdir(), 'ab-audit-prof-'));
const KICKSTART = 'launchctl kickstart -k gui/$(id -u)/com.shuiyanhaha.aistudy';
const SELF_BOOT = process.env.UI_AUDIT_SELF_BOOT === '1';
const BOOT_PORT = Number(process.env.UI_AUDIT_PORT || 5098);
let BOOT_DIR = null;
let bootChild = null;
const fails = [];
const pass = (s) => console.log(`  ✓ ${s}`);
const fail = (s) => { fails.push(s); console.log(`  ✗ ${s}`); };
function ab(args) { return execFileSync(AB, ['--session', SESSION, '--profile', PROFILE, ...args], { encoding: 'utf8', maxBuffer: 1 << 24 }); }
function pageEval(js) {
  const out = ab(['eval', js, '--json']);
  const obj = JSON.parse(out.slice(out.indexOf('{')));
  if (!obj.success) throw new Error(obj.error || 'eval failed');
  return JSON.parse(obj.data.result);
}
async function server() {
  try { const r = await fetch(`${BASE}/health`); if (!r.ok) throw new Error(`HTTP ${r.status}`); }
  catch (e) { console.error(`\n✗ 服务未启动：${BASE}/health（${e.message}）\n  请先执行：${KICKSTART}\n`); process.exit(1); }
}
/* 把 .env 注入本进程 env：自举实例与 token() 子进程都靠它拿 APP_SECRET。
   否则自举实例（无人给 APP_SECRET）用 dev 默认密钥，而 token 用 .env 真密钥 → 页面落回登录页、
   断言对着登录页判红（本 app 已被此坑绕两次）。 */
function loadDotenv() {
  const f = path.join(ROOT, '.env');
  if (!fs.existsSync(f)) return;
  for (const ln of fs.readFileSync(f, 'utf8').split('\n')) {
    const s = ln.trim();
    if (!s || s.startsWith('#') || !s.includes('=')) continue;
    const i = s.indexOf('=');
    const k = s.slice(0, i).trim();
    if (!k || k in process.env) continue;
    process.env[k] = s.slice(i + 1).trim().replace(/^["']|["']$/g, '');
  }
}
/* 自举：复制生产库 → 5098 起一次性实例；审计的写入（起局答题 / 卡自评）全落副本。 */
function sleepSync(sec) { execFileSync('sleep', [String(sec)]); }
function bootTempInstance() {
  const os = require('os');
  const { spawn } = require('child_process');
  BOOT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'aistudy-ui-audit-'));
  const src = path.join(ROOT, 'instance', 'aistudy.sqlite3');
  const dst = path.join(BOOT_DIR, 'aistudy.sqlite3');
  if (!fs.existsSync(src)) throw new Error('找不到库副本源：' + src);
  fs.copyFileSync(src, dst);
  // 让 token() 与实例都只用副本（DATABASE_PATH 被 data/db.py 优先读取）
  process.env.DATABASE_PATH = dst;
  bootChild = spawn(path.join(ROOT, '.venv', 'bin', 'python'), [path.join(ROOT, 'backend', 'app.py')], {
    env: {
      ...process.env,
      HOME: '/Users/xicheng',        // Hermes 的假 HOME 会让实例读不到 .env
      FLASK_ENV: 'development',
      HOST: '127.0.0.1',
      PORT: String(BOOT_PORT),
      DATABASE_PATH: dst,           // ← 只有副本会被写
    },
    stdio: 'ignore',
  });
  const base = `http://127.0.0.1:${BOOT_PORT}`;
  for (let i = 0; i < 60; i += 1) {
    try { execFileSync('curl', ['-fsS', `${base}/health`], { stdio: 'ignore' }); BASE = base; return; }
    catch (_) { sleepSync(1); }
  }
  throw new Error(`自举实例未在 60s 内就绪（:${BOOT_PORT}）`);
}
function teardownTempInstance() {
  if (bootChild) { try { bootChild.kill('SIGTERM'); } catch (_) { /* ignore */ } }
  if (BOOT_DIR) { try { fs.rmSync(BOOT_DIR, { recursive: true, force: true }); } catch (_) { /* ignore */ } }
}
process.on('exit', teardownTempInstance);
function token() {
  const py = spawnSync(ROOT + '/.venv/bin/python', ['-c', `
import os, sys
# 必须先加载 .env：服务启动时是 source .env 起进程的，config.py 在 import 期读 os.environ['APP_SECRET']。
# 不加载的话本函数签出的是 dev 默认密钥的 token，线上校验必 401（曾让验收错判「页面没更新」）。
if os.path.exists('.env'):
    for _ln in open('.env'):
        _ln = _ln.strip()
        if _ln and not _ln.startswith('#') and '=' in _ln:
            _k, _v = _ln.split('=', 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
sys.path.insert(0, 'backend')
from app import create_app
from auth.jwt_utils import make_token
from data.db import get_db
with create_app('production').app_context():
 row=get_db().execute("SELECT id, role FROM users WHERE role='student' AND is_active=1 ORDER BY id LIMIT 1").fetchone()
 if not row: raise SystemExit('no active student')
 print(make_token(row['id'], row['role']))
`], { cwd: ROOT, encoding: 'utf8' });
  if (py.status !== 0) throw new Error(py.stderr || '无法生成测试 token');
  fs.writeFileSync('/tmp/aistudy-ui-token', py.stdout.trim(), { mode: 0o600 });
  return py.stdout.trim();
}
const audit = `(() => {
 const body = document.body, c = document.querySelector('.content');
 const text = body.innerText || '';
 const badges = [...document.querySelectorAll('.chapter .badge')];
 const rects = badges.map(x => { const r=x.getBoundingClientRect(); return [Math.round(r.width),Math.round(r.height),x.innerText.trim()]; });
 const blocks = [...document.querySelectorAll('.content > .card, .content > .dcard')];
 const interactive = [...document.querySelectorAll('button, a, [onclick], .qcard, .chapter')].filter(x => { const r=x.getBoundingClientRect(); return r.width>0&&r.height>0; });
 const dsc=e=>{const c=(typeof e.className==='string')?e.className:((e.getAttribute&&e.getAttribute('class'))||'');return (e.tagName||'?')+(c?'.'+c.split(' ').filter(Boolean).slice(0,2).join('.'):'')+'['+(e.innerText||'').replace(/\s+/g,' ').trim().slice(0,12)+']';};
 // 全能间隙扫描（横竖都查）：旧版只看 .content 直接子元素的**竖向**间隙，
 // 于是「页头连胜条 ↕ 公式文字贴在一起」这类真问题被漏判成绿（Ray 2026-09-27 亲测发现）。
 // 规则：两侧任一为「可交互块/卡片」→ 需 ≥12px；纯文字块之间 → ≥6px。祖先/后代不算相邻。
 const TIER_HI = 'button, a, [onclick], .card, .dcard, .chapter, .home-card, .qcard, .badge, .lib-card, .zone, .btn';
 const TIER_LO = 'p, .muted, .hint, small, .formula, .sub, .day, .stat';
 const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
 const isAnc = (x, y) => x !== y && (x.contains(y) || y.contains(x));
 const need = e => e.matches(TIER_HI) ? 12 : (e.matches(TIER_LO) ? 6 : 12);
 const items = [...document.querySelectorAll(TIER_HI + ', ' + TIER_LO)].filter(vis).slice(0, 400);
 const gaps = [];
 for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) {
  const A = items[i], B = items[j]; if (isAnc(A, B)) continue;
  const a = A.getBoundingClientRect(), b = B.getBoundingClientRect();
  const xo = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  const yo = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  const nd = Math.max(need(A), need(B));
  if (yo > 0.5 && xo >= 0 && xo < nd) gaps.push([Math.round(xo * 10) / 10, '横', nd, dsc(A), dsc(B)]);
  if (xo > 0.5 && yo >= 0 && yo < nd) gaps.push([Math.round(yo * 10) / 10, '纵', nd, dsc(A), dsc(B)]);
 }
 return JSON.stringify({text, blocks:blocks.map(x=>x.innerText), rects, scroll:body.scrollWidth, inner:innerWidth, gaps});
})()`;
(async () => {
 loadDotenv();
 if (SELF_BOOT) {
  console.log(`· 自举临时实例 http://127.0.0.1:${BOOT_PORT}（生产库副本，审计写入不回灌）`);
  bootTempInstance();
 }
 console.log(`\nUI 机械断言 · ${BASE}`); await server();
 let tk; try { tk=token(); } catch(e) { fail(e.message); }
 try {
  ab(['open', BASE]);
  ab(['eval', `localStorage.setItem('aistudy_token',${JSON.stringify(tk)}); location.reload()`]);
  ab(['wait','--fn',"!document.querySelector('.loading')"]);
  // 反「SW 缓存骗验收」：注销 Service Worker + 清 Cache Storage，再带 cb 硬载一次。
  // 不做这一步，旧 SW 会把上一版页面喂给断言（表现为「公网红、本地副本绿」，曾误导 CC 判「服务是旧版」）。
  try {
   ab(['eval', `(async()=>{try{if(navigator.serviceWorker){for(const r of await navigator.serviceWorker.getRegistrations()) await r.unregister();}if(self.caches){for(const k of await caches.keys()) await caches.delete(k);}}catch(e){}return 1})()`]);
   ab(['eval', `localStorage.setItem('aistudy_token',${JSON.stringify(tk)}), location.replace(location.pathname+'?cb='+Date.now())`]);
   ab(['wait','--fn',"!document.querySelector('.loading')"]);
  } catch (_) {}
  for (const width of [390,1280]) {
   ab(['set','viewport',String(width), '900']);
   // 注意：aistudy 的 hash 路由是 `#progress` / `#quiz`（**无斜杠**）；写成 `#/progress` 会落到默认页，
   // 断言将对着错误的 DOM 判红（CC 首版即此坑，误判为「服务是旧版」）。
   for (const route of ['#progress','#quiz']) {
    // 每次带唯一 cb 参数 = 强制**冷载深链**（而不是同页 hashchange）。
    // 两者行为曾不一致：app boot 忽略 hash → 冷载显示学习主页而地址栏仍是目标路由（真缺陷）。
    // 冷载 + 等目标页真正画完：只看 .loading 消失会在「异步取数未完」时误判（公网 #quiz@390 曾由此假红）。
    ab(['open', `${BASE}/?cb=${Date.now()}${route}`]);
    ab(['wait','--fn',"(()=>{const c=document.querySelector('.content');return !document.querySelector('.loading') && !!c && c.children.length>2})()"]);
    const landed = ab(['eval', `location.hash`, '--json']);
    if (!landed.includes(`"${route}"`)) { fail(`${route}@${width}: 未落到目标路由（location.hash=${landed.trim()}）—— 检查路由格式`); continue; }
    const x=pageEval(audit);
    if(x.scroll!==x.inner) fail(`${route}@${width}: 横向滚动 ${x.scroll} != ${x.inner}`); else pass(`${route}@${width}: 无横向滚动`);
    const bad=x.gaps.filter(g=>g[0]<g[2]); if(bad.length) { try { fs.writeFileSync('/tmp/aistudy-ui-audit-gaps.json', JSON.stringify({route, width, bad}, null, 1)); } catch (_) {} } if(bad.length) fail(`${route}@${width}: 间隙不足 ${bad.length} 对（需≥12/6px）→ ` + bad.slice(0,6).map(g=>`${g[1]}${g[0]}px(需${g[2]})「${String(g[3]).replace(/\n/g,' ')}」|「${String(g[4]).replace(/\n/g,' ')}」`).join(' ;; ')); else pass(`${route}@${width}: 间隙达标（横竖全能扫）`);
    if(route==='#progress') {
     const order=['学科掌握度','各章节状态','AI 学习建议']; const pos=order.map(k=>x.blocks.findIndex(b=>b.includes(k)));
     if(pos.some(p=>p<0)||!(pos[0]<pos[1]&&pos[1]<pos[2])) fail(`${route}@${width}: 三段顺序错误`); else pass(`${route}@${width}: 三段顺序正确`);
     const forbidden=['本周概况','对话天数','测评天数','知识卡片','薄弱点（带错题依据）','巩固练习闭环'];
     forbidden.forEach(k=>x.text.includes(k)&&fail(`${route}@${width}: 删除清单命中「${k}」`));
     if(!forbidden.some(k=>x.text.includes(k))) pass(`${route}@${width}: 删除清单零命中`);
     if(!x.rects.length||new Set(x.rects.map(r=>r[0])).size!==1||new Set(x.rects.map(r=>r[1])).size!==1) fail(`${route}@${width}: tag 尺寸不唯一`); else pass(`${route}@${width}: tag 尺寸唯一`);
     if(x.rects.some(r=>!['已掌握','进行中','薄弱','未评估'].includes(r[2]))) fail(`${route}@${width}: tag 文本不在四态词表`); else pass(`${route}@${width}: 四态 tag 文本合法`);
     if(x.text.includes('薄弱点')||x.text.includes('巩固练习')) fail(`${route}@${width}: 进度页出现迁移块`); else pass(`${route}@${width}: 不出现迁移块`);
    } else {
     const wi=x.text.indexOf('薄弱点（带错题依据）'), ri=x.text.indexOf('巩固练习闭环');
     if(wi<0||ri<0||wi>ri) fail(`${route}@${width}: 测评承载块缺失或顺序错误`); else pass(`${route}@${width}: 测评承载块顺序正确`);
    }
   }
  }
 } catch(e) { fail(`agent-browser/页面断言异常：${e.message.split('\n')[0]}`); }
 try { ab(['close']); } catch (_) {}
 try { fs.unlinkSync('/tmp/aistudy-ui-token'); } catch (_) {}
 teardownTempInstance();
 if(fails.length) { console.log(`\n✗ UI 机械断言失败：${fails.length} 项`); process.exit(1); }
 console.log('\n✓ UI 机械断言全绿');
})().catch(e => { console.error(e); process.exit(1); });
