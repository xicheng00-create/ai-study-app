/* 教师视图：管理后台（资料/章节/学生）+ 发布测评 + 全班进度/周报 */
const Teacher = {
  pubSel: {},

  async render() {
    const h = App.state.hash;
    if (h === "quiz") return await this.viewQuiz();
    if (h === "progress") return await this.viewProgress();
    if (h === "report") return await this.viewReport();
    return await this.viewAdmin();
  },

  /* ===== 管理后台 ===== */
  async viewAdmin() {
    let materials = [], students = [], overview = { students: [], common_weak_chapters: [] };
    try { materials = (await API.get("/api/materials")).materials || []; } catch (e) {}
    try { students = (await API.get("/api/teacher/students")).students || []; } catch (e) {}
    try { overview = await API.get("/api/teacher/overview"); } catch (e) {}

    const grouped = {};
    App.chapters.forEach(c => { (grouped[c.folder || '未分组'] = grouped[c.folder || '未分组'] || []).push(c); });
    const lib = Object.keys(grouped).map(f => `<div class="folder">${esc(f)}</div>` + grouped[f].map(c => {
      const mats = materials.filter(m => m.chapter_id === c.id);
      const matHtml = mats.map(m => `<div style="display:flex;align-items:center;gap:6px;font-size:12px;margin-top:4px">📄 ${esc(m.original_name)}
        <span class="badge ${m.parse_status === 'parsed' ? 'parse' : 'fail'}">${m.parse_status === 'parsed' ? `已解析 ${m.chunk_count} 块` : '解析失败'}</span>
        <span class="mini-btn danger" style="margin-left:auto;padding:3px 8px" onclick="Teacher.delMaterial('${m.id}')">删</span></div>`).join('') || '<div class="muted" style="font-size:12px;margin-top:4px">暂无资料</div>';
      return `<div class="adm-card" style="flex-direction:column;align-items:stretch">
        <div style="display:flex;align-items:center;gap:13px"><div class="av">§</div><div class="meta"><div class="nm">${esc(c.name)}</div><div class="st">${mats.length} 份资料</div></div>
          <span class="mini-btn teacher" onclick="Teacher.uploadForm('${c.id}')">上传</span></div><div style="margin-top:8px;padding-left:0">${matHtml}</div></div>`;
    }).join('')).join('') || '<div class="muted">暂无章节，先新建</div>';

    const studentsHtml = students.map(s => `<div class="adm-card"><div class="av">${esc((s.display_name || s.username).charAt(0))}</div>
      <div class="meta"><div class="nm">${esc(s.display_name || s.username)}</div><div class="st"><span style="color:${s.is_active ? 'var(--green)' : 'var(--red)'}">●</span> ${s.is_active ? '活跃' : '已停用'} · ${esc(s.username)}</div></div>
      <button class="mini-btn" onclick="Teacher.resetPw('${s.id}')">重置</button>
      <button class="mini-btn danger" onclick="Teacher.toggleStudent('${s.id}',${s.is_active ? 0 : 1})">${s.is_active ? '停用' : '启用'}</button></div>`).join('') || '<div class="muted">暂无学生账号</div>';

    const overviewHtml = (overview.students || []).map(s => `<div class="card sm" style="display:flex;align-items:center;gap:12px">
      <div class="av" style="width:40px;height:40px;border-radius:11px">${esc((s.display_name || '?').charAt(0))}</div>
      <div style="flex:1"><div style="font-weight:700">${esc(s.display_name)}</div><div class="muted" style="font-size:12px">已掌握 ${s.counts.master} · 进行中 ${s.counts.progress} · 薄弱 ${s.counts.weak}</div></div></div>`).join('');

    return appbar('管理后台', '教师专有') + `<div class="content">
      <button class="btn teacher" style="margin-bottom:8px" onclick="Teacher.newChapterForm()">＋ 新建章节</button>
      <button class="btn sec" style="margin-bottom:14px" onclick="Teacher.newStudentForm()">＋ 新建学生账号</button>
      <div style="font-weight:700;font-size:15px;margin:4px 0 10px">资料与章节</div>${lib}
      <div style="font-weight:700;font-size:15px;margin:14px 0 10px">学生账号管理</div>${studentsHtml}
      <div style="font-weight:700;font-size:15px;margin:14px 0 10px">全班学习概览</div>${overviewHtml || '<div class="muted">暂无数据</div>'}
    </div>` + tabbar();
  },
  newChapterForm() {
    openSheet(`<div class="row" style="font-weight:700;cursor:default">新建章节</div>
      <div class="row" style="text-align:left;border:none;background:transparent;cursor:default">
        <input class="mini-input" id="chFolder" placeholder="文件夹（模块）"/>
        <input class="mini-input" id="chName" placeholder="章节名"/>
      </div>
      <div class="row" onclick="Teacher.createChapter()">创建</div>
      <div class="row cancel" onclick="closeSheet()">取消</div>`);
  },
  async createChapter() {
    try { await API.post("/api/chapters", { folder: document.getElementById("chFolder").value, name: document.getElementById("chName").value }); closeSheet(); await loadChapters(); toast("已创建章节"); render(); }
    catch (e) { toast(e.message); }
  },
  uploadForm(chapterId) {
    openSheet(`<div class="row" style="font-weight:700;cursor:default">上传资料（PDF/PPTX/DOCX/MD/TXT ≤30MB）</div>
      <div class="row" style="text-align:left;border:none;background:transparent;cursor:default"><input type="file" id="matFile" class="mini-input"/></div>
      <div class="row" onclick="Teacher.upload('${chapterId}')">上传并解析</div>
      <div class="row cancel" onclick="closeSheet()">取消</div>`);
  },
  async upload(chapterId) {
    const f = document.getElementById("matFile").files[0];
    if (!f) { toast("请选择文件"); return; }
    const fd = new FormData();
    fd.append("chapter_id", chapterId);
    fd.append("file", f);
    try { const d = await API.upload("/api/materials/upload", fd); closeSheet(); toast("已上传，解析状态：" + (d.parse_status === "parsed" ? "成功" : "失败")); render(); }
    catch (e) { toast(e.message); }
  },
  async delMaterial(id) {
    if (!confirm("确定删除该资料？将进入 7 天软删除窗口。")) return;
    try { await API.del("/api/materials/" + id); toast("已软删除"); render(); }
    catch (e) { toast(e.message); }
  },
  newStudentForm() {
    openSheet(`<div class="row" style="font-weight:700;cursor:default">新建学生账号</div>
      <div class="row" style="text-align:left;border:none;background:transparent;cursor:default">
        <input class="mini-input" id="stUser" placeholder="用户名"/>
        <input class="mini-input" id="stName" placeholder="显示名"/>
        <input class="mini-input" id="stGrade" placeholder="年级（可选）"/>
        <input class="mini-input" id="stPass" type="password" placeholder="初始密码"/>
      </div>
      <div class="row" onclick="Teacher.createStudent()">创建</div>
      <div class="row cancel" onclick="closeSheet()">取消</div>`);
  },
  async createStudent() {
    try {
      await API.post("/api/auth/register", {
        username: document.getElementById("stUser").value,
        display_name: document.getElementById("stName").value,
        grade: document.getElementById("stGrade").value,
        password: document.getElementById("stPass").value,
        role: "student",
      });
      closeSheet(); toast("已创建学生账号"); render();
    } catch (e) { toast(e.message); }
  },
  resetPw(id) {
    openSheet(`<div class="row" style="font-weight:700;cursor:default">重置密码</div>
      <div class="row" style="text-align:left;border:none;background:transparent;cursor:default"><input class="mini-input" id="newPw" type="password" placeholder="新密码（≥6位）"/></div>
      <div class="row" onclick="Teacher.doResetPw('${id}')">确认重置</div>
      <div class="row cancel" onclick="closeSheet()">取消</div>`);
  },
  async doResetPw(id) {
    try { await API.post(`/api/teacher/students/${id}/reset-password`, { new_password: document.getElementById("newPw").value }); closeSheet(); toast("已重置密码"); }
    catch (e) { toast(e.message); }
  },
  async toggleStudent(id, is_active) {
    try { await API.post(`/api/teacher/students/${id}/status`, { is_active: !!is_active }); toast(is_active ? "已启用" : "已停用"); render(); }
    catch (e) { toast(e.message); }
  },

  /* ===== 出题 / 发布 ===== */
  async viewQuiz() {
    let quizzes = [];
    try { quizzes = (await API.get("/api/quizzes")).quizzes || []; } catch (e) {}
    const chks = App.chapters.map(c => `<div class="chk ${this.pubSel[c.id] ? 'on' : ''}" onclick="Teacher.pubSel['${c.id}']=!Teacher.pubSel['${c.id}'];render()"><span class="box">${this.pubSel[c.id] ? '✓' : ''}</span>${esc(c.name)}</div>`).join('');
    const sel = Object.keys(this.pubSel).filter(k => this.pubSel[k]);
    const drafts = quizzes.filter(q => q.status === "draft").map(q => `<div class="card sm" style="border-color:var(--indigo)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px"><div style="font-weight:700">${esc(q.title)}</div><span class="badge na">草稿待确认</span></div>
      <div class="muted" style="font-size:12px;margin-bottom:8px">覆盖：${(q.chapter_ids || []).map(App.chapterName.bind(App)).map(esc).join('、')} · v${q.version}</div>
      <div style="display:flex;gap:8px"><button class="btn teacher sm" style="flex:1" onclick="Teacher.publish('${q.id}')">确认发布</button><button class="mini-btn danger" onclick="Teacher.dropQuiz('${q.id}')">放弃</button></div></div>`).join('');
    const published = quizzes.filter(q => q.status === "published").map(q => `<div class="card sm" style="display:flex;justify-content:space-between;align-items:center">
      <div><div style="font-weight:700">${q.version > 1 ? `<span class="badge ver">v${q.version}</span> ` : ''}${esc(q.title)}</div><div class="muted">覆盖：${(q.chapter_ids || []).map(App.chapterName.bind(App)).map(esc).join('、')}</div></div>
      <span class="mini-btn teacher" onclick="Teacher.revise('${q.id}')">重出</span></div>`).join('');
    return appbar('出题 / 发布', '选章 → 生成草稿 → 确认发布') + `<div class="content">
      <div class="card"><div style="font-weight:700;margin-bottom:6px">① 选择覆盖章节</div>${chks}
        <button class="btn teacher" style="margin-top:12px" onclick="Teacher.draft(${JSON.stringify(sel)})">生成草稿（${sel.length} 章）</button></div>
      ${drafts ? `<div style="font-weight:700;font-size:14px;margin:12px 0 8px">待确认草稿</div>${drafts}` : ''}
      <div style="font-weight:700;font-size:15px;margin:14px 0 10px">已发布的测评</div>${published || '<div class="muted">暂无</div>'}
    </div>` + tabbar();
  },
  async draft(sel) {
    const chapter_ids = (sel || []).filter(Boolean);
    if (!chapter_ids.length) { toast("请至少选择一章"); return; }
    try { await API.post("/api/quizzes/draft", { chapter_ids }); this.pubSel = {}; toast("已生成草稿，请预览后确认发布"); render(); }
    catch (e) { toast(e.message); }
  },
  async publish(id) { try { await API.post(`/api/quizzes/${id}/publish`, {}); toast("已发布，全班可见相同题目"); render(); } catch (e) { toast(e.message); } },
  async dropQuiz(id) { try { await API.del("/api/quizzes/" + id); toast("已放弃草稿"); render(); } catch (e) { toast(e.message); } },
  async revise(id) { try { await API.post(`/api/quizzes/${id}/revision`, {}); toast("已重出为新草稿（旧版保留）"); render(); } catch (e) { toast(e.message); } },

  /* ===== 全班进度 ===== */
  async viewProgress() {
    let overview = { students: [], common_weak_chapters: [] };
    try { overview = await API.get("/api/teacher/overview"); } catch (e) {}
    const cards = (overview.students || []).map(s => `<div class="card"><div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
      <div class="av" style="width:38px;height:38px;border-radius:11px">${esc((s.display_name || '?').charAt(0))}</div><div style="font-weight:700">${esc(s.display_name)}</div></div>
      <div class="stat-row" style="margin:0"><div class="stat"><div class="v" style="color:var(--green);font-size:18px">${s.counts.master}</div><div class="k">已掌握</div></div>
      <div class="stat"><div class="v" style="color:var(--amber);font-size:18px">${s.counts.progress}</div><div class="k">进行中</div></div>
      <div class="stat"><div class="v" style="color:var(--red);font-size:18px">${s.counts.weak}</div><div class="k">薄弱</div></div></div>
      ${(s.weak_chapters || []).length ? `<div class="muted" style="margin-top:10px;font-size:12px">薄弱章节：${s.weak_chapters.map(esc).join('、')}</div>` : ''}</div>`).join('');
    return appbar('全班进度', '按学生聚合') + `<div class="content">
      <div class="card"><div style="font-weight:700;margin-bottom:8px">共性薄弱章节</div>
        ${(overview.common_weak_chapters || []).map(c => `<div class="weak"><span class="badge weak">${esc(c)}</span><div class="muted" style="font-size:12.5px">多名同学待补强</div></div>`).join('') || '<div class="muted">暂无共性薄弱 🎉</div>'}</div>
      ${cards}</div>` + tabbar();
  },

  /* ===== 全班周报 ===== */
  async viewReport() {
    let overview = { students: [], common_weak_chapters: [], student_count: 0 };
    try { overview = await API.get("/api/teacher/overview"); } catch (e) {}
    const weak = overview.common_weak_chapters || [];
    const avg = (overview.students || []).reduce((a, s) => a + (s.counts.master + s.counts.progress), 0);
    return appbar('全班周报', 'RPT-004 聚合') + `<div class="content">
      <div class="report-h teacher"><div class="t">本周 · 全班聚合</div><div class="d">教师视图 · 学习周报</div></div>
      <div class="card"><div style="font-weight:700;margin-bottom:12px">全班概览</div><div class="stat-row" style="margin:0">
        <div class="stat"><div class="v">${overview.student_count || 0}</div><div class="k">学生数</div></div>
        <div class="stat"><div class="v">${(overview.students || []).length}</div><div class="k">活跃学生</div></div>
        <div class="stat"><div class="v">${avg}</div><div class="k">掌握/进行中</div></div></div></div>
      <div class="card"><div style="font-weight:700;margin-bottom:8px">共性薄弱章节</div>
        ${weak.map(c => `<div class="weak"><span class="badge weak">${esc(c)}</span><div class="muted" style="font-size:12.5px">建议下周统一加设巩固测评</div></div>`).join('') || '<div class="muted">暂无共性薄弱 🎉</div>'}</div>
      <div class="card"><div style="font-weight:700;margin-bottom:10px">AI 教学建议</div>
        <div class="ai-tip"><div class="ic">AI</div><div style="font-size:13.5px;line-height:1.5">${weak.length ? `「${weak.map(esc).join('、')}」为全班共性薄弱，建议统一加设巩固测评。` : '本周整体状态良好，可推进新章节并保持间隔复习。'}</div></div></div>
    </div>` + tabbar();
  },
};
