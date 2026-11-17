import copy
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from monitor.autostart import agent_specs, replace_dock_entry, restore_dock_entry, launch, pause, LABELS, agent_target


class PersistenceTests(unittest.TestCase):
    def test_agents_supervise_plugins_not_desktop_app(self):
        specs=agent_specs(Path('/tmp/plugin'),Path('/tmp/state'),'/usr/bin/python3','/usr/bin/node',9222)
        self.assertEqual(len(specs),2)
        for spec in specs:
            self.assertTrue(spec['KeepAlive'])
            self.assertTrue(spec['RunAtLoad'])
            self.assertNotIn('/Applications/ChatGPT.app',str(spec['ProgramArguments']))
        worker=specs[1]['ProgramArguments']
        self.assertIn('--persist',worker)
        self.assertIn('/tmp/plugin/scripts/attach.mjs',worker)

    def test_dock_roundtrip_preserves_other_entries_and_later_changes(self):
        old={'GUID':7,'tile-data':{'file-label':'ChatGPT','file-data':{'_CFURLString':'file:///Applications/ChatGPT.app/'},'book':b'old-bookmark'},'tile-type':'file-tile'}
        other={'GUID':8,'tile-data':{'file-label':'Other'}}
        items=[other,old];before=copy.deepcopy(items)
        new,backup=replace_dock_entry(items,Path('/Applications/ChatGPT.app'),Path('/tmp/ChatGPT Monitor.app'))
        self.assertEqual(items,before)
        self.assertEqual(new[0],other)
        self.assertNotIn('book',new[1]['tile-data'])
        new.insert(0,{'new':'user-added'})
        restored=restore_dock_entry(new,backup,Path('/tmp/ChatGPT Monitor.app'))
        self.assertEqual(restored,[{'new':'user-added'},other,old])

    def test_reinstall_does_not_duplicate_dock_entry(self):
        items=[{'tile-data':{'file-data':{'_CFURLString':'file:///Applications/ChatGPT.app/'}}}]
        new,backup=replace_dock_entry(items,Path('/Applications/ChatGPT.app'),Path('/tmp/Monitor.app'))
        again,next_backup=replace_dock_entry(new,Path('/Applications/ChatGPT.app'),Path('/tmp/Monitor.app'))
        self.assertEqual(new,again)
        self.assertIsNone(next_backup)
        self.assertIsNotNone(backup)

    def test_no_dock_entry_adds_one_and_uninstall_only_removes_it(self):
        new,backup=replace_dock_entry([],Path('/Applications/ChatGPT.app'),Path('/tmp/Monitor.app'))
        self.assertEqual(len(new),1)
        plistlib.dumps(backup)
        self.assertEqual(restore_dock_entry(new+[{'user':'item'}],backup,Path('/tmp/Monitor.app')),[{'user':'item'}])

    def test_launcher_does_not_restart_running_app_without_debugging(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime=Path(folder);app=runtime/'Client.app';app.mkdir()
            (runtime/'persistence.json').write_text(json.dumps({'enabled':True,'app':str(app),'port':9222}))
            process_list=subprocess.CompletedProcess([],0,stdout=str(app/'Contents/MacOS/Client'),stderr='')
            with patch('monitor.autostart.ensure_agents'),patch('monitor.autostart.run',return_value=process_list) as command,patch('monitor.autostart.urlopen',side_effect=OSError('offline')):
                with self.assertRaisesRegex(RuntimeError,'无法补加调试参数'):launch(runtime)
                self.assertEqual(command.call_args_list[0].args[0],['ps','-axo','comm='])
                self.assertEqual(command.call_count,1,'不得退出或重启正在运行的应用')

    def test_pause_waits_for_asynchronous_launchd_unload(self):
        loaded={agent_target(label):True for label in LABELS};polls={key:0 for key in loaded}
        def command(args,check=True):
            if args[1]=='print':
                key=args[2];polls[key]+=1
                if polls[key]>=2:loaded[key]=False
                return subprocess.CompletedProcess(args,0 if loaded[key] else 3,stdout='',stderr='')
            return subprocess.CompletedProcess(args,0,stdout='',stderr='')
        with patch('monitor.autostart.run',side_effect=command),patch('monitor.autostart.time.sleep'):
            pause()
        self.assertFalse(any(loaded.values()),'卸载真正完成后才能安装同名服务')


if __name__=='__main__':unittest.main()
