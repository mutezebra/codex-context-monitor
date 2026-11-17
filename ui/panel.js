(() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = value => Number.isFinite(value) ? (value >= 1e6 ? (value/1e6).toFixed(2)+'m' : value >= 1e3 ? (value/1e3).toFixed(1)+'k' : Math.round(value).toLocaleString('en-US')) : '—';
  const rate = value => Number.isFinite(value) ? value.toFixed(1) : '—';
  const pct = value => Number.isFinite(value) ? value.toFixed(1)+'%' : '—';
  const clamp = value => Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  const time = value => Number.isFinite(value) ? (value/1000).toFixed(1)+'s' : '—';
  function elapsed(s,now=Date.now()){
    if(s?.turn_status==='active') return Number.isFinite(s.turn_started_at)?Math.max(0,now-s.turn_started_at):null;
    return Number.isFinite(s?.duration_ms)?s.duration_ms:null;
  }
  function formatElapsed(value){
    if(!Number.isFinite(value))return '—';
    const seconds=Math.floor(Math.max(0,value)/1000),hours=Math.floor(seconds/3600);
    const minutes=String(Math.floor(seconds/60)%60).padStart(2,'0'),rest=String(seconds%60).padStart(2,'0');
    return hours?`${hours}:${minutes}:${rest}`:`${minutes}:${rest}`;
  }
  function resetTime(seconds) {
    if (!Number.isFinite(seconds)) return '重置时间未知';
    const minutes = Math.max(0, Math.ceil((seconds * 1000 - Date.now()) / 60000));
    return minutes ? `${Math.floor(minutes/60)}h ${minutes%60}m 后重置` : '等待刷新';
  }
  function legendRow(label, color, count, percent) {
    return `<div class="legend-row"><i class="swatch" style="background:${color}"></i><span>${label}</span><span class="value mono">${fmt(count)}</span><span class="percent mono">${pct(percent)}</span></div>`;
  }
  function quotaRow(label, data) {
    const used = data?.used_percent;
    return `<div class="quota-row"><div class="quota-label"><span>${label}</span><span><strong>${pct(used)} 已用</strong> · ${resetTime(data?.resets_at)}</span></div><div class="track"><div class="segment ${used>=100?'exhausted':''}" style="width:${clamp(used)}%"></div></div></div>`;
  }
  function chart(history) {
    const points = history.slice(-32).map(x => x.tps).filter(Number.isFinite);
    if (points.length < 2) return '<div class="micro">等待更多测速样本</div>';
    const top = Math.max(1,...points)*1.1;
    const xy = points.map((v,i) => `${(i/(points.length-1)*320).toFixed(1)},${(36-v/top*32).toFixed(1)}`).join(' ');
    return `<svg viewBox="0 0 320 40" preserveAspectRatio="none" role="img" aria-label="最近已测响应 TPS 趋势"><path d="M0 38H320" stroke="var(--line)"/><polyline points="${xy}" fill="none" stroke="var(--blue)" stroke-width="1.7" vector-effect="non-scaling-stroke"/></svg>`;
  }
  function create(root, {refresh=()=>{}}={}) {
    let tab = 'overview', current = null, problem = '', detailsOpen = false;
    root.innerHTML = '<section class="monitor"><header class="head"><span class="brand">◉</span><h1>Context Monitor</h1><span class="live"><i class="dot off"></i>连接中</span></header><div class="empty">正在读取本地会话指标…</div></section>';
    function render() {
      const focused=root.getRootNode().activeElement;
      const restoreTab=root.contains(focused)?focused?.dataset?.tab:null;
      const restoreRefresh=root.contains(focused)&&focused?.dataset?.action==='refresh';
      const restoreDetails=root.contains(focused)&&focused?.tagName==='SUMMARY';
      if (!current) {
        if (problem) root.innerHTML = `<section class="monitor"><header class="head"><span class="brand">◉</span><h1>Context Monitor</h1></header><div class="empty">${escape(problem)}</div></section>`;
        return;
      }
      const s = current, last=s.last||{}, total=s.total||{};
      const age = s.log_modified_at ? Date.now()-s.log_modified_at : Infinity;
      const active = !['completed','interrupted','unknown'].includes(s.phase);
      const stale = !!problem || (active && age>120000);
      const status = problem ? '连接中断' : stale ? '暂无新记录' : s.loading ? '读取中' : active ? '同步中' : '已同步';
      const latest = stale || s.phase==='waiting' ? null : s.latest_tps;
      const win = s.context_window, cached=last.cached_input_tokens;
      const uncached = Number.isFinite(last.input_tokens)&&Number.isFinite(cached) ? Math.max(0,last.input_tokens-cached) : null;
      const remaining = win&&Number.isFinite(s.context_tokens)? Math.max(0,win-s.context_tokens):null;
      const ratio = n => win&&Number.isFinite(n)?n/win*100:null;
      let body='';
      if(tab==='overview') {
        body=`<section><div class="track" aria-label="上下文占用 ${pct(s.context_percent)}"><span class="segment" style="background:var(--blue);width:${clamp(ratio(cached))}%"></span><span class="segment" style="background:var(--teal);width:${clamp(ratio(uncached))}%"></span><span class="segment" style="background:var(--purple);width:${clamp(ratio(last.output_tokens))}%"></span></div><div class="legend">${legendRow('缓存输入','var(--blue)',cached,ratio(cached))}${legendRow('非缓存输入','var(--teal)',uncached,ratio(uncached))}${legendRow('模型输出（含推理）','var(--purple)',last.output_tokens,ratio(last.output_tokens))}${legendRow('剩余上下文','var(--line)',remaining,ratio(remaining))}</div><p class="hint">最近一次请求快照 · 系统、技能与消息的精确拆分不可用</p></section>
          <section class="metrics"><div class="turn-timer" title="从本轮请求开始到最终回复完成，包含思考、工具执行与等待"><div><span>本轮耗时</span><small>${problem?'已断开':({active:'运行中',completed:'已完成',interrupted:'已中断'}[s.turn_status]||'未知')}</small></div><b class="mono" data-elapsed>${formatElapsed(elapsed(s))}</b></div><div class="speed-row"><div class="speed-cell"><div class="eyebrow">TPS · 最近响应</div><div class="speed mono" data-metric="latest">${rate(latest)}<span class="unit">tok/s</span></div><div class="micro">${s.phase==='waiting'?'等待本轮首个响应':stale?'等待新记录':s.latest_tps==null?'该响应缺少输出起点':'响应完成后更新'}</div></div><div class="speed-cell"><div class="eyebrow">本次会话平均</div><div class="speed mono" data-metric="average">${rate(s.average_tps)}<span class="unit">tok/s</span></div><div class="micro">按输出时间加权</div></div></div><div class="spark">${chart(s.history||[])}</div><div class="stats"><div class="stat"><span>首 TOKEN 延迟</span><b class="mono">${time(s.ttft_ms)}</b></div><div class="stat"><span>输出 / 推理</span><b class="mono">${fmt(last.output_tokens)} / ${fmt(last.reasoning_output_tokens)}</b></div><div class="stat"><span>测速覆盖</span><b class="mono">${s.measured_responses} / ${s.responses}</b></div></div></section>
          <section><h2>额度使用</h2><div class="quota"><div class="quota-head"><span>Codex${s.limits?.plan_type?' · '+escape(s.limits.plan_type):''}</span><span class="badge">本地快照</span></div>${quotaRow('5 小时窗口',s.limits?.primary)}${quotaRow('每周窗口',s.limits?.secondary)}<p class="hint">额度以日志最后一次记录为准</p></div></section>`;
      } else if(tab==='tokens') {
        body=`<section><h2>本次会话累计</h2><div class="table">${[['输入',total.input_tokens],['其中：缓存输入',total.cached_input_tokens],['输出（含推理）',total.output_tokens],['其中：推理输出',total.reasoning_output_tokens],['总 token',total.total_tokens]].map(([k,v])=>`<div class="table-row"><span>${k}</span><b class="mono">${fmt(v)}</b></div>`).join('')}<div class="table-row"><span>缓存命中率</span><b class="mono">${pct(s.cache_hit_percent)}</b></div></div><p class="hint">缓存属于输入，推理属于输出；总量中各计一次。累计消耗不等于当前上下文占用。</p></section>`;
      } else {
        body=`<section><h2>数据状态</h2><div class="table">${[['会话',s.thread_id],['阶段',s.phase],['有效测速',`${s.measured_responses} / ${s.responses}`],['累计输出时间',time(s.measured_seconds*1000)],['已计时输出',fmt(s.measured_tokens)],['上下文压缩事件',s.compactions],['跳过损坏记录',s.bad_lines],['重试次数','日志未提供'],['最近日志更新',s.log_modified_at?new Date(s.log_modified_at).toLocaleTimeString('zh-CN'):'—']].map(([k,v])=>`<div class="table-row"><span>${k}</span><span class="mono" style="overflow-wrap:anywhere;text-align:right;max-width:65%">${escape(v)}</span></div>`).join('')}</div><p class="hint">本地只读 · 不上传会话 · 每 2 秒刷新摘要</p></section>`;
      }
      root.innerHTML=`<section class="monitor"><header class="head"><span class="brand">◉</span><h1>Context Monitor</h1><span class="live"><i class="dot ${stale?'off':''}"></i>${status}</span><button class="icon-button" type="button" data-action="refresh" aria-label="刷新指标">↻</button></header>
        <section><div class="context-heading"><span>上下文窗口</span><span class="pill" title="${escape(s.model)}">${escape(s.model||'未知模型')}${s.effort?' · '+escape(s.effort):''}</span></div><div class="context-total"><strong>${fmt(s.context_tokens)}</strong><span class="muted">/ ${fmt(win)}</span><span class="muted">(${pct(s.context_percent)})</span></div></section>
        <div class="divider"></div><nav class="tabs" role="tablist" aria-label="监控视图">${[['overview','概览'],['tokens','Token 用量'],['diagnostics','诊断']].map(([key,label])=>`<button type="button" role="tab" data-tab="${key}" aria-selected="${tab===key}">${label}</button>`).join('')}</nav>${problem?`<div class="status-error">${escape(problem)}</div>`:''}${body}
        <details class="details" ${detailsOpen?'open':''}><summary>统计口径与缺失数据</summary><p>TPS 使用已完成响应的输出 token（含推理与工具参数）÷ 从首个已观测模型输出到 usage 落盘的时间，排除工具执行间隔。它是日志测得的平均速率，不是逐 token 瞬时速率。没有起始时间的响应不参与测速。会话平均按有效样本的总 token ÷ 总耗时计算。TTFT 来自最近已完成轮次。本轮耗时从日志中的请求开始事件计时，包含思考、工具和等待，最终以完成事件的总时长为准。</p></details>
        <footer class="footer"><div class="session" title="${escape(s.thread_id)}">当前会话 · ${escape(s.title||s.thread_id)}</div><div class="footnote mono"><span>in ${fmt(total.input_tokens)} · cache ${fmt(total.cached_input_tokens)}</span><span>只读</span></div></footer></section>`;
      root.querySelector('[data-action="refresh"]').onclick=refresh;
      for(const el of root.querySelectorAll('[data-tab]')) el.onclick=()=>{tab=el.dataset.tab;render();root.querySelector(`[data-tab="${tab}"]`).focus();};
      root.querySelector('details').ontoggle=e=>{detailsOpen=e.target.open;};
      if(restoreTab) root.querySelector(`[data-tab="${restoreTab}"]`)?.focus({preventScroll:true});
      if(restoreRefresh) root.querySelector('[data-action="refresh"]')?.focus({preventScroll:true});
      if(restoreDetails) root.querySelector('summary')?.focus({preventScroll:true});
    }
    return {update(s){if(current?.thread_id!==s.thread_id) detailsOpen=false;current=s;problem='';render();},error(message){problem=message;render();},
      tick(now=Date.now()){if(!current||problem)return;const el=root.querySelector('[data-elapsed]');if(el)el.textContent=formatElapsed(elapsed(current,now));}};
  }
  globalThis.ContextMonitorUI={create,rate,elapsed,formatElapsed};
})();
