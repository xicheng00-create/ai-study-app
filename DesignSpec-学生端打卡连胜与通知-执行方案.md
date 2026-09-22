# DesignSpec · 学生端 Journey 优化 + 每日打卡连胜 + 通知系统 — 执行方案

- 需求来源：用户 2026-09-18 Telegram（学生端 journey / 打卡连胜 / 班级打卡 / 设置页 / 通知）
- 目标版本：**v2.4.0**（新功能，`x.y.0`）
- 关联基线：`Design-Spec-AI学习小组app.md` §3.11/§3.12/§3.13 + §12.25（本方案的 REQ 定义同步写入）
- 唯一事实来源：本文件 + Design-Spec；实现完成后**必须**回写 Design-Spec 对应 REQ-ID 状态
- 范围：**只做学生端**（教师端仅复用「设置页」与通知中心，不改教师端业务）

> 本文件是交给 Claude Code 的唯一上下文。动手前先读仓库 `CLAUDE.md`（§2 手术式修改 / §5 版本号诚实 / §6 防撞车 / §7 验证清单）。

---

## 0. 预备资源（Hermes 已就绪 —— **别重复造、别改**）

| 项 | 状态 | CC 要做的 |
|---|---|---|
| 萌图 4 张 | ✅ 已生成：`backend/frontend/img/notify/` 下 `flame-low.png`（快灭·灰蓝丧脸）/ `flame-ok.png`（一般·珊瑚）/ `flame-hot.png`（连胜 ≥7·暖黄笑脸+星星）/ `notify-badge.png`（128² 白色剪影，Android 角标） | **只引用路径**——不重新生成、不换图、不改尺寸 |
| VAPID 密钥 | ✅ 已写入 `.env`：`VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT`（`.env` 在 `.gitignore`） | 从 `os.environ` 读即可；**不要重新生成**，私钥**不得**出现在任何响应 / 日志 / 测试断言里 |
| `pywebpush` | ✅ 已装在 `.venv`（连带 `py-vapid` / `http-ece` / `cryptography`） | 只需在 `requirements.txt` 登记 `pywebpush>=2.0` |
| 19:00 LaunchAgent | ⏳ 只需写 `deploy/com.aistudy.checkin-reminder.plist`（模板照 `deploy/com.aistudy.daily-advice.plist`） | **不要** `launchctl load / bootstrap` —— 安装与加载由 Hermes 做 |

**线上拓扑（验证用，别猜）**：服务 = launchd `com.shuiyanhaha.aistudy`（用户域，**端口 5003**，由 `deploy/aistudy-run-port.sh` 拉起）；公网 = Cloudflare 命名隧道 `https://aistudygroup.shuiyanhaha.org` → `localhost:5003`。重启命令 = `launchctl kickstart -k gui/$(id -u)/com.shuiyanhaha.aistudy`。当前线上 version = `2.3.0`。

**🚫 受保护文档（不要动）**：仓库根目录的 `ChangeRequest-*.md`、`DesignSpec-*-执行方案.md`、`ui-design-*.html`、`课件/`（已 gitignore）都是**未跟踪**的设计/素材文档 —— 不要 `git add`、不要改、不要删；`git status` 里出现它们属**正常**。提交一律 `git add <明确路径>`，**绝不 `git add -A`**。

---

## 1. 需求原文 → REQ 映射

| 用户原话 | 需求 | REQ |
|---|---|---|
| 学生端用户 journey 需要优化 | 登录后首页即「今日任务」，不再让学生自己找入口 | CHECKIN-001 |
| 每日打卡连胜（类似多邻国） | 达标日 +1，空档日归零，历史最长记录 | CHECKIN-002/003 |
| 同学登陆后自动安排学习任务（复习10张卡+刷5题才算连胜） | 服务端判定 + 自动装配今日卡组/练习 | CHECKIN-004/005/006 |
| 连胜数字 + 火焰顶部显著显示 | 常驻顶部连胜条（学生端所有页） | CHECKIN-007 |
| 班级那里优先显示谁打卡谁没打、各自连胜、按钮提醒没连胜的同学 | 班级「今日打卡」区块 + 同学互提醒 | CHECKIN-008 / NOTIF-006 |
| 点右上角头像进入设置菜单（改密码/改名/改头像/打开提醒/退出） | 独立设置页 | SET-001~005 |
| 通知功能：老师发新路径 / 新测试 / 连胜提醒 / 每晚19:00未打卡系统提醒 | 站内通知中心 + Web Push 双通道 | NOTIF-001~008 |
| 俏皮个性化提醒 + 萌图 | 文案池按连胜状态取用 + 静态萌图资源 | NOTIF-005 |

---

## 2. 核心语义（**钉死，别猜**）

### 2.1 打卡与连胜定义（CHECKIN-002/003）
- **每日任务** = 「当日复习 distinct 知识卡片 ≥ **10** 张」**且**「当日完成 distinct 练习题 ≥ **5** 道」。
- 两项同时满足的**当天**即为「达标日」= 打卡成功，连胜 +1；单日只记一次。
- **连胜存活模型（Duolingo 式）**：
  - 今天已达标 → `streak = 连续达标天数`，状态 = `done`。
  - 今天未达标 **但昨天达标** → 连胜**仍存活**，`streak` 沿用昨日值，状态 = `pending`（前端显示「今天还没打卡，连胜 N 天待续」）。
  - 昨天也未达标（出现空档日）→ 连胜**归零**，状态 = `broken`，下次达标从 1 重新开始。
- `longest_streak` = 历史最长连续天数，永不下降。
- **明确不做**：补签卡、连胜冻结/复活、连胜保护道具（登记为 YAGNI，见 §9）。

### 2.2 计数口径（服务端唯一判定，CHECKIN-004）
- 「复习卡片数」= `knowledge_reviews` 中 `user_id=学生` 且 `date(last_review_at, UTC+8) == 今天` 的 **distinct `card_id`** 计数。
  - 同一张卡当天复习多次**只计 1 张**（防刷同一张）。
- 「练习题数」= `practice_questions` 中属于该生 `practice_sessions`、且 `answered_at` 落今天（UTC+8）、`user_answer` 非空的 **distinct id** 计数。
- 阈值常量集中在 `backend/config.py`：`TASK_CARDS_REQUIRED = 10`、`TASK_QUESTIONS_REQUIRED = 5`（本期不做前端可配置 UI）。
- **判定触发点**（全部服务端自动，前端不参与判定）：
  1. `POST /api/knowledge/<card_id>/review` 成功后
  2. `POST /api/practice/<session_id>/submit` 成功后
  两处均调 `checkin.evaluate_and_maybe_complete(con, user_id)`；`GET /api/checkin/today` 每次也做一次惰性评估（幂等），保证跨日自愈。
- **幂等**：`daily_checkins` 有 `UNIQUE(user_id, checkin_date)`；重复调用不写第二行、不重复发通知。
- **时区**：统一用 `backend/data/timeutil.py` 的 `shanghai_date()`（UTC+8）判定「今天」，与班级榜 `today_*` 口径一致。

### 2.3 「自动安排今日任务」（CHECKIN-005/006）
登录后学生**不需要自己挑章节**：
- **今日卡组** = 新端点 `GET /api/knowledge/today` 自动装配：到期复习卡（`knowledge_reviews.next_review_at ≤ 今天`）优先 → 未学过的卡（无 `knowledge_reviews` 行）按章节顺序补齐 → 凑到 10 张（跨章节）。返回该生今天的任务卡组（`card_id` 列表 + 卡内容 + 进度）。不足 10 张时返回全部可用卡并在响应里给 `short` 标记（前端提示「本章卡组已学完」）。
- **今日练习** = `POST /api/checkin/start-practice`：
  - 若今天已有未完成（有题未作答）的 `practice_sessions` → 直接返回该 session id（续答）。
  - 否则抽取「薄弱章节 ∪ 有到期卡的章节 ∪ 已发布章节」，内部复用 `practice.generate_practice` 逻辑生成 **5 道**（count=5，`total_points` 按实际各题之和），返回新 session id。
  - 前端「继续刷题」按钮 → 拿 id → 进现有 `viewPracticeTake`。
- 今日卡组进度存前端 `localStorage`（键 `aistudy_kc_today_<YYYY-MM-DD>`），复用现有 deck 的进度/续学机制，**不动**现有按章节目录的卡片浏览逻辑。

### 2.4 通知 = 站内通知中心 + Web Push 双通道（NOTIF-001/002）
- **所有通知都落库**（`notifications` 表）→ App 内「通知中心」可看历史、可标已读。
- **Web Push（VAPID）**：App 关闭也能收到。这是「19:00 未打卡提醒」唯一可行通道，必须做。
  - iOS 要求：iOS 16.4+ 且 PWA 已「添加到主屏幕」；权限请求**必须由用户手势触发** → 放在设置页「打开提醒」按钮。
  - Android / 桌面 Chrome：订阅即可收，支持通知内大图（`image`）。
  - **iOS 限制（如实说明）**：iOS 的 Web Push 通知**不支持大图附件**，「萌图」在 iOS 上体现为 ① 通知 `icon`（小图标）② 点开 App 后通知中心的萌图卡片。Android 支持 `image` 字段大图。
- 通知入口：`appbar` 右上角 **铃铛图标 + 未读红点**（学生端 + 教师端都加），点开 → 通知中心页（hash `notifications`）；设置页也有入口。

### 2.5 通知类型与触发点（NOTIF-003~007）

| type | 触发 | 收件人 | 标题 / 正文（示例） |
|---|---|---|---|
| `path_published` | `curriculum.publish_session` 成功 | 全体在用学生 | 「老师发布了新学习路径」/「第2周 第1节 · AI 产品地图」 |
| `quiz_published` | `quizzes.publish_quiz` 成功 | 全体在用学生 | 「老师发布了新测评」/「测评 · 第2周 第1节」 |
| `peer_nudge` | `POST /api/checkin/nudge` | 被提醒的同学 | 「{发送者} 戳了你一下」/「别断了 🔥{N} 天连胜，快来打卡！」 |
| `streak_reminder` | 每日 19:00 定时脚本 | 今日未达标 + 已开启提醒的学生 | 见 §2.6（个性化俏皮文案 + 萌图） |
| `streak_done` | 当日达标瞬间（首次） | 本人 | 「🔥 连胜 +1」/「已连续打卡 {N} 天」 |

- **幂等**：`notify_users()` 对 `(user_id, type, ref_id, 当天)` 去重，同一天不重复推同一事件。
- **unpublish / 取消发布不发通知**。
- 发布类通知**统一排除测试号**：沿用 `class_bp.EXCLUDED_USERNAMES` 口径（`hermestest` / `hermesstu`）。

### 2.6 19:00 系统提醒（NOTIF-005）
- 载体：用户域 LaunchAgent `com.aistudy.checkin-reminder`（每日 19:00），脚本 `backend/scripts/checkin_reminder.py`（plist 模板照 `deploy/com.aistudy.daily-advice.plist`）。
- 只发给：`role='student'` + `is_active=1` + 非测试号 + **今日未达标** + `notification_prefs.push_enabled=1 且 remind_1900=1`。
- **文案池（写死在 `backend/ai/reminder_copy.py`，确定性、不调 LLM）**，按「当前连胜数 + 今日缺口」挑：
  - 连胜 ≥3 且今日 0 进度：「🔥 {N} 天连胜要熄火了——今天还差 {a} 张卡片 + {b} 道题，10 分钟就能续上！」
  - 连胜 ≥1 且有部分进度：「{name}，火焰还亮着 🔥 差最后 {a} 张卡片 + {b} 道题就保住 {N} 天连胜了。」
  - 无连胜（broken）：「🔥 火焰还没点起来呢——今天翻 10 张卡、刷 5 道题，明天你就是有连胜的人。」
  - 每天每生最多 1 条（按 `(user, type, 日期)` 去重）。
- **萌图**：静态 PNG **已就绪**在 `backend/frontend/img/notify/`（CC 只引用路径）：`flame-low.png`（今日 0 进度 + 连胜 ≥3 快灭）/ `flame-ok.png`（一般）/ `flame-hot.png`（连胜 ≥7 或当日刚达标）/ `notify-badge.png`（Android 角标）。选图规则写在 `reminder_copy.py` 里（纯函数，按 `streak` + 缺口决定）；通知 payload 带 `icon`（公网 URL，指向所选萌图）+ `image`（Android 大图，同图）+ `badge`（`notify-badge.png`）；站内通知卡片显示同一张图（`/img/notify/xxx.png`）。公网前缀 `https://aistudygroup.shuiyanhaha.org`。

### 2.7 班级「今日打卡」区块（CHECKIN-008 / NOTIF-006）
- 位置：班级页（`Student.viewClass`）**置顶**（在现有三张排行榜卡之前）。
- 每生一行：头像 + 名字 + 「🔥 N 天」 + 今日进度 `x/10 卡 · y/5 题`（或 `✓ 已打卡`，整行绿色高亮；自己那行标 `me`）。
- 未打卡同学行尾按钮 **「提醒 TA」** → `POST /api/checkin/nudge {to_user_id}`。
  - 服务端限流：同一天同一发送者对同一接收者最多 1 次（超限返回 400「今天已经提醒过 TA 了」）。
  - 不能提醒自己（400）；只能学生提醒学生（教师端不出现该按钮）。
  - 发送成功后按钮置灰为「已提醒」。

### 2.8 设置页（SET-001~005，师生共用）
- 入口：`appbar` 右上角头像 → 打开 **独立设置页**（hash `settings`），**替换**现有 `openSheet` 简易菜单（现有 `changePassword()` 逻辑移到设置页内复用）。
- 内容与顺序：
  1. **个人资料**：头像（点击 → 预设头像选择器，12 个可选，选中即保存）+ 名称（「修改名称」→ 输入框，1–20 字，保存即生效）
  2. **修改密码**（复用现有 `POST /api/auth/change-password`）
  3. **打开提醒**（Web Push 开关）：开启 → 请求权限 + `pushManager.subscribe()` + 上报订阅；关闭 → 取消订阅 + 服务端删订阅
  4. **通知中心**（未读数）→ 跳 `notifications`
  5. **退出登录**（红字，现有 `logout()`）
- **头像实现**：`users` 加列 `avatar TEXT DEFAULT ''`，存预设头像 id（`a1`..`a12`），前端映射为 emoji/内置 SVG；空值回退为「名字首字」（保持现行为）。**本期不做自定义图片上传**（P1 待定，需 uploads + 裁剪链路）。

### 2.9 顶部连胜条（CHECKIN-007）
- 学生端**所有页面**常驻（放 app shell 层，`appbar` 之下、`content` 之上，`position:sticky`）。
- 左：🔥 大字图标 + 连胜天数大字（`N 天`）；右：今日进度胶囊 `3/10 卡 · 0/5 题` + 状态（`今天还没打卡` / `✓ 今日已完成`）。
- 点击 → 进「今日任务」页/首页（学习 hub）。
- 达标瞬间：条变色（金色/珊瑚渐变）+ toast「🔥 连胜 +1，已连续 5 天！」，纯 CSS 动画。
- 教师端**不显示**连胜条（只显示铃铛 + 头像）。

---

## 3. 数据模型（新增，全部走 `data/models.py`，禁止手写 ALTER）

```sql
-- 每日打卡（达标日快照，幂等）
CREATE TABLE IF NOT EXISTS daily_checkins (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  checkin_date TEXT NOT NULL,          -- 'YYYY-MM-DD'（UTC+8）
  cards_done INTEGER NOT NULL DEFAULT 0,
  questions_done INTEGER NOT NULL DEFAULT 0,
  streak_after INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  UNIQUE(user_id, checkin_date)
);
CREATE INDEX IF NOT EXISTS idx_checkins_user ON daily_checkins(user_id, checkin_date);

-- Web Push 订阅
CREATE TABLE IF NOT EXISTS push_subscriptions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  endpoint TEXT NOT NULL UNIQUE,
  p256dh TEXT NOT NULL,
  auth TEXT NOT NULL,
  user_agent TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  last_ok_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_push_user ON push_subscriptions(user_id);

-- 站内通知（所有通知都落库）
CREATE TABLE IF NOT EXISTS notifications (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL,                  -- path_published/quiz_published/peer_nudge/streak_reminder/streak_done
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  image TEXT DEFAULT '',               -- 萌图相对路径，可空
  ref_kind TEXT DEFAULT '',
  ref_id TEXT DEFAULT '',
  is_read INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(user_id, type, ref_id, created_at)   -- 精确去重由 notify_users() 逻辑兜底（见 §2.5）
);
CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, is_read);

-- 通知偏好
CREATE TABLE IF NOT EXISTS notification_prefs (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  push_enabled INTEGER NOT NULL DEFAULT 0,
  remind_1900 INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);
```
- `users` 加列 `avatar TEXT NOT NULL DEFAULT ''` → 走 `models.migrate(con)` 增量迁移（**注意**：`migrate()` 需要 `sqlite3.Row` factory；由 app 启动自动迁移，重启即加列）。

---

## 4. API 契约

### 4.1 新 blueprint `checkin_bp`（`/api/checkin`，全部 `@jwt_required`）
| 方法 | 路径 | 角色 | 返回 |
|---|---|---|---|
| GET | `/today` | student | `{task:{cards,questions}, progress:{cards,questions}, done, streak, longest, alive, state:'pending'\|'done'\|'broken', today}` |
| GET | `/class` | student | `{date, students:[{user_id,name,avatar,checked_in,cards,questions,streak,state,can_nudge}], me:{...}}` |
| POST | `/nudge` | student | body `{to_user_id}` → `{ok:true}`；400 超限/自提醒；403 非本班/不存在 |
| POST | `/start-practice` | student | → `{session_id, reused:bool, count}`（§2.3） |

### 4.2 新 blueprint `notify_bp`（`/api/notifications`）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `` (`?limit=30`) | 本人通知列表 + `unread` 计数 |
| GET | `/unread` | `{unread}`（铃铛轮询用，轻量、**不挂 LLM 限流**） |
| POST | `/read` | body `{ids:[...]}` 或 `{all:true}` |
| POST | `/push/subscribe` | body `{endpoint,p256dh,auth}` → 存订阅 + `push_enabled=1` |
| POST | `/push/unsubscribe` | body `{endpoint}` → 删订阅 + `push_enabled=0` |
| GET | `/prefs` / POST `/prefs` | `{push_enabled, remind_1900}` |
| GET | `/vapid-public-key` | `{key}`（公钥，前端订阅用） |

### 4.3 扩展 `knowledge_bp`
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/today` | 今日任务卡组（到期优先 + 补新卡，distinct，跨章，上限 10）→ `{cards:[{id,chapter_id,chapter_name,front,back,sub_concept,status,overdue}], required, short}` |

### 4.4 扩展 `auth_bp`
| 方法 | 路径 | 说明 |
|---|---|---|
| PATCH | `/me` | body `{display_name?, avatar?}`；`display_name` 1–20 字、`avatar` 必须在预设白名单 `a1..a12` 或空串；返回更新后档案 |

> 已有 `POST /api/auth/change-password` **直接复用，不要重写**。

---

## 5. 前端改动清单（文件级）

- `backend/frontend/sw.js`
  - CACHE bump（v42 → v43）；新增 `push` 事件（`self.registration.showNotification(title, {body, icon, image, badge, data:{url}})` + 落桩）+ `notificationclick`（`clients.openWindow(data.url || '/')`，focus 已开窗口）。
- `backend/frontend/js/app.js`
  - `streakBar()`（常驻连胜条，学生端所有视图插入；数据来自 `App.checkin`）
  - `avatar()` 支持 `user.avatar` 预设头像（空值回退首字）
  - `appbar()` 右侧加铃铛 + 未读红点（`App.unread`）
  - `openMenu()` → `openSettings()`；新增 `viewSettings()`、`viewAvatarPicker()`、`viewNotifications()`
  - 通知中心：列表、未读标记、点开标记已读、跳转对应页（path_published → `path`；quiz_published → `quiz`；streak_* → 学习 hub）
  - 铃铛未读数在 `boot()` 后拉一次 + 每次 `render()` 学生端轻量刷新（不要打 LLM 限流：`/unread` 端点不加 `@rate_limit`）
- `backend/frontend/js/student.js`
  - `viewLearnHome()`：置顶「今日任务」卡（两行进度条：卡片 `x/10`、练习 `y/5`，各自「继续」按钮；达标后显示「✓ 今日已完成 · 连胜 N 天」），保留原有「对话」「知识卡片」入口
  - 新增今日卡组 deck（复用现有翻卡/滑动/复习提交逻辑，只是数据源换成 `GET /api/knowledge/today`，进度 key = `aistudy_kc_today_<date>`）
  - 「继续刷题」→ `POST /api/checkin/start-practice` → 进 `viewPracticeTake`
  - 卡片 review / 练习 submit 成功后 → 刷新 `GET /api/checkin/today` → 更新顶部条；`done` 由 false→true 时播放庆祝动画 + toast
  - `viewClass()` 顶部新增「今日打卡」区块（§2.7），保留现有排行榜卡与弹出层
- `backend/frontend/js/teacher.js`
  - 仅复用：铃铛 + 通知中心 + 设置页（`appbar` 已是共享件，若 teacher 端 appbar 走不同分支需同步）
- `backend/frontend/css/style.css`
  - 新增：`.streak-bar` `.streak-flame` `.streak-num` `.task-card` `.task-row` `.task-bar` `.task-bar-fill` `.checkin-list` `.checkin-row` `.checkin-row.me` `.checkin-done` `.nudge-btn` `.bell` `.bell-dot` `.settings-group` `.settings-row` `.avatar-grid` `.avatar-cell.sel` `.notif-item` `.notif-item.unread` `.notif-img` + 达标庆祝 keyframes
  - 复用现有 design token（`--coral` / `--coral-soft` / `--surface` / `--border` / `--radius`），**不引新色**；不引入任何新依赖/字体/图标库（复用 `app.js` 的 `ICO` + `ic()`）
  - ⚠️ 守卫：`.streak-bar` 若放 `sticky`，必须与 `.appbar` 同一不透明容器或对齐 `top`，避免历史坑「顶部缝隙漏内容」（见 runbook）

---

## 6. 后端改动清单（文件级）

| 文件 | 改动 |
|---|---|
| `backend/data/models.py` | 4 张新表 + `users.avatar` 迁移 |
| `backend/data/checkin.py`（新） | `today_str()`、`counts_today(con,uid)`、`evaluate_and_maybe_complete(con,uid)`、`streak_info(con,uid)`、`class_today(con, me_uid)`、`build_today_deck(con,uid,limit)` |
| `backend/api/checkin.py`（新） | `checkin_bp`（§4.1） |
| `backend/api/notifications.py`（新） | `notify_bp`（§4.2） |
| `backend/services/push.py`（新） | `send_push(con, user_ids, payload)`：pywebpush 封装；无 VAPID/无订阅/发送失败 → **降级为只落站内**（绝不 500）；收到 404/410 → 删该订阅 |
| `backend/services/notify.py`（新） | `notify_users(con, user_ids, type, title, body, image, ref_kind, ref_id)`：先落库（幂等）→ 再 `send_push` |
| `backend/ai/reminder_copy.py`（新） | 19:00 文案池 + 萌图选择（纯函数，确定性，不调 LLM） |
| `backend/scripts/checkin_reminder.py`（新） | 19:00 入口：直连库 → 找符合条件学生 → `notify_users` 发 `streak_reminder` → 打日志到 `logs/checkin-reminder.log` |
| `deploy/com.aistudy.checkin-reminder.plist`（新） | 用户域 LaunchAgent，19:00；模板照 `deploy/com.aistudy.daily-advice.plist` |
| `backend/api/knowledge.py` | `review()` 成功后调 `checkin.evaluate_and_maybe_complete`；新增 `GET /today` |
| `backend/api/practice.py` | `submit_practice()` 成功后调 `checkin.evaluate_and_maybe_complete`（不改生成逻辑本身） |
| `backend/api/curriculum.py` | `publish_session()` 成功后 `notify_users(... 'path_published')` |
| `backend/api/quizzes.py` | `publish_quiz()` 成功后 `notify_users(... 'quiz_published')` |
| `backend/config.py` | 阈值常量 + `VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY/VAPID_SUBJECT` 读取（`os.environ.get`） |
| `backend/app.py` | 注册两个新 blueprint；`version="2.4.0"` |
| `requirements.txt` | 登记 `pywebpush>=2.0`（**已装好在 `.venv`，无需再 pip install**） |
| `.env`（**不 commit**） | **已由 Hermes 写入** `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT`；CC 只读取，**不生成、不修改** |
| `CHANGELOG.md` | 2.4.0 条目（Added/Changed） |
| `Design-Spec-AI学习小组app.md` | §12.25 由「需求登记（待实现）」改写为「实现状态回写（v2.4.0）」；§3.11/3.12/3.13 各 REQ 标注 ✅/⚠️（定义已在仓库中，勿重写） |
| 静态资源 | ✅ **已就绪**（Hermes 提供）：`backend/frontend/img/notify/{flame-low,flame-ok,flame-hot,notify-badge}.png` —— CC 只引用路径 |

**不动的边界**：线上 launchd `com.shuiyanhaha.aistudy`（5003）、命名隧道、`deploy/aistudy-run-port.sh`、受保护未跟踪文档、教师端业务逻辑、现有「按章节浏览卡片 / 自主练习 / 测评」逻辑。

---

## 7. 限流 / 安全
- **打卡判定只在服务端**：前端无权上报「我打卡了」。
- `@rate_limit` 是**按 (user, endpoint) 分桶**（v1.19.0 已修）；新增端点中**只有会调 LLM 的**（`/api/checkin/start-practice`、`/api/knowledge/today` 的生成）才挂限流；`/api/checkin/today`、`/class`、`/api/notifications/*`、`/unread` **不挂**（高频轻量，避免饿死 LLM 额度）。
- `notifications` / `push_subscriptions` 全部按 `g.user_id` 作用域，越权读返回空/403。
- VAPID 私钥只存 `.env`，**不出现在任何 API 响应、不进 git、不写日志**。
- 通知正文中 `display_name` 等用户可控字段必须转义；`nudge` 的发送者名字由服务端取，不接受前端传入。
- nudge 限流：同日同对上限 1 次。
- 19:00 脚本本机直连库，不经 HTTP，无公网入口。

---

## 8. 验收 DoD

**自动化**
- [ ] `python -m py_compile` 通过；`make lint test smoke` 全绿
- [ ] `node --check backend/frontend/js/{app,student,teacher}.js backend/frontend/sw.js`（**必做**，`make` 不查前端 JS）
- [ ] `tests/test_checkin.py`：9 张卡不算 / 10 张算；4 题不算 / 5 题算；同卡重复复习只计 1；跨 UTC+8 日界；连胜 2 天连续；断连归零；今日未打卡但连胜存活（`state=pending`）；幂等（重复调用只 1 行 `daily_checkins`、只 1 条通知）
- [ ] `tests/test_notify.py`：通知落库 + 未读计数 + 已读；nudge 同日同对限流 400；`publish_session`/`publish_quiz` 后全体学生各 1 条通知；**push 发送抛错仍落库并返回 200**（降级）
- [ ] E2E（**临时库，绝不动生产库**）：造学生 → `POST /api/knowledge/<id>/review` ×10 + 提交 5 题 → `GET /api/checkin/today` `done=true`、`streak=1`；`GET /api/checkin/class` 该生 `checked_in=true`
- [ ] `PATCH /api/auth/me` 改名/换头像生效且非法值 400

**真机（Web Push —— 需 Ray 配合点授权，交付时如实说明，不要假装已验）**
- [ ] iPhone 主屏 PWA → 设置页「打开提醒」授权成功；`push_subscriptions` 落库
- [ ] 老师发布路径 / 发布测评 → 学生手机收到 push（或至少站内通知 + 未读角标）
- [ ] 19:00 脚本手动跑通（**Hermes 装好 LaunchAgent 后** `launchctl kickstart -k gui/$(id -u)/com.aistudy.checkin-reminder`）→ 日志写入 + 未打卡学生收到站内通知/推送

**交付一致性**
- [ ] `app.py version == 2.4.0 == CHANGELOG` 最新条目；sw.js CACHE 已 bump（v42 → v43）
- [ ] Design-Spec §12.25 与 §3.11/3.12/3.13 的 REQ 状态已回写
- [ ] Conventional Commits；**绝不 `git add -A`**（受保护文档保持未跟踪）
- [ ] **CC 不要 push、不要重启线上服务** —— 交付 = 代码 + commit；push / 重启 5003 / 线上验证 / 装 reminder LaunchAgent 由 Hermes 执行
- [ ] 交付消息里明确写：改了哪些文件、`make lint test smoke` 结果、哪些 REQ 完成、哪些没做（诚实清单）

---

## 9. 明确不做（YAGNI，登记）
- 补签卡 / 连胜冻结 / 连胜复活 / 连胜保护道具
- 自定义头像上传（P1 待定，需 uploads + 裁剪链路）
- 打卡阈值的前端可配置 UI（常量在后端；教师端后续可加）
- 邮件 / 短信 / 微信通知
- 教师端打卡统计报表（本期只做学生端班级打卡区块）
- 排行榜形态调整（已有 3 主卡 + 弹出层，不动）

---

## 10. REQ 定义（同步写入 Design-Spec）

**域前缀**：`CHECKIN`（每日打卡与连胜）、`NOTIF`（通知与提醒）、`SET`（个人设置）

| REQ | 角色 | 优先级 | 说明 |
|---|---|---|---|
| CHECKIN-001 | student | P0 | 登录后首页即「今日任务」，无需学生自己找入口 |
| CHECKIN-002 | student | P0 | 每日任务阈值：复习 ≥10 distinct 卡片 且 完成 ≥5 distinct 练习题 |
| CHECKIN-003 | student | P0 | 连胜模型：达标 +1 / 空档归零 / 今日未打但昨日达标 = 存活（pending）/ longest 永久记录 |
| CHECKIN-004 | system | P0 | 打卡判定只在服务端，幂等（UNIQUE(user_id,checkin_date)） |
| CHECKIN-005 | student | P0 | 今日卡组自动装配（到期优先 + 补新卡，跨章，上限 10） |
| CHECKIN-006 | student | P0 | 今日练习自动装配（复用/生成 5 道，续答优先） |
| CHECKIN-007 | student | P0 | 顶部常驻连胜条（🔥 + 天数 + 今日进度 + 状态） |
| CHECKIN-008 | student | P0 | 班级「今日打卡」区块：谁打卡谁没打 + 各自连胜 + 提醒 TA |
| NOTIF-001 | 全部 | P0 | 站内通知中心（列表/未读/已读/跳转） |
| NOTIF-002 | 全部 | P0 | Web Push（VAPID）订阅与推送；无订阅/发送失败降级只落站内 |
| NOTIF-003 | student | P0 | 老师发布新路径 → 全体学生通知 |
| NOTIF-004 | student | P0 | 老师发布新测评 → 全体学生通知 |
| NOTIF-005 | student | P0 | 每日 19:00 未打卡系统提醒（个性化俏皮文案 + 萌图，幂等每日 1 条） |
| NOTIF-006 | student | P0 | 同学互提醒（nudge），同日同对限流 1 次 |
| NOTIF-007 | student | P1 | 打卡成功（streak_done）即时通知 |
| NOTIF-008 | 全部 | P0 | 铃铛 + 未读角标；`/unread` 不挂 LLM 限流 |
| SET-001 | 全部 | P0 | 头像进独立设置页（取代旧 openSheet 简易菜单） |
| SET-002 | 全部 | P0 | 修改名称（display_name，1–20 字） |
| SET-003 | 全部 | P0 | 修改头像（12 个预设头像，白名单校验） |
| SET-004 | 全部 | P0 | 修改密码（复用现有端点） |
| SET-005 | 全部 | P0 | 打开提醒（Web Push 授权/订阅开关）+ 退出登录 |
