"""Service-free native factor execution, Torch fitting and as-of inference."""
import json
import os
import signal
import sys
from pathlib import Path
from . import protocol


def main():
    path=Path(sys.argv[1]);config=json.loads(path.read_text(encoding='utf-8-sig'))
    output=Path(config['output']);output.mkdir(parents=True,exist_ok=True)
    if os.getpgrp()!=os.getpid():os.setsid()
    protocol.write_json(path.parent/'pid.json',{'pid':os.getpid(),'processGroupId':os.getpgrp(),'runId':config['runId']})
    def cancel(*args):raise InterruptedError('原生模型计算已取消')
    signal.signal(signal.SIGTERM,cancel);signal.signal(signal.SIGINT,cancel)
    try:
        from .models import train_generated_model, predict_generated_model
        if config['operation']=='train':
            result=train_generated_model(config['codePath'],config['datasetPath'],output,
                                         config.get('modelParameters',{}),config['trainingParameters'])
        elif config['operation']=='predict':
            metadata=json.loads(Path(config['metadataPath']).read_text())
            result=predict_generated_model(config['codePath'],config['checkpointPath'],metadata,
                                           config['featuresPath'],config['asOf'],output)
        elif config['operation']=='factor':
            import pandas as pd
            from .runtime import configure
            from .factors import execute_and_check
            from rdagent.components.coder.factor_coder.factor import FactorTask, FactorFBWorkspace
            protocol.initialize(path.parent)
            work=Path('/opt/v3-rdagent/runs')/config['runId'];work.mkdir(parents=True,exist_ok=True)
            configure(work)
            folder=work/'factor-data';folder.mkdir(parents=True,exist_ok=True)
            daily=pd.read_parquet(config['factorDataPath'])
            daily.to_hdf(folder/'daily_pv.h5',key='data',mode='w')
            task=FactorTask(factor_name=config['factorId'],factor_description='retained native factor',factor_formulation='retained code')
            workspace=FactorFBWorkspace(target_task=task)
            workspace.inject_files(**{'factor.py':Path(config['codePath']).read_text()})
            values=execute_and_check(workspace,output)
            result={'status':'completed','dataPath':str(values)}
        else:raise ValueError('未知原生模型操作')
        protocol.write_json(path.parent/'result.json',result)
        return 0
    except BaseException as exc:
        protocol.write_json(path.parent/'result.json',{'status':'failed','error':str(exc),'errorType':type(exc).__name__})
        return 1


if __name__=='__main__':raise SystemExit(main())
