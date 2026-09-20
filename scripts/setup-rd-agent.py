"""Prepare the dedicated, D-drive-backed WSL research environment."""
import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'runtime' / 'rd-agent'
DISTRO = 'V3-RD-Agent'
PYTHON = '/opt/v3-rdagent/venv312/bin/python'
ROOTFS = 'https://cdimage.ubuntu.com/ubuntu-base/releases/22.04/release/ubuntu-base-22.04.5-base-amd64.tar.gz'
CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def decode(raw):
    return raw.decode('utf-16-le' if b'\0' in raw[:300] else 'utf-8', errors='replace').strip('\ufeff\x00\r\n ')


def wsl(*arguments, check=True):
    result = subprocess.run(['wsl.exe', *arguments], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            creationflags=CREATE_NO_WINDOW)
    output = decode(result.stdout)
    if check and result.returncode:
        raise RuntimeError(output or f'WSL exited {result.returncode}')
    return result.returncode, output


def prepare(status_only=False):
    code, output = wsl('--list', '--quiet', check=False)
    installed = DISTRO in [line.strip() for line in output.splitlines()]
    if status_only:
        state = {'distribution': DISTRO, 'installed': installed, 'location': str(ROOT / 'linux')}
        if installed:
            code, result = wsl('-d', DISTRO, '--', PYTHON, '-c',
                               "import importlib.metadata,json,sys; from rdagent.app.qlib_rd_loop.quant import QuantRDLoop; from qlib.contrib.model.pytorch_general_nn import GeneralPTNN; print(json.dumps({'python':sys.version.split()[0],'rdagent':importlib.metadata.version('rdagent'),'qlib':importlib.metadata.version('pyqlib'),'nativeLoopImport':True,'nativeTrainerImport':True}))", check=False)
            state.update(ready=code == 0, runtime=result)
        else:
            state.update(ready=False, message=output if code else '尚未安装研究环境')
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return
    if not installed:
        if 'E_ACCESSDENIED' in output or 'E_ACCESS_DENIED' in output:
            raise RuntimeError(output)
        ROOT.mkdir(parents=True, exist_ok=True)
        archive = ROOT / ROOTFS.rsplit('/', 1)[1]
        if not archive.exists():
            print('下载 Ubuntu 官方最小系统至 D 盘…', flush=True)
            temporary = archive.with_suffix('.download')
            with urllib.request.urlopen(ROOTFS, timeout=60) as response, temporary.open('wb') as target:
                while chunk := response.read(1024 * 1024):
                    target.write(chunk)
            temporary.replace(archive)
        print('创建独立 WSL2 研究环境 V3-RD-Agent…', flush=True)
        _, message = wsl('--import', DISTRO, str(ROOT / 'linux'), str(archive), '--version', '2')
        print(message, flush=True)
    print('安装 RD-Agent 原生运行依赖…', flush=True)
    # Only the dedicated distro is changed. User distributions are left alone.
    script = '''set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git build-essential ca-certificates curl libgomp1 docker.io
mkdir -p /opt/v3-rdagent
test -d /opt/v3-rdagent/venv || python3 -m venv /opt/v3-rdagent/venv
/opt/v3-rdagent/venv/bin/python -m pip install --disable-pip-version-check uv
export UV_PYTHON_INSTALL_DIR=/opt/v3-rdagent/python
/opt/v3-rdagent/venv/bin/uv python install 3.12
test -d /opt/v3-rdagent/venv312 || /opt/v3-rdagent/venv/bin/uv venv --python 3.12 /opt/v3-rdagent/venv312
/opt/v3-rdagent/venv/bin/uv pip install --python /opt/v3-rdagent/venv312/bin/python torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu
/opt/v3-rdagent/venv/bin/uv pip install --python /opt/v3-rdagent/venv312/bin/python rdagent==0.8.0 pyqlib==0.9.7 sentence-transformers mlflow==3.16.0 mlflow-skinny==3.16.0 protobuf==6.33.6
'''
    result = subprocess.run(['wsl.exe', '-d', DISTRO, '-u', 'root', '--', 'bash', '-s'],
                            input=script.encode('utf-8'), creationflags=CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(f'研究依赖安装未完成，WSL退出码 {result.returncode}；可重新运行同一准备脚本继续。')
    prepare(status_only=True)


def prepare_embeddings():
    script = '''from huggingface_hub import snapshot_download
from sentence_transformers import SentenceTransformer
import json
path = '/opt/v3-rdagent/models/bge-m3'
snapshot_download('BAAI/bge-m3', local_dir=path,
    allow_patterns=['*.json', '*.model', 'pytorch_model.bin', 'README.md'],
    ignore_patterns=['onnx/*'])
model = SentenceTransformer(path, device='cpu', local_files_only=True)
model.max_seq_length = 1024
vectors = model.encode(['A-share momentum factor research', 'A-share earnings factor research'],
    normalize_embeddings=True, show_progress_bar=False)
print(json.dumps({'model':'BAAI/bge-m3','path':path,'shape':list(vectors.shape),
    'cosine':float(vectors[0] @ vectors[1])}))
'''
    result = subprocess.run(['wsl.exe', '-d', DISTRO, '--', PYTHON, '-u', '-'],
                            input=script.encode('utf-8'), creationflags=CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('本地检索模型尚未准备完成；可用 --embeddings 继续下载。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--embeddings', action='store_true')
    args = parser.parse_args()
    try:
        if args.embeddings:
            prepare_embeddings()
        else:
            prepare(args.status)
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1)
