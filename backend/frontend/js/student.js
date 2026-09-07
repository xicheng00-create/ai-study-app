/* 学生视图：学习（引导对话）/ 测评 / 进度 / 班级 */
/* 错题完整渲染：题目 + 全部选项，标注「正确答案 / 你的答案」（choice 索引→文本，bool 文本；essay 回退文本） */
function fmtWrongCard(w) {
  const opts = (w.options || []).map(x => String(x));
  const your = w.your_answer, key = w.answer_key;
  let inner = '';
  if (w.type === 'bool') {
    inner = ['正确', '错误'].map(v => {
      const isAns = (String(key) === v), isYour = (String(your) === v);
      const cls = isAns ? ' style="border-color:var(--green);background:#eefaf0"' : (isYour ? ' style="border-color:var(--red);background:#fdecea"' : '');
      const mark = isAns ? ' ✅ 正确答案' : (isYour ? ' ❌ 你的答案' : '');
      return `<div class="opt"${cls}><span class="dot"></span>${v}${mark}</div>`;
    }).join('');
  } else if (w.type === 'choice' && opts.length) {
    const yi = parseInt(your, 10), ai = parseInt(key, 10);
    inner = opts.map((o, i) => {
      const isAns = (i === ai), isYour = (i === yi);
      const cls = isAns ? ' style="border-color:var(--green);background:#eefaf0"' : (isYour ? ' style="border-color:var(--red);background:#fdecea"' : '');
      const mark = isAns ? ' ✅ 正确答案' : (isYour ? ' ❌ 你的答案' : '');
      return `<div class="opt"${cls}><span class="dot"></span>${String.fromCharCode(65 + i)}. ${esc(o)}${mark}</div>`;
    }).join('');
  } else {
    inner = `<div class="muted" style="margin-top:6px;font-size:13px">你的答案：${esc(your || '未作答')}</div><div class="muted" style="margin-top:2px;font-size:13px">参考答案：${esc(key || '—')}</div>`;
  }
  return `<div class="card sm" style="border-color:#FAD9D6"><div style="font-size:13.5px"><b>题：</b>${esc(w.content)}${w.sub_concept ? ` <span class="muted">（${esc(w.sub_concept)}）</span>` : ''}</div>${inner}</div>`;
}

const Student = {
  convId: null,
  messages: [],
  turn: 0,
  quiz: null,
  answers: {},
  result: null,
  wrongCtx: null,      // 本次待咨询的已作答错题，仅随下一条消息发送
  tutorMode: null,     // 辅导模式开关：'guide' 引导式 / 'direct' 直接讲解（localStorage 持久化）
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
  classData: null,    // 班级排行榜响应缓存（供「更多排行榜」弹层读取）
  classQuizId: null,  // 测评分数榜当前选中的测评
  weakOpen: null,     // 薄弱点页展开的章节 id
  weakGroupOpen: {},  // 薄弱点页展开的「章→组」键：`${chapter_id}:${quiz_id|practice}`
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
    if (h === "weak") return await this.viewWeak();
    if (h === "class") return await this.viewClass();
    return await this.viewLearn();
  },

  /* ===== 学习：章节 + 引导式对话 ===== */
  async viewLearn() {
    let convs = [];
    try { convs = (await API.get("/api/conversations")).conversations || []; } catch (e) { convs = []; }
    this.convs = convs;
    // 辅导模式开关：从 localStorage 读，无则默认「直接讲解」
    this.tutorMode = localStorage.getItem("aistudy_tutor_mode") || "direct";
    if (!this.convId && convs.length) this.convId = convs[0].id;
    if (this.convId) {
      try { const d = await API.get("/api/conversations/" + this.convId); this.messages = d.messages || []; } catch (e) { this.messages = []; }
    }
    // 资料库「越新的在越左边」：按 created_at 倒序（最新添加排最左），不改 App.chapters 原序
    const chaptersSorted = [...App.chapters].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
    const chapterCards = chaptersSorted.map(c => `<div class="chapter ${App.activeChapter === c.id ? 'active' : ''}" onclick="Student.selectChapter('${c.id}')">
      <div><div class="nm">${esc(c.name)}</div><div class="mt">${esc(c.folder || '未分组')}</div></div></div>`).join('');
    // ≥2 章节时资料库改为横向滑动卡片组（单章保持竖排）
    const chapters = chaptersSorted.length >= 2 ? `<div class="chapter-scroll">${chapterCards}</div>` : chapterCards;
    const convChips = convs.map(c => `<span class="pill ${this.convId === c.id ? 'active' : ''}" style="cursor:pointer" onclick="Student.selectConv('${c.id}')" onmousedown="Student.pressStart(event,'${c.id}')" onmouseup="Student.pressEnd(event)" onmouseleave="Student.pressEnd(event)" ontouchstart="Student.pressStart(event,'${c.id}')" ontouchend="Student.pressEnd(event)" ontouchmove="Student.pressMove(event)" ontouchcancel="Student.pressEnd(event)"><span class="pill-t">${esc(c.title)}</span></span>`).join('')
      + `<span class="pill" style="cursor:pointer" onclick="Student.newConv()">＋ 新对话</span>`;
    const msgsHtml = this.messages.map(m => `<div class="msg ${m.role === 'user' ? 'user' : 'bot'}">${m.role === 'user' ? '' : '<div class="who">TUTOR</div>'}${esc(m.content)}</div>`).join('')
      + (this.pendingReply ? `<div class="msg bot"><div class="who">TUTOR</div><span class="typing"><span></span><span></span><span></span></span></div>` : '');
    const msgs = msgsHtml
      || `<div class="muted" style="padding:12px 0">${App.activeChapter ? `已选择：${esc(App.chapterName(App.activeChapter))}，开始提问（${this.tutorMode === 'guide' ? '引导式，不直接给答案' : '直接讲解，有问必答'}）` : '请从上方资料库选择章节，开始提问'}</div>`;
    const relatedHtml = (this.relatedVideos || []).length ? `<div class="card sm" style="margin-top:12px">
      <div class="sec-title">${ic('video','coral')}相关视频课（学员自选观看）</div>
      ${this.relatedVideos.map(v => `<a class="video-chip" href="${esc(v.url)}" target="_blank" rel="noopener noreferrer">▶ ${esc(v.title)}${v.platform ? ` · ${esc(v.platform)}` : ''}</a>`).join('')}
      </div>` : '';

    const isGuide = this.tutorMode === 'guide';
    // 头部（appbar + 模式切换）合并为单一吸顶块：appbar 与 seg 成为同一不透明容器，始终一起钉在 top:0，
    // 彻底消除 appbar 与 seg 之间的独立缝隙，iOS 滚动时内容不可能从中间漏出（不再依赖硬编码 top:74px）
    return `<div class="chat-head">` + appbar('学习', isGuide ? '引导式辅导 · 不直接给答案' : '直接讲解 · 有问必答') +
    `<div class="seg-wrap"><div class="seg">
        <button class="${isGuide ? 'on' : ''}" onclick="Student.setTutorMode('guide')">${ic('grad')}引导式</button>
        <button class="${isGuide ? '' : 'on'}" onclick="Student.setTutorMode('direct')">${ic('chat')}直接讲解</button>
      </div></div></div>` +
    `<div class="content chat-view">
      <!-- AI info 条：安静，不抢戏 -->
      <div class="ai-info">${ic('shield')}回答由 AI 生成，请核对资料原文 · 越界内容已拦截</div>
      <!-- 资料库：标题 + 篇数徽章 + 选中章左珊瑚条 -->
      <div class="card sm mb-12">
        <div class="card-head"><div class="card-title">${ic('book','coral')}资料库</div><span class="card-count">${App.chapters.length} 篇</span></div>
        ${chapters || '<div class="muted">暂无章节</div>'}
      </div>
      <!-- 对话 chips + 新对话 -->
      <div class="pill-wrap mb-10">${convChips}</div>
      <!-- 进度行：轮数 -->
      <div class="row-meta"><span class="pill">${ic('clock')}第 ${this.turn} / 12 轮</span></div>
      <div class="chat">${msgs}</div>
      ${relatedHtml}
    </div>
    <div class="composer"><div class="composer-body"><div class="flex"><button class="tool-btn" onclick="Student.openWrongConsult()">${ic('lightbulb')}咨询错题</button></div>${this.wrongCtx ? `<div class="muted" style="font-size:12px;margin-bottom:4px">已选 ${this.wrongCtx.length} 道错题，随本条发送</div>` : ''}<div class="flex"><input id="chatInput" class="grow" placeholder="回答引导问题，或追问…" onkeydown="if(event.key==='Enter')Student.send()"/><button class="send" onclick="Student.send()">${ic('arrowUp')}</button></div></div></div>` + tabbar();
  },
  selectChapter(id) { App.activeChapter = id; render(); },
  setTutorMode(mode) {
    // 切换辅导模式：guide 引导式 / direct 直接讲解，持久化到 localStorage
    this.tutorMode = (mode === 'guide') ? 'guide' : 'direct';
    localStorage.setItem("aistudy_tutor_mode", this.tutorMode);
    render();
  },
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
  async openWrongConsult() {
    let quizzes = [];
    try { quizzes = (await API.get("/api/quizzes")).quizzes || []; }
    catch (e) { toast(e.message); return; }
    const taken = quizzes.filter(q => q.taken);
    const rows = taken.map(q => {
      const s = q.session;
      const title = s ? `测评 · 第${s.week_no}周 第${s.session_no}节` : (q.title || '测评');
      const label = s ? `${s.title} · 覆盖：${(q.chapter_ids || []).map(App.chapterName.bind(App)).map(esc).join('、')}` : '未关联';
      return `<div class="row" onclick="Student.selectWrongConsult('${q.id}')"><div>${esc(title)}</div><div class="muted" style="font-size:12px">${esc(label)}</div></div>`;
    }).join('');
    openSheet(`<div class="row" style="font-weight:700;cursor:default">${ic('lightbulb')}咨询错题</div>${rows || '<div class="row muted" style="cursor:default">暂无已作答测评</div>'}<div class="row cancel" onclick="closeSheet()">取消</div>`);
  },
  async selectWrongConsult(id) {
    try {
      const d = await API.get(`/api/quizzes/${id}/report`);
      if (!d.wrong || !d.wrong.length) { toast('该测评没有错题'); return; }
      this.wrongCtx = d.wrong.map(w => ({ content: w.content, type: w.type,
        options: w.options, your_answer: w.your_answer, answer_key: w.answer_key }));
      closeSheet(); toast(`已选择 ${this.wrongCtx.length} 道错题`); render();
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
      const payload = { content, chapter_id: App.activeChapter, tutor_mode: this.tutorMode || "direct" };
      // 从「路径」进入提问时，携带 session 的 chapter_ids/concept_tags 供视频推荐
      if (this.askCtx) {
        payload.chapter_ids = this.askCtx.chapter_ids || [];
        payload.concept_tags = this.askCtx.concept_tags || [];
      }
      if (this.wrongCtx) payload.wrong_ctx = this.wrongCtx;
      const d = await API.post(`/api/conversations/${this.convId}/message`, payload);
      this.wrongCtx = null;
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
        const mats = (s.materials || []).map(m => `<div class="mat">${ic('file')} ${esc(m.original_name || m.filename)} <span class="dl" onclick="Student.downloadMat('${m.id}','${esc(m.original_name || m.filename)}')">${ic('download','indigo')}下载</span></div>`).join('') || '<div class="muted" style="font-size:12.5px">暂无资料</div>';
        const vids = (s.videos || []).map(v => `<a class="video-chip" href="${esc(v.url)}" target="_blank" rel="noopener noreferrer">▶ ${esc(v.title)}${v.platform ? ` · ${esc(v.platform)}` : ''}</a>`).join('') || '<div class="muted" style="font-size:12.5px">暂无视频</div>';
        const tags = (s.concept_tags || []).map(t => `<span class="badge ver">${esc(t)}</span>`).join('') || '';
        return `<details class="acc">
          <summary><div class="acc-t"><b>第${w.week_no}周 · 第${s.session_no}节</b><span>${esc(s.title)}</span></div></summary>
          <div class="acc-body">
            ${s.goal ? `<div class="muted mb-8">${ic('target','coral')}${esc(s.goal)}</div>` : ''}
            ${tags ? `<div class="pill-wrap mb-8">${tags}</div>` : ''}
            ${chaps ? `<div class="pill-wrap mb-8">${chaps}</div>` : ''}
            <div class="sec-title-sm">${ic('book','coral')}资料</div>${mats}
            <div class="sec-title-sm" style="margin:10px 0 6px">${ic('video','coral')}视频课（外链）</div>${vids}
            <button class="btn sm mt-12" onclick="Student.askSession('${s.id}')">${ic('chat')}去提问</button>
          </div>
        </details>`;
      }).join('');
      return `<div class="week-title">第 ${w.week_no} 周</div>${ss}`;
    }).join('') : `<div class="note"><div class="big">${ic('book')}</div>老师尚未发布学习路径</div>`;
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
      const s = q.session;
      const title = s ? `测评 · 第${s.week_no}周 第${s.session_no}节` : (q.title || '测评');
      return `<div class="qcard" onclick="Student.openQuiz('${q.id}')"><div class="ic">${ic('edit')}</div>
        <div class="meta"><div class="t">${ver}${esc(title)}</div><div class="s">${s ? esc(s.title) + ' · ' : ''}覆盖：${(q.chapter_ids || []).map(App.chapterName.bind(App)).map(esc).join('、')}</div></div>
        <div style="text-align:right">${badge}</div></div>`;
    }).join('') || '<div class="muted">老师尚未发布测评</div>';
    const practiceEntry = `<div class="qcard" style="border-color:var(--coral)" onclick="Student.enterPractice()"><div class="ic">${ic('target')}</div>
      <div class="meta"><div class="t">自主练习</div><div class="s">根据资料 AI 出题 · 最多 5 题 · 即答即批</div></div></div>`;
    return appbar('测评', '教师发布 · 全班同题') + `<div class="content">${practiceEntry}${list}</div>` + tabbar();
  },
  async openQuiz(id) {
    try {
      const rep = await API.get(`/api/quizzes/${id}/report`);
      if (rep.taken) {
        // 一次作答：已做过的测评点进去恒显示该次结果（分数+完整错题），不重做
        this.result = { score: rep.score, correct: rep.correct, total: rep.total, report: { wrong: rep.wrong || [] } };
        this.quiz = null; render();
      } else {
        this.quiz = await API.get(`/api/quizzes/${id}`); this.answers = {}; this.result = null; render();
      }
    } catch (e) { toast(e.message); }
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
    const ttl = (q.session ? `测评 · 第${q.session.week_no}周 第${q.session.session_no}节` : (q.title || '测评'));
    return appbar('测评', esc(ttl)) +
    `<div class="content"><div class="card sm mb-12"><div class="muted">覆盖章节：${(q.chapter_ids || []).map(App.chapterName.bind(App)).map(c => `<span class="pill" style="margin-right:6px">${esc(c)}</span>`).join('')}</div></div>
      ${qs}<button class="btn" onclick="Student.submit()">提交并批改</button>
      <button class="btn ghost" style="margin-top:8px" onclick="Student.quiz=null;Student.answers={};Student.result=null;App.activeQuiz=null;render()">返回列表</button></div>` + tabbar();
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
    const wrongHtml = wrong.length ? wrong.map(w => fmtWrongCard(w)).join('') : `<div class="muted">${ic('sparkle','coral')}全部正确</div>`;
    return appbar('测评', '批改完成') + `<div class="content">
      <div class="result"><div class="score">${r.score}</div><div class="lbl">本次得分 / 100 · 答对 ${r.correct}/${r.total}</div></div>
      <div class="card"><div class="sec-title">错题明细</div>${wrongHtml}</div>
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
      return `<div class="qcard" onclick="Student.openPractice('${s.id}')"><div class="ic">${ic('target')}</div>
        <div class="meta"><div class="t">练习 ${s.question_count} 题</div><div class="s">覆盖：${(s.chapter_ids || []).map(App.chapterName.bind(App)).map(esc).join('、')}</div></div>
        <div style="text-align:right">${status}</div></div>`;
    }).join('') || '<div class="muted">暂无练习记录</div>';
    return appbar('自主练习', 'AI 出题 · 最多 5 题 · 高难度') + `<div class="content">
      <div class="card sm"><div style="font-weight:700;font-size:13px;margin-bottom:8px">选择章节（可多选）</div>${chapterSel}
        <button class="btn mt-12" onclick="Student.generatePractice()">${ic('target')}生成练习</button>
        <button class="btn ghost" style="margin-top:8px" onclick="Student.exitPractice()">返回测评列表</button></div>
      <div class="card"><div class="sec-title">练习历史</div>${hist}</div>
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
        this.practice = { id: d.session.id, chapter_ids: d.session.chapter_ids, total_points: d.session.total_points, questions: d.questions };
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
    const n = (this.practice.questions || []).length;
    const total = (this.practice.questions || []).reduce((s, q) => s + (q.points || 0), 0);
    return appbar('自主练习', `${n} 题 · 共 ${total} 分`) + `<div class="content">
      <div class="card sm mb-12"><div class="muted">覆盖章节：${chaps || '全部'}</div></div>
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
      let opts = q.options || [];
      if (typeof opts === 'string') { try { opts = JSON.parse(opts); } catch (e) { opts = []; } }
      opts = [].concat(opts).map(String);
      const typ = q.type;
      const your = String(q.user_answer != null ? q.user_answer : '');
      const key = String(q.answer_key != null ? q.answer_key : '');
      let optHtml = '';
      if (typ === 'bool') {
        optHtml = ['正确', '错误'].map(v => {
          const isAns = (key === v), isYour = (your === v);
          const cls = isAns ? ' style="border-color:var(--green);background:#eefaf0"' : (isYour ? ' style="border-color:var(--red);background:#fdecea"' : '');
          const mark = isAns ? ' ✅' : (isYour ? ' ❌' : '');
          return `<div class="opt"${cls}><span class="dot"></span>${v}${mark}</div>`;
        }).join('');
      } else if (typ === 'choice' && opts.length) {
        const yi = parseInt(your, 10), ai = parseInt(key, 10);
        optHtml = opts.map((o, j) => {
          const isAns = (j === ai), isYour = (j === yi);
          const cls = isAns ? ' style="border-color:var(--green);background:#eefaf0"' : (isYour ? ' style="border-color:var(--red);background:#fdecea"' : '');
          const mark = isAns ? ' ✅ 正确答案' : (isYour ? ' ❌ 你的答案' : '');
          return `<div class="opt"${cls}><span class="dot"></span>${String.fromCharCode(65 + j)}. ${esc(o)}${mark}</div>`;
        }).join('');
      } else {
        optHtml = `<div style="font-size:13px;margin-top:5px"><span style="color:${ok ? 'var(--green)' : 'var(--red)'}">你的答案：${esc(your || '未作答')}（得 ${q.score} 分）</span></div><div class="muted" style="margin-top:4px">参考：${esc(key || '—')}</div>`;
      }
      return `<div class="card sm" style="border-color:${ok ? '#E2F0E6' : '#FAD9D6'}">
        <div style="font-size:13px"><b>${i + 1}. ${ok ? '✅' : '❌'}</b> ${esc(q.content)} <b class="pts">${q.points} 分</b> <span class="muted" style="font-size:12px">· 得 ${q.score} 分</span></div>
        ${optHtml}
      </div>`;
    }).join('');
    return appbar('自主练习', '批改完成') + `<div class="content">
      <div class="result"><div class="score">${r.score}</div><div class="lbl">本次得分 / 100 · 答对 ${r.correct}/${r.total}</div></div>
      <div class="card"><div class="sec-title">逐题解析（含正确答案）</div>${rows}</div>
      <button class="btn sec" onclick="Student.exitPractice()">返回练习列表</button></div>` + tabbar();
  },

  /* ===== 进度 ===== */
  toggleWeak(cid) { this.weakOpen = (this.weakOpen === cid) ? null : cid; this.weakGroupOpen = {}; render(); },
  toggleWeakGroup(cid, gid) { const k = `${cid}:${gid}`; this.weakGroupOpen[k] = !this.weakGroupOpen[k]; render(); },
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
    const weakPoints = weak.weak_points || [];
    const weakWrongCount = weakPoints.reduce(function (s, w) { return s + (w.evidence || []).length; }, 0);
    // 薄弱点入口卡：点击进入独立薄弱点页（不再内嵌展开全部错题）
    const weakHtml = `<div class="weak" style="cursor:pointer" onclick="go('weak')"><span class="badge weak" style="flex-shrink:0">${ic('pin')}</span><div style="flex:1"><div style="font-weight:600;font-size:13.5px">薄弱点 · ${weakPoints.length} 章 · ${weakWrongCount} 道错题</div><div class="muted" style="font-size:12px">点击查看按练习 / 测评分组的错题依据</div></div><span>›</span></div>`;
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
      <div class="card"><div class="sec-title">各章节状态</div>${chapList}</div>
      <div class="card"><div class="sec-title">薄弱点（带错题依据）</div>${weakHtml}</div>
      <div class="card"><div class="sec-title">巩固练习闭环（间隔复习 1→3→7）</div>${revHtml}
        <button class="btn" style="margin-top:12px" onclick="Student.genReview()">一键生成巩固练习</button></div>
    </div>` + tabbar();
  },
  async viewWeak() {
    let weak = { weak_points: [] };
    try { weak = await API.get("/api/progress/weak-points"); } catch (e) {}
    let quizzes = [];
    try { quizzes = (await API.get("/api/quizzes")).quizzes || []; } catch (e) {}
    const quizMap = {};
    quizzes.forEach(function (qq) { quizMap[qq.id] = qq; });
    const pts = weak.weak_points || [];
    const totalWrong = pts.reduce(function (s, w) { return s + (w.evidence || []).length; }, 0);
    // 章节纵向列表：点章头展开，章内按「练习错题 / 测评错题」分组，点组向下展开全部错题
    const chapterList = pts.map(w => {
      const evs = w.evidence || [];
      const mLabel = w.m == null ? '未测评' : `M=${w.m}%`;
      const open = this.weakOpen === w.chapter_id;
      const head = `<div class="weak" style="cursor:pointer" onclick="Student.toggleWeak('${w.chapter_id}')"><span class="badge weak" style="flex-shrink:0">${esc(w.name)}</span><div style="flex:1"><div style="font-weight:600;font-size:13.5px">掌握度 ${mLabel} · ${evs.length} 道错题</div></div><span>${open ? '▾' : '▸'}</span></div>`;
      let body = '';
      if (open) {
        const quizErr = {}, practiceErr = [];
        evs.forEach(function (e) {
          if (e.source === 'practice' || !e.quiz_id) practiceErr.push(e);
          else { (quizErr[e.quiz_id] = quizErr[e.quiz_id] || []).push(e); }
        });
        const groups = [];
        Object.keys(quizErr).forEach(function (qid) {
          const q = quizMap[qid] || {};
          const sess = q.session;
          const label = sess ? `测评 · 第${sess.week_no}周 第${sess.session_no}节` : (q.title || '测评');
          const gkey = `${w.chapter_id}:${qid}`;
          const gOpen = !!this.weakGroupOpen[gkey];
          const errs = quizErr[qid].map(function (e) { return fmtWrongCard({ content: e.question, type: e.type, options: e.options, your_answer: e.your_answer, answer_key: e.answer_key, sub_concept: e.sub_concept }); }).join('');
          groups.push(`<div class="weak" style="margin-left:12px"><div style="cursor:pointer;font-weight:600;font-size:13px;color:var(--coral-strong)" onclick="Student.toggleWeakGroup('${w.chapter_id}','${qid}')">${esc(label)} <span class="muted">(${quizErr[qid].length} 道)</span> <span>${gOpen ? '▾' : '▸'}</span></div>${gOpen ? errs : ''}</div>`);
        }, this);
        if (practiceErr.length) {
          const gkey = `${w.chapter_id}:practice`;
          const gOpen = !!this.weakGroupOpen[gkey];
          const pe = practiceErr.map(function (e) { return fmtWrongCard({ content: e.question, type: e.type, options: e.options, your_answer: e.your_answer, answer_key: e.answer_key, sub_concept: e.sub_concept }); }).join('');
          groups.push(`<div class="weak" style="margin-left:12px"><div style="cursor:pointer;font-weight:600;font-size:13px" onclick="Student.toggleWeakGroup('${w.chapter_id}','practice')">练习错题 <span class="muted">(${practiceErr.length} 道)</span> <span>${gOpen ? '▾' : '▸'}</span></div>${gOpen ? pe : ''}</div>`);
        }
        body = groups.join('') || '<div class="muted" style="margin-left:12px">暂无错题依据</div>';
      }
      return head + body;
    }).join('') || `<div class="muted">${ic('sparkle','coral')}暂无薄弱章节</div>`;
    return appbar('薄弱点', '带错题依据 · 按练习 / 测评分组') + `<div class="content">
      <button class="btn ghost sm" style="margin-bottom:10px" onclick="go('progress')">‹ 返回进度</button>
      <div class="card"><div class="sec-title">薄弱章节 · ${pts.length} 章 · ${totalWrong} 道错题</div>${chapterList}</div>
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
  /* 排行榜行渲染：前 3 名金/银/铜奖牌（SVG），第 4 名起普通序号 */
  _rankNum(i) {
    const cls = i === 0 ? 'gold' : i === 1 ? 'silver' : i === 2 ? 'bronze' : '';
    return cls
      ? `<div class="rank-num medal ${cls}" title="第${i + 1}名">${ic('medal')}</div>`
      : `<div class="rank-num rn">${i + 1}</div>`;
  },
  _rankRow(it, i, me, valHtml, sub) {
    const isMe = it.user_id === me;
    return `<div class="rank-row ${isMe ? 'me' : ''}">${this._rankNum(i)}<div class="rank-av ${isMe ? 'b' : ''}">${esc((it.display_name || '?').charAt(0))}</div><div class="rank-meta"><div class="nm">${esc(it.display_name)}${isMe ? '<span class="me-tag">我</span>' : ''}</div>${sub || ''}</div><div class="rank-val">${valHtml}</div></div>`;
  },
  _rankVal(v, unit) { return `<div class="v">${v}</div><div class="k">${unit}</div>`; },
  async viewClass() {
    let d = { total_turns: [], total_practice: [], today_turns: [], today_conversations: [], today_practice: [], mastery: [], quizzes: [], quiz_boards: {} };
    try { d = await API.get("/api/class/leaderboard"); } catch (e) {}
    this.classData = d;  // 缓存，供「更多排行榜」弹层读取
    const me = (App.state.user && App.state.user.id) || d.me_user_id;
    // 主屏两个排行榜卡片：① 今日对话次数 ② 今日练习次数（各卡片前 3 名奖牌）
    const card = (title, icon, entries, unit, subFn) => {
      const rows = (entries || []).map((it, i) => this._rankRow(it, i, me, this._rankVal(it.value, unit), `<div class="st">${subFn(it)}</div>`)).join('');
      return `<div class="card"><div class="card-head"><div class="card-title">${ic(icon, 'coral')}${title}</div><span class="card-count">${(entries || []).length} 人</span></div>${rows || '<div class="muted">暂无数据</div>'}</div>`;
    };
    const body = card('今日对话次数', 'chat', d.today_conversations, '个', (it) => `今日 ${it.value} 个对话`)
      + card('今日练习次数', 'target', d.today_practice, '次', (it) => `今日 ${it.value} 次练习`);
    return appbar('班级', '全班学习排行榜 · 仅同班同学') + `<div class="content">
      ${body}
      <button class="btn ghost" style="margin-top:4px" onclick="Student.openClassMore()">${ic('pin')}更多排行榜 · 累计 / 测评 / 掌握度</button>
    </div>` + tabbar();
  },
  /* 其它排行榜（累计对话轮 / 累计练习 / 测评分数 / 掌握度）收进底部弹出层，点「关闭」收起 */
  openClassMore() {
    const d = this.classData || { total_turns: [], total_practice: [], mastery: [], quizzes: [], quiz_boards: {} };
    const me = (App.state.user && App.state.user.id) || d.me_user_id;
    const rows = (entries, unit, subFn) => (entries || []).map((it, i) => this._rankRow(it, i, me, this._rankVal(it.value, unit), `<div class="st">${subFn(it)}</div>`)).join('') || '<div class="muted">暂无数据</div>';
    // 测评分数榜：默认选第一个已发布测评，chip 切换后重开弹层
    const quizSel = this.classQuizId || (d.quizzes && d.quizzes[0] && d.quizzes[0].quiz_id) || null;
    const quizChips = (d.quizzes || []).map(q => `<div class="c ${quizSel === q.quiz_id ? 'on' : ''}" onclick="Student.setClassQuiz('${q.quiz_id}')">${esc(q.label || q.title)}${q.version > 1 ? ` v${q.version}` : ''}</div>`).join('');
    const board = (quizSel && d.quiz_boards && d.quiz_boards[quizSel]) || [];
    const quizRows = board.map((it) => {
      const isMe = it.user_id === me;
      if (it.absent) {
        return `<div class="rank-row ${isMe ? 'me' : ''}"><div class="rank-num rn">—</div><div class="rank-av ${isMe ? 'b' : ''}">${esc((it.display_name || '?').charAt(0))}</div><div class="rank-meta"><div class="nm">${esc(it.display_name)}${isMe ? '<span class="me-tag">我</span>' : ''}</div><div class="st">未参加本次测评</div></div><div class="rank-val"><div class="v">—</div><div class="k">未参加</div></div></div>`;
      }
      return this._rankRow(it, (it.rank || 1) - 1, me, `<div class="v">${it.score}</div><div class="k">/100</div>`, `<div class="st">得分 ${it.score}</div>`);
    }).join('') || '<div class="muted">暂无数据</div>';
    const masteryRows = (d.mastery || []).map((it, i) => {
      const sub = it.avg_m == null ? '<div class="st">未评估</div>' : `<div class="st">平均 M ${it.avg_m}% · 已掌握 ${it.mastered_count} 章</div>`;
      const val = it.avg_m == null ? '—' : it.avg_m;
      return this._rankRow(it, i, me, `<div class="v">${val}</div><div class="k">%</div>`, sub);
    }).join('') || '<div class="muted">暂无数据</div>';
    const sec = (t) => `<div class="sec-head">${t}</div>`;
    openSheet(`<div class="row" style="font-weight:700;cursor:default">${ic('pin')}更多排行榜</div>
      <div style="text-align:left;padding:4px 14px;max-height:52vh;overflow-y:auto">
        ${sec('累计对话轮')}${rows(d.total_turns, '轮', (it) => `累计 ${it.value} 轮对话`)}
        ${sec('累计练习')}${rows(d.total_practice, '次', (it) => `累计 ${it.value} 次练习`)}
        ${sec('测评分数')}<div class="qp">${quizChips || '<div class="muted">暂无已发布测评</div>'}</div>${quizRows}
        ${sec('掌握度')}${masteryRows}
      </div>
      <div class="row cancel" onclick="closeSheet()">关闭</div>`);
  },
  setClassQuiz(id) { this.classQuizId = id; this.openClassMore(); },
};
