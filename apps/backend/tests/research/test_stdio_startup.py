"""Exercise the Windows Node-pipe startup with a local AKShare-shaped fixture."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == 'win32' and shutil.which('node'), 'Windows Node pipe regression')
class StdioStartupTests(unittest.TestCase):
    def test_members_worker_and_child_start_without_network(self):
        source = Path(__file__).resolve().parents[2] / 'src'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'akshare.py').write_text(
                "import pandas as pd\n"
                "def stock_sector_detail(**kwargs):\n"
                " return pd.DataFrame([{'symbol':'sh600000','name':'本地管道测试','trade':10,'volume':100}])\n",
                encoding='utf-8')
            # Only replace the external provider module, leaving _ak's actual
            # subprocess arguments/stdio and the server's thread pool intact.
            bootstrap = (
                'import sys,subprocess\n'
                f'sys.path.insert(0,{str(source)!r})\n'
                'original=subprocess.run\n'
                'def local_provider(args,**kwargs):\n'
                " if isinstance(args,list) and len(args)>2 and args[1]=='-c' and 'import akshare' in args[2]:\n"
                f"  args=list(args);args[2]='import sys;sys.path.insert(0,'+repr({str(root)!r})+');'+args[2]\n"
                ' return original(args,**kwargs)\n'
                'subprocess.run=local_provider\n'
                'from v3_backend.research.server import main\nmain()\n')
            script = r"""
const {spawn}=require('child_process');
const child=spawn(process.argv[1],['-u','-c',process.argv[2],'--app-data',process.argv[3]],{stdio:['pipe','pipe','pipe'],windowsHide:true});
let data=Buffer.alloc(0),errors='';
const timer=setTimeout(()=>{child.kill();console.error('RPC timed out',errors);process.exitCode=1},12000);
child.stderr.on('data',chunk=>errors+=chunk);
child.stdout.on('data',chunk=>{
 data=Buffer.concat([data,chunk]);const end=data.indexOf('\r\n\r\n');if(end<0)return;
 const length=Number(/Content-Length: (\d+)/.exec(data.subarray(0,end).toString())[1]);
 if(data.length<end+4+length)return;
 console.log(data.subarray(end+4,end+4+length).toString());clearTimeout(timer);child.stdin.end();
});
child.on('exit',code=>{clearTimeout(timer);if(code)process.exitCode=code});
const body=JSON.stringify({id:'members',method:'market.members',params:{instrument:{kind:'industry',symbol:'SINA_NEW_CBZZ'},refresh:true}});
child.stdin.write(`Content-Length: ${Buffer.byteLength(body)}\r\nContent-Type: application/json; charset=utf-8\r\n\r\n${body}`);
"""
            # Raw JS source needs literal JS escapes, not doubled escapes.
            script = script.replace('\\\\', '\\')
            result = subprocess.run([shutil.which('node'), '-e', script, sys.executable, bootstrap, str(root/'profile')],
                                    capture_output=True, text=True, encoding='utf-8', timeout=18,
                                    env={**os.environ, 'PYTHONUTF8':'1'}, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0, result.stderr)
            response = json.loads(result.stdout)
            self.assertNotIn('error', response)
            self.assertEqual(response['result']['status'], 'ready')
            self.assertEqual(response['result']['rows'][0]['name'], '本地管道测试')

