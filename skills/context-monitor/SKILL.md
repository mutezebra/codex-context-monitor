---
name: context-monitor
description: 打开、停止或排查本地 Codex Context Monitor，查看上下文、token、TPS、会话平均速度、本轮耗时和额度快照。适用于明确的 Codex 会话监控请求。
---

# Context Monitor

以本技能目录向上两级定位插件根目录，不依赖固定安装路径。

## 常驻安装与恢复

用户要求常驻、自动启动或重启后自动生效时，执行 `python3 <插件根目录>/scripts/manage.py enable-autostart`。该动作安装用户级 LaunchAgent 和监控启动器，并将现有 Dock 应用入口可逆地指向启动器；用户不希望修改 Dock 时使用 `--no-dock`。

通过 `status` 核对 persistent 和两个 agents 的 loaded/running。常驻模式下代理自动恢复；应用关闭时等待，不擅自重启应用。不要把“代理已加载”当成“状态条已显示”，还需检查当前聊天挂载状态。

普通路径启动的应用可能没有调试端口，后台无法补加参数。应说明从 Dock 的 ChatGPT Monitor 入口启动；不能为此强制结束正在运行的聊天。更新源码后再次运行 enable-autostart 可更新稳定运行副本。

## 打开面板

1. 从当前聊天工具上下文或 `CODEX_THREAD_ID` 获取当前会话 UUID。不要以“最近更新的会话”代替当前会话；不能确定时先询问。
2. 执行 `python3 <插件根目录>/scripts/manage.py start --thread <UUID>`。
3. 将返回的 `panel_url` 用 `open_in_codex` 的 browser 类型打开在当前会话右侧。没有该工具时交付本地链接。该 URL 是本机访问凭证，不发到外部服务。
4. 这是固定绑定会话的面板，切换到其他聊天时需为该聊天重新打开。

## 输入框工具栏

执行 `python3 <插件根目录>/scripts/manage.py toolbar` 探测默认 9222 端口。可用时脚本仅在识别出的主聊天输入框旁添加临时状态条；会话取输入框自身的会话标记，旧版才回退明确的 URL 会话 ID，不绑定右侧旁聊。侧边栏选中状态可能滞后，不能作为会话身份来源。排查串会话时核对 status 中 threadId、snapshotThreadId 和面板底部绑定 ID 是否一致。

未开启 DevTools 时不能宣称已显示。先保留面板，再说明从监控入口启动的要求。不要自行终止用户正在运行的其他聊天。后续启用步骤见插件根目录 `README.md`。

## 停止与口径

执行 `python3 <插件根目录>/scripts/manage.py stop` 暂停采集。常驻模式会在下次登录自动恢复；永久关闭需 `disable-autostart`，它会恢复原 Dock 入口并移除登录代理。

TPS 是已完成模型响应的日志平均速率，包含推理和工具调用参数，不是逐 token 瞬时测量。会话平均按可用计时样本的输出 token 之和除以时间之和；缺失样本不参与，UI 显示覆盖率。缓存和推理均为子集，不重复相加。不根据字符数伪造 token，不读取认证文件。

本轮耗时从 task_started 开始，包含思考、工具与等待；运行时每秒增长，结束后采用日志 duration_ms 并冻结，新一轮重置。不等同点击发送按钮到开始执行之前的排队/网络时长。中断应显示“已中断”，不可当作完成。
