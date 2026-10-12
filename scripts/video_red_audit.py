#!/usr/bin/env python3
"""Run real A12-A19 assertions against isolated deliberately broken builds."""
import os, pathlib, shutil, subprocess, sys, tempfile
ROOT = pathlib.Path(__file__).resolve().parents[1]
DEST = ROOT / 'docs' / 'audit' / 'video'
DEST.mkdir(parents=True, exist_ok=True)
CASES = {
 'A1': ('backend/frontend/js/api.js', 'if (!opts.silent && typeof loadingOn', 'if (typeof loadingOn', ['node','scripts/video_ui_audit.js']),
 'A2': ('backend/frontend/js/student.js', 'this._videoPaint(card.id, next.status);', 'document.querySelector(\'.kc-card\').replaceWith(document.querySelector(\'.kc-card\').cloneNode(true)); this._videoPaint(card.id, next.status);', ['node','scripts/video_ui_audit.js']),
 'A3': ('backend/api/videos.py', 'row = _video(con, cid)', 'row = con.execute("SELECT * FROM card_videos WHERE core_card_id=? AND requested_by=? ORDER BY requested_at DESC LIMIT 1", (cid, g.user_id)).fetchone()', ['.venv/bin/pytest','-q','tests/test_videos.py::test_batch_api_dedup_idempotency_and_permissions','--no-cov']),
 'A4': ('backend/api/videos.py', "status='active' ORDER BY created_at DESC LIMIT 1", "status='complete' ORDER BY created_at DESC LIMIT 1", ['.venv/bin/pytest','-q','tests/test_videos.py::test_batch_api_dedup_idempotency_and_permissions','--no-cov']),
 'A5': ('backend/video_worker.py', 'if ready + failed:', 'if False:', ['.venv/bin/pytest','-q','tests/test_videos.py::test_batch_notification_exactly_once','--no-cov']),
 'A6': ('backend/api/videos.py', 'len(ids) > 100', 'len(ids) > 1000', ['.venv/bin/pytest','-q','tests/test_videos.py::test_batch_api_dedup_idempotency_and_permissions','--no-cov']),
 'A7': ('backend/video_worker.py', 'if con.execute("SELECT 1 FROM card_video_daily_runs', 'if False and con.execute("SELECT 1 FROM card_video_daily_runs', ['.venv/bin/pytest','-q','tests/test_videos.py::test_prewarm_daily_idempotency_and_exact_deck','--no-cov']),
 'A8': ('backend/video_worker.py', 'mode="task"', 'mode="extra"', ['.venv/bin/pytest','-q','tests/test_videos.py::test_prewarm_uses_task_deck_card_set','--no-cov']),
 'A9': ('backend/frontend/js/student.js', "API.get('/api/videos/index', { silent: true })", "API.get('/api/videos/index')", ['node','scripts/video_ui_audit.js']),
 'A10': ('backend/video_worker.py', 'notify=1 ORDER BY created_at', 'notify=0 ORDER BY created_at', ['.venv/bin/pytest','-q','tests/test_videos.py::test_manual_requests_create_one_notification','--no-cov']),
 'A11': ('backend/api/videos.py', "VALUES(?,?,?,?, 'manual',1,?)", "VALUES(?,?,?,?, 'batch',1,?)", ['.venv/bin/pytest','-q','tests/test_videos.py::test_manual_notification_and_prewarm_dedup','--no-cov']),
 'A12': ('backend/api/videos.py', 'linked_cards = {cid: cards[cid] for cid in linked_ids if cid in cards}', 'linked_cards = {cid: cards[cid] for cid in linked_ids if cid in cards and cid == cards[cid]["core_card_id"]}', ['.venv/bin/pytest','-q','tests/test_videos.py::test_video_index_card_link_set_and_core_flags','--no-cov']),
 'A13': ('backend/frontend/js/student.js', "${state === 'ready' ? ' has-video' : ''}", "''", ['node','scripts/video_ui_audit.js']),
 'A14': ('backend/frontend/js/student.js', '<button class="kc-video-badge" onclick="event.stopPropagation();Student.openCardVideo(\'${c.id}\')">${badge}</button>', '', ['node','scripts/video_ui_audit.js']),
 'A15': ('backend/frontend/js/student.js', "const ordered = this.videoTopicGroups?.[id] || names;", "const ordered = []; chapter.videos = {全部卡片: Object.values(chapter.videos).flat()}; ordered.push('全部卡片');", ['node','scripts/video_ui_audit.js']),
 'A16': ('backend/api/videos.py', '"n_cards": r["n_cards"] or 0', '"n_cards": 1', ['.venv/bin/pytest','-q','tests/test_videos.py::test_video_listing_adjacent_topics_fields','--no-cov']),
 'A17': ('backend/frontend/js/student.js', 'onclick="Student.openVideoCards(\'${v.video_id}\')">相关卡片 (${v.n_cards})', 'onclick="Student.openVideoCards(\'${v.video_id}\')">相关卡片 (0)', ['node','scripts/video_ui_audit.js']),
 'A18': ('backend/frontend/js/student.js', '视频 ${topicVideo?.cards_with_video || 0}/${topicVideo?.cards_total ?? t.cards.length} 卡', '视频 0/0 卡', ['node','scripts/video_ui_audit.js']),
 'A19': ('backend/frontend/js/student.js', "API.get('/api/videos/index', { silent: true })", "API.get('/api/videos/index')", ['node','scripts/video_ui_audit.js']),
}
def main():
  labels=sys.argv[1:] or list(CASES)
  for label in labels:
    rel,good,bad,cmd=CASES[label]
    with tempfile.TemporaryDirectory(prefix=f'vid-{label}-') as td:
      work=pathlib.Path(td)/'repo';work.mkdir()
      # Minimal isolated code checkout from git; DB and artifacts remain isolated in the harness.
      subprocess.run(['git','archive','HEAD'],cwd=ROOT,stdout=open(pathlib.Path(td)/'src.tar','wb'),check=True)
      subprocess.run(['tar','-xf',str(pathlib.Path(td)/'src.tar'),'-C',str(work)],check=True)
      for folder in ['backend','scripts','tests']:
        if (ROOT/folder).exists(): shutil.copytree(ROOT/folder,work/folder,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
      (work/'.env').write_text('APP_SECRET=mutation-secret-123456789012345678901234\nJWT_SECRET=mutation-secret-123456789012345678901234\n')
      for name in ['Makefile','pytest.ini']:
        if (ROOT/name).exists(): shutil.copy2(ROOT/name,work/name)
      if (ROOT/'.env').exists():
        shutil.copy2(ROOT/'.env',work/'.env')
        shutil.copy2(ROOT/'.env',pathlib.Path(td)/'.env')
      else:
        (work/'.env').write_text('APP_SECRET=mutation-secret-123456789012345678901234\nJWT_SECRET=mutation-secret-123456789012345678901234\n')
      f=work/rel;text=f.read_text()
      if good not in text: raise SystemExit(f'{label}: mutation pattern not found')
      f.write_text(text.replace(good,bad) if label in ("A9", "A19") else text.replace(good,bad,1))
      env=os.environ.copy();env['PYTHONPATH']=str(work/'backend')+os.pathsep+env.get('PYTHONPATH',''); env['DATABASE_PATH']=str(pathlib.Path(td)/'mutation.sqlite3'); env['ROOT']=str(ROOT); env['VIDEO_AUDIT_PYTHON']=str(ROOT/'.venv/bin/python'); env['APP_SECRET']='mutation-secret-123456789012345678901234'; env['JWT_SECRET']=env['APP_SECRET']
      if label in ('A1','A2','A9','A13','A14','A15','A17','A18','A19'):
        env['UI_AUDIT_SELF_BOOT']='1';env['VIDEO_AUDIT_SOURCE_DB']=str(ROOT/'instance/aistudy.sqlite3');env['VIDEO_AUDIT_PYTHON']=str(ROOT/'.venv/bin/python');env['AGENT_BROWSER']=os.environ.get('AGENT_BROWSER','/Users/xicheng/.nvm/versions/node/v22.22.0/bin/agent-browser');env['UI_AUDIT_PORT']=str(5200+int(label[1:]));env['VIDEO_AUDIT_SESSION']='bad-'+label
      actual=cmd[:]; actual[0]=str(ROOT/cmd[0]) if cmd[0].startswith('.venv/') else cmd[0]
      if actual[0].endswith('/pytest'): actual=[actual[0],'-c',str(ROOT/'pytest.ini'),*actual[1:]]
      r=subprocess.run(actual,cwd=work,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180)
      text=f'$ {" ".join(actual)}\n{r.stdout}EXIT={r.returncode}\n'
      (DEST/f'REQ-VID-{label}-RED.txt').write_text(text)
      print(f'{label}: exit {r.returncode}; raw output -> docs/audit/video/REQ-VID-{label}-RED.txt')
      if r.returncode==0: raise SystemExit(f'{label}: bad build did not fail assertion')
      target = 'AssertionError' if label in ('A12','A16','A6') else ('E_INPUT' if label == 'A6' else ('✗ '+label+' '))
      if target not in r.stdout and not (label in ('A3','A4','A5','A7','A8','A10','A11') and ('AssertionError' in r.stdout or 'assert ' in r.stdout)): raise SystemExit(f'{label}: BLOCKED, missing target assertion failure')
  return 0
if __name__=='__main__':sys.exit(main())
