const pending=new Map<string,string>();
export function stageLocalHandoff(text:string,projectId?:string){const key=projectId??'global';pending.set(key,text);window.dispatchEvent(new Event('v3-local-handoff'));}
export function takeLocalHandoff(projectId?:string){const key=projectId??'global',text=pending.get(key);pending.delete(key);return text;}
