/* 学生视图：学习（引导对话）/ 测评 / 进度 / 周报 */
const Student = {
  convId: null,
  messages: [],
  turn: 0,
  quiz: null,
  answers: {},
  result: null,

  async render() {
    const h = App.state.hash;
    if (h === "quiz") {
      if (this.result) return this.viewResult();
      if (this.quiz) return this.viewQuizTake();
      return await this.viewQuizList();
    }
    if (h === "progress") return await this.viewProgress();
    if (h === "report") return await this.viewReport();
    return await this.viewLearn();
  },

  /* ===== 学习：章节 + 引导式对话 ===== */
  async viewLearn() {
    let convs = [];
    try { convs = (await API.get("/api/conversations")).conversations || []; } catch (e) { convs = []; }
    if (!this.convId && convs.length) this.convId = convs[0].id;
    if (this.convId) {
      try { const d = await API.get("/api/conversations/" + this.convId); this.messages = d.messages || []; } catch (e) { this.messages = []; }
    }
    const chapters = App.chapters.map(c => `<div class="chapter ${App.activeChapter === c.id ? 'active' : ''}" onclick="Student.selectChapter('${c.id}')">
      <div><div class="nm">${esc(c.name)}</div><div class="mt">${esc(c.folder || '未分组')}</div></div></div>`).join('');
    const convChips = convs.map(c => `<span class="pill ${this.convId === c.id ? 'active' : ''}" style="cursor:pointer" onclick="Student.selectConv('${c.id}')">${esc(c.title)}</span>`).join('')
      + `<span class="pill" style="cursor:pointer" onclick="Student.newConv()">＋ 新对话</span>`;
    const msgs = this.messages.map(m => `<div class="msg ${m.role === 'user' ? 'user' : 'bot'}">${m.role === 'user' ? '' : '<div class="who">TUTOR</div>'}${esc(m.content)}</div>`).join('')
      || `<div class="muted" style="padding:12px 0">从左侧选择章节，开始引导式提问（不会直接给答案）。</div>`;

    return appbar('学习', '引导式辅导 · 不直接给答案') +
    `<div class="content">
      <div class="pill-wrap" style="margin-bottom:10px">
        <span class="pill active">🧑‍🎓 ${esc((App.state.user && App.state.user.grade) || '未设置年级')}</span>
        <span class="pill">🧭 引导式</span>
      </div>
      <div class="gate">🛡️ 回答由 AI 生成，请核对资料原文 · 越界内容已拦截</div>
      <div class="card sm" style="margin-bottom:12px"><div style="font-weight:700;font-size:13px;margin-bottom:8px">📚 资料库（点选范围）</div>${chapters || '<div class="muted">暂无章节</div>'}</div>
      <div class="pill-wrap" style="margin-bottom:10px">${convChips}</div>
      <div class="pill" style="margin-bottom:10px">🧭 第 ${this.turn} / 12 轮</div>
      <div class="chat">${msgs}</div>
    </div>
    <div class="composer"><input id="chatInput" placeholder="回答引导问题，或追问…" onkeydown="if(event.key==='Enter')Student.send()"/><button class="send" onclick="Student.send()">↑</button></div>` + tabbar();
  },
  selectChapter(id) { App.activeChapter = id; render(); },
  selectConv(id) { this.convId = id; render(); },
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
    render();
    try {
      const d = await API.post(`/api/conversations/${this.convId}/message`, { content, chapter_id: App.activeChapter });
      this.messages.push({ role: "assistant", content: d.reply });
      this.turn = d.turn;
      render();
    } catch (e) { toast(e.message); render(); }
  },
  async delConv(id) {
    try { await API.del("/api/conversations/" + id); this.convId = null; render(); toast("已删除对话"); }
    catch (e) { toast(e.message); }
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
    return appbar('测评', '教师发布 · 全班同题') + `<div class="content">${list}</div>` + tabbar();
  },
  async openQuiz(id) {
    try { this.quiz = await API.get("/api/quizzes/" + id); this.answers = {}; this.result = null; render(); }
    catch (e) { toast(e.message); }
  },
  viewQuizTake() {
    const q = this.quiz.quiz;
    const qs = (this.quiz.questions || []).map((item, i) => {
      if (item.type === "essay") return `<div class="q"><div class="qt"><span class="n">${i + 1}</span><span>${esc(item.content)}</span></div><textarea id="ans_${item.id}" placeholder="输入你的回答…"></textarea></div>`;
      // bool 是非题：无 options，固定渲染「正确 / 错误」两个按钮
      if (item.type === "bool") {
        const boolOpts = ['正确', '错误'].map(v => `<div class="opt" id="opt_${item.id}_${v}" onclick="Student.pick('${item.id}','${v}')"><span class="dot"></span>${v}</div>`).join('');
        return `<div class="q"><div class="qt"><span class="n">${i + 1}</span><span>${esc(item.content)}</span></div>${boolOpts}</div>`;
      }
      const opts = (item.options || []).map((o, oi) => `<div class="opt" id="opt_${item.id}_${oi}" onclick="Student.pick('${item.id}',${oi})"><span class="dot"></span>${esc(o)}</div>`).join('');
      return `<div class="q"><div class="qt"><span class="n">${i + 1}</span><span>${esc(item.content)}</span></div>${opts}</div>`;
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

  /* ===== 进度 ===== */
  async viewProgress() {
    let mastery = { chapters: [], counts: { master: 0, progress: 0, weak: 0, na: 0 } };
    let weak = { weak_points: [] };
    let reviews = { review_items: [] };
    try { mastery = await API.get("/api/progress/mastery"); } catch (e) {}
    try { weak = await API.get("/api/progress/weak-points"); } catch (e) {}
    try { reviews = await API.get("/api/progress/review-items"); } catch (e) {}
    const c = mastery.counts || { master: 0, progress: 0, weak: 0, na: 0 };
    const chapList = (mastery.chapters || []).map(ch => {
      const st = stateOf(ch.m, ch.attempts);
      return `<div class="chapter"><div><div class="nm">${esc(ch.name)}</div><div class="mt">掌握度 ${ch.m == null ? '—' : ch.m + '%'} · 作答 ${ch.attempts} 次</div></div><span class="badge ${st.cls}">${st.label}</span></div>`;
    }).join('') || '<div class="muted">暂无章节</div>';
    const weakHtml = (weak.weak_points || []).map(w => `<div class="weak"><span class="badge weak" style="flex-shrink:0">${esc(w.name)}</span><div><div style="font-weight:600;font-size:13.5px">M=${w.m}%</div>
      ${(w.evidence || []).slice(0, 2).map(e => `<div class="ev">• ${esc(e.question)}</div>`).join('')}</div></div>`).join('') || '<div class="muted">暂无薄弱章节 🎉</div>';
    const revHtml = (reviews.review_items || []).map(r => `<div class="rev-item ${r.status === 'done' ? 'done' : ''}">
      <span class="badge ${r.status === 'done' ? 'master' : 'weak'}">${esc(App.chapterName(r.chapter_id))}</span>
      <div style="flex:1;font-size:13px">${r.status === 'done' ? '已完成' : (r.due ? '已到期，可作答' : '下次复习 ' + r.interval_days + ' 天后')}</div>
      ${r.status === 'pending' && r.due ? `<button class="mini-btn" style="border-color:var(--coral);color:var(--coral-strong)" onclick="Student.openReview('${r.id}')">作答</button>` : ''}</div>`).join('') || '<div class="muted" style="font-size:12.5px">尚未生成复习计划</div>';
    return appbar('进度', '按章节掌握度（仅本人）') + `<div class="content">
      <div class="stat-row"><div class="stat"><div class="v" style="color:var(--green)">${c.master}</div><div class="k">已掌握</div></div>
        <div class="stat"><div class="v" style="color:var(--amber)">${c.progress}</div><div class="k">进行中</div></div>
        <div class="stat"><div class="v" style="color:var(--red)">${c.weak}</div><div class="k">薄弱</div></div>
        <div class="stat"><div class="v" style="color:var(--text-3)">${c.na}</div><div class="k">未评估</div></div></div>
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

  /* ===== 周报 ===== */
  async viewReport() {
    let d = null;
    try { d = await API.get("/api/reports/weekly"); } catch (e) { d = { stats: {}, weak_chapters: [], advice: "" }; }
    const s = d.stats || {};
    const advice = (d.advice || "").split("\n").filter(Boolean);
    return appbar('周报', '本周学习总结') + `<div class="content">
      <div class="report-h"><div class="t">本周</div><div class="d">${esc((App.state.user && App.state.user.display_name) || '')} 的学习周报</div></div>
      <div class="card"><div style="font-weight:700;margin-bottom:12px">本周概况</div><div class="stat-row" style="margin:0">
        <div class="stat"><div class="v">${s.days || 0}</div><div class="k">学习天数</div></div>
        <div class="stat"><div class="v">${s.conversations || 0}</div><div class="k">对话天数</div></div>
        <div class="stat"><div class="v">${s.quizzes || 0}</div><div class="k">测评天数</div></div></div></div>
      <div class="card"><div style="font-weight:700;margin-bottom:10px">成绩分析</div>
        <div>平均：<b>${s.avg_score == null ? '—' : s.avg_score}</b> · 最高：<b>${s.max_score == null ? '—' : s.max_score}</b></div>
        <div class="muted" style="margin-top:6px">薄弱章节：${(d.weak_chapters || []).map(esc).join('、') || '无'}</div></div>
      <div class="card"><div style="font-weight:700;margin-bottom:10px">AI 学习建议</div>
        ${advice.length ? advice.map(t => `<div class="ai-tip"><div class="ic">AI</div><div style="font-size:13.5px;line-height:1.5">${esc(t)}</div></div>`).join('') : '<div class="muted">本周暂无建议</div>'}</div>
    </div>` + tabbar();
  },
};
