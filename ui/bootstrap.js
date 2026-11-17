(() => {
  const thread = new URLSearchParams(location.search).get('thread');
  let pending=false;
  const view=ContextMonitorUI.create(document.getElementById('monitor'),{refresh:poll});
  async function poll(){
    if(pending) return;
    if(!thread){view.error('请通过插件启动命令提供明确的会话 ID。');return;}
    pending=true;
    try{
      const response=await fetch('api/session/'+encodeURIComponent(thread),{signal:AbortSignal.timeout(5000)});
      if(!response.ok) throw new Error('本地会话暂时不可读');
      view.update(await response.json());
    }catch{view.error('连接中断，最后一次指标已停止更新。请确认监控服务仍在运行。');}
    finally{pending=false;}
  }
  poll();setInterval(poll,2000);
  setInterval(()=>view.tick(),1000);
})();
