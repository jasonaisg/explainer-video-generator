# 环境与工具发现规范

## 通用原则

- 不得假定操作系统、Shell、用户名、盘符、主目录、包管理器、虚拟环境名称或安装目录。
- 优先复用当前进程已经使用的 Python 3 解释器和当前机器已有工具。不得仅为了匹配示例而新建环境。
- 先发现、再验证、后调用。PATH 中出现名称不等于工具可用；必须运行轻量版本或帮助命令确认。
- 自动发现失败时，允许用户显式提供当前机器的可执行文件或启动器。机器解析出的绝对路径只写入该项目的环境报告或配置，不得回写 Skill 模板。
- 不自动安装依赖。仅当缺失工具会阻断当前阶段时，说明缺项、用途和最小可行方案，再遵守宿主平台的授权规则处理。
- 环境报告不得包含密钥、令牌、完整环境变量、用户文档内容或其他无关机器信息。

## 命令占位符

本文档与 Skill 中的 `<python>`、`<hyperframes>`、`<ffmpeg>` 和 `<ffprobe>` 都是占位符，不是字面命令：

- `<python>`：当前已验证能运行 bundled scripts 的 Python 3 调用方式。
- `<hyperframes>`：当前项目已验证的 HyperFrames CLI 调用方式。
- `<ffmpeg>`、`<ffprobe>`：当前机器已验证的媒体工具调用方式。

调用方式可以是 PATH 中的命令，也可以是用户提供的启动器路径。若调用需要环境管理器或额外参数，将完整调用方式保存在当前项目配置中，不得把它固化进 Skill。

## 标准探测

从 Skill 根目录运行：

```text
<python> scripts/check_environment.py [--output <environment-report.json>]
```

探测器只使用 Python 标准库，不修改机器。它记录平台摘要、当前 Python 版本，以及 PATH 中可解析的 HyperFrames、FFmpeg、FFprobe、Node.js、npm、npx 和浏览器候选。显式启动器不在 PATH 时，可逐项传入：

```text
<python> scripts/check_environment.py --hyperframes <启动器> --browser <浏览器可执行文件> --output <environment-report.json>
```

生成报告后：

1. 用实际 CLI 的 `--version` 或 `--help` 验证所需功能和参数。
2. 将 HyperFrames 的实际调用方式与版本写入 `project-config.json` 的 `backend.launcher` 和 `backend.version`。
3. P01 前确认 FFprobe 可用；需要转码或媒体代理时再确认 FFmpeg。
4. P07–P13 前确认 HyperFrames、其所需运行时和兼容浏览器可用。
5. 只有开启自动转录时才检查相应转录后端；关闭的可选模块不得制造依赖阻断。

探测不到可执行文件不等于内容问题，也不得触发内容风险。它只在相关阶段确实需要该工具且没有可行替代调用时，作为客观执行问题处理。
