#!/usr/bin/env node
// 通过已开启的本地 DevTools 通道推送摘要；不修改应用资源。
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const args=process.argv.slice(2);
const arg=(key,fallback)=>{const i=args.indexOf(key);return i<0?fallback:args[i+1];};
const port=Number(arg('--port','9222'));
const runtime=arg('--runtime',path.join(process.env.XDG_STATE_HOME||path.join(os.homedir(),'.local/state'),'codex-context-monitor'));
if(!Number.isInteger(port)||port<1||port>65535)throw Error('无效端口');
const probe=args.includes('--probe'),once=args.includes('--once'),persist=args.includes('--persist');
const sockets=new Map();let stop=false;
async function connect(url){
  const parsed=new URL(url);
  if(parsed.protocol!=='ws:'||!['127.0.0.1','localhost'].includes(parsed.hostname)||Number(parsed.port)!==port)throw Error('拒绝非本地 DevTools WebSocket');
  const ws=new WebSocket(url),pending=new Map();let id=0;
  await new Promise((resolve,reject)=>{const t=setTimeout(()=>{ws.close();reject(Error('连接超时'));},3000);ws.addEventListener('open',()=>{clearTimeout(t);resolve();},{once:true});ws.addEventListener('error',()=>{clearTimeout(t);reject(Error('连接失败'));},{once:true});});
  ws.addEventListener('message',e=>{const m=JSON.parse(e.data);const p=pending.get(m.id);if(p){clearTimeout(p.timer);pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);}});
  return {ws,async evaluate(expression){
    if(ws.readyState!==WebSocket.OPEN)throw Error('页面连接已关闭');
    const n=++id;
    const promise=new Promise((resolve,reject)=>{const timer=setTimeout(()=>{pending.delete(n);reject(Error('页面响应超时'));},5000);pending.set(n,{resolve,reject,timer});});
    ws.send(JSON.stringify({id:n,method:'Runtime.evaluate',params:{expression,returnByValue:true,awaitPromise:true}}));
    const result=await promise;if(result.exceptionDetails)throw Error('监控脚本执行失败');return result.result?.value;
  }};
}
const css=await fs.readFile(path.join(root,'ui/panel.css'),'utf8');
const ui=await fs.readFile(path.join(root,'ui/panel.js'),'utf8');
const inject=await fs.readFile(path.join(root,'ui/inject.js'),'utf8');
async function tick(){
  const response=await fetch(`http://127.0.0.1:${port}/json/list`,{signal:AbortSignal.timeout(2000)});
  const targets=await response.json();let results=[];
  for(const target of targets){
    if(target.type!=='page'||!target.webSocketDebuggerUrl||! /^(app|codex|file):/.test(target.url))continue;
    try{
      let conn=sockets.get(target.id);
      if(!conn||conn.ws.readyState!==WebSocket.OPEN){conn=await connect(target.webSocketDebuggerUrl);sockets.set(target.id,conn);}
      const recognized=await conn.evaluate("!!document.querySelector('[data-codex-composer-root]')");
      if(!recognized)continue;
      if(probe){results.push({target:target.id,composer:true});continue;}
      await conn.evaluate(`if(!globalThis.__contextMonitor){globalThis.__contextMonitorCSS=${JSON.stringify(css)};${ui}\n${inject}}`);
      const status=await conn.evaluate('globalThis.__contextMonitor.status()');
      results.push(status);
      if(status.threadId){
        const state=JSON.parse(await fs.readFile(path.join(runtime,'server.json'),'utf8'));
        const request=await fetch(state.url+'api/session/'+status.threadId,{signal:AbortSignal.timeout(5000)});
        if(request.ok){const data=await request.json();await conn.evaluate(`globalThis.__contextMonitor?.update(${JSON.stringify(data)})`);}
      }
    }catch(error){results.push({error:error.message});}
  }
  for(const [id,conn] of sockets)if(!targets.some(t=>t.id===id)){conn.ws.close();sockets.delete(id);}
  return results;
}
async function cleanup(){for(const conn of sockets.values()){if(!probe&&!once)try{await conn.evaluate('globalThis.__contextMonitor?.dispose()');}catch{}conn.ws.close();}sockets.clear();}
process.on('SIGTERM',()=>{stop=true;});process.on('SIGINT',()=>{stop=true;});
let reportedState=null;
function report(state){if(persist&&state!==reportedState){console.log(JSON.stringify({state}));reportedState=state;}}
try{
  let first=true,failures=0;
  do{
    if(persist){
      try{
        const state=JSON.parse(await fs.readFile(path.join(runtime,'server.json'),'utf8'));
        const response=await fetch(state.url+'health',{signal:AbortSignal.timeout(2000)});
        if(!response.ok||(await response.json()).service!=='codex-context-monitor')throw Error('服务未就绪');
      }catch{report('waiting_for_service');await new Promise(resolve=>setTimeout(resolve,2000));continue;}
    }
    try{
      const result=await tick();failures=0;
      report('connected');
      if(first||once||probe){console.log(JSON.stringify({targets:result},null,2));first=false;}
      if(probe&&!result.some(r=>r.composer))process.exitCode=3;
      if(once&&!result.some(r=>r.mounted&&r.visible))process.exitCode=3;
    }catch(error){
      failures++;
      report('waiting_for_app');
      for(const conn of sockets.values())conn.ws.close();sockets.clear();
      if(probe||once||failures===1)console.error('未发现可访问的 Codex DevTools 端口。应用尚未启用调试，未修改界面。');
      if(probe||once){process.exitCode=2;break;}
      if(!persist&&failures>=5){process.exitCode=2;break;}
    }
    if(probe||once)break;
    await new Promise(resolve=>setTimeout(resolve,2000));
    if(!persist)try {const s=JSON.parse(await fs.readFile(path.join(runtime,'server.json'),'utf8'));await fetch(s.url+'health',{signal:AbortSignal.timeout(2000)});}catch{stop=true;}
  }while(!stop);
}finally{await cleanup();}
