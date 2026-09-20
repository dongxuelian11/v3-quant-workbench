"""Actual WSL process isolation check; no service request or training is started."""
import json
import subprocess
import time
from pathlib import Path
from v3_backend.research import rd_agent
from v3_backend.research.storage import write_json

root=Path(__file__).resolve().parents[4]/'artifacts/round4-implementation/windows-rd-cancel'
root.mkdir(parents=True,exist_ok=True)
processes=[]
try:
    for name in ('owner-a','owner-b'):
        directory=root/name;bridge=directory/'rd_bridge';bridge.mkdir(parents=True,exist_ok=True)
        write_json(bridge/'config.json',{'runId':'cancel-fixture-'+name,'action':'factor','rounds':1,'codeRepairRounds':1})
        write_json(bridge/'launch.json',{'runId':'cancel-fixture-'+name,'status':'launched'})
        process=subprocess.Popen(rd_agent.command('-m','v3_backend.research.rd_runners.run',rd_agent.linux_path(bridge)),
            stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        processes.append((directory,process))
        deadline=time.monotonic()+20
        while not (bridge/'pid.json').exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.1)
        assert (bridge/'pid.json').exists(), 'native pid registration failed'
    stopped=rd_agent.stop(processes[0][0])
    processes[0][1].wait(timeout=10)
    assert stopped['stopped'] and processes[1][1].poll() is None
    summary={'evidence':'actual WSL native entrypoints waiting for stdin, no model service call',
             'selectedGroupStopped':True,'otherResearchGroupStillRunning':True}
    write_json(root/'summary.json',summary)
    print(json.dumps(summary,indent=2))
finally:
    for directory,process in processes:
        rd_agent.stop(directory)
        process.wait(timeout=10)
        process.stdin.close()
