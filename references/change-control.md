# 变更请求、产物依赖图与选择性返工规范

## 目录

1. [适用范围](#适用范围)
2. [核心对象](#核心对象)
3. [产物登记规则](#产物登记规则)
4. [依赖传播规则](#依赖传播规则)
5. [变更请求生命周期](#变更请求生命周期)
6. [选择性返工工单](#选择性返工工单)
7. [用户互动与授权](#用户互动与授权)
8. [原 Session 与替代 Session](#原-session-与替代-session)
9. [验收与关闭](#验收与关闭)
10. [故障恢复与禁止事项](#故障恢复与禁止事项)
11. [命令速查](#命令速查)

## 适用范围

在任一产物已审批、已提交或已被下游使用后，只要用户提出修改、发现缺陷、替换输入、改变配置，或后续阶段暴露出上游问题，立即进入本协议。不得直接编辑旧产物，也不得默认从某阶段开始重跑全部下游。

本机制维护三个独立对象：

- 变更请求 `CR-xxxx`：说明为什么改、改什么，以及用户原话。
- 产物级依赖图：说明每个具体产物依赖哪些具体产物。
- 选择性返工工单 `RW-xxxx-xx`：说明某个原阶段 Session 只需重建或验证哪些产物。

## 核心对象

### 产物节点

每个可被下游消费的文件或逻辑交付物必须有稳定 `artifact_id`。节点至少记录：

- `artifact_id`：跨版本不变的语义标识，例如 `captions.timeline`、`design.motion-script`、`render.captioned-master`。
- `path`、`type`、`producer_phase`、`version`、`sha256`。
- `depends_on`：直接依赖及传播模式。
- `status`：`VALID`、`REWORK_REQUIRED`、`VERIFY_REQUIRED`、`PENDING_REVIEW` 或 `RETIRED`。
- `history`：被替代版本的路径、版本、哈希、状态和时间。

不要把 `approval-record.md`、`stage-result.json` 等可变控制记录登记为内容产物。不要给同一语义对象每次生成新 ID；使用稳定 ID 并递增 `version`。

### 变更请求

状态依次为：

```text
OPEN → ANALYZED → APPROVED → IN_REWORK → CLOSED
```

`ANALYZED` 只是影响提案，尚未使任何产物失效。只有用户明确批准影响范围，并由项目经理执行 `issue-orders` 后，相关产物才会进入返工或验证状态。

### 返工工单

状态依次为：

```text
BLOCKED → READY → IN_PROGRESS ↔ WAITING_USER
→ SUBMISSION_AUTHORIZED → SUBMITTED → ACCEPTED
```

每个受影响阶段最多生成一张工单；同一工单可以包含多个产物。跨阶段工单依据真实产物边建立前置关系，而不是简单按 P00–P14 全串联。

## 产物登记规则

阶段产物首次冻结或验收前，使用 `register-artifact` 登记。先登记上游，再登记下游：

```text
<python> scripts/change_control.py register-artifact <项目目录> --artifact-id <稳定ID> --path <文件> --phase Pxx --version <版本> --type <类型> [--depends-on <上游ID[:REBUILD|VERIFY]>]
```

登记依赖时只写直接依赖，不要把所有祖先重复列入。脚本拒绝不存在的依赖和循环依赖。

阶段交付清单的相应文件项应同时记录 `artifact_id`、`version` 和 `depends_on`，使普通交付验证与变更控制能相互追溯。路径与哈希仍由交付清单冻结；依赖图记录跨阶段语义关系。

可复制 `assets/templates/artifact-map-template.json`，再由 `build_manifest.py --artifact-map <文件>` 把元数据写入清单。清单冻结后批量导入依赖图：

```text
<python> scripts/change_control.py import-manifest <项目目录> --manifest stages/Pxx/deliverables-manifest.json
```

导入器按依赖顺序处理同一清单中的节点，并拒绝缺失依赖、循环、文件漂移或对返工中产物的普通覆盖。

最低登记范围：规范化配置、源媒体清单、主时间轴、校正转录、事实锁定、人物布局、动效脚本、动作时间设计、各 A 场景模块的源码、数据和局部预览、共享组件、字幕数据、素材许可表、声音方案、HyperFrames 总合成、各类预览、草稿、最终渲染、质检报告和交付包。场景产物使用 `scene.A01.source`、`scene.A01.data`、`scene.A01.preview` 等稳定 ID；单场景变化默认只重建自身并验证相邻边界，共享依赖变化沿消费者关系传播。关闭的可选模块不创建虚构产物。

## 依赖传播规则

依赖边必须指定以下一种传播模式：

- `REBUILD`：上游变更后，下游产物必须重新生成。例如字幕时间轴到带字幕成片。
- `VERIFY`：上游变更后，下游产物可以保持字节不变，但必须提供回归证据。例如文档措辞变化到与该措辞无关的技术报告。

目标产物自身始终为 `REBUILD`。影响分析沿反向依赖边传递：只有 `REBUILD` 链继续保持强制重建；经过任意 `VERIFY` 边后，下游默认为回归验证。若同一产物通过不同路径同时得到 `REBUILD` 和 `VERIFY`，取 `REBUILD`。

没有依赖边就不得声称产物受影响。发现漏边时，先修复依赖图并重新分析，不得手工扩大或缩小分析结果。对确实独立的产物保留 `VALID`，不得因“阶段在后面”而整体作废。

## 变更请求生命周期

### 1. 登记请求

项目经理忠实记录用户要求，不立即修改文件：

```text
<python> scripts/change_control.py create-request <项目目录> --title <标题> --description <完整需求> --reason <原因> --requested-by <请求人> --request-quote <用户原话> --target <artifact_id>
```

一个请求可重复使用 `--target` 指定多个起点。目标不清楚时先与用户澄清；不得凭文件名猜测。

### 2. 生成影响分析

```text
<python> scripts/change_control.py analyze <项目目录> CR-xxxx
```

项目经理向用户展示：变更起点、必须重建的产物、仅需验证的产物、对应阶段、明确不受影响的产物，以及预计需要恢复的 Session。此时任何节点仍保持原状态。

### 3. 用户批准范围

用户可以继续问答、增删目标或要求修正依赖。每次图或目标变化后必须重新分析。只有用户明确表示批准当前影响范围，才能记录：

```text
<python> scripts/change_control.py approve-plan <项目目录> CR-xxxx --approved-by <用户> --approval-quote <明确批准原话>
```

查看分析文件不等于批准；讨论方案、原则同意、只批准某个文件或含附加条件的答复也不能被扩张解释为全部批准。

### 4. 签发工单

```text
<python> scripts/change_control.py issue-orders <项目目录> CR-xxxx
```

该命令把受影响节点标为 `REWORK_REQUIRED` 或 `VERIFY_REQUIRED`，按产出阶段创建工单，并只放行没有未完成前置工单的工单。批准后的影响分析或依赖图发生变化时，脚本必须拒绝签发。

## 选择性返工工单

每张工单必须包含：变更请求、原阶段、指定 Session、前置工单、必须重建的产物、仅需验证的产物和禁止扩张范围。

开始工单前生成提示词并恢复原 Session：

```text
<python> scripts/change_control.py order-prompt <项目目录> RW-xxxx-xx
<python> scripts/change_control.py start-order <项目目录> RW-xxxx-xx
```

重建产物后登记新路径、版本与哈希：

```text
<python> scripts/change_control.py update-artifact <项目目录> RW-xxxx-xx --artifact-id <ID> --path <新文件> --version <新版本>
```

如果直接依赖发生变化，重复 `--depends-on` 写入完整的新直接依赖集合。旧节点元数据自动进入 `history`；旧文件和旧审批证据必须保留。

仅需验证的产物必须运行与变更风险相称的回归检查，并记录可定位的证据：

```text
<python> scripts/change_control.py verify-artifact <项目目录> RW-xxxx-xx --artifact-id <ID> --evidence <报告路径、命令或结论>
```

不得把“肉眼看起来没问题”作为唯一回归证据。媒体产物应检查时间、画幅、编码、同步或关键帧；字幕应检查文本、时间范围、安全区和烧录结果；工程产物应运行 HyperFrames 的 lint、validate、inspect 或对应测试。

## 用户互动与授权

所有返工工单都涉及已冻结成果，必须回到原阶段 Session 与用户互动。记录每一项反馈并使用稳定事项 ID：

```text
<python> scripts/change_control.py record-review <项目目录> RW-xxxx-xx --item-id <ITEM-ID> --status OPEN --message <反馈>
<python> scripts/change_control.py record-review <项目目录> RW-xxxx-xx --item-id <ITEM-ID> --status CLOSED --message <处理结果>
```

返工同样服从用户最终内容权威。Agent 对内容的判断使用 `change_control.py record-advice` 写入工单的 `advisory_items`，始终非阻断且不得撤销提交授权；不得把 Agent 建议写入 `review_items`。用户决定使用 `record-owner-decision` 保存，对项目经理及下游工单具有约束力。

文件批示、问答、内容认可或附条件同意不等于提交授权。重建和验证全部完成、用户提出的事项全部关闭后，阶段 Session 展示最终产物版本、处理清单和回归证据，再单独询问：

`当前返工工单 RW-xxxx-xx 的全部产物与验证已完成，未决事项为 0。你是否明确授权我把这个版本提交项目经理验收？`

用户明确授权后执行：

```text
<python> scripts/change_control.py authorize-order <项目目录> RW-xxxx-xx --authorized-by <用户> --authorization-quote <明确授权原话>
```

授权绑定工单内全部产物的版本和 SHA-256。授权后任何产物更新或审阅互动都会使授权失效。

## 原 Session 与替代 Session

工单默认分配给产物原始 `producer_phase` 的已登记 Session。项目经理应把 `order-prompt` 发送回该 Session，保留先前讨论语境。

原 Session 无法恢复、上下文不可用或平台已归档时，创建同阶段替代 Session，名称使用：

```text
EVG-Pxx-<项目简称>-RW-<变更号>-A<尝试号>
```

替代 Session 只读取 Skill、工单、变更请求、影响分析、依赖图、原阶段最新已验收交接及工单点名的直接依赖。不得要求它重读全部历史对话。把真实新 Session ID 写入工单并保留原 ID；不得编造编号。

平台返回真实编号后，使用命令完成分配并保留旧 Session 历史：

```text
<python> scripts/change_control.py assign-order <项目目录> RW-xxxx-xx --session-id <真实编号> [--session-name <名称>] [--platform <平台>] --reason <替代原因>
```

## 验收与关闭

阶段 Session 提交工单：

```text
<python> scripts/change_control.py submit-order <项目目录> RW-xxxx-xx --summary <返工摘要>
```

项目经理核对范围、版本、哈希、回归证据、零未完成用户要求和最新提交授权后验收；不得因 Agent 内容建议未被采纳而拒绝工单：

```text
<python> scripts/change_control.py accept-order <项目目录> RW-xxxx-xx --evidence <验收证据>
```

验收后，工单中的产物恢复为 `VALID`。脚本自动检查其他工单的真实前置关系，只把所有前置均已验收的工单从 `BLOCKED` 改为 `READY`。

全部工单验收后，项目经理关闭请求：

```text
<python> scripts/change_control.py close-request <项目目录> CR-xxxx --evidence <整体回归与关闭证据>
```

关闭前必须确认最终交付版本矩阵、项目状态、依赖图和实际文件一致。若 P14 已验收后发生变更，相关交付包和发布质检必须通过依赖图进入重建或验证工单，不能继续沿用旧的 `COMPLETE` 结论。

## 故障恢复与禁止事项

- 每次恢复先运行 `validate_project.py` 和 `change_control.py status`，以文件状态为准。
- 不得直接编辑 `artifact-dependency-graph.json` 来绕过循环、缺失依赖或状态门禁。
- 不得用旧的 `projectctl.py invalidate` 代替本机制处理可定位的局部变更；它只保留给依赖图尚未建立的旧项目或明确要求全量重做的紧急场景。
- 不得在影响分析获批前修改产物。
- 不得把未列入工单的“顺手优化”混入返工；如确有必要，创建新的变更请求或回到分析阶段扩展目标。
- 不得在前置工单未验收时启动 `BLOCKED` 工单。
- 不得覆盖旧版本、旧审批、旧哈希或旧回归证据。

## 命令速查

```text
bootstrap
register-artifact
import-manifest
create-request → analyze → approve-plan → issue-orders
assign-order / order-prompt → start-order
update-artifact / verify-artifact / record-review
authorize-order → submit-order → accept-order
close-request
status
```
