import type { WorkspaceState } from '../../../../../packages/contracts/src/research';
export const navigationItems=[['today','研究首页'],['quote','查看行情'],['market','市场概况'],['screener','筛选与自选'],['selection','每日选股'],['positions','实际持仓'],['data','数据中心'],['reports','研报库']] as const;
export function orderedNavigation(value:WorkspaceState['navigation']){const ids=[...new Set([...(value?.order??[]),...navigationItems.map(([id])=>id)])];return [...navigationItems].sort((a,b)=>Number(value?.pinned?.includes(b[0])??false)-Number(value?.pinned?.includes(a[0])??false)||ids.indexOf(a[0])-ids.indexOf(b[0]));}
