# Agent delivery kernel · 可复用 AI 交付内核（演示仓库）

> 一个**从零用合成数据重写**的演示项目：把"怎么把一次性的 Agent 交付变成可复用体系"做成一套确定性内核。
> 与生产项目完全无关：**无客户名、无真实表名/字段/码值、无业务口径、无连接信息、无日报格式**；所有示例值均为合成。
> 设计的问题来自真实现场：换项目要从零收资料、升级后旧项目不知道新增了什么、接入失败被当成"没选过"而静默跳过。

## 它解决什么

| 问题 | 本仓库的做法 |
|---|---|
| 一次性交付，经验沉不下来 | **声明式能力清单**：每条能力登记"怎么检测没接上 / 接入步骤 / 完成判据 / 降级" |
| 升级后新增能力在旧项目里静默失效 | **能力差集**：包内清单 × 项目态 → 待补接入能力，不靠人记得 |
| 旧会话读不到新版 agent 规则 | **自包含任务单**：步骤、命令、确认门、续跑点写进任务单，照单执行即可 |
| 不通就跳过、接了个半吊子 | **三态拆开**：决定（持久） / 通道可达（运行时） / 文档覆盖（运行时）；不通是"待修复"不是"未提供" |
| 修到一半断了，下次从头来 | **断点状态位**：`--step` 记录 `blocked_reason` + `resume_at`，下次从断点续跑 |
| 升级覆盖用户配置 | **收口断言**：只追加不覆盖；coverage、受保护文件哈希不变，否则不报完成 |

## 快速开始

```bash
# 1) 复制示例工作目录（模拟一个"旧项目"）
cp -r examples/workdir /tmp/demo-workdir

# 2) 只读体检：能力差集 + 自包含任务单（不写任何文件）
python scripts/kernel.py --workdir /tmp/demo-workdir --json

# 3) 记录一步状态（断点续跑的状态位）
python scripts/kernel.py --workdir /tmp/demo-workdir \
  --step example_channel:probe:blocked --note "endpoint_unreachable" --json

# 4) 收口断言（能力未就绪时会 blocked，不会谎报完成）
python scripts/kernel.py --workdir /tmp/demo-workdir --finalize --json

# 5) 回归
python -m unittest discover -s tests -v
```

## 结构

```
schemas/capabilities.yaml       能力清单（声明式，无业务词）
scripts/kernel.py              一句话入口：差集 / 任务单 / 状态位 / 收口
tests/test_kernel.py           零依赖回归（只读安全 / 差集 / 任务单 / 断点 / 收口 / 可扩展）
examples/workdir/              合成项目态（inputs / registry / manifest 全是假数据）
examples/self-use-log.csv      自用实证采集模板（E3 级证据）
```

## 核心设计取舍（面试可讲）

1. **状态拆成三态，不是一个字段**：把"用户是否决定接入"（持久）与"当前通不通"（运行时、会变）混成一格，探测失败就只能清空字段 → 被当成"用户没选过" → 新能力静默跳过。拆开后，"待修复"与"未提供"才可区分。
2. **任务单自包含**：旧会话的上下文锁死在启动那一刻，光在新版规则里写指令它读不到。所以把流程输出成带全部命令与续跑点的任务单，执行方照单执行。
3. **收口不是终点，是判据**：`--finalize` 必须同时满足受保护文件哈希不变、coverage 不变、能力就绪或明确 declined，否则返回 blocked 并给出缺口。
4. **加能力不改代码**：`capabilities.yaml` 里加一条登记，差集与任务单自动生成；内核脚本零改动。
5. **默认只读**：检查动作绝不写项目态；落状态只在显式 `--step` / `--finalize` 时发生。

## 证据等级说明（诚实边界）

本仓库证明的是**工程可靠性与可复用设计**（负向测试、断点续跑、收口断言、加能力零改动），不是生产环境成效。演示数据全部合成，不含任何真实业务结果。实际项目中的业务成效需要上线后跟踪采集，模板见 `examples/self-use-log.csv`。

## License

MIT
