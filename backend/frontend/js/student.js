/* 学生视图：学习（引导对话）/ 测评 / 进度 / 班级 */
const Student = {
  convId: null,
  messages: [],
  turn: 0,
  quiz: null,
  answers: {},
  result: null,
  practiceView: false,   // 自主练习入口（与教师测评列表并列）
  practice: null,        // 当前练习会话（含 questions，无 answer_key）
  practiceResult: null,  // {summary, detail}：批改结果
  practiceChapters: [],  // 练习选章（可多选）
  practiceSessions: [],  // 练习历史列表
  relatedVideos: [],   // 最近一次对话返回的相关视频课（CHAT-010）
  askCtx: null,        // 从「路径」进入提问时携带的 chapter_ids/concept_tags
  curriculum: null,
  pendingReply: false, // 等待 DeepSeek 回复期间驱动思考气泡（避免被 render 重载覆盖）
  convs: [],          // 学习页对话 pill 列表缓存（长按删除时查标题）
  classCat: 0,        // 班级排行榜当前分类（0~5）
  classQuizId: null,  // 测评分数榜当前选中的测评
  _pressTimer: null,  // 长按手势定时器
  _pressX: 0, _pressY: 0, _touchTs: 0, _suppressClick: false,

  async render() {
    const h = App.state.hash;
    if (h === "quiz") {
      if (this.result) return this.viewResult();
      if (this.quiz) return this.viewQuizTake();
      if (this.practiceResult) return this.viewPracticeResult();
      if (this.practice) return this.viewPracticeTake();
      if (this.practiceView) return await this.viewPractice();
      return await this.viewQuizList();
    }
    if (h === "path") return await this.viewPath();
    if (h === "progress") return await this.viewProgress();
    if (h === "class") return await this.viewClass();
    return await this.viewLearn();
  },

  /* ===== 学习：章节 + 引导式对话 ===== */
  async viewLearn() {
    let convs = [];
    try { convs = (await API.get("/api/conversations")).conversations || []; } catch (e) { convs = []; }
    this.convs = convs;
    if (!this.convId && convs.length) this.convId = convs[0].id;
    if (this.convId) {
      try { const d = await API.get("/api/conversations/" + this.convId); this.messages = d.messages || []; } catch (e) { this.messages = []; }
    }
    const chapterCards = App.chapters.map(c => `<div class="chapter ${App.activeChapter === c.id ? 'active' : ''}" onclick="Student.selectChapter('${c.id}')">
      <div><div class="nm">${esc(c.name)}</div><div class="mt">${esc(c.folder || '未分组')}</div></div></div>`).join('');
    // ≥2 章节时资料库改为横向滑动卡片组（单章保持竖排）
    const chapters = App.chapters.length >= 2 ? `<div class="chapter-scroll">${chapterCards}</div>` : chapterCards;
    const convChips = convs.map(c => `<span class="pill ${this.convId === c.id ? 'active' : ''}" style="cursor:pointer" onclick="Student.selectConv('${c.id}')" onmousedown="Student.pressStart(event,'${c.id}')" onmouseup="Student.pressEnd(event)" onmouseleave="Student.pressEnd(event)" ontouchstart="Student.pressStart(event,'${c.id}')" ontouchend="Student.pressEnd(event)" ontouchmove="Student.pressMove(event)" ontouchcancel="Student.pressEnd(event)"><span class="pill-t">${esc(c.title)}</span></span>`).join('')
      + `<span class="pill" style="cursor:pointer" onclick="Student.newConv()">＋ 新对话</span>`;
    const msgsHtml = this.messages.map(m => `<div class="msg ${m.role === 'user' ? 'user' : 'bot'}">${m.role === 'user' ? '' : '<div class="who">TUTOR</div>'}${esc(m.content)}</div>`).join('')
      + (this.pendingReply ? `<div class="msg bot"><div class="who">TUTOR</div><span class="typing"><span></span><span></span><span></span></span></div>` : '');
    const msgs = msgsHtml
      || `<div class="muted" style="padding:12px 0">${App.activeChapter ? `已选择：${esc(App.chapterName(App.activeChapter))}，开始提问（不会直接给答案）` : '请从上方资料库选择章节，开始提问'}</div>`;
    const relatedHtml = (this.relatedVideos || []).length ? `<div class="card sm" style="margin-top:12px">
      <div style="font-weight:700;font-size:13px;margin-bottom:8px">🎬 相关视频课（学员自选观看）</div>
      ${this.relatedVideos.map(v => `<a class="video-chip" href="${esc(v.url)}" target="_blank" rel="noopener noreferrer">▶ ${esc(v.title)}${v.platform ? ` · ${esc(v.platform)}` : ''}</a>`).join('')}
      </div>` : '';

    return appbar('学习', '引导式辅导 · 不直接给答案') +
    `<div class="content chat-view">
      <div class="pill-wrap" style="margin-bottom:10px">
        <span class="pill active">🧑‍🎓 引导式</span>
      </div>
      <div class="gate">🛡️ 回答由 AI 生成，请核对资料原文 · 越界内容已拦截</div>
      <div class="card sm" style="margin-bottom:12px"><div style="font-weight:700;font-size:13px;margin-bottom:8px">📚 资料库（点选范围）</div>${chapters || '<div class="muted">暂无章节</div>'}</div>
      <div class="pill-wrap" style="margin-bottom:10px">${convChips}</div>
      <div class="pill" style="margin-bottom:10px">🧭 第 ${this.turn} / 12 轮</div>
      <div class="chat">${msgs}</div>
      ${relatedHtml}
    </div>
    <div class="composer"><input id="chatInput" placeholder="回答引导问题，或追问…" onkeydown="if(event.key==='Enter')Student.send()"/><button class="send" onclick="Student.send()">↑</button></div>` + tabbar();
  },
  selectChapter(id) { App.activeChapter = id; render(); },
  selectConv(id) {
    // 长按弹删除后浏览器会补发 click，这里抑制以免误切换
    if (this._suppressClick) { this._suppressClick = false; return; }
    this.convId = id; render();
  },
  /* 对话 pill 长按删除：touchstart/touchend + mousedown/mouseup 双兼容 */
  pressStart(e, id) {
    // 忽略 touchend 后浏览器派生的合成 mouse 事件，避免长按后误触发 click
    if (e.type === "mousedown" && this._touchTs && Date.now() - this._touchTs < 700) return;
    const p = (e.touches && e.touches[0]) || e;
    this._pressX = p.clientX; this._pressY = p.clientY;
    this._suppressClick = false;
    clearTimeout(this._pressTimer);
    this._pressTimer = setTimeout(() => { this._suppressClick = true; this.confirmDeleteConv(id); }, 600);
  },
  pressMove(e) {
    const p = e.touches && e.touches[0];
    if (p && (Math.abs(p.clientX - this._pressX) > 10 || Math.abs(p.clientY - this._pressY) > 10)) {
      clearTimeout(this._pressTimer);
    }
  },
  pressEnd(e) {
    if (e.type === "touchend" || e.type === "touchcancel") this._touchTs = Date.now();
    clearTimeout(this._pressTimer);
    setTimeout(() => { this._suppressClick = false; }, 400);
  },
  confirmDeleteConv(id) {
    const c = (this.convs || []).find(x => x.id === id);
    openSheet(`<div class="row" style="font-weight:700">删除对话</div>
      <div class="row" style="text-align:left;border:none;background:transparent;cursor:default;font-size:13px;color:var(--text-2)">确定删除「${esc(c ? c.title : '该对话')}」？删除后对话记录不可恢复。</div>
      <div class="row danger" onclick="Student.delConv('${id}')">删除对话</div>
      <div class="row cancel" onclick="closeSheet()">取消</div>`);
  },
  async newConv() {
    try {
      const d = await API.post("/api/conversations", { chapter_id: App.activeChapter, title: "新对话" });
      this.convId = d.id; this.messages = []; this.turn = 0;
      render(); toast("已新建对话");
    } catch (e) { toast(e.message); }
  },
  async send() {
    const input = document.getElementById("chatInput");
    const content = (input.value || "").trim();
    if (!content) return;
    if (!this.convId) { await this.newConv(); }
    input.value = "";
    this.messages.push({ role: "user", content });
    this.pendingReply = true;   // 显示思考气泡（即时反馈）
    render();
    try {
      const payload = { content, chapter_id: App.activeChapter };
      // 从「路径」进入提问时，携带 session 的 chapter_ids/concept_tags 供视频推荐
      if (this.askCtx) {
        payload.chapter_ids = this.askCtx.chapter_ids || [];
        payload.concept_tags = this.askCtx.concept_tags || [];
      }
      const d = await API.post(`/api/conversations/${this.convId}/message`, payload);
      this.messages.push({ role: "assistant", content: d.reply });
      this.turn = d.turn;
      this.relatedVideos = d.related_videos || [];
      this.pendingReply = false;
      render();
    } catch (e) {
      this.pendingReply = false;
      toast(e.message); render();
    }
  },
  async delConv(id) {
    closeSheet();
    try {
      await API.del("/api/conversations/" + id);
      this.convId = null; this.messages = []; this.turn = 0;
      render(); toast("已删除对话");
    } catch (e) { toast(e.message); }
  },

  async downloadMat(id, filename) {
    try { await API.download(id, filename); } catch (e) { toast(e.message); }
  },

  /* ===== 学习路径（周→节手风琴）===== */
  async viewPath() {
    let weeks = [];
    try { weeks = (await API.get("/api/curriculum")).weeks || []; } catch (e) { weeks = []; }
    this.curriculum = weeks;
    const body = weeks.length ? weeks.map(w => {
      const ss = (w.sessions || []).map(s => {
        const chaps = (s.chapters || []).map(c => `<span class="pill">${esc(c.name)}</span>`).join('') || '';
        const mats = (s.materials || []).map(m => `<div class="mat">📄 ${esc(m.original_name || m.filename)} <span class="dl" onclick="Student.downloadMat('${m.id}','${esc(m.original_name || m.filename)}')">⬇ 下载</span></div>`).join('') || '<div class="muted" style="font-size:12.5px">暂无资料</div>';
        const vids = (s.videos || []).map(v => `<a class="video-chip" href="${esc(v.url)}" target="_blank" rel="noopener noreferrer">▶ ${esc(v.title)}${v.platform ? ` · ${esc(v.platform)}` : ''}</a>`).join('') || '<div class="muted" style="font-size:12.5px">暂无视频</div>';
        const tags = (s.concept_tags || []).map(t => `<span class="badge ver">${esc(t)}</span>`).join('') || '';
        return `<details class="acc">
          <summary><div class="acc-t"><b>第${w.week_no}周 · 第${s.session_no}节</b><span>${esc(s.title)}</span></div></summary>
          <div class="acc-body">
            ${s.goal ? `<div class="muted" style="margin-bottom:8px">🎯 ${esc(s.goal)}</div>` : ''}
            ${tags ? `<div class="pill-wrap" style="margin-bottom:8px">${tags}</div>` : ''}
            ${chaps ? `<div class="pill-wrap" style="margin-bottom:8px">${chaps}</div>` : ''}
            <div style="font-weight:600;font-size:12.5px;margin-bottom:6px">📚 资料</div>${mats}
            <div style="font-weight:600;font-size:12.5px;margin:10px 0 6px">🎬 视频课（外链，自行观看）</div>${vids}
            <button class="btn sm" style="margin-top:12px" onclick="Student.askSession('${s.id}')">💬 去提问</button>
          </div>
        </details>`;
      }).join('');
      return `<div class="week-title">第 ${w.week_no} 周</div>${ss}`;
    }).join('') : '<div class="note"><div class="big">📖</div>老师尚未发布学习路径</div>';
    return appbar('学习路径', '8 周 · 周/节进度') + `<div class="content">${body}</div>` + tabbar();
  },

  askSession(sessionId) {
    const weeks = this.curriculum || [];
    let s = null;
    for (const w of weeks) for (const x of (w.sessions || [])) if (x.id === sessionId) { s = x; break; }
    const chapter_ids = (s && s.chapter_ids) || [];
    this.askCtx = { chapter_ids, concept_tags: (s && s.concept_tags) || [] };
    App.activeChapter = chapter_ids[0] || null;
    this.relatedVideos = [];
    App.state.hash = "learn";
    render();
    toast("已进入该节提问，输入你的问题吧");
  },

  /* ===== 测评 ===== */
  async viewQuizList() {
    let quizzes = [];
    try { quizzes = (await API.get("/api/quizzes")).quizzes || []; } catch (e) { quizzes = []; }
    const list = quizzes.map(q => {
      const badge = q.taken ? `<span class="badge master">已完成 ${q.score}</span>` : `<span class="badge prog">待完成</span>`;
      const ver = q.version > 1 ? `<span class="badge ver">v${q.version}</span> ` : '';
      return `<div class="qcard" onclick="Student.openQuiz('${q.id}')"><div class="ic">📝</div>
        <div class="meta"><div class="t">${ver}${esc(q.title)}</div><div class="s">覆盖：${(q.chapter_ids || []).map(App.chapterName.bind(App)).map(esc).join('、')}</div></div>
        <div style="text-align:right">${badge}</div></div>`;
    }).join('') || '<div class="muted">老师尚未发布测评</div>';
    const practiceEntry = `<div class="qcard" style="border-color:var(--coral)" onclick="Student.enterPractice()"><div class="ic">🎯</div>
      <div class="meta"><div class="t">自主练习</div><div class="s">根据资料 AI 生成 · 即答即批</div></div></div>`;
    return appbar('测评', '教师发布 · 全班同题') + `<div class="content">${practiceEntry}${list}</div>` + tabbar();
  },
  async openQuiz(id) {
    try { this.quiz = await API.get("/api/quizzes/" + id); this.answers = {}; this.result = null; render(); }
    catch (e) { toast(e.message); }
  },
  viewQuizTake() {
    const q = this.quiz.quiz;
    const qs = (this.quiz.questions || []).map((item, i) => {
      if (item.type === "essay") return `<div class="q"><div class="qt"><span class="n">${i + 1}</span><span>${esc(item.content)}<b class="pts">${item.points} 分</b></span></div><textarea id="ans_${item.id}" placeholder="输入你的回答…"></textarea></div>`;
      // bool 是非题：无 options，固定渲染「正确 / 错误」两个按钮
      if (item.type === "bool") {
        const boolOpts = ['正确', '错误'].map(v => `<div class="opt" id="opt_${item.id}_${v}" onclick="Student.pick('${item.id}','${v}')"><span class="dot"></span>${v}</div>`).join('');
        return `<div class="q"><div class="qt"><span class="n">${i + 1}</span><span>${esc(item.content)}<b class="pts">${item.points} 分</b></span></div>${boolOpts}</div>`;
      }
      const opts = (item.options || []).map((o, oi) => `<div class="opt" id="opt_${item.id}_${oi}" onclick="Student.pick('${item.id}',${oi})"><span class="dot"></span>${esc(o)}</div>`).join('');
      return `<div class="q"><div class="qt"><span class="n">${i + 1}</span><span>${esc(item.content)}<b class="pts">${item.points} 分</b></span></div>${opts}</div>`;
    }).join('');
    return appbar('测评', esc(q.title)) +
    `<div class="content"><div class="card sm" style="margin-bottom:12px">覆盖章节：${(q.chapter_ids || []).map(App.chapterName.bind(App)).map(c => `<span class="pill" style="margin-right:6px">${esc(c)}</span>`).join('')}</div>
      ${qs}<button class="btn" onclick="Student.submit()">提交并批改</button>
      <button class="btn ghost" style="margin-top:8px" onclick="App.activeQuiz=null;render()">返回列表</button></div>` + tabbar();
  },
  pick(qid, val) {
    // val：choice 传选项索引、bool 传「正确/错误」文本；统一存字符串供后端比对
    this.answers[qid] = String(val);
    const parent = document.getElementById("opt_" + qid + "_" + val).parentElement;
    parent.querySelectorAll(".opt").forEach(o => o.classList.remove("chosen"));
    document.getElementById("opt_" + qid + "_" + val).classList.add("chosen");
  },
  async submit() {
    const answers = (this.quiz.questions || []).map(q => {
      let ans = this.answers[q.id] || "";
      if (q.type === "essay") ans = document.getElementById("ans_" + q.id).value || "";
      return { question_id: q.id, answer: ans };
    });
    try {
      const d = await API.post(`/api/quizzes/${this.quiz.quiz.id}/attempts`, { answers });
      this.result = d;
      try { this.result.report = await API.get(`/api/quizzes/${this.quiz.quiz.id}/report`); } catch (e) { this.result.report = { wrong: [] }; }
      render();
    } catch (e) { toast(e.message); }
  },
  viewResult() {
    const r = this.result || {};
    const wrong = (r.report && r.report.wrong) || [];
    const wrongHtml = wrong.length ? wrong.map(w => `<div class="card sm" style="border-color:#FAD9D6"><div style="font-size:13px"><b>题：</b>${esc(w.content)}</div>
      <div style="font-size:13px;margin-top:5px"><span style="color:var(--red)">你的答案：${esc(w.your_answer || '未作答')}</span></div>
      <div class="muted" style="margin-top:4px">参考：${esc(w.answer_key)}</div></div>`).join('') : '<div class="muted">全部正确 🎉</div>';
    return appbar('测评', '批改完成') + `<div class="content">
      <div class="result"><div class="score">${r.score}</div><div class="lbl">本次得分 / 100 · 答对 ${r.correct}/${r.total}</div></div>
      <div class="card"><div style="font-weight:700;margin-bottom:8px">错题明细</div>${wrongHtml}</div>
      <button class="btn sec" onclick="App.activeQuiz=null;Student.quiz=null;Student.result=null;render()">返回测评列表</button></div>` + tabbar();
  },

  /* ===== 自主练习 ===== */
  enterPractice() {
    this.practiceView = true;
    this.practice = null; this.practiceResult = null; this.answers = {};
    this.practiceChapters = App.activeChapter ? [App.activeChapter] : [];
    render();
  },
  exitPractice() {
    this.practiceView = false; this.practice = null; this.practiceResult = null;
    this.practiceSessions = [];
    render();
  },
  togglePracticeChapter(id) {
    const sel = this.practiceChapters || [];
    const i = sel.indexOf(id);
    if (i >= 0) sel.splice(i, 1); else sel.push(id);
    this.practiceChapters = sel;
    render();
  },
  async viewPractice() {
    let sessions = [];
    try { sessions = (await API.get("/api/practice")).sessions || []; } catch (e) { sessions = []; }
    this.practiceSessions = sessions;
    const chapters = App.chapters;
    const sel = this.practiceChapters || [];
    const chapterSel = chapters.map(c => `<div class="chapter ${sel.includes(c.id) ? 'active' : ''}" onclick="Student.togglePracticeChapter('${c.id}')"><div><div class="nm">${esc(c.name)}</div><div class="mt">${esc(c.folder || '未分组')}</div></div></div>`).join('') || '<div class="muted">暂无章节</div>';
    const hist = sessions.map(s => {
      const status = s.completed ? `<span class="badge master">已完成 ${s.score}</span>` : `<span class="badge prog">进行中</span>`;
      return `<div class="qcard" onclick="Student.openPractice('${s.id}')"><div class="ic">🎯</div>
        <div class="meta"><div class="t">练习 ${s.question_count} 题</div><div class="s">覆盖：${(s.chapter_ids || []).map(App.chapterName.bind(App)).map(esc).join('、')}</div></div>
        <div style="text-align:right">${status}</div></div>`;
    }).join('') || '<div class="muted">暂无练习记录</div>';
    return appbar('自主练习', 'AI 出题 · 合计 100 分') + `<div class="content">
      <div class="card sm"><div style="font-weight:700;font-size:13px;margin-bottom:8px">选择章节（可多选）</div>${chapterSel}
        <button class="btn" style="margin-top:12px" onclick="Student.generatePractice()">🎯 生成练习</button>
        <button class="btn ghost" style="margin-top:8px" onclick="Student.exitPractice()">返回测评列表</button></div>
      <div class="card"><div style="font-weight:700;margin-bottom:8px">练习历史</div>${hist}</div>
    </div>` + tabbar();
  },
  async generatePractice() {
    const ids = (this.practiceChapters && this.practiceChapters.length) ? this.practiceChapters : [App.activeChapter];
    if (!ids || !ids.length) { toast("请先选择章节"); return; }
    try {
      const d = await API.post("/api/practice/generate", { chapter_ids: ids });
      this.practice = d; this.practiceResult = null; this.answers = {};
      render(); toast("已生成练习");
    } catch (e) { toast(e.message); }
  },
  async openPractice(id) {
    try {
      const d = await API.get("/api/practice/" + id);
      if (d.session && d.session.completed) {
        const qs = d.questions || [];
        this.practiceResult = {
          summary: { score: d.session.score, correct: qs.filter(q => q.correct === 1).length, total: qs.length },
          detail: d,
        };
        this.practice = null;
      } else {
        this.practice = { id: d.session.id, chapter_ids: d.session.chapter_ids, questions: d.questions };
        this.answers = {}; this.practiceResult = null;
      }
      render();
    } catch (e) { toast(e.message); }
  },
  viewPracticeTake() {
    const qs = (this.practice.questions || []).map((item, i) => {
      if (item.type === "essay") return `<div class="q"><div class="qt"><span class="n">${i + 1}</span><span>${esc(item.content)}<b class="pts">${item.points} 分</b></span></div><textarea id="ans_${item.id}" placeholder="输入你的回答…"></textarea></div>`;
      if (item.type === "bool") {
        const boolOpts = ['正确', '错误'].map(v => `<div class="opt" id="opt_${item.id}_${v}" onclick="Student.pick('${item.id}','${v}')"><span class="dot"></span>${v}</div>`).join('');
        return `<div class="q"><div class="qt"><span class="n">${i + 1}</span><span>${esc(item.content)}<b class="pts">${item.points} 分</b></span></div>${boolOpts}</div>`;
      }
      const opts = (item.options || []).map((o, oi) => `<div class="opt" id="opt_${item.id}_${oi}" onclick="Student.pick('${item.id}',${oi})"><span class="dot"></span>${esc(o)}</div>`).join('');
      return `<div class="q"><div class="qt"><span class="n">${i + 1}</span><span>${esc(item.content)}<b class="pts">${item.points} 分</b></span></div>${opts}</div>`;
    }).join('');
    const chaps = (this.practice.chapter_ids || []).map(App.chapterName.bind(App)).map(c => `<span class="pill" style="margin-right:6px">${esc(c)}</span>`).join('');
    return appbar('自主练习', '合计 100 分') + `<div class="content">
      <div class="card sm" style="margin-bottom:12px">覆盖章节：${chaps || '全部'}</div>
      ${qs}<button class="btn" onclick="Student.submitPractice()">提交并批改</button>
      <button class="btn ghost" style="margin-top:8px" onclick="Student.exitPractice()">返回练习列表</button></div>` + tabbar();
  },
  async submitPractice() {
    const answers = (this.practice.questions || []).map(q => {
      let ans = this.answers[q.id] || "";
      if (q.type === "essay") ans = document.getElementById("ans_" + q.id).value || "";
      return { question_id: q.id, answer: ans };
    });
    try {
      const d = await API.post(`/api/practice/${this.practice.id}/submit`, { answers });
      let detail = { questions: [] };
      try { detail = await API.get(`/api/practice/${this.practice.id}`); } catch (e) {}
      this.practiceResult = { summary: d, detail };
      this.practice = null;
      render();
    } catch (e) { toast(e.message); }
  },
  viewPracticeResult() {
    const r = this.practiceResult.summary || {};
    const qs = (this.practiceResult.detail && this.practiceResult.detail.questions) || [];
    const rows = qs.map((q, i) => {
      const ok = q.correct === 1;
      return `<div class="card sm" style="border-color:${ok ? '#E2F0E6' : '#FAD9D6'}">
        <div style="font-size:13px"><b>${i + 1}. ${ok ? '✅' : '❌'}</b> ${esc(q.content)} <b class="pts">${q.points} 分</b></div>
        ${q.user_answer !== undefined ? `<div style="font-size:13px;margin-top:5px"><span style="color:${ok ? 'var(--green)' : 'var(--red)'}">你的答案：${esc(q.user_answer || '未作答')}（得 ${q.score} 分）</span></div>` : ''}
        <div class="muted" style="margin-top:4px">参考：${esc(q.answer_key || '')}</div>
      </div>`;
    }).join('');
    return appbar('自主练习', '批改完成') + `<div class="content">
      <div class="result"><div class="score">${r.score}</div><div class="lbl">本次得分 / 100 · 答对 ${r.correct}/${r.total}</div></div>
      <div class="card"><div style="font-weight:700;margin-bottom:8px">逐题解析（含正确答案）</div>${rows}</div>
      <button class="btn sec" onclick="Student.exitPractice()">返回练习列表</button></div>` + tabbar();
  },

  /* ===== 进度 ===== */
  async viewProgress() {
    let mastery = { chapters: [], counts: { master: 0, progress: 0, weak: 0, na: 0 } };
    let weak = { weak_points: [] };
    let reviews = { review_items: [] };
    let advice = { has_advice: false, advice: "" };
    let weekly = { stats: {}, weak_chapters: [] };
    try { mastery = await API.get("/api/progress/mastery"); } catch (e) {}
    try { weak = await API.get("/api/progress/weak-points"); } catch (e) {}
    try { reviews = await API.get("/api/progress/review-items"); } catch (e) {}
    try { advice = await API.get("/api/progress/advice"); } catch (e) {}
    try { weekly = await API.get("/api/progress/weekly-stats"); } catch (e) {}
    const c = mastery.counts || { master: 0, progress: 0, weak: 0, na: 0 };
    const chapList = (mastery.chapters || []).map(ch => {
      const st = stateOf(ch.m, ch.attempts);
      return `<div class="chapter"><div><div class="nm">${esc(ch.name)}</div><div class="mt">掌握度 ${ch.m == null ? '—' : ch.m + '%'} · 作答 ${ch.attempts} 次</div></div><span class="badge ${st.cls}">${st.label}</span></div>`;
    }).join('') || '<div class="muted">暂无章节</div>';
    const weakHtml = (weak.weak_points || []).map(w => {
      const mLabel = w.m == null ? '未测评' : `M=${w.m}%`;
      const tag = w.from_practice ? '<span class="badge prog" style="margin-left:6px">练习错题</span>' : '';
      return `<div class="weak"><span class="badge weak" style="flex-shrink:0">${esc(w.name)}</span><div><div style="font-weight:600;font-size:13.5px">${mLabel}${tag}</div>
      ${(w.evidence || []).slice(0, 2).map(e => `<div class="ev">• ${esc(e.question)}${e.source === 'practice' ? '（练习）' : ''}</div>`).join('')}</div></div>`;
    }).join('') || '<div class="muted">暂无薄弱章节 🎉</div>';
    const revHtml = (reviews.review_items || []).map(r => `<div class="rev-item ${r.status === 'done' ? 'done' : ''}">
      <span class="badge ${r.status === 'done' ? 'master' : 'weak'}">${esc(App.chapterName(r.chapter_id))}</span>
      <div style="flex:1;font-size:13px">${r.status === 'done' ? '已完成' : (r.due ? '已到期，可作答' : '下次复习 ' + r.interval_days + ' 天后')}</div>
      ${r.status === 'pending' && r.due ? `<button class="mini-btn" style="border-color:var(--coral);color:var(--coral-strong)" onclick="Student.openReview('${r.id}')">作答</button>` : ''}</div>`).join('') || '<div class="muted" style="font-size:12.5px">尚未生成复习计划</div>';
    // AI 学习建议（RPT-003 改每日）：显示在掌握度下方
    const adviceLines = (advice.advice || "").split("\n").filter(Boolean);
    const adviceHtml = advice.has_advice && adviceLines.length
      ? adviceLines.map(t => `<div class="ai-tip"><div class="ic">AI</div><div style="font-size:13.5px;line-height:1.5">${esc(t)}</div></div>`).join('')
      : '<div class="muted">今日暂无建议（每天自动生成）</div>';
    // 本周概况 + 成绩分析（RPT-001/002 迁移）
    const s = weekly.stats || {};
    const weeklyHtml = `<div class="card"><div style="font-weight:700;margin-bottom:12px">本周概况</div>
      <div class="stat-row" style="margin:0">
        <div class="stat"><div class="v">${s.days || 0}</div><div class="k">学习天数</div></div>
        <div class="stat"><div class="v">${s.conversations || 0}</div><div class="k">对话天数</div></div>
        <div class="stat"><div class="v">${s.quizzes || 0}</div><div class="k">测评天数</div></div></div>
      <div style="font-size:13px;margin-top:10px">平均：<b>${s.avg_score == null ? '—' : s.avg_score}</b> · 最高：<b>${s.max_score == null ? '—' : s.max_score}</b></div>
      <div class="muted" style="margin-top:6px">薄弱章节：${(weekly.weak_chapters || []).map(esc).join('、') || '无'}</div></div>`;
    return appbar('进度', '按章节掌握度（仅本人）') + `<div class="content">
      <div class="stat-row"><div class="stat"><div class="v" style="color:var(--green)">${c.master}</div><div class="k">已掌握</div></div>
        <div class="stat"><div class="v" style="color:var(--amber)">${c.progress}</div><div class="k">进行中</div></div>
        <div class="stat"><div class="v" style="color:var(--red)">${c.weak}</div><div class="k">薄弱</div></div>
        <div class="stat"><div class="v" style="color:var(--text-3)">${c.na}</div><div class="k">未评估</div></div></div>
      <div class="card"><div style="font-weight:700;margin-bottom:10px">AI 学习建议</div>${adviceHtml}</div>
      ${weeklyHtml}
      <div class="card"><div style="font-weight:700;margin-bottom:8px">各章节状态</div>${chapList}</div>
      <div class="card"><div style="font-weight:700;margin-bottom:8px">薄弱点（带错题依据）</div>${weakHtml}</div>
      <div class="card"><div style="font-weight:700;margin-bottom:8px">巩固练习闭环（间隔复习 1→3→7）</div>${revHtml}
        <button class="btn" style="margin-top:12px" onclick="Student.genReview()">一键生成巩固练习</button></div>
    </div>` + tabbar();
  },
  async genReview() {
    try { const d = await API.post("/api/progress/review-items/generate", {}); toast("已为 " + d.created + " 个薄弱章生成巩固练习"); render(); }
    catch (e) { toast(e.message); }
  },
  async openReview(id) {
    try {
      const d = await API.get("/api/progress/review-items/" + id);
      const q = d.question || {};
      // 复习项 options 可能是 JSON 字符串（后端未二次解析），统一转数组
      let optsArr = q.options;
      if (typeof optsArr === 'string') { try { optsArr = JSON.parse(optsArr); } catch (e) { optsArr = []; } }
      optsArr = optsArr || [];
      const boolOpts = q.type === 'bool'
        ? ['正确', '错误'].map(v => `<div class="row" style="text-align:left;border:none;background:transparent;padding:8px 16px" onclick="Student.answerReview('${id}','${v}')">${v}</div>`).join('')
        : '';
      const opts = optsArr.map((o, oi) => `<div class="row" style="text-align:left;border:none;background:transparent;padding:8px 16px" onclick="Student.answerReview('${id}','${oi}')">${String.fromCharCode(65 + oi)}. ${esc(o)}</div>`).join('');
      const essay = q.type === "essay" ? `<div class="row" style="text-align:left;border:none;background:transparent;cursor:default"><textarea class="mini-input" id="revAns" placeholder="输入回答"></textarea><div class="row" onclick="Student.answerReview('${id}',document.getElementById('revAns').value)">提交</div></div>` : '';
      const answerArea = q.type === 'essay' ? essay : (q.type === 'bool' ? boolOpts : opts);
      openSheet(`<div class="row" style="font-weight:700;cursor:default">巩固练习 · ${esc(App.chapterName(d.chapter_id))}</div>
        <div class="row" style="text-align:left;border:none;background:transparent;cursor:default">${esc(q.content)}</div>${answerArea}
        <div class="row cancel" onclick="closeSheet()">取消</div>`);
    } catch (e) { toast(e.message); }
  },
  async answerReview(id, answer) {
    try {
      const d = await API.post(`/api/progress/review-items/${id}/complete`, { answer: String(answer) });
      closeSheet();
      toast(d.correct ? `答对 ✓ 间隔 ${d.next_interval_days} 天` : `答错 · 间隔重置 1 天`);
      render();
    } catch (e) { toast(e.message); }
  },

  /* ===== 班级 ===== */
  async viewClass() {
    let d = { total_turns: [], total_practice: [], today_turns: [], today_conversations: [], mastery: [], quizzes: [], quiz_boards: {} };
    try { d = await API.get("/api/class/leaderboard"); } catch (e) {}
    const me = (App.state.user && App.state.user.id) || d.me_user_id;
    const cat = this.classCat || 0;
    const cats = ["累计对话轮", "累计练习", "今日对话轮", "今日对话次数", "测评分数", "掌握度"];
    const chips = cats.map((t, i) => `<div class="chip ${cat === i ? 'active' : ''}" onclick="Student.setClassCat(${i})">${t}</div>`).join('');

    const badge = (i) => i === 0 ? 'r1' : i === 1 ? 'r2' : i === 2 ? 'r3' : 'rn';
    const av = (it, isMe) => `<div class="rank-av ${isMe ? 'b' : ''}">${esc((it.display_name || '?').charAt(0))}</div>`;
    const name = (it, isMe) => `<div class="nm">${esc(it.display_name)}${isMe ? '<span class="me-tag">我</span>' : ''}</div>`;
    const row = (it, i, valHtml, sub = '') => {
      const isMe = it.user_id === me;
      return `<div class="rank-row ${isMe ? 'me' : ''}"><div class="rank-num ${badge(i)}">${i + 1}</div>${av(it, isMe)}<div class="rank-meta">${name(it, isMe)}${sub}</div><div class="rank-val">${valHtml}</div></div>`;
    };
    const num = (v, unit) => `<div class="v">${v}</div><div class="k">${unit}</div>`;

    let body = '';
    if (cat === 0) body = (d.total_turns || []).map((it, i) => row(it, i, num(it.value, '轮'), `<div class="st">累计 ${it.value} 轮对话</div>`)).join('');
    else if (cat === 1) body = (d.total_practice || []).map((it, i) => row(it, i, num(it.value, '次'), `<div class="st">累计 ${it.value} 次练习</div>`)).join('');
    else if (cat === 2) body = (d.today_turns || []).map((it, i) => row(it, i, num(it.value, '轮'), `<div class="st">今日 ${it.value} 轮对话</div>`)).join('');
    else if (cat === 3) body = (d.today_conversations || []).map((it, i) => row(it, i, num(it.value, '个'), `<div class="st">今日 ${it.value} 个对话</div>`)).join('');
    else if (cat === 4) {
      const quizSel = this.classQuizId || (d.quizzes && d.quizzes[0] && d.quizzes[0].quiz_id) || null;
      const quizChips = (d.quizzes || []).map(q => `<div class="c ${quizSel === q.quiz_id ? 'on' : ''}" onclick="Student.setClassQuiz('${q.quiz_id}')">${esc(q.title)}${q.version > 1 ? ` v${q.version}` : ''}</div>`).join('');
      const board = (quizSel && d.quiz_boards && d.quiz_boards[quizSel]) || [];
      body = `<div class="qp">${quizChips || '<div class="muted">暂无已发布测评</div>'}</div>` + board.map((it) => {
        const isMe = it.user_id === me;
        if (it.absent) {
          return `<div class="rank-row ${isMe ? 'me' : ''}"><div class="rank-num rn">—</div>${av(it, isMe)}<div class="rank-meta">${name(it, isMe)}<div class="st">未参加本次测评</div></div><div class="rank-val"><div class="v">—</div><div class="k">未参加</div></div></div>`;
        }
        return `<div class="rank-row ${isMe ? 'me' : ''}"><div class="rank-num ${badge((it.rank || 1) - 1)}">${it.rank}</div>${av(it, isMe)}<div class="rank-meta">${name(it, isMe)}<div class="st">得分 ${it.score}</div></div><div class="rank-val"><div class="v">${it.score}</div><div class="k">/100</div></div></div>`;
      }).join('');
    } else {
      body = (d.mastery || []).map((it, i) => {
        const isMe = it.user_id === me;
        const sub = it.avg_m == null ? '<div class="st">未评估</div>' : `<div class="st">平均 M ${it.avg_m}% · 已掌握 ${it.mastered_count} 章</div>`;
        const val = it.avg_m == null ? '—' : it.avg_m;
        return `<div class="rank-row ${isMe ? 'me' : ''}"><div class="rank-num ${badge(i)}">${i + 1}</div>${av(it, isMe)}<div class="rank-meta">${name(it, isMe)}${sub}</div><div class="rank-val"><div class="v">${val}</div><div class="k">%</div></div></div>`;
      }).join('');
    }
    return appbar('班级', '全班学习排行榜 · 仅同班同学') + `<div class="content">
      <div class="pill-wrap" style="margin-bottom:12px">${chips}</div>
      ${body || '<div class="muted">暂无数据</div>'}
    </div>` + tabbar();
  },
  setClassCat(i) { this.classCat = i; render(); },
  setClassQuiz(id) { this.classQuizId = id; this.classCat = 4; render(); },
};
