"""用户级 launchd 托管与可逆的 Dock 启动入口安装。"""
import copy
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen

LABELS = ('local.codex-context-monitor.server', 'local.codex-context-monitor.toolbar')
BUNDLE_ID = 'local.codex-context-monitor.launcher'


def run(args, check=True):
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(f'{args[0]} 执行失败：{result.stderr.strip()}')
    return result


def agent_specs(root, runtime, python, node, port, codex_home=None):
    commands = [[python, '-m', 'monitor.server', '--runtime', str(runtime)],
                [node, str(root/'scripts/attach.mjs'), '--runtime', str(runtime), '--port', str(port), '--persist']]
    if codex_home:
        commands[0] += ['--home', str(codex_home)]
    return [dict(Label=label, ProgramArguments=command, WorkingDirectory=str(root),
                 RunAtLoad=True, KeepAlive=True, ThrottleInterval=5, ProcessType='Background',
                 EnvironmentVariables={'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
                 StandardOutPath=str(runtime/(label.rsplit('.',1)[-1]+'.launchd.log')),
                 StandardErrorPath=str(runtime/(label.rsplit('.',1)[-1]+'.launchd.log')))
            for label,command in zip(LABELS,commands)]


def dock_path(item):
    value=item.get('tile-data',{}).get('file-data',{}).get('_CFURLString','')
    return Path(unquote(urlsplit(value).path)) if value else None


def replace_dock_entry(items, original, launcher):
    result=copy.deepcopy(items)
    existing=next((i for i,item in enumerate(result) if dock_path(item)==launcher),None)
    if existing is not None:
        return result,None
    index=next((i for i,item in enumerate(result) if dock_path(item)==original),None)
    backup={'original':copy.deepcopy(result[index])} if index is not None else {}
    tile=copy.deepcopy(result[index]) if index is not None else {'tile-type':'file-tile','tile-data':{}}
    data=tile['tile-data']
    tile.pop('book',None);data.pop('book',None)
    data.update({'file-label':'ChatGPT Monitor','bundle-identifier':BUNDLE_ID,
                 'file-data':{'_CFURLString':launcher.as_uri()+'/', '_CFURLStringType':15}})
    if index is None:result.append(tile)
    else:result[index]=tile
    return result,backup


def restore_dock_entry(items, backup, launcher):
    result=[]
    for item in items:
        if dock_path(item)!=launcher:result.append(copy.deepcopy(item))
        elif backup.get('original') is not None:result.append(copy.deepcopy(backup['original']))
    return result


def read_dock():
    return plistlib.loads(run(['defaults','export','com.apple.dock','-']).stdout.encode()).get('persistent-apps',[])


def write_dock(items):
    run(['defaults','write','com.apple.dock','persistent-apps','-array',
         *[plistlib.dumps(item).decode() for item in items]])
    run(['killall','Dock'],check=False)


def config(runtime):
    try:return json.loads((runtime/'persistence.json').read_text())
    except (OSError,ValueError):return {}


def owned(path):
    marker=path/'Contents/Resources/context-monitor-owned' if path.suffix=='.app' else path/'.context-monitor-owned'
    try:return marker.read_text()==BUNDLE_ID
    except OSError:return False


def enabled(runtime):
    return config(runtime).get('enabled') is True


def agent_target(label):
    return f'gui/{os.getuid()}/{label}'


def ensure_agents():
    for label in LABELS:
        if run(['launchctl','print',agent_target(label)],check=False).returncode:
            run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(Path.home()/'Library/LaunchAgents'/f'{label}.plist')])


def agent_status():
    result={}
    for label in LABELS:
        info=run(['launchctl','print',agent_target(label)],check=False)
        import re
        pid=re.search(r'\bpid = (\d+)',info.stdout)
        result[label.rsplit('.',1)[-1]]={'loaded':info.returncode==0,
            'running':'state = running' in info.stdout,'pid':int(pid[1]) if pid else None}
    return result


def pause():
    for label in reversed(LABELS):
        run(['launchctl','bootout',agent_target(label)],check=False)
        deadline=time.monotonic()+15
        while run(['launchctl','print',agent_target(label)],check=False).returncode==0:
            if time.monotonic()>=deadline:raise RuntimeError('监控服务尚未卸载完成：'+label)
            time.sleep(.1)


def stop_legacy(runtime):
    for filename,needle in [('toolbar.json','scripts/attach.mjs'),('server.json','-m monitor.server')]:
        try:pid=int(json.loads((runtime/filename).read_text())['pid'])
        except (OSError,ValueError,KeyError):continue
        command=run(['ps','-p',str(pid),'-o','command='],check=False).stdout
        if needle not in command or str(runtime) not in command:continue
        os.kill(pid,signal.SIGTERM)
        for _ in range(70):
            if run(['ps','-p',str(pid)],check=False).returncode:break
            time.sleep(.1)
        else:raise RuntimeError('旧监控进程没有正常退出，未强制结束')


def build_launcher(root, launcher, python, original, temporary):
    command=shlex.join([python,str(root/'scripts/manage.py'),'launch'])
    literal=command.replace('\\','\\\\').replace('"','\\"')
    source=temporary/'launcher.applescript'
    source.write_text(f'on run\n    do shell script "{literal}"\nend run\non reopen\n    run\nend reopen\n')
    run(['osacompile','-o',str(launcher),str(source)])
    info=launcher/'Contents/Info.plist'
    values=plistlib.loads(info.read_bytes())
    values.update(CFBundleIdentifier=BUNDLE_ID,CFBundleDisplayName='ChatGPT Monitor',LSUIElement=True)
    info.write_bytes(plistlib.dumps(values))
    icon=original/'Contents/Resources/app.icns'
    if icon.is_file():shutil.copy2(icon,launcher/'Contents/Resources/applet.icns')
    (launcher/'Contents/Resources/context-monitor-owned').write_text(BUNDLE_ID)
    run(['codesign','--force','--sign','-',str(launcher)])


def install(source, runtime, app, port=9222, dock=True):
    if not app.is_dir():raise ValueError('找不到桌面应用：'+str(app))
    python=shutil.which('python3');node=shutil.which('node')
    if not python or not node:raise RuntimeError('需要 Python 3 和 Node.js 22+')
    version=run([node,'-p','process.versions.node.split(".")[0]']).stdout.strip()
    if int(version)<22:raise RuntimeError('需要 Node.js 22 或更新版本')
    runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
    base=Path.home()/'Library/Application Support/Context Monitor'
    root=base/'plugin';launcher=Path.home()/'Applications/ChatGPT Monitor.app'
    for path in (root,launcher):
        if path.exists() and not owned(path):
            raise RuntimeError('目标目录已存在且不属于本插件：'+str(path))
    base.mkdir(parents=True,exist_ok=True);launcher.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='install-',dir=runtime) as temporary_name:
        temporary=Path(temporary_name);staged=temporary/'plugin';staged.mkdir()
        for name in ('monitor','scripts','ui','skills','.codex-plugin'):
            shutil.copytree(source/name,staged/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copy2(source/'README.md',staged/'README.md')
        (staged/'.context-monitor-owned').write_text(BUNDLE_ID)
        staged_launcher=temporary/'ChatGPT Monitor.app'
        build_launcher(root,staged_launcher,python,app,temporary)
        pause();stop_legacy(runtime)
        # 仅替换带所有权标记的插件副本，原应用保持原状。
        if root.exists():shutil.rmtree(root)
        shutil.move(str(staged),root)
        if launcher.exists():shutil.rmtree(launcher)
        shutil.move(str(staged_launcher),launcher)
        jobs=Path.home()/'Library/LaunchAgents';jobs.mkdir(parents=True,exist_ok=True)
        specs=agent_specs(root,runtime,python,node,port,Path(os.environ.get('CODEX_HOME',Path.home()/'.codex')))
        for spec in specs:
            job=jobs/(spec['Label']+'.plist');job.write_bytes(plistlib.dumps(spec));job.chmod(0o644)
            run(['launchctl','enable',agent_target(spec['Label'])])
        settings={'enabled':True,'root':str(root),'launcher':str(launcher),'app':str(app),'port':port,
                  'dock':dock or config(runtime).get('dock',False)}
        state=runtime/'persistence.json';state.write_text(json.dumps(settings));state.chmod(0o600)
        try:
            ensure_agents()
            if dock:
                items=read_dock();changed,backup=replace_dock_entry(items,app,launcher)
                if backup is not None and not (runtime/'dock-original.plist').exists():
                    (runtime/'dock-original.plist').write_bytes(plistlib.dumps(backup))
                if changed!=items:write_dock(changed)
        except Exception:
            pause();settings['enabled']=False;state.write_text(json.dumps(settings))
            raise
    return {**settings,'agents':agent_status()}


def disable(runtime):
    settings=config(runtime)
    if not settings:return {'enabled':False}
    pause()
    launcher=Path(settings['launcher'])
    backup=runtime/'dock-original.plist'
    if settings.get('dock') and backup.exists():
        current=read_dock();restored=restore_dock_entry(current,plistlib.loads(backup.read_bytes()),launcher)
        if current!=restored:write_dock(restored)
    for label in LABELS:(Path.home()/'Library/LaunchAgents'/f'{label}.plist').unlink(missing_ok=True)
    if owned(launcher):shutil.rmtree(launcher)
    settings['enabled']=False;(runtime/'persistence.json').write_text(json.dumps(settings))
    return {'enabled':False,'dock_restored':settings.get('dock',False)}


def launch(runtime):
    settings=config(runtime)
    if not settings.get('enabled'):raise RuntimeError('请先启用常驻模式')
    ensure_agents()
    app=Path(settings['app'])
    if not app.is_dir():raise RuntimeError('原应用已移动：'+str(app))
    processes=run(['ps','-axo','comm=']).stdout.splitlines()
    running=any(line.strip().startswith(str(app/'Contents/MacOS')+'/') for line in processes)
    if running:
        try:
            with urlopen(f'http://127.0.0.1:{settings["port"]}/json/list',timeout=2) as response:
                targets=json.load(response)
            ready=any(t.get('type')=='page' and t.get('url','').startswith('app://') for t in targets)
        except (OSError,ValueError):ready=False
        if not ready:raise RuntimeError('应用已用普通方式启动，无法补加调试参数。请正常退出后从 Dock 的 ChatGPT Monitor 重新打开。')
    run(['open','-a',str(app),'--args','--remote-debugging-address=127.0.0.1',f'--remote-debugging-port={settings["port"]}'])
    (runtime/'launcher-last-run.json').write_text(json.dumps({'at':time.time(),'app':str(app),'port':settings['port']}))
    return {'launched':True,'app':str(app),'port':settings['port']}
