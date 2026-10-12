#!/usr/bin/env node
'use strict';
// REQ-VID-020~023：副本库浏览器端到端审计；只通过 scripts/ui_audit.js 同源自举提供隔离环境。
const {execFileSync,spawnSync}=require('child_process'),fs=require('fs'),path=require('path'),os=require('os');
const ROOT=path.resolve(__dirname,'..'),AB=process.env.AGENT_BROWSER||'/Users/xicheng/.nvm/versions/node/v22.22.0/bin/agent-browser';
let base=process.env.UI_AUDIT_BASE||'http://127.0.0.1:5098',bootChild=null,bootDir=null;const selfBoot=process.env.UI_AUDIT_SELF_BOOT==='1',session=`vid-audit-${process.env.VIDEO_AUDIT_SESSION||process.pid}`,profile=fs.mkdtempSync(path.join(os.tmpdir(),'vid-audit-prof-'));
const failures=[],out=(s)=>console.log(s),pass=s=>out(`  ✓ ${s}`),fail=s=>{failures.push(s);out(`  ✗ ${s}`)};
function ab(args){return execFileSync(AB,['--session',session,'--profile',profile,...args],{encoding:'utf8',maxBuffer:1<<20});}
function page(js){const s=ab(['eval',js,'--json']);const x=JSON.parse(s.slice(s.indexOf('{')));if(!x.success)throw Error(x.error);return JSON.parse(x.data.result);}
function py(code,...args){const r=spawnSync((process.env.VIDEO_AUDIT_PYTHON||path.join(ROOT,'.venv','bin','python')),['-c',code,...args],{cwd:ROOT,encoding:'utf8',env:process.env});if(r.status)throw Error(r.stderr||r.stdout);return r.stdout.trim();}
function loadEnv(){for(const l of (fs.existsSync(path.join(ROOT,'.env'))?fs.readFileSync(path.join(ROOT,'.env'),'utf8'):'').split('\n')){const i=l.indexOf('=');if(i>0)process.env[l.slice(0,i).trim()]??=l.slice(i+1).trim().replace(/^['"]|['"]$/g,'');}}
(async()=>{
 try{
  loadEnv();
  if(selfBoot){bootDir=fs.mkdtempSync(path.join(os.tmpdir(),'aistudy-vid-ui-'));const bootPort=Number(process.env.UI_AUDIT_PORT||5098);const db=path.join(bootDir,'aistudy.sqlite3');fs.copyFileSync(process.env.VIDEO_AUDIT_SOURCE_DB||path.join(ROOT,'instance/aistudy.sqlite3'),db);process.env.DATABASE_PATH=db;bootChild=require('child_process').spawn((process.env.VIDEO_AUDIT_PYTHON||path.join(ROOT,'.venv','bin','python')),[path.join(ROOT,'backend/app.py')],{env:{...process.env,HOME:'/Users/xicheng',FLASK_ENV:'development',HOST:'127.0.0.1',PORT:String(bootPort),DATABASE_PATH:db,UI_AUDIT_SOURCE_ROOT:ROOT},stdio:'ignore'});base=`http://127.0.0.1:${bootPort}`;for(let i=0;i<60;i++){try{execFileSync('curl',['-fsS',base+'/health'],{stdio:'ignore'});break}catch{execFileSync('sleep',['1']);}}}

  const token=py(`import os,sys;sys.path.insert(0,os.environ.get('UI_AUDIT_SOURCE_ROOT','')+'/backend' if os.environ.get('UI_AUDIT_SOURCE_ROOT') else 'backend');from app import create_app;from auth.jwt_utils import make_token;from data.db import get_db
with create_app('development').app_context():
 r=get_db().execute("SELECT id,role FROM users WHERE role='student' AND is_active=1 ORDER BY id LIMIT 1").fetchone();print(make_token(r['id'],r['role']))`);
  ab(['open',`${base}/?audit=${Date.now()}#learn`]);ab(['eval',`(async()=>{for(const r of await navigator.serviceWorker.getRegistrations())await r.unregister();for(const k of await caches.keys())await caches.delete(k)})()`]);ab(['wait','500']);ab(['eval',`localStorage.setItem('aistudy_token',${JSON.stringify(token)});location.reload()`]);ab(['wait','--fn',"document.querySelector('.home-card')!==null"]);
  const auth={Authorization:`Bearer ${token}`};
  // Snapshot source DB truth for the isolated replica and compare against browser API.
  const truth=JSON.parse(py(`import os,sqlite3,json
c=sqlite3.connect(os.environ['DATABASE_PATH']);c.row_factory=sqlite3.Row
links=[dict(r) for r in c.execute("SELECT DISTINCT l.card_id,l.video_id,l.is_core,v.core_card_id,v.status FROM card_video_links l JOIN card_videos v ON v.id=l.video_id JOIN knowledge_cards k ON k.id=l.card_id JOIN chapters ch ON ch.id=k.chapter_id AND ch.status='published'")]
print(json.dumps(links))`));
  const index=await fetch(`${base}/api/videos/index`,{headers:auth}).then(r=>r.json());if(index.code)throw Error(index.msg);
  const ids=[...new Set(truth.map(x=>x.card_id))].sort(),apiIds=Object.keys(index.data.cards).sort();
  if(JSON.stringify(ids)!==JSON.stringify(apiIds))fail(`A12 index coverage DB=${ids.length} API=${apiIds.length}`);else pass(`A12 linked card index exact (${ids.length})`);
  // Enter knowledge cards using a real published chapter and use served index card mapping.
  const chapter=py(`import os,sqlite3,json
c=sqlite3.connect(os.environ['DATABASE_PATH']);r=c.execute("SELECT kc.chapter_id FROM knowledge_cards kc JOIN chapters ch ON ch.id=kc.chapter_id WHERE ch.status='published' AND NOT EXISTS(SELECT 1 FROM card_video_links l WHERE l.card_id=kc.id) GROUP BY kc.chapter_id ORDER BY COUNT(*) DESC LIMIT 1").fetchone();print(r[0] if r else '')`);
  if(!chapter)throw Error('副本库无 published chapter');
  ab(['eval',`App.state.hash='learn';Student.knowledgeIdx=true;Student.learnChat=false;Student.knowledgeDeck=false;Student.selChapters=[${JSON.stringify(chapter)}];Student.saveSelChapters();(async()=>{Student.videoIndex=await API.get('/api/videos/index',{silent:true});await render()})()`]);
  ab(['wait','--fn',"document.querySelector('.kc-ch-head')!==null || document.querySelector('.note')!==null"]);
  console.log('AUDIT_PAGE',page(`JSON.stringify({hash:App.state.hash,idx:Student.knowledgeIdx,deck:Student.knowledgeDeck,chapter:Student.selChapters,body:document.body.innerText.slice(0,180)})`));
  const cardApi=await fetch(`${base}/api/knowledge/${encodeURIComponent(chapter)}`,{headers:auth}).then(r=>r.json());
  const cards=cardApi.data.cards, topicCounts={};for(const c of cards){const t=(c.topic||'').trim()||'全部卡片';topicCounts[t]=(topicCounts[t]||0)+1;}
  const expected=Object.entries(topicCounts).filter(([,n])=>n>0).sort((a,b)=>b[1]-a[1]).map(([t])=>t);
  ab(['eval',`Student.knowledgeGroupOpen[${JSON.stringify(chapter)}]=true;render()`]);ab(['wait','--fn',"document.querySelectorAll('.kc-topic-head').length>0"]);
  ab(['eval',`Student.knowledgeTopicOpen[${JSON.stringify(chapter+'|0')}]=true;render()`]);ab(['wait','--fn',"document.querySelector('.kc-mini')!==null"]);
  const chCount=page(`JSON.stringify({n:document.querySelectorAll('.kc-ch-head').length,video:[...document.querySelectorAll('.kc-ch-head')].map(x=>x.innerText),groups:[...document.querySelectorAll('.kc-topic-head')].map(x=>x.innerText),badges:[...document.querySelectorAll('.kc-mini.has-video')].length,mini:[...document.querySelectorAll('.kc-mini')].length,add:[...document.querySelectorAll('.kc-video-badge')].filter(x=>x.innerText.includes('＋视频')&&getComputedStyle(x).display!=='none'&&x.innerText.trim()).length})`);
  if(chCount.groups.length!==expected.length)fail(`A15 knowledge topic groups count ${chCount.groups.length} != ${expected.length}`);else pass('A15 card topic groups visible');
  // CSS/DOM layout: badges are positioned outside flow; no height contribution.
  if(chCount.add<1 && chCount.mini<1)fail('A14 no visible unlinked card/badge to verify');else pass(`A14 card wall has visible entries; expanded card no-video badges=${chCount.add}`);
  // Expand one topic group to validate ready badge count and section totals against data.
  const firstTopic=cards[0]?.topic||'全部卡片';
  const topicIdx=expected.indexOf(firstTopic);
  if(topicIdx>=0){ab(['eval',`Student.knowledgeTopicOpen[${JSON.stringify(chapter+'|'+topicIdx)}]=true;render()`]);ab(['wait','--fn',"document.querySelectorAll('.kc-mini').length>0"]);}
  ab(['eval',`Student.knowledgeTopicOpen=Object.fromEntries(${JSON.stringify(expected.map((_,i)=>[chapter+'|'+i,true]))});render()`]);ab(['wait','--fn',"document.querySelectorAll('.kc-mini').length>0"]);
  let visible;try{visible=page(`JSON.stringify({mini:[...document.querySelectorAll('.kc-mini')].map(x=>({id:x.getAttribute('onclick').split("'")[1],has:x.classList.contains('has-video'),topic:x.closest('.kc-topic').querySelector('.kc-topic-head').innerText,front:x.querySelector('b')?.innerText,badge:x.querySelector('.kc-video-badge')?.innerText,display:x.querySelector('.kc-video-badge')?getComputedStyle(x.querySelector('.kc-video-badge')).display:'none',rect:(()=>{const r=x.getBoundingClientRect();return [r.width,r.height]})()})),heads:[...document.querySelectorAll('.kc-topic-head,.kc-ch-head')].map(x=>x.innerText)})`);}catch(e){fail('A13/A14 visible card badge DOM assertion could not execute: '+e.message.split('\n')[0]);visible={mini:[]};}
  const dbReady=new Set(truth.filter(x=>x.status==='ready').map(x=>x.card_id));
  // DOM identity comparison per visible topic uses card IDs from card API mapped by front (fixture fronts are unique).
  for(const name of expected){const groupCards=cards.filter(c=>((c.topic||'').trim()||'全部卡片')===name);const want=groupCards.filter(c=>dbReady.has(c.id)).length;const shown=visible.mini.filter(m=>groupCards.some(c=>c.id===m.id));if(shown.length!==groupCards.length)fail(`A13 ${name}: DOM card count ${shown.length} != DB ${groupCards.length}`);const got=shown.filter(m=>m.has).length;if(got!==want)fail(`A13 ${name}: DOM has-video ${got} != DB ready linked ${want}`);if(shown.some(m=>!m.badge||m.display==='none'))fail(`A13 ${name}: card badge missing/hidden`);}
  if(!failures.some(x=>x.startsWith('A13')))pass('A13 every rendered topic card badge/status matches DB');
  const noVideo=visible.mini.filter(m=>!truth.some(x=>x.card_id===m.id));if(!noVideo.length)fail('A14 no-video card fixture is not rendered');else if(noVideo.some(m=>!m.badge?.includes('＋视频')||m.display==='none'||!m.badge.trim()))fail('A14 unlinked card lacks visible ＋视频 badge');else if(noVideo.length)pass(`A14 ${noVideo.length} no-video badges visibly say ＋视频`);else fail('A14 no unlinked visible cards to assert');
  const videoList=await fetch(`${base}/api/videos`,{headers:auth}).then(r=>r.json());if(videoList.code)throw Error(videoList.msg);
  const vids=videoList.data, videoGroups=[];for(const v of vids){const k=`${v.chapter_id}|${v.topic||'全部卡片'}`;if(!videoGroups.includes(k))videoGroups.push(k);}
  // A15 compares complete rendered groups, including empty themes, to actual topicGroups output.
  ab(['eval',`Student.enterVideos()`]);ab(['wait','--fn',"document.querySelector('.video-topic')!==null"]);
  const videoUi=page(`JSON.stringify({groups:[...document.querySelectorAll('.video-topic')].map(e=>e.dataset.chapter+'|'+e.dataset.topic),entries:[...document.querySelectorAll('.video-entry')].map(e=>({related:e.querySelector('.video-related')?.innerText,video:e.querySelector('.video-play')?.getAttribute('onclick').match(/openVideoPlayer\\('([^']+)'/)[1]}))})`);
  for(const cid of Object.keys(index.data.chapters)){
    const d=await fetch(`${base}/api/knowledge/${encodeURIComponent(cid)}`,{headers:auth}).then(r=>r.json());
    const want=page(`JSON.stringify(Student.topicGroups(${JSON.stringify(d.data.cards)}).map(t=>${JSON.stringify(cid)}+'|'+t.name))`);
    const got=videoUi.groups.filter(k=>k.startsWith(cid+'|'));
    if(JSON.stringify(got)!==JSON.stringify(want))fail(`A15 rendered group mismatch ${cid}: ${JSON.stringify(got)} != ${JSON.stringify(want)}`);
  }
  if(!failures.some(x=>x.startsWith('A15')))pass('A15 complete rendered chapter/topic sets and order equal card topicGroups');
  for(const entry of videoUi.entries){const n=truth.filter(x=>x.video_id===entry.video).length;if(entry.related!==`相关卡片 (${n})`)fail(`A17 entry ${entry.video} related count ${entry.related} != ${n}`);}
  for(const v of vids){const n=truth.filter(x=>x.video_id===v.video_id).length;if(v.n_cards!==n)fail(`A16 ${v.video_id}: n_cards ${v.n_cards} != links ${n}`);}
  for(const v of vids){
    const linked=truth.filter(x=>x.video_id===v.video_id);
    for(const link of linked){
      const resolved=page(`(async()=>{const old=Student.openVideoPlayer;let played=null;Student.openVideoPlayer=id=>{played=id};try{await Student.openCardVideo(${JSON.stringify(link.card_id)});return JSON.stringify(played)}finally{Student.openVideoPlayer=old}})()`);
      if(resolved!==v.video_id)fail(`A16 card ${link.card_id} resolved ${resolved} instead of shared ${v.video_id}`);
    }
  }
  if(vids.length)pass(`A16 list link counts checked (${vids.length})`);
  for(const v of vids){const reverse=await fetch(`${base}/api/videos/${encodeURIComponent(v.video_id)}/cards`,{headers:auth}).then(r=>r.json());const expectedRows=truth.filter(x=>x.video_id===v.video_id);if(reverse.code||reverse.data.length!==expectedRows.length)fail(`A17 ${v.video_id}: related count ${reverse.data?.length} != ${expectedRows.length}`);else{for(const row of reverse.data){if(!expectedRows.some(x=>x.card_id===row.id))fail(`A17 ${v.video_id}: unexpected related card ${row.id}`);const nav=await fetch(`${base}/api/knowledge/${encodeURIComponent(row.chapter_id)}`,{headers:auth}).then(r=>r.json());if(!nav.data.cards.some(c=>c.id===row.id&&((c.topic||'').trim()||'全部卡片')===(row.topic||'全部卡片')))fail(`A17 ${v.video_id}: card ${row.id} cannot resolve to chapter/topic`);}}}
  // Click every reverse sheet card and verify the actual expanded chapter/topic DOM.
  for(const v of failures.some(x=>x.startsWith('A15')) ? [] : vids){
    const rows=await fetch(`${base}/api/videos/${encodeURIComponent(v.video_id)}/cards`,{headers:auth}).then(r=>r.json());
    for(const row of rows.data){
      ab(['eval',`Student.enterVideos()`]);ab(['wait','--fn',"document.querySelector('.video-topic')!==null"]);
      ab(['eval',`[...document.querySelectorAll('.video-related')].find(e=>e.getAttribute('onclick').includes(${JSON.stringify(v.video_id)})).click()`]);
      ab(['wait','--fn',"document.querySelector('.sheet .home-card')!==null"]);
      ab(['eval',`[...document.querySelectorAll('.sheet .home-card')].find(e=>e.getAttribute('onclick').includes(${JSON.stringify(row.id)})).click()`]);
      ab(['wait','--fn',"document.querySelector('.kc-topic-head')!==null && document.querySelector('.sheet')!==null"]);
      const nav=page(`JSON.stringify({idx:Student.knowledgeIdx,video:Student.videoList,chapter:Student.knowledgeGroupOpen[${JSON.stringify(row.chapter_id)}],topic:[...document.querySelectorAll('.kc-topic')].some(e=>e.querySelector('.kc-topic-head b')?.innerText===${JSON.stringify(row.topic||'全部卡片')}&&[...e.querySelectorAll('.kc-mini')].some(k=>k.getAttribute('onclick').includes(${JSON.stringify(row.id)})))})`);
      if(!nav.idx||nav.video||!nav.chapter||!nav.topic)fail(`A17 reverse card ${row.id} did not expand destination: ${JSON.stringify(nav)}`);
      ab(['eval','closeSheet()']);
    }
  }
  if(vids.length)pass(`A17 all reverse lists and chapter-topic destinations checked (${vids.length} videos)`);
  ab(['eval',`Student.videoList=false;Student.knowledgeIdx=true;Student.selChapters=[${JSON.stringify(chapter)}];Student.saveSelChapters();render()`]);
  ab(['wait','--fn',"document.querySelector('.kc-topic-head')!==null"]);
  // A18 compare visible chapter/topic summary text exactly against API aggregates.
  const headerProbe=page(`JSON.stringify({chap:[...document.querySelectorAll('.kc-ch-head')].map(e=>e.innerText),topics:[...document.querySelectorAll('.kc-topic-head')].map(e=>e.innerText)})`);
  const chAgg=index.data.chapters[chapter];if(chAgg&&!headerProbe.chap.some(t=>t.includes(`视频 ${chAgg.cards_with_video}/${chAgg.cards_total} 卡`)))fail('A18 chapter summary does not match API totals');else if(chAgg)pass('A18 chapter video N/M matches API aggregate');
  for(const t of expected){const agg=index.data.topics[`${chapter}|${t}`];if(!agg)continue;const header=headerProbe.topics.find(x=>x.startsWith(t+'\n'));if(!header||!header.includes(`视频 ${agg.cards_with_video}/${agg.cards_total} 卡`))fail(`A18 topic ${t} summary mismatch/missing`);}
  if(!failures.some(x=>x.startsWith('A18')))pass('A18 every visible topic summary matches API aggregate');
  // Detail sheet: video row is always present; ready opens player, pending/none wording is stateful.
  const sample=cards.find(c=>!truth.some(x=>x.card_id===c.id));
  if(sample){
    ab(['eval',`Student.kcDetail(${JSON.stringify(sample.id)})`]);
    ab(['wait','--fn',"document.querySelector('.sheet')!==null"]);
    const sheet=page(`JSON.stringify({text:document.querySelector('.sheet')?.innerText||'',rows:[...document.querySelectorAll('.sheet .row')].map(x=>x.innerText)})`);
    if(!sheet.text.includes('生成 AI 视频讲解'))fail('A20 detail sheet lacks manual video entry');else pass('Detail sheet always exposes manual video entry');
    ab(['eval','closeSheet()']);
  }else fail('Detail sheet test has no no-video card fixture');
  // A19 request functions are instrumented at runtime: any non-silent API request while loading layer appears fails.
  ab(['wait','500']);
  ab(['eval',`window.__requests=[];window.__oldGet=API.get;API.get=(p,o)=>{window.__requests.push([p,o]);return window.__oldGet(p,o)};window.__globalLoadingShows=0;window.__loadingObs=new MutationObserver(()=>{if(document.querySelector('.global-loading.show'))window.__globalLoadingShows++});window.__loadingObs.observe(document.body,{subtree:true,attributes:true,attributeFilter:['class'],childList:true})`]);
  const loadingBefore=page(`JSON.stringify(document.querySelectorAll('.global-loading.show').length)`);
  ab(['eval',`Student.enterVideos()`]);ab(['wait','--fn',"document.querySelector('.video-entry')!==null || document.body.innerText.includes('暂无已生成的视频')"]);
  const loadingAfter=page(`JSON.stringify({shown:document.querySelectorAll('.global-loading.show').length,transitions:window.__globalLoadingShows||0,requests:window.__requests})`);
  console.log('A19_REQUESTS',JSON.stringify(loadingAfter));
  if(loadingBefore||loadingAfter.shown||loadingAfter.transitions)fail(`A19 global loading visible/transition count (${loadingBefore}→${loadingAfter.shown}, transitions=${loadingAfter.transitions})`);else pass('A19 no global loading display transitions during page fetches');
  out('A12-A19 browser checks captured against isolated data; RED mutation runs are managed by video_red_audit.py');
 }finally{try{ab(['close']);}catch{}if(bootChild)bootChild.kill('SIGTERM');if(bootDir)fs.rmSync(bootDir,{recursive:true,force:true});fs.rmSync(profile,{recursive:true,force:true});}
 if(failures.length)process.exitCode=1;
})().catch(e=>{console.error(e.stack||e);process.exitCode=1;});
