# Context Monitor

本地只读 Codex 监控插件，包含浅色/深色侧面板和可选输入框 TPS 状态条。

## 当前能力

- 上下文占用、缓存/非缓存输入、模型输出、剩余空间。
- 最近已完成响应 TPS、本次会话按时间加权的平均 TPS、最近样本曲线。
- 本轮总耗时：运行中每秒增长，最终回复完成或中断后停止；新一轮自动归零。
- 输入、输出、缓存、推理计数，测速覆盖率，首 token 延迟。
- 日志中的 5 小时/周额度快照。
- 固定绑定一个会话的本地网页面板，可在 Codex 右侧浏览器面板打开。
- 实验性工具栏注入：放在权限控件右侧的空白区，空间不足隐藏，切换会话清空旧值。

**当前验证边界：**面板与输入框状态条均已在本机当前桌面应用实测（2026-11-17）。已验证真实 TPS、主聊天切换、同时打开旁聊、点击展开、Escape 收起，以及权限按钮无遮挡。状态条依赖内部 DOM，不是官方工具栏扩展接口；不修改应用包。

## 安装

当前支持 macOS，需要 Python 3.10+；工具栏另外需要 Node.js 22+。运行时没有第三方包依赖。

已登录 GitHub 且有仓库读取权限时，可以通过仓库安装：

```sh
codex plugin marketplace add https://github.com/mutezebra/codex-context-monitor
codex plugin add context-monitor@context-monitor-local
```

也可以克隆仓库，在根目录执行：

```sh
codex plugin marketplace add "$PWD"
codex plugin add context-monitor@context-monitor-local
```

新一轮对话中请求：`$context-monitor 打开当前会话监控面板`。

也可以直接启动：

```sh
python3 scripts/manage.py start --thread <当前会话UUID>
```

返回的 `panel_url` 是本机可访问的面板链接。面板固定绑定该会话，不会跟随另一个聊天自动切换。采集器只监听回环地址，访问路径随机生成；不要将这个地址分享给他人。进程状态位于 `${XDG_STATE_HOME:-~/.local/state}/codex-context-monitor/`。默认后台运行，不添加开机启动。

## 在输入框工具栏启用 TPS

工具栏采用 CDP 临时注入，依赖应用内部 DOM。它不是官方公开的工具栏扩展点，应用升级可能需要适配。

1. 等待其他聊天任务完成，正常退出桌面应用。
2. 在插件根目录执行 `sh scripts/launch-with-toolbar.sh`，以仅本地的 DevTools 端口启动应用。此脚本拒绝在应用仍运行时继续，不会强制退出应用。
3. 打开目标 Codex 聊天，再执行 `python3 scripts/manage.py toolbar`。
4. 成功识别主聊天、输入框和权限按钮后，在其右侧显示 `TPS 108.2 · 均值 96.4 · 本轮 02:35`（此处数字仅为格式示例，速度单位为 tok/s）。点击展开同款监控卡片，按 Escape 收起。

默认端口 9222，可设置 `CONTEXT_MONITOR_PORT` 并给管理命令传 `--port`。旧版应用可用 `CONTEXT_MONITOR_APP=/Applications/Codex.app`。

DevTools 能操作应用页面，仅用于本机调试，不应对局域网或互联网开放。新版应用采用内存路由时，读取侧边栏唯一的活动本地线程标记，只挂到主聊天，排除右侧旁聊。目标按钮或会话不唯一时不会注入；不以“最近活跃聊天”代替当前聊天。若探测失败，请保留诊断结果供适配。只有真正显示成功才会启动持续采集器。

## 日常使用与维护

- 使用过程中无需手动刷新，采集和计时会自行更新。
- 普通方式重启桌面应用后，临时状态条会消失。按上面的启动步骤重新启用即可；未配置开机启动或应用自动改写。
- 桌面应用升级后，内部 DOM 或日志格式可能改变。如果状态条消失或数据不可用，需要更新插件适配。
- GitHub 保存源码与版本记录，不会自动把提交部署到本机。手动克隆安装的版本可以用 `git pull --ff-only` 更新源码，再运行 `codex plugin add context-monitor@context-monitor-local` 更新安装副本；正在运行的监控服务需要重载才能使用新代码。
- 不要在活动聊天期间为更新插件而强制退出桌面应用。插件自身的采集服务可以单独停止、重新启动。

## 统计口径

`总 token = 输入 + 输出`。缓存输入包含在输入里；推理输出包含在输出里。

上下文占用是最近请求的 `total_tokens / model_context_window`，不是整个会话累计消耗。日志不能可靠拆分消息、系统指令和技能占比，因此没有照抄参考图中的分类数字。

TPS 是日志测得的**已完成响应平均速率**，不是逐 token 瞬时速度：

```text
响应 TPS = 输出 token（含推理与工具调用参数）
           /（usage 记录时间 - 该响应首个已观测模型输出开始时间）
会话平均 = 可测速响应的输出 token 总和 / 对应时间总和
```

工具执行间隔不计入时间。没有模型输出起点的响应不参与测速，面板明确显示覆盖率。usage 落盘相对最后一个 token 存在小幅延迟，该口径不等同服务端推理引擎的纯生成吞吐率。TTFT 使用最近已完成轮次的日志值；新轮次开始后先置空。

当服务断开或活跃会话 2 分钟没有新日志时，当前 TPS 置空并提示状态；历史平均仍保留。额度来自日志快照，后台不会调用账户接口。

### 本轮耗时

这是单次执行轮次的端到端耗时，不是整个聊天累计时长。运行中按 `当前时间 - task_started 事件时间` 计算，前端每秒刷新；收到 `task_complete` 后优先使用日志原有的 `duration_ms`，缺失时用完成时间减开始时间。包含模型思考、工具执行、审批及其他轮内等待。

计时起点是 Codex 开始这一轮的日志事件，不能精确测量点击发送到该事件之前的网络或排队延迟。下一轮重新计时；运行中追加指令若仍属于同一轮，不重置。中断事件会冻结计时并标记“已中断”，不会把中断当作最终回答。断开采集连接时不继续伪装为在线计时。超过一小时显示 `h:mm:ss`。

## 停止与卸载

```sh
python3 scripts/manage.py stop
codex plugin remove context-monitor@context-monitor-local
codex plugin marketplace remove context-monitor-local
```

工具栏采集器检测到服务停止后会移除自身节点并退出。重启应用也会移除临时注入；正常启动应用即可关闭本次启用的 DevTools 端口。

## 开发与验证

运行时不需要 Python 第三方包或 npm 依赖。UI 测试使用 Playwright Core 与本机 Chrome：

```sh
python3 -m unittest discover -s tests -v
node tests/timer.cjs
npm install
CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" npm run test:ui
node --check scripts/attach.mjs
```

测试截图生成在 `artifacts/`，不纳入 Git。原始会话日志、认证数据、服务访问凭证和本地开发过程记录不包含在仓库中。
