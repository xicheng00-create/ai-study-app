#!/usr/bin/env node
'use strict';
/* PROG-015：学生进度/测评页 UI 机械断言。 */
const { execFileSync, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');
const AB = process.env.AGENT_BROWSER || '/Users/xicheng/.nvm/versions/node/v22.22.0/bin/agent-browser';
const BASE = (process.env.UI_AUDIT_BASE || 'http://127.0.0.1:5004').replace(/\/$/, '');
const SESSION = `ui-audit-${process.pid}`;
const KICKSTART = 'launchctl kickstart -k gui/$(id -u)/com.shuiyanhaha.aistudy';
const fails = [];
const pass = (s) => console.log(`  ✓ ${s}`);
const fail = (s) => { fails.push(s); console.log(`  ✗ ${s}`); };
function ab(args) { return execFileSync(AB, ['--session', SESSION, ...args], { encoding: 'utf8', maxBuffer: 1 << 24 }); }
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
function token() {
  const py = spawnSync(ROOT + '/.venv/bin/python', ['-c', `
import os, sys
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
 const gaps=[]; for(let i=0;i<interactive.length;i++) for(let j=i+1;j<interactive.length;j++){const a=interactive[i].getBoundingClientRect(),b=interactive[j].getBoundingClientRect(); if(b.top>=a.bottom-1 && Math.min(a.right,b.right)-Math.max(a.left,b.left)>0 && b.top-a.bottom<12) gaps.push(b.top-a.bottom);}
 return JSON.stringify({text, blocks:blocks.map(x=>x.innerText), rects, scroll:body.scrollWidth, inner:innerWidth, gaps});
})()`;
(async () => {
 console.log(`\nUI 机械断言 · ${BASE}`); await server();
 let tk; try { tk=token(); } catch(e) { fail(e.message); }
 try {
  ab(['open', BASE]);
  ab(['eval', `localStorage.setItem('aistudy_token',${JSON.stringify(tk)}); location.reload()`]);
  ab(['wait','--fn',"!document.querySelector('.loading')"]);
  for (const width of [390,1280]) {
   ab(['set','viewport',String(width), '900']);
   for (const route of ['#/progress','#/quiz']) {
    ab(['open', `${BASE}/${route}`]); ab(['wait','--fn',"!document.querySelector('.loading')"]);
    const x=pageEval(audit);
    if(x.scroll!==x.inner) fail(`${route}@${width}: 横向滚动 ${x.scroll} != ${x.inner}`); else pass(`${route}@${width}: 无横向滚动`);
    if(x.gaps.some(g=>g<12)) fail(`${route}@${width}: 可交互块间隙 < 12px`); else pass(`${route}@${width}: 可交互块间隙 ≥ 12px`);
    if(route==='#/progress') {
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
 if(fails.length) { console.log(`\n✗ UI 机械断言失败：${fails.length} 项`); process.exit(1); }
 console.log('\n✓ UI 机械断言全绿');
})().catch(e => { console.error(e); process.exit(1); });
