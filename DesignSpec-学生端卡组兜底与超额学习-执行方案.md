# 执行方案：学生端卡组兜底与超额学习（CR-2026-0919-DECK → CHECKIN-009~012）

> **本文档是交 Claude Code 的唯一上下文。** 请先读本文件，再读 `CLAUDE.md`、`Design-Spec-AI学习小组app.md` §3.11 与 §12.27。
> 目标版本 **v2.5.0**。仓库根目录：`/Users/xicheng/WorkBuddy/AI学习小组app`。

---

## 1. 背景：用户实报的缺陷（已实测复现，附证据）

**用户原话（Ray，2026-09-19 真机）**：
> 「AI 学习小组 / 复习卡片会遇到**今日没有可复习的卡片**，结果卡在那里，应该把**掌握度低的卡片随机抽出来**，而且发配的任务应该要**优先匹配未学习的卡片**，而且学生若是想多学也可以。」

**Hermes 只读诊断结果（真实库，2026-09-19）**：

| 学生 | reviews 状态分布 | `build_today_deck` 结果 |
|---|---|---|
| `hermesstu` | `mastered`:43 + `reviewing`:21（`next_review_at=2026-09-21` 未到期） | **0 张**，`short=True` ← **卡死复现** |
| `Qingran` | `learning`:4 + `new`:60（`learn_count` **全 0**） | 10 张（4 learning + 6 new） |
| `Winnie` | `new`:64（`learn_count` **全 0**） | 10 张（10 new） |
| `Han` | 无 reviews 行 | 10 张（10 new） |

库况：`knowledge_cards` 共 **64** 张，全部属于 **2 个 `published`** 章节。

### 缺陷 A：卡组会返回 0 张 → 学生彻底卡死
`build_today_deck` 只有两档（到期复习、无 review 行的新卡）。当学生把卡学到 `mastered`（永不到期）或 `next_review_at` 未到时，**两档皆空** → 返回 `cards: []`、`short=True`。
前端 `backend/frontend/js/student.js:147`：

```js
if (!cards.length) { toast('今天没有可复习的卡片'); return; }   // ← 死路：只弹一句，无出路
```

学生凑不到 10 张 → 当日无法达标 → **连胜断掉，且永远无解**。

### 缺陷 B：「未学习」口径错了 → 任务永远发旧卡，课程推不动
`GET /api/knowledge/<chapter_id>`（`backend/api/knowledge.py::cards`）在返回章节卡片前，会对该章**每一张卡**调用 `_review()`，**全量懒建** `knowledge_reviews` 行：

```python
row = con.execute("SELECT * FROM knowledge_reviews WHERE card_id=? AND user_id=?", ...)
if row is None:
    now = models.utcnow()
    con.execute("INSERT INTO knowledge_reviews (id,card_id,user_id,next_review_at,created_at) VALUES (?,?,?,?,?)",
                (models.new_id(), card_id, g.user_id, now, now))
```

→ 学生**只要点开一次某章的「知识卡片」浏览**，该章所有卡就有了 review 行（`status='new'`、`learn_count=0`、`next_review_at=now`）。后果双杀：
1. `new` 档的判据是 `NOT EXISTS (SELECT 1 FROM knowledge_reviews ...)` → 这些卡**从此不再算「新卡」**，永远推不进任务；
2. 它们 `next_review_at = now ≤ today` 又被算作**「到期复习」** → 任务发出去的全是**学生从没真正翻过的卡**，却以「复习」名义下发。

**正确口径：「未学习」= `learn_count = 0`（从未真正翻过卡）**，与「有没有 review 行」无关。

---

## 2. 本次要做（REQ 定义见 Design-Spec §3.11；动手前请核对该节）

### 2.1 `backend/data/checkin.py::build_today_deck` —— 三档装配，永不返回空

**新签名**（保持向后兼容，`limit` 仍可省）：

```python
def build_today_deck(con, user_id, limit=None, mode="task", rng=None) -> dict:
```

**装配优先级（去重后截到 `limit`，`limit` 缺省 `TASK_CARDS_REQUIRED`）**：

| 档 | 来源 | 排序 |
|---|---|---|
| ① 未学习 | `learn_count = 0`（**含无 review 行**的卡） | `kc.chapter_id, kc.rowid` 升序（保证按课程顺序推进） |
| ② 到期复习 | `status != 'mastered'` 且 `date(next_review_at, UTC+8) <= today` 且 `learn_count > 0` | `next_review_at` 升序 |
| ③ 低掌握度随机补足 | 已发布章节的全部卡 | 见下 |

- 三档都只取 `kc.chapter_id IN (SELECT id FROM chapters WHERE status='published')` 的卡。
- 档① 与档② 用同一个去重集合（`seen` by `kc.id`），档① 优先。
- **档③（本 REQ 核心，CHECKIN-010）**：避免卡死，同时满足用户要的「掌握度低」+「随机」：
  1. 候选 = 已发布章节全部卡（排除已入选的），按 **`(status 档位权重 ASC, learn_count ASC, interval_days ASC)`** 升序排序；
     权重表：`{"new": 0, "learning": 1, "reviewing": 2, "mastered": 3}`（越小越不熟）。
     无 review 行的卡视为 `status='new'`、`learn_count=0`、`interval_days=0`（最不熟，排最前）。
  2. 取**最差的前 `POOL = max(3 * limit, 20)` 张**作为候选池。
  3. 池内 `rng.shuffle()` 后按顺序补足剩余空位。
- **`rng` 参数**：缺省 `None` → 函数内 `rng = random.Random()`。**测试注入固定 seed**（如 `random.Random(42)`）以保证结果确定。
- **`mode` 参数**：
  - `"task"`（缺省）：上述三档。
  - `"extra"`（CHECKIN-011）：先排除**今日已复习过的卡**（`date(last_review_at, UTC+8) == today`）再跑三档；额外组**不承诺**凑满 `limit`。
  - 其它值：**不报错**，按 `"task"` 处理（防御性）。
- **返回结构（在现有 `cards` / `required` / `short` 基础上扩展）**：
  - 每张卡**新增 `learn_count`**（int；无 review 行时为 `0`）——前端用它显示「新卡」角标（可选）。
  - **新增 `empty_reason`**：`cards` 为空时才非空串；真真空（库中无已发布章节的卡）→ `"no_published_cards"`；否则 `""`。
  - `mode="extra"` 时**新增 `extra: True`**。
  - `short` 语义保持：`len(cards) < limit`。`mode="extra"` 时 `short` 恒为 `False`（额外组不承诺）。

> ⚠️ **`cards` 非空保证**：只要存在「已发布章节的卡」，第③档一定补得出东西 → `cards` 长度 **> 0**。这是「永不死路」的硬约束，务必写成单测。

### 2.2 `backend/api/knowledge.py::today_deck` —— 接受 `?mode=`

```python
@knowledge_bp.route("/today", methods=["GET"])
def today_deck():
    """今日任务卡组（CHECKIN-005/009/010/011）"""
    mode = (request.args.get("mode") or "task").strip()
    if mode not in ("task", "extra"):
        mode = "task"          # 白名单回落，不返回 4xx
    deck = checkin.build_today_deck(con, g.user_id, mode=mode)
    return ok(deck)
```

`GET /api/checkin/today` 里 `checkin.build_today_deck(con, g.user_id)` 的调用**保持 `mode="task"` 缺省**，`task.cards` 口径不变。

### 2.3 `backend/frontend/js/student.js` —— 「再学一组」+ 空卡组可点出路

四处改动（手术式，别顺手重构）：

**(a) `taskCardHtml()`（约 line 132-140）**：`task()` 工厂目前对已完成的项硬编码 `disabled`。要为「复习卡片」这一行**单独**开放「再学一组」：
- 达标后该行按钮文案由「已完成」改为 **「再学一组」**，**可点**，`onclick="Student.startExtraDeck()"`；进度显示仍为 `10/10`（不改成 20）。
- 「刷练习题」行保持原样（`continuePractice()` 生成新 session 已天然支持多刷，本次不动）。
- 最小做法：给 `task()` 加一个可选参数（如 `afterDone`）承载「完成后按钮」的 label/onclick/是否 disabled，只对卡片行传「再学一组」。

**(b) `startTodayDeck()`（约 line 143-161）**：把死路改成有出路的交互：
```js
if (!cards.length) {
  if (d.empty_reason === 'no_published_cards') {
    openSheet(`<div class="row" style="font-weight:700">还没有可学的卡片</div>
      <div class="row" style="text-align:left;border:none;background:transparent;cursor:default;font-size:13px;color:var(--text-2)">去「资料库」勾选章节 → 点「知识卡片」生成后即可开始今日复习。</div>
      <div class="row" onclick="closeSheet();Student.enterKnowledge()">去资料库</div>
      <div class="row cancel" onclick="closeSheet()">取消</div>`);
  } else {
    toast('暂时没有可复习的卡片，稍后再试');
  }
  return;
}
```
> 注意：`enterKnowledge()` 内会 `await render()`，配合 `closeSheet()` 使用（参考同文件既有写法）。

**(c) 新增 `startExtraDeck()`**：与 `startTodayDeck()` 同构，但请求 `API.get('/api/knowledge/today?mode=extra')`：
- `this.todayDeck = true` 复用同一翻卡视图与断点续学；额外组**不**走「继续今日复习？」的续学弹层判定（避免与任务组进度 key 混淆），直接从第 0 张开始；
- 额外组进度 key 与任务组区分，避免互相覆盖（`_kcSave/_kcLoad` 已按 `todayDeck` 分支，请检查 `_kcTodayKey()` 是否需加后缀，例如按模式区分；**不要破坏任务组的续学**）。
- 空卡组时：`toast('今天的卡片都学完啦，明天再来 🔥')`（额外组没有卡不是错误，说明真的全复习过了）。

**(d) 翻卡视图收尾**：`viewKnowledgeDeck()`（约 line 418-424）在卡组走完时已 `_kcClear()` + 回 `learn` 首页，**保持不动**，只确认额外组走这条路也对。

### 2.4 测试

`tests/test_checkin.py` 按 Design-Spec §3.11「测验锚点」补用例（**固定 seed**，不依赖真实 LLM）：
1. **三档优先级**：造 3 张未学 + 3 张到期 + 若干已学，断言 `limit=5` 时顺序为「未学 3 → 到期 2」。
2. **未学习口径**：卡有 review 行但 `learn_count=0` → **仍算未学习**（档①，排最前）；`learn_count>0` 且 `next_review_at` 未到 → 不进档②。
3. **全 mastered / 未到期时仍发满 10 张**：造 12 张 `mastered`（`learn_count>0`、`next_review_at` 未来）→ `cards` 长度 **== 10**，`empty_reason == ""`，`short == False`（**这条就是用户报的 bug 的回归测试**）。
4. **同 seed 结果一致**：同 `rng=random.Random(42)` 两次调用返回同一 `id` 序列。
5. **低掌握度优先**：档③ 里 `status='learning'` 的卡必须先于 `mastered` 出现。
6. **`mode="extra"` 排除今日已复习**：把若干卡 `last_review_at` 设为今天 → 不出现在 extra 卡组。
7. **真真空**：库中无已发布章节的卡 → `cards == []` 且 `empty_reason == "no_published_cards"`。
8. **既有用例不回归**：现有 9 张不算 / 10 张算、同卡去重、跨日界、连胜模型等全部仍绿。

---

## 3. 边界（**不要动**）

- ❌ 不改 `GET /api/knowledge/<chapter_id>` 的懒建行行为（存在 review 行是 KNOW 域的既有设计，本次只在**判定口径**上绕过它）。
- ❌ 不改打卡判定（`counts_today` / `evaluate_and_maybe_complete`）与阈值常量。
- ❌ 不改班级页、通知中心、19:00 提醒脚本、`sw.js` 缓存策略。
- ❌ 不动教师端任何逻辑。
- ❌ 不新增依赖、不改 `requirements.txt`。
- ❌ 不做：补签卡 / 连胜道具 / 让学生自定义卡组配比。

## 4. 交付规范（违反即返工）

1. **手术式修改**：只写解决问题所需的最少代码，不重构无关代码。
2. **先读规格再编码**：`CLAUDE.md` §4 要求任何交付必须**同步回写 Design-Spec**。本次请把 `Design-Spec-AI学习小组app.md` 的 **§12.27「需求登记（待实现）」整节改写为「实现状态回写（v2.5.0）」**，并逐条标 ✅/⚠️（格式对齐 §12.25）；§3.11 里 CHECKIN-009~012 的「**待实现**」标注去掉、状态改 ✅。
3. **版本号诚实规则**：本次会产生 `CHANGELOG.md` 条目 → 必须**同 commit** 把 `backend/app.py` 的 `version = "2.4.1"` bump 到 **`"2.5.0"`**，与 CHANGELOG 完全一致。`sw.js` 的 `CACHE` 由 `aistudy-shell-v43` bump 到 **`v44`**（有前端 JS 改动）。
4. **每阶段可运行可验收**：
   - 后端：`python -m py_compile <改动文件>`
   - 前端：`node --check backend/frontend/js/student.js`（**`make` 不查前端 JS，必须自己跑**）
   - 闸门：`make lint test smoke` 必须 exit=0；前端 `node --check` 通过。
5. **中文注释，只注关键逻辑；PEP8；单文件 < 300 行；函数单一职责。**（注意 `checkin.py` 现 206 行，加完三档逻辑仍在 300 行内。）
6. **测试确定性红线**：跑 pytest **不得真打外部 LLM**（`tests/conftest.py` 已全局屏蔽 key，别绕过）。
7. **API 风格**：成功 `{code:0,data:...}`；错误 `{code:E,msg:...}`（本次 `mode` 非法值**回落**而非报错，见 §2.2）。
8. **时间一律 UTC 存储**，「今天」判定用 `data/timeutil.shanghai_date()`（UTC+8），与既有口径一致。
9. **Conventional Commits**，改完**立即 commit**（一个 commit 完成全部改动）。
10. **🚫 不要 `git push`**、**🚫 不要重启线上服务**（push / 重启 5003 / 线上验证全由 Hermes 做）。
11. **🚫 绝不 `git add -A`**：仓库根目录有 7 个受保护未跟踪文件（`ChangeRequest-*.md`、`DesignSpec-*-执行方案.md`、`ui-design-*.html`、`deploy/aistudy-run-port.sh`、`小白AI课程8周学习路径.md`），逐个 `git add <明确路径>`。
12. 开工前先 `git status` 确认干净；改完 `git log --oneline -1` 汇报 commit sha。

## 5. 交付时请回报

- commit sha + `git show <sha> --name-only --format=""` 的全量改动文件清单
- `make lint test smoke` 的 exit code 与测试通过数
- `node --check` 结果
- 新增测试用例名清单（对应 §2.4 的 1~8 条）
- Design-Spec §12.27 与 §3.11 的回写是否已完成
- 任何你**没做**或**不确定**的事（诚实清单，别美化）
