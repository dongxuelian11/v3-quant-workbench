import type {ScreenerPlan} from '../../../../../packages/contracts/src/research';
type Editor={read:()=>ScreenerPlan|undefined;replace:(next:ScreenerPlan)=>void};
const editors=new Map<string,Editor>();
export function registerAssistantEditor(id:string,editor:Editor){editors.set(id,editor);return()=>{if(editors.get(id)===editor)editors.delete(id);};}
export function assistantDraft(id?:string){return id?editors.get(id)?.read():undefined;}
export function replaceAssistantDraft(id:string,previous:ScreenerPlan,next:ScreenerPlan){
 const editor=editors.get(id);
 if(!editor||JSON.stringify(editor.read())!==JSON.stringify(previous))throw new Error('选股草稿已变化，请重新解释后应用。');
 editor.replace(next);
}
