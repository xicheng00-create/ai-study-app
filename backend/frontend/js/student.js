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
  practiceCount: 5,     // 每次练习题数
  knowledgeIdx: false, knowledgeDeck: false, knowledgeCards: [], knowledgePos: 0,
  knowledgeFlipped: false, knowledgeSwipe: null, knowledgeGroupOpen: {},  // 知识卡片列表页按章分组展开态（cid → bool）
  selChapters: null,    // 学习多选集（hub 资料库勾选，localStorage 记忆；null=未初始化 → 全选）
  _kcBusy: false,       // 翻卡异步锁：飞出动画/提交期间防连点与重入
  learnChat: false,     // 学习 tab 子视图：true=对话页；false=学习主菜单（hub：对话/知识卡片两入口）
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
  _noReload: false,   // 发送后重绘期间跳过服务器消息重拉（保住即时上屏）
  _adviceBusy: false, // 生成今日建议异步锁
  _swSuppress: false, // 练习历史左滑结束补发 click 的抑制

  async render() {
    const h = App.state.hash;
    // 离开学习区：退出知识卡片全屏态（复习进度已存 localStorage，回来可续）
    if (h !== "learn") { this.knowledgeIdx = false; this.knowledgeDeck = false; this.knowledgeFlipped = false; this._kcBusy = false; }
    if (this.knowledgeDeck) return this.viewKnowledgeDeck();
    if (this.knowledgeIdx) return await this.viewKnowledge();
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
    if (h === "learn" && this.learnChat) return await this.viewLearnChat();
    return await this.viewLearnHome();
  },

  /* ===== 学习主菜单（hub）：资料库选章 + 对话/知识卡片两入口 ===== */
  async viewLearnHome() {
    this.initSelChapters();
    // 资料库竖排（不横滑），最新在前；多选 list：勾选章驱动对话跨章检索 + 知识卡片跨章复习
    const chaptersSorted = [...App.chapters].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
    const sel = this.selChapters || [];
    const rows = chaptersSorted.map(c => {
      const on = sel.indexOf(c.id) >= 0;
      return `<div class="chapter ${on ? 'active' : ''}" onclick="Student.toggleChapterMulti('${c.id}')">
      <div><div class="nm">${esc(c.name)}</div><div class="mt">${esc(c.folder || '未分组')}</div></div>
      <span class="chk${on ? ' on' : ''}">${on ? ic('check') : ''}</span></div>`;
    }).join('');
    const selN = sel.length, totalN = App.chapters.length;
    const sub = totalN ? `已选 ${selN}/${totalN} 章 · 跨章对话 + 卡片复习` : '';
    const scope = selN ? `已勾 ${selN} 章` : '未勾选（按全部资料）';
    return `<div class="chat-head">` + appbar('学习', sub) +
    `</div><div class="content">
      <div class="card sm mb-12">
        <div class="card-head"><div class="card-title">${ic('book', 'coral')}资料库</div><span class="card-count">${totalN} 篇 · 已选 <b class="sel-count">${selN}</b></span></div>
        <div class="lib-tools"><button class="mini-btn" onclick="Student.setAllChapters(true)">全选</button><button class="mini-btn" onclick="Student.setAllChapters(false)">清空</button></div>
        <div class="lib-list">${rows || '<div class="muted">暂无章节</div>'}</div>
      </div>
      <button class="home-card" onclick="Student.openChat()">
        <span class="home-ic">${ic('chat')}</span>
        <span class="home-txt"><b>对话</b><small>${scope} · 向 TUTOR 跨章提问，自动标注来源</small></span>
        <span class="home-go">›</span>
      </button>
      <button class="home-card" onclick="Student.enterKnowledge()">
        <span class="home-ic alt">${ic('cards')}</span>
        <span class="home-txt"><b>知识卡片</b><small>${scope} · 翻卡记忆，进度计入掌握度</small></span>
        <span class="home-go">›</span>
      </button>
    </div>` + tabbar();
  },
  // ===== 学习多选集：勾选章节（驱动对话跨章检索 + 知识卡片跨章复习），localStorage 记忆 =====
  initSelChapters() {
    if (this.selChapters !== null || !App.chapters.length) return;
    try {
      const saved = JSON.parse(localStorage.getItem('aistudy_sel_chapters') || 'null');
      const valid = (saved || []).filter(id => App.chapters.some(c => c.id === id));
      this.selChapters = valid.length ? valid : App.chapters.map(c => c.id);
    } catch (e) { this.selChapters = App.chapters.map(c => c.id); }
  },
  // 有效选集；勾选空 → 全部章节兜底（保证学习范围非空）
  selChapterIds() {
    this.initSelChapters();
    const valid = (this.selChapters || []).filter(id => App.chapters.some(c => c.id === id));
    return valid.length ? valid : App.chapters.map(c => c.id);
  },
  toggleChapterMulti(id) {
    this.initSelChapters();
    const i = this.selChapters.indexOf(id);
    if (i >= 0) this.selChapters.splice(i, 1); else this.selChapters.push(id);
    this.saveSelChapters(); render();
  },
  setAllChapters(on) {
    this.selChapters = on ? App.chapters.map(c => c.id) : [];
    this.saveSelChapters(); render();
  },
  saveSelChapters() {
    try { localStorage.setItem('aistudy_sel_chapters', JSON.stringify(this.selChapters)); } catch (e) {}
  },
  // 主菜单 → 对话页
  openChat() { this.learnChat = true; this.knowledgeIdx = false; this.knowledgeDeck = false; render(); },
  // 学习 tab 再点：卡片/对话子视图 → 强制回主菜单
  goLearn() {
    if (App.state.hash === 'learn' && (this.learnChat || this.knowledgeIdx || this.knowledgeDeck)) {
      this.learnChat = false; this.knowledgeIdx = false; this.knowledgeDeck = false; this.knowledgeFlipped = false;
      return render();
    }
    go('learn');
  },
  // 对话页 ← 返回主菜单
  backToLearn() { this.learnChat = false; render(); },
  // 知识卡片视图退出：落回来源（从对话进→回对话；从主菜单进→回主菜单）
  leaveKnowledge() {
    this.knowledgeIdx = false; this.knowledgeDeck = false; this.knowledgeFlipped = false;
    render();
  },

  /* ===== 对话页（学习 tab 子视图）===== */
  async viewLearnChat() {
    let convs = [];
    try { convs = (await API.get("/api/conversations")).conversations || []; } catch (e) { convs = []; }
    this.convs = convs;
    // 辅导模式开关：从 localStorage 读，无则默认「直接讲解」
    this.tutorMode = localStorage.getItem("aistudy_tutor_mode") || "direct";
    // 资料范围 = 学习多选集（hub 勾选）；选集空 → 全部章节兜底
    const sel = this.selChapterIds();
    if (!this.askCtx && (!App.activeChapter || sel.indexOf(App.activeChapter) < 0)) App.activeChapter = sel[0] || null;
    if (!this.convId && convs.length) this.convId = convs[0].id;
    // 发送后重绘期间（_noReload）跳过服务器重拉：本地已含刚上屏的用户消息，
    // 重拉会把未落库消息冲掉 → 输入的问题要等 TUTOR 回复才出现（v2.1.0 修）
    if (!this._noReload && this.convId) {
      try { const d = await API.get("/api/conversations/" + this.convId); this.messages = d.messages || []; } catch (e) { this.messages = []; }
    }
    this.scrollChatToBottom();
    const convChips = convs.map(c => `<span class="pill ${this.convId === c.id ? 'active' : ''}" style="cursor:pointer" onclick="Student.selectConv('${c.id}')" onmousedown="Student.pressStart(event,'${c.id}')" onmouseup="Student.pressEnd(event)" onmouseleave="Student.pressEnd(event)" ontouchstart="Student.pressStart(event,'${c.id}')" ontouchend="Student.pressEnd(event)" ontouchmove="Student.pressMove(event)" ontouchcancel="Student.pressEnd(event)"><span class="pill-t">${esc(c.title)}</span></span>`).join('')
      + `<span class="pill" style="cursor:pointer" onclick="Student.newConv()">＋ 新对话</span>`;
    const msgsHtml = this.messages.map(m => `<div class="msg ${m.role === 'user' ? 'user' : 'bot'}">${m.role === 'user' ? '' : '<div class="who">TUTOR</div>'}${esc(m.content)}</div>`).join('')
      + (this.pendingReply ? `<div class="msg bot"><div class="who">TUTOR</div><span class="typing"><span></span><span></span><span></span></span></div>` : '');
    const modeTxt = this.tutorMode === 'guide' ? '引导式，不直接给答案' : '直接讲解，有问必答';
    const selTxt = sel.length > 1
      ? `已选 ${sel.length} 章：${sel.slice(0, 2).map(id => App.chapterName(id)).join('、')}${sel.length > 2 ? ` 等 ${sel.length} 章` : ''}`
      : (sel.length === 1 ? App.chapterName(sel[0]) : '全部资料');
    const msgs = msgsHtml
      || `<div class="muted" style="padding:12px 0">资料范围：<b>${esc(selTxt)}</b>（回「学习」页可调整勾选）<br/>开始提问（${modeTxt}）——跨章提问会自动标注来源章节。</div>`;
    const relatedHtml = (this.relatedVideos || []).length ? `<div class="card sm" style="margin-top:12px">
      <div class="sec-title">${ic('video', 'coral')}相关视频课（学员自选观看）</div>
      ${this.relatedVideos.map(v => `<a class="video-chip" href="${esc(v.url)}" target="_blank" rel="noopener noreferrer">▶ ${esc(v.title)}${v.platform ? ` · ${esc(v.platform)}` : ''}</a>`).join('')}
      </div>` : '';

    const isGuide = this.tutorMode === 'guide';
    // 头部（appbar + 模式切换）合并为单一吸顶块：appbar 与 seg 成为同一不透明容器，始终一起钉在 top:0，
    // 彻底消除 appbar 与 seg 之间的独立缝隙，iOS 滚动时内容不可能从中间漏出（不再依赖硬编码 top:74px）
    return `<div class="chat-head">` + appbar('对话', isGuide ? '引导式辅导 · 不直接给答案' : '直接讲解 · 有问必答', 'Student.backToLearn()') +
    `<div class="seg-wrap"><div class="seg">
        <button class="${isGuide ? 'on' : ''}" onclick="Student.setTutorMode('guide')">${ic('grad')}引导式</button>
        <button class="${isGuide ? '' : 'on'}" onclick="Student.setTutorMode('direct')">${ic('chat')}直接讲解</button>
      </div></div></div>` +
    `<div class="content chat-view">
      <!-- AI info 条：安静，不抢戏 -->
      <div class="ai-info">${ic('shield')}回答由 AI 生成，请核对资料原文 · 越界内容已拦截</div>
      <!-- 资料范围（多选集来自学习页资料库勾选）+ 对话 chips -->
      <div class="scope-bar">${ic('book', 'coral')}<span>${esc(selTxt)}</span></div>
      <div class="pill-wrap mb-10">${convChips}</div>
      <!-- 进度行：轮数 -->
      <div class="row-meta"><span class="pill">${ic('clock')}第 ${this.turn} / 12 轮</span></div>
      <div class="chat">${msgs}</div>
      ${relatedHtml}
    </div>
    <div class="composer"><div class="composer-body"><div class="flex"><button class="tool-btn" onclick="Student.openWrongConsult()">${ic('lightbulb')}咨询错题</button></div>${this.wrongCtx ? `<div class="muted" style="font-size:12px;margin-bottom:4px">已选 ${this.wrongCtx.length} 道错题，随本条发送</div>` : ''}<div class="flex"><input id="chatInput" class="grow" placeholder="回答引导问题，或追问…" onkeydown="if(event.key==='Enter')Student.send()"/><button class="send" onclick="Student.send()">${ic('arrowUp')}</button></div></div></div>` + tabbar();
  },
  async enterKnowledge() {
    const sel = this.selChapterIds();
    if (!sel.length) return toast('请先选择章节');
    this.knowledgeIdx = true; this.knowledgeDeck = false; await render();
  },
  async viewKnowledge() {
    const sel = this.selChapterIds();
    if (!sel.length) return '';
    // 跨章合并：逐章拉卡（每章失败不影响其他章），扁平卡集供 deck 复习，分组供列表浏览
    const groups = [];
    const cardsAll = [];
    let errN = 0;
    for (const cid of sel) {
      let d = null;
      try { d = await API.get('/api/knowledge/' + cid); } catch (e) { errN++; continue; }
      const cs = (d && d.cards) || [];
      if (!cs.length) continue;
      const chName = App.chapterName(cid);
      cs.forEach(c => { c.chName = chName; cardsAll.push(c); });
      groups.push({ cid, name: chName, cards: cs });
    }
    if (errN) toast(errN + ' 个章节加载失败');
    this.knowledgeGroups = groups;
    this.knowledgeCards = cardsAll;
    if (!cardsAll.length) {
      return appbar('知识卡片', `已选 ${sel.length} 章`, 'Student.leaveKnowledge()') + `<div class="content">
        <div class="note"><div class="big">${ic('cards')}</div>所选章节还没有知识卡片</div>
        <div class="muted" style="text-align:center">教师发布章节后自动生成；稍后下拉刷新</div>
        <button class="btn" style="margin-top:14px" onclick="Student.generateKnowledge()">${ic('sparkle')}立即生成</button>
      </div>` + tabbar();
    }
    const count = k => cardsAll.filter(c => c.status === k).length;
    const due = cardsAll.filter(c => c.status !== 'mastered' && String(c.next_review_at || '').slice(0, 10) <= new Date().toISOString().slice(0, 10)).length;
    const gBody = groups.map(g => {
      const gc = g.cards;
      const gcount = k => gc.filter(c => c.status === k).length;
      const gdue = gc.filter(c => c.status !== 'mastered' && String(c.next_review_at || '').slice(0, 10) <= new Date().toISOString().slice(0, 10)).length;
      const open = !!this.knowledgeGroupOpen[g.cid];
      return `<div class="kc-ch">
        <div class="kc-ch-head" onclick="Student.toggleKnowledgeGroup('${g.cid}')">
          <div style="flex:1"><b>${esc(g.name)}</b><small>${gc.length} 张 · 已掌握 ${gcount('mastered')} · 学习中 ${gcount('learning') + gcount('reviewing')} · 未学 ${gcount('new')} · 今日待复习 ${gdue}</small></div>
          <span class="caret">${open ? '▾' : '▸'}</span></div>
        ${open ? `<div class="kc-grid">${gc.map(c => `<div class="kc-mini ${c.status}" onclick="Student.kcDetail('${c.id}')"><b>${esc(c.front)}</b><small>${esc(c.sub_concept || '知识点')}</small></div>`).join('')}</div>` : ''}</div>`;
    }).join('');
    return appbar('知识卡片', `已选 ${sel.length} 章 · 共 ${cardsAll.length} 张`, 'Student.leaveKnowledge()') + `<div class="content">
      <button class="btn" style="width:100%;margin-bottom:14px" onclick="Student.startKnowledgeDeck()">${ic('cards')}开始复习（${cardsAll.length} 张${due ? ` · 今日待复习 ${due}` : ''}）</button>
      <div class="kc-summary"><b>总览</b><span>已掌握 ${count('mastered')} · 学习中 ${count('learning') + count('reviewing')} · 未学 ${count('new')} · 今日待复习 ${due} · 点章头展开看卡片</span></div>
      ${gBody}
    </div>` + tabbar();
  },
  toggleKnowledgeGroup(cid) { this.knowledgeGroupOpen[cid] = !this.knowledgeGroupOpen[cid]; render(); },
  kcStatusBadge(st) {
    const m = { mastered: ['master', '已掌握'], reviewing: ['prog', '复习中'], learning: ['prog', '学习中'], new: ['weak', '未学'] };
    const x = m[st] || m.new;
    return `<span class="badge ${x[0]}">${x[1]}</span>`;
  },
  // 点卡片 → 详情 sheet（正/反面 + 去问 TUTOR）
  kcDetail(id) {
    const c = (this.knowledgeCards || []).find(x => x.id === id); if (!c) return;
    openSheet(`<div class="row" style="font-weight:700;cursor:default;display:flex;align-items:center;gap:8px;flex-wrap:wrap">${ic('cards')}知识卡片${c.chName ? `<span class="muted" style="font-size:12px;font-weight:500">${esc(c.chName)}</span>` : ''}${this.kcStatusBadge(c.status)}</div>
      <div class="sheet-txt"><b>${esc(c.front)}</b></div>
      <div class="sheet-txt dim">${esc(c.back)}</div>
      <div class="row" onclick="Student.askKcTutor('${c.id}')">${ic('chat')}去问 TUTOR · 就这个知识点深入讲解</div>
      <div class="row cancel" onclick="closeSheet()">关闭</div>`);
  },
  // 知识卡片 → 对话（v2.1.0）：跳到对话页并自动提问该卡知识点；
  // kc_ctx 带卡片答案进 payload，TUTOR 基于它发散讲解（卡片内容不进聊天历史文本）
  async askKcTutor(id) {
    const c = (this.knowledgeCards || []).find(x => x.id === id); if (!c) return;
    closeSheet();
    this.askCtx = null;                 // 卡片自带章节范围，不继承「路径」上下文
    this.learnChat = true; this.knowledgeIdx = false; this.knowledgeDeck = false;
    App.activeChapter = c.chapter_id;
    await this.doSend(
      `请围绕「${c.front}」这个知识点详细展开讲解：它是什么意思、核心要点、具体例子，以及容易搞错的地方。`,
      (p) => { p.chapter_ids = [c.chapter_id]; p.kc_ctx = { front: c.front, back: c.back, sub_concept: c.sub_concept || '', chapter_id: c.chapter_id }; }
    );
  },
  async generateKnowledge() {
    try { const d = await API.post('/api/knowledge/generate', { chapter_ids: this.selChapterIds() }); this.knowledgeCards = d.cards || []; toast('知识卡片已生成'); render(); } catch (e) { toast(e.message); }
  },
  // 复习进度本地存储（暂停退出/续学）；v2.0 卡集跨章：记录签名（章 id 集）而非单 cid
  _kcKey() {
    const ids = [];
    this.knowledgeCards.forEach(c => { if (ids.indexOf(c.chapter_id) < 0) ids.push(c.chapter_id); });
    return ids.slice().sort().join(',');
  },
  _kcSave() {
    const key = this._kcKey(); if (!key) return;
    try { localStorage.setItem('aistudy_kc_progress', JSON.stringify({ ids: key.split(','), pos: this.knowledgePos, ts: Date.now() })); } catch (e) {}
  },
  _kcLoad() {
    try { return JSON.parse(localStorage.getItem('aistudy_kc_progress')) || null; } catch (e) { return null; }
  },
  _kcClear() { try { localStorage.removeItem('aistudy_kc_progress'); } catch (e) {} },
  _kcSavedMatch(saved) {
    if (!saved) return false;
    const key = this._kcKey();
    if (saved.ids && saved.ids.length) return saved.ids.slice().sort().join(',') === key;
    // 兼容旧格式 {cid}：单章卡集且章号一致
    return !!(saved.cid && key && key.indexOf(',') < 0 && key === saved.cid);
  },
  startKnowledgeDeck() {
    const saved = this._kcLoad();
    if (saved && this._kcSavedMatch(saved) && saved.pos > 0 && saved.pos < this.knowledgeCards.length) {
      openSheet(`<div class="row" style="font-weight:700">继续上次复习？</div>
        <div class="row" style="text-align:left;border:none;background:transparent;cursor:default;font-size:13px;color:var(--text-2)">上次复习到第 ${saved.pos} / ${this.knowledgeCards.length} 张，可接着往后复习。</div>
        <div class="row" onclick="Student.resumeKnowledgeDeck()">继续复习</div>
        <div class="row" onclick="Student.resetKnowledgeDeck()">重新开始</div>
        <div class="row cancel" onclick="closeSheet()">取消</div>`);
      return;
    }
    this.knowledgePos = 0; this.knowledgeFlipped = false; this._suppressClick = false; this.knowledgeDeck = true; render();
  },
  resumeKnowledgeDeck() {
    const saved = this._kcLoad(); closeSheet();
    this.knowledgePos = this._kcSavedMatch(saved) ? saved.pos : 0;
    this.knowledgeFlipped = false; this._suppressClick = false; this.knowledgeDeck = true; render();
  },
  resetKnowledgeDeck() {
    closeSheet(); this._kcClear(); this.knowledgePos = 0; this.knowledgeFlipped = false; this._suppressClick = false; this.knowledgeDeck = true; render();
  },
  viewKnowledgeDeck() {
    const c = this.knowledgeCards[this.knowledgePos];
    if (!c) { this.knowledgeDeck = false; this._kcClear(); return this.viewKnowledge(); }
    const total = this.knowledgeCards.length;
    const chTxt = c.chName || '';
    // 卡面：正面小字显示「章 · 知识点」；翻转动画由 flipKnowledge 切 class 驱动（不再整页 render，保证 3D 过渡生效）
    return appbar('复习知识卡片', `第 ${this.knowledgePos + 1} / ${total} 张`, 'Student.pauseKnowledge()') + `<div class="content"><div class="kc-progress"><i style="width:${(this.knowledgePos + 1) / total * 100}%"></i></div>
    <div class="kc-scene" ontouchstart="Student.kcTouchStart(event)" ontouchmove="Student.kcTouchMove(event)" ontouchend="Student.kcTouchEnd(event)" ontouchcancel="Student.kcTouchEnd(event)">
      <div class="kc-card ${this.knowledgeFlipped ? 'is-flipped' : ''} kc-in" onmousedown="Student.kcMouseDown(event)" onclick="Student.flipKnowledge()">
        <div class="kc-face kc-front"><small>${esc(chTxt)} · ${esc(c.sub_concept || '知识点')}</small><b>${esc(c.front)}</b><span>点击翻转查看答案</span></div>
        <div class="kc-face kc-back"><small>${esc(chTxt)} · 答案与解析</small><b>${esc(c.back)}</b></div>
      </div></div>
    <div class="kc-hint">拖动卡片：右滑 = 记住了 · 左滑 = 没记住</div>
    <div class="kc-actions"><button class="btn ghost" onclick="Student.reviewKnowledge(false)">${ic('cross')}没记住</button><button class="btn" onclick="Student.reviewKnowledge(true)">记住了${ic('check')}</button></div>
    <button class="btn ghost kc-quit" onclick="Student.pauseKnowledge()">${ic('back')}暂停退出（保存进度）</button></div>` + tabbar();
  },
  // ===== 卡片手势动画：翻转切 class（3D 过渡）、拖拽跟手、超阈值甩出/回弹、换卡入场 =====
  flipKnowledge() {
    if (this._suppressClick) { this._suppressClick = false; return; }   // 拖动结束补发的 click 抑制
    const el = this._kcCardEl(); if (!el) return;
    this.knowledgeFlipped = !this.knowledgeFlipped;
    el.classList.toggle('is-flipped');    // 同一 DOM 切 class → CSS transition 播放翻转动画
  },
  _kcCardEl() { return document.querySelector('.kc-card'); },
  // touch 拖拽（iOS 翻卡主路径）
  kcTouchStart(e) {
    if (this._kcBusy) return;
    const t = e.touches[0];
    this._kcPointer = { x: t.clientX, y: t.clientY, dragging: false, dx: 0 };
  },
  kcTouchMove(e) {
    const pt = this._kcPointer; if (!pt || this._kcBusy) return;
    const t = e.touches[0];
    const dx = t.clientX - pt.x, dy = t.clientY - pt.y;
    if (!pt.dragging) {
      if (Math.abs(dx) < 6) return;                                   // 未到阈值：等 tap/竖向滚动判定
      if (Math.abs(dy) > Math.abs(dx)) { this._kcPointer = null; return; }  // 竖向滚动 → 放弃横拖
      pt.dragging = true;
      const el = this._kcCardEl(); if (el) el.classList.add('dragging');   // 拖拽期关 transition → 跟手
    }
    e.preventDefault();
    pt.dx = dx;
    const el = this._kcCardEl();
    if (el) el.style.transform = `translateX(${dx}px) rotate(${dx * .045}deg)`;
  },
  kcTouchEnd() {
    const pt = this._kcPointer; this._kcPointer = null;
    if (!pt) return;
    const el = this._kcCardEl(); if (!el) return;
    el.classList.remove('dragging');
    if (!pt.dragging) return;                                          // tap → 交给 click 翻转
    el.style.transform = '';                                           // 先回规则态再决定飞/弹（同一帧 → 过渡衔接）
    this._suppressClick = true;
    setTimeout(() => { this._suppressClick = false; }, 400);
    if (Math.abs(pt.dx) > 70) this.reviewKnowledge(pt.dx > 0);         // 右滑=记住了 / 左滑=没记住（v2.1.0 修方向反）
    // 未超阈值：transform 已清空 → CSS transition 弹回原位
  },
  // mouse 拖拽（桌面调试/教师机）：mousedown 起全局监听，up 解绑
  kcMouseDown(e) {
    if (this._kcBusy || e.button !== 0) return;
    this._kcPointer = { x: e.clientX, y: e.clientY, dragging: false, dx: 0, mouse: true };
    e.preventDefault();
    this._kcOnMove = ev => this._kcMouseMove(ev);
    this._kcOnUp = () => this.kcMouseUp();
    document.addEventListener('mousemove', this._kcOnMove);
    document.addEventListener('mouseup', this._kcOnUp);
  },
  _kcMouseMove(e) {
    const pt = this._kcPointer; if (!pt) return;
    const dx = e.clientX - pt.x, dy = e.clientY - pt.y;
    if (!pt.dragging) {
      if (Math.abs(dx) < 6) return;
      if (Math.abs(dy) > Math.abs(dx)) { this.kcMouseUp(); return; }
      pt.dragging = true;
      const el = this._kcCardEl(); if (el) el.classList.add('dragging');
    }
    pt.dx = dx;
    const el = this._kcCardEl();
    if (el) el.style.transform = `translateX(${dx}px) rotate(${dx * .045}deg)`;
  },
  kcMouseUp() {
    document.removeEventListener('mousemove', this._kcOnMove);
    document.removeEventListener('mouseup', this._kcOnUp);
    this._kcOnMove = null; this._kcOnUp = null;
    const pt = this._kcPointer; this._kcPointer = null;
    if (!pt || !pt.dragging) return;                                   // 纯点击 → click 翻转
    const el = this._kcCardEl(); if (!el) return;
    el.classList.remove('dragging');
    el.style.transform = '';
    this._suppressClick = true;
    setTimeout(() => { this._suppressClick = false; }, 400);
    if (Math.abs(pt.dx) > 70) this.reviewKnowledge(pt.dx > 0);
  },
  // 暂停退出：存进度 + 退出复习视图（落回来源：对话或主菜单）
  pauseKnowledge() {
    if (this.knowledgeCards.length && this.knowledgePos < this.knowledgeCards.length) this._kcSave();
    this.knowledgeIdx = false; this.knowledgeDeck = false; this.knowledgeFlipped = false; this._kcBusy = false;
    render();
  },
  async reviewKnowledge(remembered) {
    const c = this.knowledgeCards[this.knowledgePos]; if (!c || this._kcBusy) return;
    const el = this._kcCardEl();
    this._kcBusy = true;
    // 先播飞出动画（右=记住了 / 左=没记住），再提交 → 新卡入场
    if (el) { el.style.pointerEvents = 'none'; el.classList.add(remembered ? 'out-r' : 'out-l'); }
    await new Promise(r => setTimeout(r, 340));
    try {
      const d = await API.post('/api/knowledge/' + c.id + '/review', { remembered });
      this.knowledgeCards[this.knowledgePos] = d.card;
      this.knowledgePos++; this.knowledgeFlipped = false; this._kcBusy = false;
      if (this.knowledgePos >= this.knowledgeCards.length) this._kcClear(); else this._kcSave();
      this._suppressClick = false;
      render();   // 新卡带 .kc-in 入场动画
    } catch (e) {
      if (el) { el.classList.remove('out-r', 'out-l'); el.style.pointerEvents = ''; el.style.transform = ''; }
      this._kcBusy = false; toast(e.message);
    }
  },
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
    if (input) input.value = "";
    await this.doSend(content, (payload) => {
      // 检索范围：从「路径」提问 → 用该 session 的章；普通提问勾选 >1 章 → 多选集跨章检索
      if (this.askCtx) {
        payload.chapter_ids = this.askCtx.chapter_ids || [];
        payload.concept_tags = this.askCtx.concept_tags || [];
      } else {
        const sel = this.selChapterIds();
        if (sel.length > 1) payload.chapter_ids = sel;
      }
      if (this.wrongCtx) payload.wrong_ctx = this.wrongCtx;
    });
  },
  // 发送消息公共通道：先本地即时上屏（pendingReply 思考气泡），再等 TUTOR 回复。
  // v2.1.0：知识卡片「去问 TUTOR」也走这里（decorate 注入 kc_ctx）。
  async doSend(content, decorate) {
    if (!this.convId) { await this.newConv(); }
    this.messages.push({ role: "user", content });
    this.pendingReply = true;   // 显示思考气泡（即时反馈）
    this._noReload = true;      // 本次重绘不重拉消息，保住刚上屏的用户消息
    render();
    this.scrollChatToBottom();
    try {
      const payload = { content, chapter_id: App.activeChapter, tutor_mode: this.tutorMode || "direct" };
      if (decorate) decorate(payload);
      const d = await API.post(`/api/conversations/${this.convId}/message`, payload);
      this.wrongCtx = null;
      this.messages.push({ role: "assistant", content: d.reply });
      this.turn = d.turn;
      this.relatedVideos = d.related_videos || [];
      this.pendingReply = false;
      this._noReload = false;
      render();
      this.scrollChatToBottom();
    } catch (e) {
      this.pendingReply = false;
      this._noReload = false;
      toast(e.message); render();
    }
  },
  // render 为异步视图更新，下一帧再贴底才能覆盖思考气泡和 TUTOR 新回复。
  scrollChatToBottom() {
    requestAnimationFrame(() => {
      const el = document.querySelector('.content.chat-view');
      if (el) el.scrollTop = el.scrollHeight;
    });
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
      <div class="meta"><div class="t">自主练习</div><div class="s">根据资料 AI 出题 · 5-10 题自选 · 即答即批</div></div></div>`;
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
  /* ===== 练习历史左滑删除（swipe-row 结构：swipe-main 内容 + swipe-del 底层红按钮）===== */
  swStart(e, id) {
    if (this._sw) return;
    if (e.type === "mousedown" && this._touchTs && Date.now() - this._touchTs < 700) return;  // 忽略触摸派生的合成 mouse
    const p = (e.touches && e.touches[0]) || e;
    const row = document.getElementById("sw_" + id); if (!row) return;
    const main = row.querySelector(".swipe-main");
    this._sw = { id, x: p.clientX, y: p.clientY, dx: 0, base: row.classList.contains("open") ? -84 : 0, dragging: false, main };
    if (e.type === "mousedown") e.preventDefault();
  },
  swMove(e) {
    const s = this._sw; if (!s) return;
    const p = (e.touches && e.touches[0]) || e;
    const dx0 = p.clientX - s.x, dy = p.clientY - s.y;
    if (!s.dragging) {
      if (Math.abs(dx0) < 6) return;                                  // 未到阈值：交给 tap
      if (Math.abs(dy) > Math.abs(dx0)) { this._sw = null; return; }  // 竖向滚动 → 放弃横拖
      s.dragging = true;
      s.main.style.transition = "none";                               // 拖动期跟手
    }
    if (e.cancelable) e.preventDefault();
    s.dx = Math.max(-84, Math.min(0, s.base + dx0));                  // 仅向左展开（已开时右拉回收）
    s.main.style.transform = `translateX(${s.dx}px)`;
  },
  swEnd(e, id) {
    const s = this._sw; this._sw = null;
    if (!s) return;
    if (e.type === "touchend" || e.type === "touchcancel") this._touchTs = Date.now();
    if (!s.dragging) return;                                          // tap → 交给 click
    s.main.style.transition = "";
    const row = document.getElementById("sw_" + id);
    const open = s.dx < -40;
    if (row) row.classList.toggle("open", open);
    s.main.style.transform = open ? "translateX(-84px)" : "";
    this._swSuppress = true;                                          // 抑制随后的 click 打开练习
    setTimeout(() => { this._swSuppress = false; }, 350);
  },
  delPractice(id) {
    const s = (this.practiceSessions || []).find(x => x.id === id);
    openSheet(`<div class="row" style="font-weight:700">删除练习记录</div>
      <div class="row" style="text-align:left;border:none;background:transparent;cursor:default;font-size:13px;color:var(--text-2)">确定删除${s && s.completed ? '' : '这条「进行中」'}练习？删除后不可恢复，其错题不再计入薄弱点。</div>
      <div class="row danger" onclick="Student.confirmDelPractice('${id}')">删除</div>
      <div class="row cancel" onclick="closeSheet()">取消</div>`);
  },
  async confirmDelPractice(id) {
    closeSheet();
    try {
      await API.del("/api/practice/" + id);
      this.practiceSessions = (this.practiceSessions || []).filter(x => x.id !== id);
      toast("已删除练习记录"); render();
    } catch (e) { toast(e.message); }
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
    // 历史条目：左滑露出删除（v2.1.0），完成后/进行中均可删
    const hist = sessions.map(s => {
      const status = s.completed ? `<span class="badge master">已完成 ${s.score}</span>` : `<span class="badge prog">进行中</span>`;
      const body = `<div class="qcard" onclick="Student.openPractice('${s.id}')"><div class="ic">${ic('target')}</div>
        <div class="meta"><div class="t">练习 ${s.question_count} 题</div><div class="s">覆盖：${(s.chapter_ids || []).map(App.chapterName.bind(App)).map(esc).join('、')}</div></div>
        <div style="text-align:right">${status}</div></div>`;
      return `<div class="swipe-row" id="sw_${s.id}" ontouchstart="Student.swStart(event,'${s.id}')" ontouchmove="Student.swMove(event)" ontouchend="Student.swEnd(event,'${s.id}')" ontouchcancel="Student.swEnd(event,'${s.id}')" onmousedown="Student.swStart(event,'${s.id}')" onmousemove="Student.swMove(event)" onmouseup="Student.swEnd(event,'${s.id}')" onmouseleave="Student.swEnd(event,'${s.id}')">
        <div class="swipe-del" onclick="Student.delPractice('${s.id}')">${ic('trash')}删除</div>
        <div class="swipe-main">${body}</div></div>`;
    }).join('') || '<div class="muted">暂无练习记录</div>';
    return appbar('自主练习', 'AI 出题 · 5-10 题 · 高难度') + `<div class="content">
      <div class="card sm"><div style="font-weight:700;font-size:13px;margin-bottom:8px">选择章节（可多选）</div>${chapterSel}
        <label class="count-label">题数<select class="count-sel" onchange="Student.practiceCount=Number(this.value)">${[5,6,7,8,9,10].map(n => `<option value="${n}" ${n === Student.practiceCount ? 'selected' : ''}>${n} 题</option>`).join('')}</select></label>
        <button class="btn mt-12" onclick="Student.generatePractice()">${ic('target')}生成练习</button>
        <button class="btn ghost" style="margin-top:8px" onclick="Student.exitPractice()">返回测评列表</button></div>
      <div class="card"><div class="sec-title">练习历史</div>${hist}</div>
    </div>` + tabbar();
  },
  async generatePractice() {
    const ids = (this.practiceChapters && this.practiceChapters.length) ? this.practiceChapters : [App.activeChapter];
    if (!ids || !ids.length) { toast("请先选择章节"); return; }
    try {
      const d = await API.post("/api/practice/generate", { chapter_ids: ids, count: this.practiceCount || 5 });
      this.practice = d; this.practiceResult = null; this.answers = {};
      render(); toast("已生成练习");
    } catch (e) { toast(e.message); }
  },
  async openPractice(id) {
    if (this._swSuppress) { this._swSuppress = false; return; }   // 左滑结束补发的 click 抑制
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
    let kcOv = { chapters: [] };
    try { kcOv = await API.get("/api/knowledge/overview"); } catch (e) {}
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
    // AI 学习建议（RPT-003 改每日，v2.1.0：自动生成长期未生效 → 改为点击生成，一天最多一次）
    const adviceLines = (advice.advice || "").split("\n").filter(Boolean);
    const adviceHtml = advice.has_advice && adviceLines.length
      ? adviceLines.map(t => `<div class="ai-tip"><div class="ic">AI</div><div style="font-size:13.5px;line-height:1.5">${esc(t)}</div></div>`).join('')
        + `<div class="muted" style="font-size:11.5px;margin-top:6px">${esc(advice.advice_date || '')} 生成 · 每天最多生成一次</div>`
      : `<div class="muted" style="margin-bottom:8px">还没有学习建议——点下方按钮立即生成：AI 根据你今天的对话、练习、测评与薄弱章节给出 3 条建议（每天一次）</div>
         <button class="btn sm" onclick="Student.genAdvice()" ${this._adviceBusy ? 'disabled' : ''}>${ic('sparkle')}${this._adviceBusy ? '正在生成…' : '生成今日建议'}</button>`;
    // 本周概况 + 成绩分析（RPT-001/002 迁移）
    const s = weekly.stats || {};
    const weeklyHtml = `<div class="card"><div style="font-weight:700;margin-bottom:12px">本周概况</div>
      <div class="stat-row" style="margin:0">
        <div class="stat"><div class="v">${s.days || 0}</div><div class="k">学习天数</div></div>
        <div class="stat"><div class="v">${s.conversations || 0}</div><div class="k">对话天数</div></div>
        <div class="stat"><div class="v">${s.quizzes || 0}</div><div class="k">测评天数</div></div></div>
      <div style="font-size:13px;margin-top:10px">平均：<b>${s.avg_score == null ? '—' : s.avg_score}</b> · 最高：<b>${s.max_score == null ? '—' : s.max_score}</b></div>
      <div class="muted" style="margin-top:6px">薄弱章节：${(weekly.weak_chapters || []).map(esc).join('、') || '无'}</div></div>`;
    // 知识卡片学习进度块：数据 GET /api/knowledge/overview（仅含已产生复习记录的章）
    const kcChs = (kcOv.chapters || []).filter(x => x.counts && x.counts.total > 0);
    const kcTotal = kcChs.reduce((s, x) => s + x.counts.total, 0);
    const kcMastered = kcChs.reduce((s, x) => s + x.counts.mastered, 0);
    const kcHtml = kcChs.length
      ? `<div class="card"><div class="sec-title">知识卡片（计入掌握度）</div>${kcChs.map(x => {
          const ct = x.counts;
          const pct = Math.round(ct.mastered / ct.total * 100);
          return `<div class="chapter" style="cursor:default"><div><div class="nm">${esc(App.chapterName(x.chapter_id))}</div>
            <div class="mt">已掌握 ${ct.mastered}/${ct.total} 张 · 学习中 ${ct.learning + ct.reviewing} · 未学 ${ct.new} · 今日待复习 ${ct.today_due}</div>
            <div class="kc-bar"><i style="width:${pct}%"></i></div></div>
            <span class="badge ${ct.mastered === ct.total ? 'master' : (ct.mastered ? 'prog' : 'weak')}">${pct}%</span></div>`;
        }).join('')}
      <div class="muted" style="font-size:12px;margin-top:6px">已掌握 ${kcMastered}/${kcTotal} 张 · 仅已掌握卡片计入掌握度（5 分/张，复习越近权重越高）</div>
      <details class="kc-help"><summary>掌握度怎么算？（含知识卡片口径）</summary>
        <div>掌握度 M =「已得权重分 ÷ 总分 × 100」，把三类学习成果合在一起：<br/>
        <b>① 测评 / 练习</b>：按每次作答得分加权计入；<br/>
        <b>② 知识卡片</b>：只有复习到「已掌握」的卡才计入，每张按满分 5 分算；学习中 / 复习中 / 未学的卡既不罚分也不计分；<br/>
        <b>③ 卡片权重会随时间衰减</b>：距上次复习每满 1 周权重减半（×0.5^周），复习越近贡献越大，很久不复习的已掌握卡权重会趋近 0——所以要常回来翻卡；<br/>
        <b>④ 等级</b>：M ≥ 80 且有效作答 ≥ 2 次 = 已掌握；50–80 = 进行中；&lt;50 = 薄弱；从未作答 = 未评估。</div></details></div>`
      : `<div class="card"><div class="sec-title">知识卡片（计入掌握度）</div><div class="muted" style="font-size:12.5px">还没有复习过知识卡片——去「学习」页勾选章节开始翻卡记忆</div></div>`;
    return appbar('进度', '按章节掌握度（仅本人）') + `<div class="content">
      <div class="stat-row"><div class="stat"><div class="v" style="color:var(--green)">${c.master}</div><div class="k">已掌握</div></div>
        <div class="stat"><div class="v" style="color:var(--amber)">${c.progress}</div><div class="k">进行中</div></div>
        <div class="stat"><div class="v" style="color:var(--red)">${c.weak}</div><div class="k">薄弱</div></div>
        <div class="stat"><div class="v" style="color:var(--text-3)">${c.na}</div><div class="k">未评估</div></div></div>
      <div class="card"><div style="font-weight:700;margin-bottom:10px">AI 学习建议</div>${adviceHtml}</div>
      ${weeklyHtml}
      ${kcHtml}
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
  // 点击生成今日 AI 学习建议（一天最多一次，后端幂等：当天已有则直接返回）
  async genAdvice() {
    if (this._adviceBusy) return;
    this._adviceBusy = true; render();
    try {
      const d = await API.post("/api/progress/advice/generate", {});
      toast(d.generated ? "今日建议已生成" : "今天已生成过建议");
    } catch (e) { toast(e.message); }
    this._adviceBusy = false; render();
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
