[English](README.md) | **简体中文**

# script-or-think（脚本还是思考）

一个智能体技能，为多步骤任务的每一步回答同一个问题：
**这一步该交给代码、模型、子智能体，还是人？**

任务开始前，每一步诚实回答六个问题（输入是否确定？是否只有一个正确答案？机器如何校验？出错代价多大？是否影响外部世界？调用路径是否已知？）。五条有序规则把答案转换成通道——`SCRIPT`、`THINK`、`SCOUT` 或 `HUMAN`——并生成一份计划文件：每步都有校验，每个子智能体都有预算，每个高代价对外操作前都站着一个人。跑过几轮后，执行记录驱动一个棘轮，提出单档调整：稳定的缓存起来，恒定的冻结成常量，子智能体反复走的同一条路径写成脚本，总出错的脚本前面加一个整理步骤。

## 为什么需要

智能体倾向于把一切交给模型，因为模型本来就在运行。结果是：token 花在排序和算数上，邮件和付款由自由生成来“决定并发送”，步骤“看起来完成了”却没有任何校验，定期任务永远不会变便宜。相反的失败也存在——僵硬的脚本因为没人先让模型整理输入而反复失败。本技能让这种划分变得有意识、有记录，并能依据证据调整。

## 功能

- **步骤卡**——每步六个字段：`inputs`、`answer`、`check`、`wrong_cost`、`effect`、`path`。
- **五条分流规则（R1–R5）**——对外影响永远由代码执行；输入杂乱但答案唯一的步骤拆成“模型整理 -> 代码计算”；调用路径未知的变成有边界的 `SCOUT`；无法校验又代价高的判断交给 `HUMAN`，只问一个精确问题。
- **决定 / 执行分离**——思考决定做什么，代码去做，关键时刻中间有闸门。
- **计划检查**——`READY` / `FIX`：没有未校验的模型步骤、没有无界循环、没有缺闸门的高代价操作、没有悬空依赖。
- **执行记录**——每步一行 JSONL，带输入/输出指纹，便于跨轮比较和断点续跑。
- **棘轮**——`FREEZE`、`CACHE`、`TIGHTEN`、`PROMOTE`、`SPLIT`、`DEMOTE`、`SAMPLE`、`KEEP`、`WAIT`；绝不自行取消人工闸门，也不会把对外操作从代码通道移走。
- 零依赖辅助脚本 `scripts/sot.py`（route / lint / fp / ratchet），JSON 输出，退出码适合 CI；14 个测试。

## 安装

把整个文件夹复制到智能体的技能目录：

| 智能体 | 位置 |
|---|---|
| Claude Code | `~/.claude/skills/script-or-think/`（或项目内 `.claude/skills/`） |
| Codex | `~/.codex/skills/script-or-think/` |
| Cursor | 项目内 `.cursor/skills/script-or-think/`，或在规则中引用 `SKILL.md` |
| Gemini CLI / 其他 | 放在任意位置，让智能体读取 `SKILL.md` |

```bash
git clone https://github.com/fangdididi/script-or-think ~/.claude/skills/script-or-think
```

中文用户可以让智能体读取 `SKILL.zh-CN.md`。

## 使用

可以这样对智能体说：

- “在搭这个周一报表例行任务之前，先给每一步分流——脚本还是模型？”
- “我们的发票智能体又慢又偶尔出错。拆分通道并检查计划。”
- “我们有六周的运行记录——现在哪些可以固化？”

或自己运行辅助脚本（Python 3.8+，无依赖）：

```bash
python3 scripts/sot.py route examples/steps.json > plan.json   # 步骤卡 -> 通道
python3 scripts/sot.py lint plan.json                           # READY (0) / FIX (1)
python3 scripts/sot.py fp output.json                           # 生成记录用的稳定指纹
python3 scripts/sot.py ratchet examples/records.jsonl           # 建议的通道调整
python3 -m unittest discover -s tests                           # 运行测试
```

## 示例

`examples/steps.json` 用七张卡描述一个每周供应商发票任务。分流结果：

```
collect         SCRIPT          R2
extract.shape   THINK           R3   模型从各种 PDF 版式读出结构化数据
extract.run     SCRIPT          R3   代码核对金额和日期
match           SCRIPT          R2
chase           SCOUT           R4   15 次调用，工具：po_search、mail_search
summary         THINK           R5   补上 rubric（原校验为 none，代价低）
pay             SCRIPT + 闸门   R1   精确付款调用先给人看
dispute.decide  HUMAN           R1
dispute.act     SCRIPT          R1
```

记录五周后（`examples/records.jsonl`），棘轮建议：`chase` -> 固化为脚本（每周工具路径相同），`extract.shape` -> CACHE，`match` -> DEMOTE（需要先整理输入），争议审批 -> KEEP（人修改过一次）。

## 文件结构

```
script-or-think/
├── SKILL.md              # 技能说明（英文）
├── SKILL.zh-CN.md        # 技能说明（中文）
├── README.md
├── README.zh-CN.md
├── scripts/sot.py        # route / lint / fp / ratchet 辅助脚本，仅用标准库
├── tests/test_sot.py     # 14 个单元测试
├── examples/
│   ├── steps.json        # 发票任务的步骤卡
│   ├── plan.json         # 分流后的计划
│   └── records.jsonl     # 五周的执行记录
└── LICENSE               # MIT
```

## 许可证

MIT © 2026 fangdididi
