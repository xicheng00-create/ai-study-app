/* 教师视图：管理后台（资料/章节/学生）+ 发布测评 + 全班进度/周报 */
const Teacher = {
  pubSel: {},
  quizConfig: { choice: 10, essay: 5 },   // 100 分组合（QUIZ-005）
  QUIZ_PRESETS: [
    { key: "10c5e", label: "10 选择 + 5 问答", cfg: { choice: 10, essay: 5 } },
    { key: "8c6e", label: "8 选择 + 6 问答", cfg: { choice: 8, essay: 6 } },
    { key: "20c", label: "20 选择", cfg: { choice: 20 } },
  ],
  curSel: {},       // Session 表单章节多选
  async downloadMat(id, filename) {
    try { await API.download(id, filename); } catch (e) { toast(e.message); }
  },
  sessions: [],     // 课程管理缓存（周→节）
  videos: [],

  async render() {
    const h = App.state.hash;
    if (h === "curriculum") return await this.viewCurriculum();
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
      const matHtml = mats.map(m => `<div style="display:flex;align-items:center;gap:8px;font-size:12px;margin-top:6px"><span style="flex:1;min-width:0;word-break:break-word">📄 ${esc(m.original_name)}</span>
        <span class="badge ${m.parse_status === 'parsed' ? 'parse' : 'fail'}" style="flex-shrink:0">${m.parse_status === 'parsed' ? `已解析 ${m.chunk_count} 块` : '解析失败'}</span>
        <span class="mini-btn" style="flex-shrink:0" onclick="Teacher.downloadMat('${m.id}','${esc(m.original_name)}')">下载</span>
        <span class="mini-btn danger" style="flex-shrink:0" onclick="Teacher.delMaterial('${m.id}')">删</span></div>`).join('') || '<div class="muted" style="font-size:12px;margin-top:4px">暂无资料</div>';
      return `<div class="adm-card" style="flex-direction:column;align-items:stretch">
        <div style="display:flex;align-items:flex-start;gap:13px"><div class="av">§</div><div class="meta" style="flex:1;min-width:0"><div class="nm">${esc(c.name)}</div><div class="st">${esc(c.folder || '未分组')} · ${mats.length} 份资料</div></div></div>
        <div style="display:flex;gap:8px;margin-top:10px;justify-content:flex-end"><span class="mini-btn teacher" onclick="Teacher.uploadForm('${c.id}')">上传</span>
          <span class="mini-btn" onclick="Teacher.editChapterForm('${c.id}')">编辑</span>
          <span class="mini-btn danger" onclick="Teacher.delChapter('${c.id}')">删除</span></div><div style="margin-top:12px;padding-left:0">${matHtml}</div></div>`;
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
  editChapterForm(chapterId) {
    const c = App.chapters.find(x => x.id === chapterId);
    openSheet(`<div class="row" style="font-weight:700;cursor:default">编辑章节</div>
      <div class="row" style="text-align:left;border:none;background:transparent;cursor:default">
        <input class="mini-input" id="eFolder" placeholder="文件夹（模块）" value="${esc(c ? (c.folder || '') : '')}"/>
        <input class="mini-input" id="eName" placeholder="章节名" value="${esc(c ? c.name : '')}"/>
      </div>
      <div class="row" onclick="Teacher.doEditChapter('${chapterId}')">保存</div>
      <div class="row cancel" onclick="closeSheet()">取消</div>`);
  },
  async doEditChapter(chapterId) {
    try { await API.put(`/api/chapters/${chapterId}`, { folder: document.getElementById("eFolder").value, name: document.getElementById("eName").value }); closeSheet(); await loadChapters(); toast("已保存"); render(); }
    catch (e) { toast(e.message); }
  },
  async delChapter(chapterId) {
    const c = App.chapters.find(x => x.id === chapterId);
    if (!confirm(`确定删除章节「${c ? c.name : ''}」？其下资料需先删除。`)) return;
    try { await API.del(`/api/chapters/${chapterId}`); await loadChapters(); toast("已删除章节"); render(); }
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

  /* ===== 课程管理（Session / 视频课 CRUD + 发布状态机）===== */
  async viewCurriculum() {
    let weeks = [];
    try { weeks = (await API.get("/api/curriculum")).weeks || []; } catch (e) {}
    try { this.videos = (await API.get("/api/curriculum/videos")).videos || []; } catch (e) { this.videos = []; }
    this.sessions = [];
    weeks.forEach(w => (w.sessions || []).forEach(s => this.sessions.push(s)));

    const sessHtml = weeks.length ? weeks.map(w => {
      const ss = (w.sessions || []).map(s => {
        const badge = s.status === 'published' ? '<span class="badge master">已发布</span>' : '<span class="badge na">草稿</span>';
        const vids = (s.videos || []).map(v => `<div class="mat">▶ ${esc(v.title)}${v.platform ? ` · ${esc(v.platform)}` : ''}</div>`).join('') || '<div class="muted" style="font-size:12px">暂无视频</div>';
        return `<div class="adm-card" style="flex-direction:column;align-items:stretch">
          <div style="display:flex;align-items:center;gap:10px"><div style="font-weight:700;flex:1">第${w.week_no}周 · 第${s.session_no}节 ${esc(s.title)}</div>${badge}</div>
          ${s.goal ? `<div class="muted" style="font-size:12px;margin:4px 0">🎯 ${esc(s.goal)}</div>` : ''}
          <div class="muted" style="font-size:12px;margin-bottom:4px">关联章节：${(s.chapter_ids || []).map(App.chapterName.bind(App)).map(esc).join('、') || '无'}</div>
          <div>${vids}</div>
          <div style="display:flex;gap:8px;margin-top:10px">
            ${s.status === 'published'
              ? `<button class="mini-btn" onclick="Teacher.unpublishSession('${s.id}')">取消发布</button>`
              : `<button class="mini-btn teacher" onclick="Teacher.publishSession('${s.id}')">发布</button>`}
            <button class="mini-btn" onclick="Teacher.editSessionForm('${s.id}')">编辑</button>
            <button class="mini-btn danger" onclick="Teacher.delSession('${s.id}')">删除</button>
          </div>
        </div>`;
      }).join('');
      return `<div class="week-title">第 ${w.week_no} 周</div>${ss}`;
    }).join('') : '<div class="muted">暂无 Session，先新建</div>';

    const vidsHtml = this.videos.map(v => `<div class="adm-card">
      <div class="meta"><div class="nm">▶ ${esc(v.title)}</div><div class="st">${v.week_no != null ? '第' + v.week_no + '周' : '整周'}${v.session_no != null ? ' · 第' + v.session_no + '节' : ''} · ${esc(v.platform || '外链')} · ${v.status === 'published' ? '已发布' : '草稿'}</div></div>
      <button class="mini-btn" onclick="Teacher.editVideoForm('${v.id}')">编辑</button>
      <button class="mini-btn danger" onclick="Teacher.delVideo('${v.id}')">删</button>
    </div>`).join('') || '<div class="muted">暂无视频课</div>';

    return appbar('课程管理', '学习路径 · 发布后学生可见') + `<div class="content">
      <button class="btn teacher" style="margin-bottom:8px" onclick="Teacher.newSessionForm()">＋ 新建 Session</button>
      <button class="btn sec" style="margin-bottom:14px" onclick="Teacher.newVideoForm()">＋ 新建视频课</button>
      <div style="font-weight:700;font-size:15px;margin:4px 0 10px">学习路径（周→节）</div>${sessHtml}
      <div style="font-weight:700;font-size:15px;margin:14px 0 10px">视频课（外链）</div>${vidsHtml}
    </div>` + tabbar();
  },

  _splitTags(raw) { return (raw || "").split(/[,，]/).map(s => s.trim()).filter(Boolean); },
  renderCurChecks() {
    const el = document.getElementById("curChecks");
    if (!el) return;
    el.innerHTML = App.chapters.map(c => `<div class="chk ${this.curSel[c.id] ? 'on' : ''}" onclick="Teacher.curSel['${c.id}']=!Teacher.curSel['${c.id}'];Teacher.renderCurChecks()"><span class="box">${this.curSel[c.id] ? '✓' : ''}</span>${esc(c.name)}</div>`).join('') || '<div class="muted" style="font-size:12px">暂无章节</div>';
  },

  newSessionForm() {
    this.curSel = {};
    openSheet(`<div class="row" style="font-weight:700;cursor:default">新建 Session（草稿）</div>
      <div class="row" style="text-align:left;border:none;background:transparent;cursor:default">
        <input class="mini-input" id="sWeek" placeholder="周次（如 1）"/>
        <input class="mini-input" id="sNo" placeholder="节次（如 1）"/>
        <input class="mini-input" id="sTitle" placeholder="标题"/>
        <input class="mini-input" id="sGoal" placeholder="目标（可选）"/>
        <input class="mini-input" id="sTags" placeholder="概念标签，逗号分隔（可选）"/>
        <div style="font-size:12.5px;font-weight:700;margin:10px 0 4px">关联章节</div>
        <div id="curChecks">${App.chapters.map(c => `<div class="chk" onclick="Teacher.curSel['${c.id}']=!Teacher.curSel['${c.id}'];Teacher.renderCurChecks()"><span class="box"></span>${esc(c.name)}</div>`).join('') || '<div class="muted" style="font-size:12px">暂无章节</div>'}</div>
      </div>
      <div class="row" onclick="Teacher.createSession()">创建</div>
      <div class="row cancel" onclick="closeSheet()">取消</div>`);
  },
  async createSession() {
    const chapter_ids = Object.keys(this.curSel || {}).filter(k => this.curSel[k]);
    try {
      await API.post("/api/curriculum/sessions", {
        week_no: parseInt(document.getElementById("sWeek").value) || 0,
        session_no: parseInt(document.getElementById("sNo").value) || 0,
        title: document.getElementById("sTitle").value,
        goal: document.getElementById("sGoal").value,
        chapter_ids,
        concept_tags: this._splitTags(document.getElementById("sTags").value),
      });
      closeSheet(); toast("已创建 Session（草稿）"); render();
    } catch (e) { toast(e.message); }
  },
  editSessionForm(id) {
    const s = (this.sessions || []).find(x => x.id === id);
    if (!s) return;
    this.curSel = {};
    (s.chapter_ids || []).forEach(cid => { this.curSel[cid] = true; });
    openSheet(`<div class="row" style="font-weight:700;cursor:default">编辑 Session</div>
      <div class="row" style="text-align:left;border:none;background:transparent;cursor:default">
        <input class="mini-input" id="sWeek" placeholder="周次" value="${s.week_no}"/>
        <input class="mini-input" id="sNo" placeholder="节次" value="${s.session_no}"/>
        <input class="mini-input" id="sTitle" placeholder="标题" value="${esc(s.title)}"/>
        <input class="mini-input" id="sGoal" placeholder="目标" value="${esc(s.goal || '')}"/>
        <input class="mini-input" id="sTags" placeholder="概念标签，逗号分隔" value="${esc((s.concept_tags || []).join(','))}"/>
        <div style="font-size:12.5px;font-weight:700;margin:10px 0 4px">关联章节</div>
        <div id="curChecks">${App.chapters.map(c => `<div class="chk ${this.curSel[c.id] ? 'on' : ''}" onclick="Teacher.curSel['${c.id}']=!Teacher.curSel['${c.id}'];Teacher.renderCurChecks()"><span class="box">${this.curSel[c.id] ? '✓' : ''}</span>${esc(c.name)}</div>`).join('') || '<div class="muted" style="font-size:12px">暂无章节</div>'}</div>
      </div>
      <div class="row" onclick="Teacher.doEditSession('${id}')">保存</div>
      <div class="row cancel" onclick="closeSheet()">取消</div>`);
  },
  async doEditSession(id) {
    const chapter_ids = Object.keys(this.curSel || {}).filter(k => this.curSel[k]);
    try {
      await API.put(`/api/curriculum/sessions/${id}`, {
        week_no: parseInt(document.getElementById("sWeek").value) || 0,
        session_no: parseInt(document.getElementById("sNo").value) || 0,
        title: document.getElementById("sTitle").value,
        goal: document.getElementById("sGoal").value,
        chapter_ids,
        concept_tags: this._splitTags(document.getElementById("sTags").value),
      });
      closeSheet(); toast("已保存"); render();
    } catch (e) { toast(e.message); }
  },
  async delSession(id) {
    if (!confirm("删除该 Session？其下视频一并删除，章节/资料保留。")) return;
    try { await API.del(`/api/curriculum/sessions/${id}`); toast("已删除 Session"); render(); }
    catch (e) { toast(e.message); }
  },
  async publishSession(id) {
    try { await API.post(`/api/curriculum/sessions/${id}/publish`, {}); toast("已发布，学生立即可见"); render(); }
    catch (e) { toast(e.message); }
  },
  async unpublishSession(id) {
    try { await API.post(`/api/curriculum/sessions/${id}/unpublish`, {}); toast("已取消发布（回草稿）"); render(); }
    catch (e) { toast(e.message); }
  },

  newVideoForm() {
    openSheet(`<div class="row" style="font-weight:700;cursor:default">新建视频课</div>
      <div class="row" style="text-align:left;border:none;background:transparent;cursor:default">
        <input class="mini-input" id="vTitle" placeholder="标题"/>
        <input class="mini-input" id="vUrl" placeholder="视频 URL"/>
        <input class="mini-input" id="vPlatform" placeholder="平台（bilibili / ima…，可选）"/>
        <input class="mini-input" id="vWeek" placeholder="周次（可选，整周留空）"/>
        <input class="mini-input" id="vNo" placeholder="节次（可选）"/>
        <input class="mini-input" id="vTags" placeholder="概念标签，逗号分隔（可选）"/>
      </div>
      <div class="row" onclick="Teacher.createVideo()">创建</div>
      <div class="row cancel" onclick="closeSheet()">取消</div>`);
  },
  async createVideo() {
    const week = document.getElementById("vWeek").value;
    const no = document.getElementById("vNo").value;
    try {
      await API.post("/api/curriculum/videos", {
        title: document.getElementById("vTitle").value,
        url: document.getElementById("vUrl").value,
        platform: document.getElementById("vPlatform").value,
        week_no: week === "" ? null : (parseInt(week) || 0),
        session_no: no === "" ? null : (parseInt(no) || 0),
        concept_tags: this._splitTags(document.getElementById("vTags").value),
      });
      closeSheet(); toast("已创建视频课"); render();
    } catch (e) { toast(e.message); }
  },
  editVideoForm(id) {
    const v = (this.videos || []).find(x => x.id === id);
    if (!v) return;
    openSheet(`<div class="row" style="font-weight:700;cursor:default">编辑视频课</div>
      <div class="row" style="text-align:left;border:none;background:transparent;cursor:default">
        <input class="mini-input" id="vTitle" placeholder="标题" value="${esc(v.title)}"/>
        <input class="mini-input" id="vUrl" placeholder="URL" value="${esc(v.url)}"/>
        <input class="mini-input" id="vPlatform" placeholder="平台" value="${esc(v.platform || '')}"/>
        <input class="mini-input" id="vWeek" placeholder="周次" value="${v.week_no == null ? '' : v.week_no}"/>
        <input class="mini-input" id="vNo" placeholder="节次" value="${v.session_no == null ? '' : v.session_no}"/>
        <input class="mini-input" id="vTags" placeholder="概念标签" value="${esc((v.concept_tags || []).join(','))}"/>
      </div>
      <div class="row" onclick="Teacher.doEditVideo('${id}')">保存</div>
      <div class="row cancel" onclick="closeSheet()">取消</div>`);
  },
  async doEditVideo(id) {
    const week = document.getElementById("vWeek").value;
    const no = document.getElementById("vNo").value;
    try {
      await API.put(`/api/curriculum/videos/${id}`, {
        title: document.getElementById("vTitle").value,
        url: document.getElementById("vUrl").value,
        platform: document.getElementById("vPlatform").value,
        week_no: week === "" ? null : (parseInt(week) || 0),
        session_no: no === "" ? null : (parseInt(no) || 0),
        concept_tags: this._splitTags(document.getElementById("vTags").value),
      });
      closeSheet(); toast("已保存"); render();
    } catch (e) { toast(e.message); }
  },
  async delVideo(id) {
    if (!confirm("确定删除该视频课？")) return;
    try { await API.del(`/api/curriculum/videos/${id}`); toast("已删除视频课"); render(); }
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
      <div class="muted" style="font-size:12px;margin-bottom:8px">覆盖：${(q.chapter_ids || []).map(App.chapterName.bind(App)).map(esc).join('、')} · v${q.version} · ${q.total_points} 分</div>
      <div style="display:flex;gap:8px"><button class="btn teacher sm" style="flex:1" onclick="Teacher.publish('${q.id}')">确认发布</button><button class="mini-btn danger" onclick="Teacher.dropQuiz('${q.id}')">放弃</button></div></div>`).join('');
    const published = quizzes.filter(q => q.status === "published").map(q => `<div class="card sm" style="display:flex;justify-content:space-between;align-items:center">
      <div><div style="font-weight:700">${q.version > 1 ? `<span class="badge ver">v${q.version}</span> ` : ''}${esc(q.title)}</div><div class="muted">覆盖：${(q.chapter_ids || []).map(App.chapterName.bind(App)).map(esc).join('、')} · ${q.total_points} 分</div></div>
      <span class="mini-btn teacher" onclick="Teacher.revise('${q.id}')">重出</span></div>`).join('');
    const cfg = this.quizConfig || {};
    const presetHtml = this.QUIZ_PRESETS.map(p => {
      const on = (cfg.choice || 0) === (p.cfg.choice || 0) && (cfg.bool || 0) === (p.cfg.bool || 0) && (cfg.essay || 0) === (p.cfg.essay || 0);
      return `<span class="pill ${on ? 'active' : ''}" style="cursor:pointer" onclick="Teacher.setQuizPreset('${p.key}')">${p.label}</span>`;
    }).join('');
    const total = (cfg.choice || 0) * 5 + (cfg.bool || 0) * 5 + (cfg.essay || 0) * 10;
    return appbar('出题 / 发布', '选章 → 100 分组合 → 生成草稿 → 确认发布') + `<div class="content">
      <div class="card"><div style="font-weight:700;margin-bottom:6px">① 选择覆盖章节</div>${chks}</div>
      <div class="card"><div style="font-weight:700;margin-bottom:6px">② 选择 100 分组合</div>
        <div class="pill-wrap" style="margin-bottom:8px">${presetHtml}</div>
        <div style="display:flex;gap:6px;align-items:center">
          <input class="mini-input" id="cfgChoice" placeholder="选择" style="flex:1" value="${cfg.choice || ''}"/>
          <input class="mini-input" id="cfgBool" placeholder="是非" style="flex:1" value="${cfg.bool || ''}"/>
          <input class="mini-input" id="cfgEssay" placeholder="问答" style="flex:1" value="${cfg.essay || ''}"/>
          <span class="mini-btn" onclick="Teacher.applyCustomConfig()">自定义</span>
        </div>
        <div class="muted" style="font-size:12px;margin-top:6px">当前组合：${total} 分（${total === 100 ? '✓ 有效' : '须为 100'})</div>
        <button class="btn teacher" style="margin-top:12px" onclick="Teacher.draft()">生成草稿（${sel.length} 章）</button></div>
      ${drafts ? `<div style="font-weight:700;font-size:14px;margin:12px 0 8px">待确认草稿</div>${drafts}` : ''}
      <div style="font-weight:700;font-size:15px;margin:14px 0 10px">已发布的测评</div>${published || '<div class="muted">暂无</div>'}
    </div>` + tabbar();
  },
  setQuizPreset(key) {
    const p = this.QUIZ_PRESETS.find(x => x.key === key);
    if (p) { this.quizConfig = Object.assign({}, p.cfg); render(); }
  },
  applyCustomConfig() {
    const n = (id) => { const v = document.getElementById(id).value.trim(); return v === "" ? 0 : (parseInt(v) || 0); };
    const cfg = { choice: n("cfgChoice"), bool: n("cfgBool"), essay: n("cfgEssay") };
    const total = (cfg.choice || 0) * 5 + (cfg.bool || 0) * 5 + (cfg.essay || 0) * 10;
    if (total !== 100) { toast("自定义组合合计须为 100 分"); return; }
    this.quizConfig = cfg; render();
  },
  async draft() {
    const chapter_ids = Object.keys(this.pubSel || {}).filter(k => this.pubSel[k]);
    if (!chapter_ids.length) { toast("请至少选择一章"); return; }
    try { await API.post("/api/quizzes/draft", { chapter_ids, config: this.quizConfig || {} }); this.pubSel = {}; toast("已生成草稿，请预览后确认发布"); render(); }
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
      <div class="av" style="width:38px;height:38px;border-radius:11px">${esc((s.display_name || '?').charAt(0))}</div><div style="font-weight:700">${esc(s.display_name)}</div>
      <span class="mini-btn teacher" style="margin-left:auto" onclick="Teacher.openReview('${s.id}')">测评覆核</span></div>
      <div class="stat-row" style="margin:0"><div class="stat"><div class="v" style="color:var(--green);font-size:18px">${s.counts.master}</div><div class="k">已掌握</div></div>
      <div class="stat"><div class="v" style="color:var(--amber);font-size:18px">${s.counts.progress}</div><div class="k">进行中</div></div>
      <div class="stat"><div class="v" style="color:var(--red);font-size:18px">${s.counts.weak}</div><div class="k">薄弱</div></div></div>
      ${(s.weak_chapters || []).length ? `<div class="muted" style="margin-top:10px;font-size:12px">薄弱章节：${s.weak_chapters.map(esc).join('、')}</div>` : ''}</div>`).join('');
    return appbar('全班进度', '按学生聚合') + `<div class="content">
      <div class="card"><div style="font-weight:700;margin-bottom:8px">共性薄弱章节</div>
        ${(overview.common_weak_chapters || []).map(c => `<div class="weak"><span class="badge weak">${esc(c)}</span><div class="muted" style="font-size:12.5px">多名同学待补强</div></div>`).join('') || '<div class="muted">暂无共性薄弱 🎉</div>'}</div>
      ${cards}</div>` + tabbar();
  },

  /* ===== 测评覆核改分（QUIZ-009）===== */
  async openReview(studentId) {
    let d = null;
    try { d = await API.get(`/api/teacher/students/${studentId}/quizzes`); }
    catch (e) { toast(e.message); return; }
    const name = (d.student && d.student.display_name) || '';
    const subs = (d.attempts || []).map(s => {
      const qs = (s.details || []).map(q => `
        <div style="padding:8px 0;border-bottom:1px solid var(--line,#eee)">
          <div style="font-size:12.5px">${esc(q.content)}<span class="badge ${q.type === 'essay' ? 'prog' : 'na'}" style="margin-left:6px">${q.type === 'essay' ? '问答' : '选择/是非'} · ${q.points} 分</span></div>
          <div class="muted" style="font-size:12px;margin-top:4px">AI 评分：${q.is_reviewed ? `<s>${q.score}</s> → 已覆核 <b>${q.reviewed_score}</b>` : q.score}</div>
          <div style="display:flex;gap:6px;margin-top:6px;align-items:center">
            <input class="mini-input" id="rv_${q.id}" placeholder="0~${q.points}" style="flex:1"/>
            <span class="mini-btn teacher" onclick="Teacher.saveReview('${q.id}')">保存</span>
          </div>
        </div>`).join('');
      return `<div style="margin:10px 0;border:1px solid var(--line,#ddd);border-radius:10px;padding:10px">
        <div style="font-weight:700;font-size:13px">${esc(s.title)} · v${s.version}</div>
        <div class="muted" style="font-size:12px;margin-bottom:4px">得分率 ${s.score}%</div>${qs}</div>`;
    }).join('') || '<div class="muted">该生暂无作答记录</div>';
    openSheet(`<div class="row" style="font-weight:700;cursor:default">测评覆核改分 · ${esc(name)}</div>
      <div style="max-height:62vh;overflow:auto;padding:0 16px">${subs}</div>
      <div class="row cancel" onclick="closeSheet()">关闭</div>`);
  },
  async saveReview(attemptId) {
    const el = document.getElementById("rv_" + attemptId);
    const v = el ? el.value.trim() : "";
    if (v === "") { toast("请输入覆核分数"); return; }
    try { await API.put(`/api/attempts/${attemptId}/review`, { score: Number(v) }); toast("已保存覆核分数"); }
    catch (e) { toast(e.message); }
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
