# Session 调度规范

## Session 拓扑

- 维护一个名为 `EVG-PM-<项目简称>` 的项目经理 Session。
- 维护十五个名为 `EVG-P00-<简称>` 至 `EVG-P14-<简称>` 的阶段 Session。
- 一次只运行一个阶段。只有前置阶段被验收后，才创建下一个 Session。
- 项目经理只保留精简上下文：项目状态、Session 注册表、决定、问题、交接、交付清单和门禁证据。

## 注册表

记录 `role`、`phase`、`session_name`、`session_id`、`platform`、`status`、`created_at`、`last_seen_at`、`input_version`、`attempt`、`predecessor`、`successor` 和 `prompt_path`。外部平台返回真实编号前使用 `UNASSIGNED`，不得编造编号。

Session 状态：`PLANNED`、`CREATED`、`ACTIVE`、`WAITING_USER`、`SUBMISSION_AUTHORIZED`、`SUBMITTED`、`ACCEPTED`、`REVISION_REQUIRED`、`FAILED`、`SUPERSEDED`。

阶段状态：`NOT_STARTED`、`READY`、`IN_PROGRESS`、`SELF_CHECK`、`USER_REVIEW`、`SUBMISSION_AUTHORIZED`、`SUBMITTED`、`REVISION_REQUIRED`、`ACCEPTED`、`STALE`、`BLOCKED`。

新初始化项目使用 1.3 版控制协议，将 Agent 内容建议、用户要求、用户最终决定和客观执行问题分别保存。旧项目已经正式验收的历史阶段不倒追撤销；迁移前运行 `projectctl.py migrate-governance`，旧项目存在非零问题计数时必须使用 `--legacy-phase-classification Pxx=ADVISORY|OBJECTIVE` 逐阶段分类，或在确认全部同类时使用 `--legacy-items-as`，不得由 Agent 自动猜测。旧项目首次发生变更时仍运行 `change_control.py bootstrap`，补建产物依赖图与变更控制目录。

上述英文状态值是脚本和 JSON 使用的固定枚举，不得翻译或自行新增。

## 分发协议

1. 项目经理验证依赖后运行 `projectctl.py prepare <项目根目录> Pxx`。
2. 项目经理运行 `projectctl.py prompt <项目根目录> Pxx`。
3. 平台支持且已授权时，由项目经理创建 Session；否则把提示词交给用户手动创建。
4. 项目经理运行 `projectctl.py register <项目根目录> Pxx --session-id <真实编号> [--platform <平台>]`。
5. 阶段 Session 读取任务包并输出启动报告：角色、已接受输入、检测到的版本、缺失项、计划检查和第一个动作。

## 交接协议

每个阶段写入：

- `task-packet.md`：由项目经理确定的范围、读取路径、写入路径、禁止事项、交付物和门禁。
- `stage-result.json`：结果、检查、决定、问题数量和建议的下一步动作。
- `deliverables-manifest.json`：路径、类型、版本、SHA-256、制作方和验证证据。
- `handoff.md`：下一阶段真正需要的精简事实，不得复制整段讨论。
- `open-issues.md`：负责人、等级、证据、所需决定和状态。
- `approval-record.md`：审阅互动、内容意见、处理状态、最终提交授权、时间、范围和被替代授权的完整事件记录。
- `content-advice.json`：Agent 的非阻断内容参考建议，`gate_effect` 永远为 `NONE`。
- `owner-decisions.json`：用户具有约束力的最终内容决定。
- `review-items.json`：用户提出且尚待执行或回答的事项。
- `stage-issues.json`：依据用户技术契约可客观复现的执行问题，是 `open-issues.md` 和 `stage-result.json` 问题计数的权威源。

项目经理验证产物后执行 `accept` 或 `return`。阶段 Session 不得自行验收。

## 阶段内互动与双层门禁

阶段 Session 是用户参与的正式讨论空间，不是完成后才汇报的后台执行器。

1. 在对应阶段 Session 中展示方案或产物，直接与用户讨论，按反馈修改。文件批注、内容意见和最终提交授权必须分别记录，不得混为一谈。
2. 用户最新明确决定是唯一最终内容权威。项目经理不得代替用户批准或重新评判内容；项目经理只检查决定是否被准确执行，并执行技术、完整性、证据和跨阶段验收。Agent 内容建议不得影响项目状态。
3. P00、P04、P05、P07、P08、P10、P14 只有在最终版本完成、自检通过、批注和问答及附加要求全部关闭后，才能单独请求提交授权。只有用户明确表示“可以提交项目经理”并写入 `SUBMISSION_AUTHORIZED`，才能提交。接收或批注文件、内容认可、原则同意、附条件批准、沉默、含糊回应、仅查看或未反对均不算授权。
4. 阶段提交后，优先通过平台能力通知项目经理；没有跨 Session 通知能力时，向用户输出：`本阶段已提交，请返回 EVG-PM-<项目简称>，由项目经理验收并创建下一阶段。`
5. 项目经理验收上述七个阶段及任何发生用户最终决定的动态互动阶段前，必须直接读取 `approval-record.md`，确认最新事件是有效的 `SUBMISSION_AUTHORIZED`，并核对最终产物、版本、范围、用户授权原话、零开放客观阻断、零未完成用户要求、已关闭条件、已完成问答及时间。不得把未采纳的 Agent 建议计入未决事项。
6. 用户提出阶段内修改时，继续使用原阶段 Session。若原 Session 丢失或上下文不可用，按 Session 恢复协议建立同阶段替代 Session，而不是在项目经理 Session 中代做修改。
7. 项目经理只处理全局范围、Session 调度、跨阶段冲突、变更影响、版本失效和正式放行。字体、画面、文案、动画、字幕或混音等具体阶段问题留在对应阶段 Session 讨论。

用户在审阅过程中的批注、提问、修改要求或内容认可，使用 `record-review` 记录。此命令会撤销此前尚未提交的授权。Agent 自己提出的内容判断必须使用 `record-advice`，不得使用 `record-review`，且不会改变项目状态或撤销授权：

```text
<python> scripts/projectctl.py record-review <项目目录> Pxx --event QUESTION --artifact <产物路径或编号> --version <版本> --message <用户问题或反馈>
<python> scripts/projectctl.py record-advice <项目目录> Pxx --advice-id ADV-Pxx-001 --topic <主题> --recommendation <参考建议> --rationale <理由>
<python> scripts/projectctl.py record-owner-decision <项目目录> Pxx --decision-id DEC-Pxx-001 --decision KEEP_ORIGINAL --scope <范围> --decision-quote <用户原话> --advice-id ADV-Pxx-001 --advice-disposition REJECTED
```

`record-approval` 仅记录内容意见（`APPROVED`、`APPROVED_WITH_CONDITIONS` 或 `REVISION_REQUIRED`），同样不能授权提交。保留该命令是为了区分内容决定与最终提交授权。

所有用户要求关闭、开放客观阻断为零并冻结最终版本后，阶段 Session 必须先展示最终汇总，再单独询问用户是否授权提交项目经理。用户明确授权后使用：

单独询问时使用清楚而不诱导的表述，例如：`当前最终版本为 vX，批注、附加要求和问答均已处理，未决事项为 0。你是否明确授权我现在把这个版本提交给项目经理验收？` 在用户回答前不得发送项目经理通知。

```text
<python> scripts/projectctl.py authorize-submit <项目目录> Pxx --artifact <最终产物路径或编号> --version <最终版本> --scope <提交范围> --authorization-quote <用户明确授权原话> --open-items 0 --conditions-status CLOSED --qa-status COMPLETE
```

只有 `authorize-submit` 能生成 `SUBMISSION_AUTHORIZED`。此后任何用户 `record-review`、`record-approval`、客观问题、文件修改或新版本都会使授权失效；单纯新增 `record-advice` 不会使授权失效。提交与验收均以最新一个互动事件为准。

交付清单不得包含 `approval-record.md`、`stage-result.json`、`open-issues.md`、`content-advice.json`、`owner-decisions.json`、`review-items.json` 或 `stage-issues.json`；这些是可变控制记录，不是冻结内容产物。提交授权分别绑定交付清单及其产物 SHA-256，以及用户决定、用户要求和客观问题组成的治理快照。授权后内容建议仍可增加；产物或治理快照变化时提交器必须拒绝提交并要求重新授权。

阶段内执行循环：

```text
读取任务包并输出启动报告
→ 分析或制作
→ 展示阶段成果
→ 与用户批注、问答并修改
→ 关闭全部要求与问题
→ 自检、生成交接包并冻结最终版本
→ 展示最终汇总并单独请求提交授权
→ 用户明确授权
→ 记录 SUBMISSION_AUTHORIZED
→ 不再修改，提交并通知项目经理
```

P01、P02、P03、P06、P09、P11、P12、P13 默认可以自主完成技术工作，但一旦需要用户解释事实、选择方案、解决同步或配置歧义、确认许可或扩大已批准范围，必须进入 `WAITING_USER` 或 `USER_REVIEW`，不得自行猜测后提交。

## 变更与返工

已审批产物发生变化时，读取[变更请求、产物依赖图与选择性返工规范](change-control.md)，使用 `change_control.py` 建立 `CR-xxxx`、产物级影响分析和 `RW-xxxx-xx` 工单。先取得用户对影响范围的明确批准，再修改产物。只使依赖图实际命中的产物失效；没有被命中的已审批成果继续有效。

工单默认回到产物原阶段 Session。原 Session 不可用时才创建带 `-RW-<变更号>-A<尝试号>` 的同阶段替代 Session。每张工单独立完成用户互动、提交授权和项目经理验收；上游工单验收后只放行依赖它的工单。

## Session 恢复

Session 丢失或上下文过长时，将其标记为 `SUPERSEDED`，增加 `attempt`，创建替代 Session，并只提供最新任务包和已验收交接。不得要求新 Session 阅读废弃对话。项目文件与对话冲突时，以已验收、已版本化的文件为准，并记录冲突。

## 平台适配

平台提供原生 Session 或任务管理工具时优先使用。平台不支持时，生成相同的 Markdown 启动提示词，指导用户手动打开新 Session。工作流不得依赖某一家平台的专用接口才能运行。
