import type { ExperimentRef } from "../../../../../packages/contracts/src/research";
import { useEffect, useRef, useState } from "react";
import { request, useResearch } from "./state";

/** Each backend operation owns its own ID, including a schema probe before analysis. */
export function readScope() {
  const pending = new Set<string>();
  return {
    async request<T>(method: string, params: object): Promise<T> {
      const readId = crypto.randomUUID();
      pending.add(readId);
      try { return await request<T>(method, { ...params, readId }); }
      finally { pending.delete(readId); }
    },
    cancel() { for (const readId of pending) void request("reads.cancel", { readId }).catch(() => {}); }
  };
}

export function useResultExport(scope: string) {
  const s = useResearch();
  const current = useRef<{readId:string;cancelled:boolean;saving:boolean}|null>(null);
  const [busy,setBusy] = useState(false), [cancelling,setCancelling] = useState(false), [saving,setSaving] = useState(false);
  useEffect(() => { setBusy(false);setCancelling(false);setSaving(false);return () => {
    const job=current.current;
    if(job){job.cancelled=true;if(!job.saving)void request("reads.cancel",{readId:job.readId}).catch(()=>{});current.current=null;}
  }; }, [scope]);
  function cancel() {
    const job=current.current;if(!job||job.cancelled||job.saving)return;
    job.cancelled=true;setCancelling(true);
    void s.act(async()=>{await request("reads.cancel",{readId:job.readId});s.setNotice("已请求中止导出；已完成的临时输出可能保留。不会打开保存对话框。");});
  }
  function run(params:({projectId?:string;experimentId:string;table?:string;format:"csv"|"xlsx"}|{experiments:ExperimentRef[];baselineRef?:ExperimentRef;format:"csv"|"xlsx"}),suggestedName:string) {
    if(current.current)return;
    const job={readId:crypto.randomUUID(),cancelled:false,saving:false};current.current=job;
    setBusy(true);setCancelling(false);setSaving(false);
    void s.act(async()=>{
      try {
        const result=await request<{path:string}>("exports.create",{...params,readId:job.readId});
        if(job.cancelled||current.current!==job)return;
        job.saving=true;setSaving(true);
        const path=await window.v3Research!.exportFile({format:params.format,sourcePath:result.path,suggestedName});
        if(path&&!job.cancelled&&current.current===job)s.setNotice(`已导出：${path}`);
      } catch(error) {if(!job.cancelled)throw error;}
      finally {if(current.current===job){current.current=null;setBusy(false);setCancelling(false);setSaving(false);}}
    });
  }
  return {busy,cancelling,saving,cancel,run};
}
