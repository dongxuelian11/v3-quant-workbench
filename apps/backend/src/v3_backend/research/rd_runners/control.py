"""Stop one retained native run group and confirm that no live member remains."""
import json
import os
import signal
import sys
import time
from pathlib import Path


def stop(pid_path, run_id):
    import psutil
    record = json.loads(Path(pid_path).read_text())
    group = int(record['processGroupId'])
    if record['runId'] != run_id or group != int(record['pid']) or group <= 1:
        raise ValueError('研究进程记录不匹配')
    if psutil.pid_exists(group):
        process = psutil.Process(group)
        if process.status() != psutil.STATUS_ZOMBIE:
            command = process.cmdline()
            if not any(name in command for name in ('v3_backend.research.rd_runners.run','v3_backend.research.rd_runners.model_io')) or os.getpgid(group) != group:
                raise ValueError('研究进程身份已改变，不终止其他进程')

    def alive():
        found = []
        for process in psutil.process_iter(['pid', 'status']):
            try:
                if os.getpgid(process.pid) == group and process.status() != psutil.STATUS_ZOMBIE:
                    found.append(process.pid)
            except (ProcessLookupError, psutil.NoSuchProcess):
                pass
        return found

    for sig, timeout in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        if not alive():
            break
        try: os.killpg(group, sig)
        except ProcessLookupError: pass
        deadline = time.monotonic() + timeout
        while alive() and time.monotonic() < deadline:
            time.sleep(.1)
    remaining = alive()
    if remaining:
        raise RuntimeError('研究进程组尚未退出: ' + str(remaining))
    return {'stopped': True, 'runId': run_id, 'processGroupId': group, 'remainingPids': []}


if __name__ == '__main__':
    print(json.dumps(stop(sys.argv[1], sys.argv[2])))
