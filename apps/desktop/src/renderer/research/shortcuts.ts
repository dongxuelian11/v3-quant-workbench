export const defaultShortcuts={commandSearch:"Ctrl+K",settings:"Ctrl+,",sidebar:"Ctrl+B",assistant:"Ctrl+Alt+A",quoteList:"Ctrl+Alt+L"};
export type ShortcutAction=keyof typeof defaultShortcuts;
export const shortcutLabels:Record<ShortcutAction,string>={commandSearch:"搜索／命令",settings:"打开设置",sidebar:"项目侧栏",assistant:"研究助手栏",quoteList:"当前行情证券列表"};
export function eventShortcut(event:Pick<KeyboardEvent,'key'|'ctrlKey'|'altKey'|'shiftKey'|'metaKey'>):string {
  if(['Control','Alt','Shift','Meta','Dead','Unidentified'].includes(event.key))return '';
  const key=event.key===' '?'Space':event.key==='+'?'Plus':event.key.length===1?event.key.toUpperCase():event.key;
  return [...(event.ctrlKey?['Ctrl']:[]),...(event.altKey?['Alt']:[]),...(event.shiftKey?['Shift']:[]),...(event.metaKey?['Meta']:[]),key].join('+');
}
export function matchesShortcut(event:KeyboardEvent,binding:string|undefined){return !!binding&&eventShortcut(event).toLowerCase()===binding.toLowerCase();}
export function shortcutTargetBlocked(event:KeyboardEvent){return event.defaultPrevented||event.repeat||event.isComposing||!!(event.target as HTMLElement|null)?.closest('input,textarea,select,[contenteditable=true],dialog,[role=dialog]');}
export function shortcutConflicts(bindings:Record<ShortcutAction,string>):string[] {
  const seen=new Map<string,string>(),messages:string[]=[];
  for(const [action,binding] of Object.entries(bindings)){if(!binding)continue;const normalized=binding.toLowerCase();const label=shortcutLabels[action as ShortcutAction];if(seen.has(normalized))messages.push(`${label}与${seen.get(normalized)}使用相同快捷键。`);else seen.set(normalized,label);if(!/^(ctrl|alt|meta)\+/i.test(binding))messages.push(`${label}需要包含 Ctrl、Alt 或 Meta，避免占用普通输入。`);if(['alt+f4','ctrl+r','ctrl+w','ctrl+shift+i','ctrl+shift+j','ctrl+plus','ctrl+shift+plus','ctrl+-','ctrl+0'].includes(normalized))messages.push(`${label}与窗口或浏览器操作冲突，请改用其他组合。`);}
  return messages;
}
