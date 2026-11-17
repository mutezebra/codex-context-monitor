const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const {chromium}=require('playwright-core');
const root=path.resolve(__dirname,'..');
const tid='00000000-0000-0000-0000-000000000001';
const sample={thread_id:tid,title:'布局验收样本（非真实测速）',model:'gpt-6-astra',effort:'high',phase:'running',latest_tps:108.2,average_tps:96.4,
  context_tokens:172300,context_window:840000,context_percent:20.5,cache_hit_percent:98.5,
  last:{input_tokens:171616,cached_input_tokens:169000,output_tokens:684,reasoning_output_tokens:344},
  total:{input_tokens:202000,cached_input_tokens:198970,output_tokens:4200,reasoning_output_tokens:1200,total_tokens:206200},
  measured_responses:8,responses:10,measured_seconds:40,measured_tokens:3856,ttft_ms:2800,compactions:0,bad_lines:0,
  limits:{plan_type:'plus',primary:{used_percent:72,window_minutes:300,resets_at:Date.now()/1000+3600},secondary:{used_percent:84,window_minutes:10080,resets_at:Date.now()/1000+86400}},
  log_modified_at:Date.now(),history:[60,90,82,108].map(tps=>({tps}))};
sample.turn_status='active';sample.turn_started_at=Date.now()-65000;
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_BIN||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try{
    const page=await browser.newPage({viewport:{width:440,height:1100},deviceScaleFactor:2});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    const css=await fs.readFile(path.join(root,'ui/panel.css'),'utf8');
    const ui=await fs.readFile(path.join(root,'ui/panel.js'),'utf8');
    const inject=await fs.readFile(path.join(root,'ui/inject.js'),'utf8');
    await page.route('http://monitor.test/**',r=>r.fulfill({contentType:'text/html',body:'<!doctype html><html><head><meta charset="utf-8"></head><body><main id="monitor"></main></body></html>'}));
    await page.goto('http://monitor.test/thread/'+tid);
    await page.addStyleTag({content:css});await page.addScriptTag({content:ui});
    await page.evaluate(s=>{window.view=ContextMonitorUI.create(document.querySelector('main'));view.update(s);},sample);
    assert.match(await page.locator('[data-metric="average"]').innerText(),/96.4/);
    await page.evaluate(s=>view.tick(s.turn_started_at+66000),sample);
    assert.equal(await page.locator('[data-elapsed]').innerText(),'01:06');
    await page.evaluate(s=>{view.update({...s,turn_status:'completed',duration_ms:67321});view.tick(s.turn_started_at+999000);},sample);
    assert.equal(await page.locator('[data-elapsed]').innerText(),'01:07','完成后停止增长');
    await page.evaluate(s=>view.update(s),sample);
    await page.getByRole('tab',{name:'Token 用量'}).click();
    assert.match(await page.locator('main').innerText(),/206.2k/);
    await page.evaluate(s=>view.update(s),sample);
    assert.equal(await page.evaluate(()=>document.activeElement.dataset.tab),'tokens','轮询不夺走键盘焦点');
    await page.getByRole('tab',{name:'概览'}).click();
    await fs.mkdir(path.join(root,'artifacts'),{recursive:true});
    await page.screenshot({path:path.join(root,'artifacts/panel-fixture-light.png'),fullPage:true});
    await page.emulateMedia({colorScheme:'dark'});
    await page.screenshot({path:path.join(root,'artifacts/panel-fixture-dark.png'),fullPage:true});
    await page.setViewportSize({width:320,height:950});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'窄面板不得横向溢出');
    await page.evaluate(()=>view.error('测试断线'));
    assert.match(await page.locator('[data-metric="latest"]').innerText(),/—/);
    await page.evaluate(s=>{s.title='<img src=x onerror="window.XSS=1">';view.update(s);},sample);
    assert.equal(await page.evaluate(()=>window.XSS),undefined,'会话标题应作为文字渲染');
    await page.emulateMedia({colorScheme:'light'});
    await page.setViewportSize({width:1100,height:820});
    await page.setContent('<style>body{font:14px -apple-system;background:#fafafa}[data-codex-composer-root]{position:fixed;bottom:20px;left:30px;right:30px;padding:20px;border:1px solid #ddd;border-radius:22px;background:white}.input{height:70px}.row{display:flex;align-items:center;gap:10px}button{height:32px;border:0;border-radius:18px;background:#f5f5f5;padding:0 12px;font:14px -apple-system}.end{margin-left:auto}.anchor{width:30px;padding:0}</style><div data-codex-composer-root><div class="input" contenteditable="true" role="textbox" aria-label="消息"></div><div class="row"><button>＋</button><button id="permission" onclick="window.permissionClicked=true">完全访问</button><button class="anchor">⚓</button><button class="end">GPT ▾</button><button>↑</button></div></div>');
    await page.addScriptTag({content:ui});await page.evaluate(s=>{globalThis.__contextMonitorCSS=s;},css);
    await page.evaluate(()=>document.addEventListener('keydown',e=>{if(e.key==='Escape')e.stopImmediatePropagation();},true));
    await page.addScriptTag({content:inject});
    await page.evaluate(s=>__contextMonitor.update(s),sample);
    assert.equal(await page.evaluate(()=>__contextMonitor.status().visible),true);
    const timerBefore=await page.locator('#context-monitor-toolbar [data-elapsed]').innerText();
    await page.waitForFunction(before=>document.querySelector('#context-monitor-toolbar').shadowRoot.querySelector('[data-elapsed]').textContent!==before,timerBefore,{timeout:3500});
    await page.evaluate(s=>__contextMonitor.update({...s,turn_status:'completed',duration_ms:67321}),sample);
    assert.equal(await page.locator('#context-monitor-toolbar [data-elapsed]').innerText(),'01:07');
    await page.evaluate(s=>__contextMonitor.update(s),sample);
    await page.addScriptTag({content:inject});
    assert.equal(await page.locator('#context-monitor-toolbar').count(),1,'重复注入应幂等');
    await page.getByRole('button',{name:'完全访问',exact:true}).click();
    assert.equal(await page.evaluate(()=>window.permissionClicked),true,'权限按钮必须保持可点击');
    await page.screenshot({path:path.join(root,'artifacts/toolbar-fixture.png')});
    await page.getByRole('button',{name:'打开 Context Monitor，查看 TPS 和会话平均速度'}).click();
    assert.equal(await page.locator('#context-monitor-drawer').isVisible(),true);
    await page.keyboard.press('Escape');assert.equal(await page.locator('#context-monitor-drawer').isVisible(),false);
    await page.evaluate(()=>history.pushState({},'', '/thread/00000000-0000-0000-0000-000000000002'));
    await page.waitForFunction(()=>document.querySelector('#context-monitor-toolbar').shadowRoot.textContent.includes('TPS — · 均值 —'));
    await page.evaluate(s=>__contextMonitor.update(s),sample);
    assert.equal(await page.evaluate(()=>document.querySelector('#context-monitor-toolbar').shadowRoot.querySelector('button').textContent.includes('108.2')),false,'旧会话更新必须被拒绝');
    await page.evaluate(id=>{
      history.pushState({},'', '/index.html');
      document.querySelector('[data-codex-composer-root]').setAttribute('data-composer-placement','thread');
      const row=document.createElement('div');row.id='active-thread';
      for(const [key,value] of Object.entries({'data-app-action-sidebar-thread-active':'true','data-app-action-sidebar-thread-host-id':'local','data-app-action-sidebar-thread-kind':'local','data-app-action-sidebar-thread-id':'local:'+id}))row.setAttribute(key,value);
      document.body.append(row);
    },tid);
    assert.equal(await page.evaluate(()=>__contextMonitor.threadId()),tid,'内存路由应使用真实的活动侧栏标记');
    await page.evaluate(()=>{
      const composer=document.querySelector('[data-codex-composer-root]');
      const main=document.createElement('section');main.setAttribute('data-app-shell-focus-area','main');
      composer.before(main);main.append(composer);
      const side=document.createElement('aside');side.setAttribute('data-app-shell-focus-area','right-panel');
      side.innerHTML='<div data-codex-composer-root data-composer-placement="thread" style="width:100px;position:static"><button>完全访问</button></div>';
      document.body.append(side);
    });
    assert.equal(await page.evaluate(()=>__contextMonitor.threadId()),tid,'旁聊输入框不影响主聊天会话绑定');
    await page.evaluate(s=>__contextMonitor.update(s),sample);
    await page.waitForFunction(()=>__contextMonitor.status().visible);
    await page.evaluate(()=>document.querySelector('#active-thread').setAttribute('data-app-action-sidebar-thread-host-id','remote'));
    assert.equal(await page.evaluate(()=>__contextMonitor.threadId()),null,'远端会话不得读取本地日志');
    await page.evaluate(()=>document.querySelector('#active-thread').setAttribute('data-app-action-sidebar-thread-host-id','local'));
    await page.evaluate(()=>document.querySelector('[data-codex-composer-root]').setAttribute('data-composer-placement','home'));
    assert.equal(await page.evaluate(()=>__contextMonitor.threadId()),null,'首页不得使用残留活动线程');
    await page.evaluate(()=>document.querySelector('[data-codex-composer-root]').setAttribute('data-composer-placement','thread'));
    await page.evaluate(s=>__contextMonitor.update(s),sample);
    await page.setViewportSize({width:380,height:820});
    await page.waitForFunction(()=>__contextMonitor.status().visible===false);
    await page.evaluate(()=>__contextMonitor.dispose());
    assert.equal(await page.locator('#context-monitor-toolbar').count(),0);
    await page.evaluate(()=>{document.querySelector('[data-codex-composer-root]').removeAttribute('data-codex-composer-root');document.querySelector('[data-app-shell-focus-area="right-panel"]').remove();});
    await page.addScriptTag({content:inject});
    assert.equal(await page.locator('#context-monitor-toolbar').count(),0,'未知界面不能猜测注入');
    await page.evaluate(()=>__contextMonitor.dispose());
    assert.deepEqual(errors,[]);
    console.log('PASS: 面板数值、分页、焦点、深浅色、窄宽度、断线、XSS、工具栏幂等/权限按钮/切换会话/空间不足/卸载。');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
