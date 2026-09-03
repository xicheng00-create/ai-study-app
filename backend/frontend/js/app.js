/* App shell：boot / hash 路由 / 登录 / tabbar / toast / sheet */
const ICONS = {
  learn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
  path: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="18" cy="18" r="3"/><path d="M8.5 8.5L15.5 15.5"/></svg>',
  quiz: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>',
  progress: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 14l4-4 3 3 5-6"/></svg>',
  report: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M9 13h6M9 17h6"/></svg>',
  class: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.4"/><circle cx="17" cy="10" r="2.4"/><path d="M3 19c0-2.8 2.7-4.5 6-4.5s6 1.7 6 4.5"/><path d="M15.4 14.4c2.1.2 3.6 1.4 4.6 3.6"/></svg>',
  admin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
};

const App = {
  state: { token: "", role: null, user: null, hash: "learn" },
  chapters: [],       // {id, name, folder}
  activeChapter: null,
  activeQuiz: null,

  chapterName(id) {
    const c = this.chapters.find(x => x.id === id);
    return c ? c.name : (id || "全部资料");
  },
};

function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
function stateOf(m, attempts) {
  if (m == null) return { key: "na", label: "未评估", cls: "na" };
  if (m >= 80 && attempts >= 2) return { key: "master", label: "已掌握", cls: "master" };
  if (m >= 50) return { key: "prog", label: "进行中", cls: "prog" };
  return { key: "weak", label: "薄弱", cls: "weak" };
}
function toast(m) {
  let t = document.getElementById("toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; document.body.appendChild(t); }
  t.textContent = m; t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 1800);
}
/* 全局请求加载指示器：并发计数，首个请求显示、全部结束隐藏 */
let _loadingCount = 0, _loadingEl = null, _loadingText = "加载中…";
function loadingOn(text) {
  if (text) _loadingText = text;
  _loadingCount++;
  if (!_loadingEl) {
    _loadingEl = document.createElement("div");
    _loadingEl.className = "global-loading";
    _loadingEl.innerHTML = '<span class="spin"></span><span class="gl-txt"></span>';
    document.body.appendChild(_loadingEl);
  }
  _loadingEl.querySelector(".gl-txt").textContent = _loadingText;
  _loadingEl.classList.add("show");
}
function loadingOff() {
  if (_loadingCount > 0) _loadingCount--;
  if (_loadingCount <= 0) {
    _loadingCount = 0;
    if (_loadingEl) _loadingEl.classList.remove("show");
  }
}
function openSheet(html) {
  document.getElementById("sheet").innerHTML = html;
  document.getElementById("sheetMask").classList.add("show");
}
function closeSheet() { document.getElementById("sheetMask").classList.remove("show"); }
function avatar() {
  const role = App.state.role;
  const ch = (App.state.user && App.state.user.display_name || "?").charAt(0);
  return `<div class="avatar ${role === 'teacher' ? 'teacher' : ''}" onclick="openMenu()">${esc(ch)}</div>`;
}
function appbar(title, sub) {
  return `<div class="appbar"><div><h1>${esc(title)}</h1>${sub ? `<div class="sub">${esc(sub)}</div>` : ''}</div>${avatar()}</div>`;
}
function tabbar() {
  const h = App.state.hash;
  if (App.state.role === 'teacher') {
    const tabs = [["curriculum", "课程", ICONS.path], ["admin", "管理", ICONS.admin], ["quiz", "测评", ICONS.quiz], ["progress", "进度", ICONS.progress], ["class", "班级活动", ICONS.class]];
    return `<div class="tabbar">${tabs.map(([k, l, ic]) => `<button class="tab teacher ${h === k ? 'active' : ''}" onclick="go('${k}')">${ic}<span>${l}</span></button>`).join('')}</div>`;
  }
  const tabs = [["learn", "学习", ICONS.learn], ["path", "路径", ICONS.path], ["quiz", "测评", ICONS.quiz], ["progress", "进度", ICONS.progress], ["class", "班级", ICONS.class]];
  return `<div class="tabbar">${tabs.map(([k, l, ic]) => `<button class="tab ${h === k ? 'active' : ''}" onclick="go('${k}')">${ic}<span>${l}</span></button>`).join('')}</div>`;
}
function go(h) { App.state.hash = h; if (h === "quiz") App.activeQuiz = null; location.hash = h; render(); }

async function loadChapters() {
  try { const d = await API.get("/api/chapters"); App.chapters = d.chapters || []; } catch (e) { App.chapters = []; }
}

function viewLogin() {
  return `<div class="login">
    <div class="logo"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 4.6L19 9l-4 3.4.9 5.6L12 15.8 8.1 18l.9-5.6L5 9l5.1-1.4z"/></svg></div>
    <h2>AI 学习小组</h2><div class="tag">私有化 AI 辅助学习 · 仅限本组</div>
    <div class="field"><label>账号</label><input id="loginUser" autocomplete="username" placeholder="teacher / 学生账号"/></div>
    <div class="field"><label>密码</label><input id="loginPass" type="password" autocomplete="current-password" placeholder="••••••"/></div>
    <div class="err" id="loginErr"></div>
    <button class="btn" onclick="doLogin()">登 录</button>
  </div>`;
}
async function doLogin() {
  const username = document.getElementById("loginUser").value.trim();
  const password = document.getElementById("loginPass").value;
  const errEl = document.getElementById("loginErr");
  errEl.textContent = "";
  if (!username || !password) { errEl.textContent = "请输入账号与密码"; return; }
  try {
    const d = await API.post("/api/auth/login", { username, password });
    API.setToken(d.token);
    App.state.user = d;
    App.state.role = d.role;
    await boot();
  } catch (e) {
    errEl.textContent = e.message;
  }
}
function openMenu() {
  const role = App.state.role;
  const name = (App.state.user && App.state.user.display_name) || "用户";
  openSheet(`<div class="row" style="font-weight:700">${esc(name)}（${role === 'teacher' ? '教师' : '学生'}）</div>
    <div class="row" onclick="changePassword()">修改密码</div>
    <div class="row danger" onclick="logout()">退出登录</div>
    <div class="row cancel" onclick="closeSheet()">取消</div>`);
}
async function changePassword() {
  closeSheet();
  openSheet(`<div class="row" style="font-weight:700;cursor:default">修改密码</div>
    <div class="row" style="text-align:left;border:none;background:transparent;cursor:default">
      <input class="mini-input" id="oldPw" type="password" placeholder="旧密码"/>
      <input class="mini-input" id="newPw" type="password" placeholder="新密码（≥6位）"/>
    </div>
    <div class="row" onclick="submitChangePassword()">确认修改</div>
    <div class="row cancel" onclick="closeSheet()">取消</div>`);
}
async function submitChangePassword() {
  const old_password = document.getElementById("oldPw").value;
  const new_password = document.getElementById("newPw").value;
  try {
    await API.post("/api/auth/change-password", { old_password, new_password });
    closeSheet(); toast("密码已修改");
  } catch (e) { toast(e.message); }
}
function logout() {
  closeSheet();
  API.setToken("");
  App.state = { token: "", role: null, user: null, hash: "learn" };
  location.hash = "login";
  render();
}

/* 渲染入口：根据角色 + hash 分发到 Student / Teacher 视图 */
async function render() {
  const root = document.getElementById("screen");
  if (!App.state.role) {
    root.innerHTML = viewLogin();
    return;
  }
  try {
    let html = "";
    if (App.state.role === "student") {
      html = await Student.render();
    } else {
      html = await Teacher.render();
    }
    root.innerHTML = html;
    root.scrollTop = 0;
  } catch (e) {
    root.innerHTML = `<div class="note"><div class="big">⚠️</div>${esc(e.message)}<br><button class="btn ghost sm" style="margin-top:14px" onclick="render()">重试</button></div>`;
  }
}

async function boot() {
  if (!API.getToken()) { App.state.role = null; render(); return; }
  try {
    const me = await API.get("/api/auth/me");
    App.state.user = me;
    App.state.role = me.role;
    App.state.hash = (me.role === "teacher") ? "admin" : "learn";
  } catch (e) {
    API.setToken("");
    App.state.role = null;
  }
  await loadChapters();
  render();
}

window.addEventListener("hashchange", () => {
  if (App.state.role) { App.state.hash = location.hash.replace("#", "") || App.state.hash; render(); }
});

/* 键盘弹起时固定输入框不错位：--kb 补偿安卓键盘高度（iOS 下 offsetTop 随键盘上移，约 0） */
function syncVisualViewport() {
  if (!window.visualViewport) return;
  const vv = window.visualViewport;
  const kb = Math.max(0, window.innerHeight - (vv.height + vv.offsetTop));
  document.documentElement.style.setProperty("--kb", kb + "px");
}
if (window.visualViewport) {
  window.visualViewport.addEventListener("resize", syncVisualViewport);
  window.visualViewport.addEventListener("scroll", syncVisualViewport);
}

window.onload = boot;
