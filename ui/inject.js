/* 临时挂载：只操作自身节点，不替换原生输入框或权限控件。 */
(() => {
  if (globalThis.__contextMonitor) return;
  let host=null, button=null, drawer=null, view=null, activeThread=null, refreshed=0, snapshot=null;
  let anchor=null, resizeObserver=null, frame=null, disposed=false;
  const uuid='[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}';
  function composerRoot(){
    const roots=[...document.querySelectorAll('[data-codex-composer-root]')].filter(el=>
      el.getBoundingClientRect().width>0&&!el.closest('[data-app-shell-focus-area="right-panel"]'));
    const main=roots.filter(el=>el.closest('[data-app-shell-focus-area="main"]'));
    const candidates=main.length?main:roots;
    return candidates.length===1?candidates[0]:null;
  }
  function threadId() {
    const root=composerRoot();
    if(!root||root.getAttribute('data-composer-placement')==='home')return null;
    // 内存路由下侧栏状态可能滞后，输入框自己的会话标记才对应当前显示内容。
    const markers=root.querySelectorAll('[data-above-composer-conversation-id]');
    let id=null;
    if(markers.length){
      const ids=[...markers].map(el=>el.getAttribute('data-above-composer-conversation-id'));
      if(ids.some(value=>!new RegExp('^'+uuid+'$','i').test(value)))return null;
      const unique=new Set(ids.map(value=>value.toLowerCase()));
      if(unique.size!==1)return null;
      id=[...unique][0];
    }else{
      id=(location.pathname+location.hash).match(new RegExp('(?:threads?|tasks?|local)/('+uuid+')(?:[/?#]|$)','i'))?.[1]?.toLowerCase();
    }
    if(!id)return null;
    const rows=[...document.querySelectorAll('[data-app-action-sidebar-thread-id]')].filter(el=>
      el.getAttribute('data-app-action-sidebar-thread-id')?.split(':').at(-1)?.toLowerCase()===id);
    if(rows.length&&!rows.some(el=>el.getAttribute('data-app-action-sidebar-thread-host-id')==='local'&&el.getAttribute('data-app-action-sidebar-thread-kind')==='local'))return null;
    return id;
  }
  function findAnchor() {
    const root=composerRoot();
    if(!root) return null;
    const buttons=[...root.querySelectorAll('button')].filter(el=>el.getBoundingClientRect().width>0);
    // 可访问名称标识控件职责，按钮正文则会随权限模式变化。
    const controls=buttons.filter(el=>/^(更改权限|Change permissions)$/.test(el.getAttribute('aria-label')?.trim()||''));
    if(controls.length)return controls.length===1?controls[0]:null;
    // 旧版没有可访问名称时，只回退已知的权限文案，不按按钮序号猜测。
    const matches=buttons.filter(el=>
      /^(完全访问|Full access|默认权限|Default permissions|Read.only|只读)$/.test(el.textContent.trim()));
    return matches.length===1?matches[0]:null;
  }
  function detach() {
    host?.remove();drawer?.remove();resizeObserver?.disconnect();
    host=button=drawer=view=anchor=resizeObserver=null;
  }
  function position() {
    if(!anchor?.isConnected||!host) return;
    const a=anchor.getBoundingClientRect(), root=anchor.closest('[data-codex-composer-root]');
    const r=root.getBoundingClientRect();
    let left=a.right+10, right=r.right-12;
    // 遇到同一行原生按钮即让出空间。只跳过紧贴权限按钮的小图标。
    for(const el of root.querySelectorAll('button')) {
      if(el===anchor)continue;
      const box=el.getBoundingClientRect();
      if(!box.width||Math.abs((box.top+box.bottom)/2-(a.top+a.bottom)/2)>15||box.left<a.right-1)continue;
      if(box.left-left<14&&box.width<=42) left=Math.max(left,box.right+8);
      else right=Math.min(right,box.left-10);
    }
    const space=right-left;
    host.style.display=space>=280?'block':'none';
    host.style.left=left+'px';host.style.top=(a.top+(a.height-28)/2)+'px';
    host.style.width=Math.min(space,340)+'px';
    if(drawer) {drawer.style.maxHeight=Math.max(200,innerHeight-80)+'px';}
  }
  function mount() {
    frame=null;
    if(disposed) return;
    const id=threadId();
    if(id!==activeThread){
      activeThread=id;snapshot=null;refreshed=Date.now();
      if(button){button.textContent='TPS — · 均值 — · 本轮 —';button.setAttribute('aria-expanded','false');}
      drawer?.remove();drawer=view=null;
    }
    const next=findAnchor();
    if(!id||!next){detach();return;}
    if(anchor===next&&host?.isConnected){position();return;}
    detach();anchor=next;
    host=document.createElement('div');host.id='context-monitor-toolbar';
    Object.assign(host.style,{position:'fixed',zIndex:'30',height:'28px',pointerEvents:'auto'});
    const shadow=host.attachShadow({mode:'open'});
    shadow.innerHTML='<style>:host{color-scheme:light dark}button{width:100%;height:28px;display:flex;align-items:center;justify-content:center;gap:8px;border:0;border-radius:7px;background:transparent;color:light-dark(#74767e,#a9abb4);font:11px -apple-system,BlinkMacSystemFont,sans-serif;white-space:nowrap;cursor:pointer;font-variant-numeric:tabular-nums}button:hover{background:light-dark(#f3f4f5,#35363c)}button:focus-visible{outline:2px solid #479de1;outline-offset:2px}b{font:500 11px ui-monospace,SFMono-Regular,monospace;color:light-dark(#383b42,#e3e4e8)}i{font-style:normal;opacity:.4}</style><button type="button" aria-label="打开 Context Monitor，查看 TPS 和会话平均速度" aria-expanded="false">TPS — · 均值 —</button>';
    button=shadow.querySelector('button');button.title='最近响应 TPS / 会话加权平均 / 本轮总耗时（含工具与等待）；点击展开';
    button.onclick=toggle;
    document.body.append(host);
    resizeObserver=new ResizeObserver(schedule);resizeObserver.observe(anchor.closest('[data-codex-composer-root]'));
    position();if(snapshot)update(snapshot);
  }
  function toggle(){
    if(!drawer){
      drawer=document.createElement('aside');drawer.id='context-monitor-drawer';
      Object.assign(drawer.style,{position:'fixed',zIndex:'100',right:'20px',top:'48px',width:'min(400px,calc(100vw - 32px))',maxHeight:'calc(100vh - 80px)',overflow:'auto',borderRadius:'18px',boxShadow:'0 12px 60px #0003'});
      drawer.setAttribute('aria-label','Context Monitor');
      const shadow=drawer.attachShadow({mode:'open'});
      const style=document.createElement('style');style.textContent=globalThis.__contextMonitorCSS+'\n.monitor{min-height:0}';shadow.append(style);
      const content=document.createElement('div');shadow.append(content);view=ContextMonitorUI.create(content);
      document.body.append(drawer);drawer.hidden=true;
    }
    drawer.hidden=!drawer.hidden;
    button?.setAttribute('aria-expanded',String(!drawer.hidden));
    if(snapshot)view.update(snapshot);
  }
  function update(s){
    mount();
    if(s.thread_id!==threadId()) return;
    snapshot=s;refreshed=Date.now();
    if(!button)return;
    const oldActive=!['completed','interrupted','unknown'].includes(s.phase)&&Date.now()-s.log_modified_at>120000;
    const latest=oldActive||s.phase==='waiting'?null:s.latest_tps;
    button.innerHTML=`<span>TPS <b>${ContextMonitorUI.rate(latest)}</b></span><i>·</i><span>均值 <b>${ContextMonitorUI.rate(s.average_tps)}</b></span><i>·</i><span>本轮 <b data-elapsed>${ContextMonitorUI.formatElapsed(ContextMonitorUI.elapsed(s))}</b></span>`;
    if(view&&!drawer.hidden)view.update(s);
  }
  function schedule(){if(!frame&&!disposed)frame=requestAnimationFrame(mount);}
  const observer=new MutationObserver(records=>{
    if(records.some(r=>r.type==='attributes'||r.type==='childList'&&[...r.addedNodes,...r.removedNodes].some(n=>
      n.nodeType===1&&n.id!=='context-monitor-toolbar'&&n.id!=='context-monitor-drawer')))schedule();
  });
  observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['data-above-composer-conversation-id','data-app-action-sidebar-thread-id','data-app-action-sidebar-thread-host-id','data-app-action-sidebar-thread-kind','data-composer-placement']});
  const key=e=>{if(e.key==='Escape'&&drawer&&!drawer.hidden){e.preventDefault();e.stopImmediatePropagation();drawer.hidden=true;button?.setAttribute('aria-expanded','false');button?.focus();}};
  // 宿主在 document 捕获阶段处理快捷键，先关闭本插件面板，避免 Escape 被宿主消费。
  window.addEventListener('keydown',key,true);
  window.addEventListener('resize',schedule);window.addEventListener('scroll',schedule,true);
  const timer=setInterval(()=>{
    mount();
    if(button&&Date.now()-refreshed>8000){button.textContent='TPS — · 监控已断开';view?.error('监控连接已断开');return;}
    if(snapshot){const el=button?.querySelector('[data-elapsed]');if(el)el.textContent=ContextMonitorUI.formatElapsed(ContextMonitorUI.elapsed(snapshot));if(drawer&&!drawer.hidden)view?.tick();}
  },1000);
  globalThis.__contextMonitor={threadId,update,status:()=>({threadId:threadId(),snapshotThreadId:snapshot?.thread_id??null,anchor:!!findAnchor(),mounted:!!host,visible:host?.style.display!=='none'&&!!host}),
    dispose(){disposed=true;observer.disconnect();clearInterval(timer);cancelAnimationFrame(frame);window.removeEventListener('keydown',key,true);window.removeEventListener('resize',schedule);window.removeEventListener('scroll',schedule,true);detach();delete globalThis.__contextMonitor;delete globalThis.__contextMonitorCSS;delete globalThis.ContextMonitorUI;}};
  mount();
})();
