# aistudy 五屏组件级视觉对齐报告（v2.13.1）

## 逐屏改动表

| 屏 | 组件 | 改前值 | 改后值 |
|---|---|---|---|
| 学习 `#learn` | 入口卡 | 旧阴影/通用尺寸；图标 44px | `#FFFDF8` + 1px `#E5DECC`，16px；图标 36px/11px |
| 学习 `#learn` | 今日任务 | 标题 13px；进度条 7px | 标题 15/700；深橙计数 14px；进度条 4px 橙 |
| 学习 `#learn` | 资料库行 | 勾选框 22px 圆形 | 19px/6px 方角，hairline 分隔，文字 13.5px |
| 路径/闪卡 `#knowledge` | 浏览卡片 | 继承卡片样式 | 自带 1px hairline、16px 圆角、纸底 |
| 路径/闪卡 `#knowledge` | 闪卡 | 正反面 20px 圆角 | 正反面 1px hairline、16px 圆角、轻阴影；保留翻面/滑动 |
| 路径/闪卡 `#knowledge` | 复习操作 | 通用按钮旧高度 | 48px/15px/700/14px 圆角 |
| 测评 `#quiz` | 题目卡图标 | 42px/12px | 34px/10px |
| 测评 `#quiz` | 题目卡文字 | 14.5px/700，副文 12px | 15px/800，副文 12.5px |
| 进度 `#progress` | hero/三格/章节 | 46px 橙；无竖线/底线；bar 5px | 44px 墨色；三格竖线+底线；bar 4px |
| 班级 `#class` | 打卡行 | 11px padding；达标特殊背景 | 15px padding；14px 行块；达标淡绿 8px chip |
| 班级 `#class` | 提醒按钮 | 药丸/无统一次按钮 | 33px、13/800、hairline、8px；已提醒置灰 |

全局壳：底色 `#FAF6ED`、卡片 `#FFFDF8`、hairline `#E5DECC`、appbar 19/800、tabbar 62px。

## 机械断言

`make ui-audit` 已覆盖五屏与 390/1280 两档，最终结果：`UI 机械断言全绿`。
失败信息均包含屏、组件、期望值与实际值格式。

## 反证记录

本轮断言均使用统一失败出口，失败退出码为 2；以下为可复现反证项：

- 将 `.qcard .ic` 的 `34px` 改回 `42px`：`#quiz · 题目图标 · 期望 34px`，审计 FAIL。
- 将 `.home-ic` 的 `36px` 改回 `44px`：`#learn · 入口卡` 目标断言 FAIL。
- 将 `.kc-card` 的 `1px` 边框删除：`#knowledge · 闪卡 · 期望自边框 1px`，审计 FAIL。
- 将 `.nudge-btn` 的高度改回药丸旧值：`#class · 提醒按钮 · 期望 32-34px`，审计 FAIL。
- 将 `.dcard .hero .v` 的字号改回 `46px`：进度 hero 目标断言 FAIL。

## 文案零删减

五屏前后文案集合差集：`消失 = 0`，`新增用户可见文案 = 0`。进度页 2.12.2 已批准的章节重复文案删除例外保持不变。
