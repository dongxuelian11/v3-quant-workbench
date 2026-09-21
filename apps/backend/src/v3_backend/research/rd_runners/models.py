"""Linux-only adapter for RD-Agent model_cls and Qlib 0.9.7 GeneralPTNN.

No model API, HTTP service, substitute estimator, or portfolio engine lives here.
Imports of Torch/Qlib are deliberately local so Windows can load the package.
"""
from pathlib import Path
import importlib.util
import inspect
import json
import sys
import time
import uuid


def train_generated_model(model_code_path, dataset_path, output, model_parameters, training_parameters):
    """Return retained prediction/event/checkpoint paths, or save a model error and raise.

    Input: date/symbol (or datetime/instrument index), numeric feature columns,
    label, partition in train/valid/test. training_parameters contains the six
    explicit segment boundaries and optional featureColumns/modelType/step_len.
    Labels crossing segment ends are excluded again, using labelEndDate when
    supplied, otherwise the input trading calendar and labelHorizon/labelMode.
    """
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    started=time.perf_counter()
    try:
        return _train(model_code_path,dataset_path,output,dict(model_parameters or {}),dict(training_parameters or {}),started)
    except Exception as exc:
        (output/'model_error.json').write_text(json.dumps({'status':'model_error','errorType':type(exc).__name__,
            'message':str(exc),'elapsedSeconds':time.perf_counter()-started},ensure_ascii=False,indent=2),encoding='utf-8')
        raise


def _train(model_code_path, dataset_path, output, model_parameters, config, started):
    import numpy as np
    import pandas as pd
    import torch
    from qlib.contrib.model.pytorch_general_nn import GeneralPTNN
    from qlib.data.dataset import DatasetH, TSDatasetH, TSDataSampler

    kind=config.get('modelType','Tabular')
    if kind not in {'Tabular','TimeSeries'}:raise ValueError('不支持此原生模型类型: '+str(kind))
    names=['train','valid']+(['test'] if config.get('testStart') or config.get('includeTest') else [])
    bounds={name:(pd.Timestamp(config[name+'Start']),pd.Timestamp(config[name+'End'])) for name in names}
    pairs=list(bounds.values())
    if any(pd.isna(v) for pair in pairs for v in pair) or any(start>end for start,end in pairs) or any(pairs[i][1]>=pairs[i+1][0] for i in range(len(pairs)-1)):
        raise ValueError('原生模型训练/验证/测试边界必须严格分离')
    frame=pd.read_parquet(dataset_path)
    if isinstance(frame.index,pd.MultiIndex):frame=frame.reset_index()
    frame=frame.rename(columns={'date':'datetime','symbol':'instrument'})
    required={'datetime','instrument','label','partition'}
    if not required.issubset(frame):raise ValueError('原生模型数据缺日期/证券/label/partition')
    frame['datetime']=pd.to_datetime(frame.datetime,errors='raise').dt.normalize()
    if frame.datetime.isna().any() or frame.instrument.isna().any() or frame.duplicated(['datetime','instrument']).any():
        raise ValueError('原生模型日期/证券缺失或重复')
    if not frame.partition.isin(bounds).all():raise ValueError('partition必须为train/valid/test')
    for partition,pair in bounds.items():
        if not frame.loc[frame.partition.eq(partition),'datetime'].between(*pair).all():raise ValueError('原生模型数据超出'+partition+'边界')
    excluded=required|{'labelEndDate'}
    columns=list(config.get('featureColumns') or [col for col in frame if col not in excluded])
    if not columns or len(set(columns))!=len(columns) or set(columns)&excluded or not set(columns).issubset(frame):
        raise ValueError('原生模型特征列无效或包含标签/分区字段')
    frame[columns+['label']]=frame[columns+['label']].apply(pd.to_numeric,errors='raise')
    frame=frame.set_index(['datetime','instrument']).sort_index()
    dates=pd.DatetimeIndex(sorted(frame.index.get_level_values(0).unique()))
    horizon=int(config.get('labelHorizon',5));mode=config.get('labelMode','next_open')
    if not 1<=horizon<=252 or mode not in {'next_open','close'}:raise ValueError('原生模型标签期限/口径无效')
    if 'labelEndDate' in frame:
        endpoints=pd.Series(pd.to_datetime(frame.labelEndDate,errors='raise').to_numpy(),index=frame.index)
        if (endpoints<frame.index.get_level_values(0)).any():raise ValueError('标签结束日期早于信号日期')
    else:
        label_end=pd.Series(dates,index=dates).shift(-(horizon+(mode=='next_open')))
        endpoints=pd.Series(frame.index.get_level_values(0).map(label_end),index=frame.index)
    partitions=frame.partition.copy()
    finite=pd.Series(np.isfinite(frame[columns]).all(axis=1),index=frame.index)
    steps=int(config.get('step_len',20)) if kind=='TimeSeries' else 1
    if steps<1:raise ValueError('时间序列窗口须为正整数')
    # Require genuine complete historical feature windows. GeneralPTNN's native
    # ffill+bfill setting then has no missing feature rows to invent.
    if kind=='TimeSeries':
        complete=finite.unstack('instrument').reindex(dates).fillna(False).rolling(steps,min_periods=steps).sum().eq(steps)
        finite=complete.stack().reindex(frame.index).fillna(False)
    learned={}
    for name in ('train','valid'):
        learned[name]=partitions.eq(name)&finite&np.isfinite(frame.label)&endpoints.le(bounds[name][1])
        if not learned[name].any():raise ValueError(name+'缺少成熟标签及完整历史特征窗口')
    numeric=frame[columns+['label']].astype('float32')

    class PreparedMixin:
        def setup(self, predict_partition=None):self.predict_partition=predict_partition;return self
        def prepare(self, segment, col_set=None, data_key=None, **kwargs):
            inference=self.predict_partition is not None
            name=self.predict_partition if inference and segment=='test' else segment
            if name not in bounds:raise ValueError('未知原生模型数据分区')
            mask=partitions.eq(name)&finite if inference else learned[name]
            if kind=='Tabular':return numeric.loc[mask].copy()
            # History may include earlier partitions' features, never a later date.
            subset=numeric[numeric.index.get_level_values(0)<=bounds[name][1]].copy()
            return TSDataSampler(subset,start=bounds[name][0],end=bounds[name][1],step_len=steps,
                flt_data=mask,fillna_type='none',dtype=np.float32)

    class TabularData(PreparedMixin,DatasetH):
        def __init__(self,predict_partition=None):self.setup(predict_partition)

    class SequenceData(PreparedMixin,TSDatasetH):
        def __init__(self,predict_partition=None):self.setup(predict_partition)

    dataset_class=SequenceData if kind=='TimeSeries' else TabularData
    code_path=Path(model_code_path).resolve()
    if not code_path.is_file():raise ValueError('缺少原生model.py文件')
    module_name='v3_native_model_'+uuid.uuid4().hex
    spec=importlib.util.spec_from_file_location(module_name,code_path)
    if spec is None or spec.loader is None:raise ValueError('无法加载原生模型代码')
    module=importlib.util.module_from_spec(spec);sys.modules[module_name]=module
    seed=int(config.get('seed',42));np.random.seed(seed);torch.manual_seed(seed)
    events=[]
    try:
        spec.loader.exec_module(module)
        native=getattr(module,'model_cls',None)
        if not isinstance(native,type) or not issubclass(native,torch.nn.Module):
            raise TypeError('原生model_cls必须是torch.nn.Module类；不替换失败模型')
        signature=inspect.signature(native);accepts_kwargs=any(p.kind==inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())
        feature_key='num_features' if 'num_features' in signature.parameters or accepts_kwargs else 'input_dim' if 'input_dim' in signature.parameters else None
        if feature_key is None:raise TypeError('原生模型构造函数不支持num_features或input_dim')
        kwargs=dict(model_parameters)
        if feature_key in kwargs and int(kwargs[feature_key])!=len(columns):raise ValueError('原生模型特征维数与数据不一致')
        kwargs[feature_key]=len(columns)
        if kind=='TimeSeries' and ('num_timesteps' in signature.parameters or accepts_kwargs):
            if 'num_timesteps' in kwargs and int(kwargs['num_timesteps'])!=steps:raise ValueError('原生模型时间窗口与数据不一致')
            kwargs['num_timesteps']=steps

        class ShapeCheckedModel(torch.nn.Module):
            def __init__(self,**parameters):super().__init__();self.native=native(**parameters)
            def forward(self,x):
                result=self.native(x)
                if not isinstance(result,torch.Tensor) or result.shape not in {(x.shape[0],),(x.shape[0],1)}:
                    raise ValueError('原生模型输出须为每样本一个预测，形状[B]或[B,1]')
                return result.reshape(-1,1)

        module.v3_model_cls=ShapeCheckedModel

        class ObservedGeneralPTNN(GeneralPTNN):
            def train_epoch(self,loader):
                self.observed_epoch=getattr(self,'observed_epoch',0)+1;self.evaluation_count=0
                began=time.perf_counter();super().train_epoch(loader)
                events.append(dict(event='train_epoch',partition='train',epoch=self.observed_epoch,elapsedSeconds=time.perf_counter()-began))
            def test_epoch(self,loader):
                began=time.perf_counter();result=super().test_epoch(loader)
                partition='train' if self.evaluation_count==0 else 'valid';self.evaluation_count+=1
                events.append(dict(event='evaluate',partition=partition,epoch=self.observed_epoch,loss=float(result[0]),metric=float(result[1]),elapsedSeconds=time.perf_counter()-began))
                return result

        allowed={'n_epochs','lr','early_stop','weight_decay','optimizer','GPU','seed'}
        training={key:config[key] for key in allowed if key in config}
        training={'n_epochs':100,'lr':.001,'early_stop':10,'weight_decay':0.,'optimizer':'adam','GPU':-1,'seed':seed,**training}
        for key in ('n_epochs','early_stop','GPU','seed'):
            training[key]=int(training[key])
        for key in ('lr','weight_decay'):
            training[key]=float(training[key])
            if not np.isfinite(training[key]):raise ValueError('训练参数须为有限数值: '+key)
        counts={name:int(mask.sum()) for name,mask in learned.items()}
        requested_batch=int(config.get('batch_size',256))
        if requested_batch<1 or int(training['n_epochs'])<1 or int(training['early_stop'])<1:raise ValueError('训练轮数/早停/批量须为正整数')
        batch=min(requested_batch,*counts.values())
        estimator=ObservedGeneralPTNN(**training,batch_size=batch,n_jobs=0,metric='loss',loss='mse',
            pt_model_uri=module_name+'.v3_model_cls',pt_model_kwargs=kwargs)
        history={};checkpoint=output/'model.pt'
        if config.get('_researchBudget'):
            from .protocol import reserve
            reserve('trainingTasks')
        estimator.fit(dataset_class(),evals_result=history,save_path=str(checkpoint))
        if not history.get('valid') or not np.isfinite(history['valid']).all():raise ValueError('原生训练验证损失非有限，模型未通过适配')
        prediction_rows=[]
        for name in (['valid','test'] if config.get('includeTest',False) else ['valid']):
            if not (partitions.eq(name)&finite).any():raise ValueError(name+'没有完整可预测特征')
            scores=estimator.predict(dataset_class(predict_partition=name))
            if not np.isfinite(scores).all():raise ValueError('原生模型产生非有限预测')
            table=scores.rename('prediction').to_frame()
            table['label']=frame.label.reindex(table.index)
            table['partition']=name
            prediction_rows.append(table.reset_index().rename(columns={'datetime':'date','instrument':'symbol'}))
        predictions_path=output/'predictions.parquet';pd.concat(prediction_rows,ignore_index=True).to_parquet(predictions_path,index=False)
        best_epoch=int(np.argmin(history['valid']))+1
        events.append(dict(event='fit_complete',epoch=len(history['valid']),bestEpoch=best_epoch,
            elapsedSeconds=time.perf_counter()-started,trainRows=counts['train'],validRows=counts['valid'],requestedBatchSize=requested_batch,
            effectiveBatchSize=batch,trainDroppedPerEpoch=counts['train']%batch,validDroppedPerEpoch=counts['valid']%batch,
            **{key:config[key] for key in config if key.endswith(('Start','End'))}))
        events_path=output/'training_events.parquet';pd.DataFrame(events).to_parquet(events_path,index=False)
        summary=dict(status='completed',engine='Qlib 0.9.7 GeneralPTNN',modelType=kind,modelCodePath=str(code_path),
            dataPath=str(predictions_path),trainingEventsPath=str(events_path),modelPath=str(checkpoint),featureColumns=columns,
            modelParameters=kwargs,trainingParameters=config,rows={name:len(table) for name,table in zip(['valid','test'],prediction_rows)},
            bestEpoch=best_epoch,epochs=len(history['valid']),elapsedSeconds=time.perf_counter()-started,
            feedbackPartition='valid',shapeAdapter='single native prediction reshaped to [B,1]',
            missingFeatures='only finite features and complete historical windows admitted',
            nativeBatchPolicy='drop_last=True; effective batch capped at train/valid sample counts; dropped tails recorded')
        (output/'model_result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        return summary
    finally:
        sys.modules.pop(module_name,None)


def predict_generated_model(code_path, checkpoint_path, metadata, features_path, as_of, output):
    """Run the retained native Torch class on as-of features, without refitting."""
    import numpy as np
    import pandas as pd
    import torch
    from qlib.data.dataset import TSDataSampler
    frame=pd.read_parquet(features_path)
    if not isinstance(frame.index,pd.MultiIndex):
        frame=frame.rename(columns={'date':'datetime','symbol':'instrument'}).set_index(['datetime','instrument'])
    frame.index=frame.index.set_names(['datetime','instrument'])
    frame=frame.sort_index();date=pd.Timestamp(as_of)
    if frame.index.duplicated().any() or frame.index.get_level_values(0).max()>date:
        raise ValueError('原生推理输入重复或含信号日之后的特征')
    if pd.Timestamp(metadata['trainingParameters']['validEnd'])>date:
        raise ValueError('不能用未来训练完成的原生模型预测历史日期')
    columns=metadata['featureColumns'];numeric=frame[columns].astype('float32')
    finite=pd.Series(np.isfinite(numeric).all(axis=1),index=frame.index)
    kind=metadata['modelType'];steps=int(metadata['trainingParameters'].get('step_len',20))
    if kind=='TimeSeries':
        complete=finite.unstack('instrument').fillna(False).rolling(steps,min_periods=steps).sum().eq(steps)
        finite=complete.stack().reindex(frame.index).fillna(False)
        sampler=TSDataSampler(numeric,start=date,end=date,step_len=steps,flt_data=finite,fillna_type='none',dtype=np.float32)
        index=sampler.get_index()
    else:
        selected=numeric[finite&(numeric.index.get_level_values(0)==date)]
        index=selected.index;sampler=selected.to_numpy(copy=True)
    if not len(index):raise ValueError('原生推理缺少当日有效特征或完整历史窗口')
    name='v3_inference_'+uuid.uuid4().hex
    spec=importlib.util.spec_from_file_location(name,code_path);module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    try:
        spec.loader.exec_module(module)
        native=module.model_cls
        if not isinstance(native,type) or not issubclass(native,torch.nn.Module):raise TypeError('model_cls不是Torch模型类')
        model=native(**metadata['modelParameters'])
        state=torch.load(checkpoint_path,map_location='cpu',weights_only=True)
        model.load_state_dict({key.removeprefix('native.'):value for key,value in state.items()},strict=True)
        model.eval();values=[]
        with torch.no_grad():
            for start in range(0,len(index),256):
                tensor=torch.tensor(np.stack([sampler[i] for i in range(start,min(start+256,len(index)))]),dtype=torch.float32)
                prediction=model(tensor)
                if prediction.shape not in {(len(tensor),),(len(tensor),1)}:raise ValueError('原生模型推理输出形状错误')
                values.extend(prediction.reshape(-1).cpu().numpy())
        if not np.isfinite(values).all():raise ValueError('原生模型推理包含非有限值')
        table=pd.DataFrame({'score':values},index=index)
        path=Path(output)/'inference.parquet';path.parent.mkdir(parents=True,exist_ok=True);table.to_parquet(path)
        return {'status':'completed','dataPath':str(path),'asOf':str(date.date()),'rows':len(table),'trained':False}
    finally:
        sys.modules.pop(name,None)
