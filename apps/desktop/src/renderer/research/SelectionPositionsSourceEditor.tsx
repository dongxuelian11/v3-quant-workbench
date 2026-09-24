import React, { useEffect, useLayoutEffect, useState } from 'react';
import type { SelectionPositionsSource, SimulationAccount, SimulationAccountRef } from '../../../../../packages/contracts/src/research';
import { errorText, request } from './state';
import { PositionsEditor } from './SelectionPanel';
import './simulation.css';

export const accountKey = (ref: SimulationAccountRef) => JSON.stringify([ref.projectId ?? null, ref.accountId]);
export const accountRef = (account: SimulationAccount): SimulationAccountRef => ({ accountId: account.id, projectId: account.projectId ?? null });
export const accountLabel = (account: SimulationAccount) => `${account.name} · ${account.projectId ? `旧项目 ${account.projectId}` : '全局'} · ${account.id.slice(0, 8)}`;
export function SelectionPositionsSourceEditor({ value, onChange, saveRef, disabled = false }: {
  value: SelectionPositionsSource; onChange: (value: SelectionPositionsSource) => void;
  saveRef: React.RefObject<(() => Promise<void>) | null>; disabled?: boolean;
}) {
  const [accounts, setAccounts] = useState<SimulationAccount[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [retry, setRetry] = useState(0);
  const [snapshot, setSnapshot] = useState<SimulationAccount | null>(null);
  const selectedKey = value.kind === 'simulation' && value.accountId ? accountKey(value) : '';
  useEffect(() => {
    if (value.kind !== 'simulation') return;
    let alive = true; setLoading(true); setError(''); setSnapshot(null);
    void request<SimulationAccount[]>('simulation.accounts.list').then(async rows => {
      if (!alive) return;
      setAccounts(rows);
      if (value.accountId) {
        const current = await request<SimulationAccount>('simulation.accounts.get', { accountId: value.accountId, projectId: value.projectId ?? null });
        if (alive) setSnapshot(current);
      }
    }).catch(e => { if (alive) setError(errorText(e)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [value.kind, selectedKey, retry]);
  useLayoutEffect(() => {
    if (value.kind === 'actual') return;
    const validate = async () => {
      if (value.kind === 'simulation' && (!value.accountId || loading || error || !snapshot || accountKey(accountRef(snapshot)) !== selectedKey)) throw Error('请先选择并读取模拟账户。');
    };
    saveRef.current = validate;
    return () => { if (saveRef.current === validate) saveRef.current = null; };
  }, [value.kind, selectedKey, loading, error, snapshot, saveRef]);
  return <section className="simulation-source"><div className="r-toolbar"><label>持仓来源 <select aria-label="每日研究持仓来源" disabled={disabled} value={value.kind} onChange={e => onChange(e.target.value === 'simulation' ? { kind: 'simulation', accountId: '', projectId: null } : { kind: e.target.value as 'none' | 'actual' })}><option value="none">无持仓 · 仅研究候选</option><option value="actual">实际持仓</option><option value="simulation">模拟账户 · 只读</option></select></label>{value.kind === 'simulation' && <><select aria-label="每日研究模拟账户" disabled={disabled || loading} value={selectedKey} onChange={e => { const current = accounts.find(a => accountKey(accountRef(a)) === e.target.value); if (current) onChange({ kind: 'simulation', ...accountRef(current) }); }}><option value="">选择账户</option>{accounts.map(a => <option key={accountKey(accountRef(a))} value={accountKey(accountRef(a))}>{accountLabel(a)}</option>)}</select><button disabled={loading || disabled} onClick={() => setRetry(n => n + 1)}>重新读取</button></>}</div>
    {value.kind === 'none' && <p className="r-note">生成候选研究，无需填写现金和持仓。</p>}
    {value.kind === 'actual' && <PositionsEditor saveRef={saveRef} />}
    {value.kind === 'simulation' && <>{loading && <p role="status">正在读取账户…</p>}{error && <p role="alert">{error}</p>}{!loading && !error && !accounts.length && <p>尚无模拟账户，请先在模拟账户页创建。</p>}{snapshot && <><p className="r-note">{accountLabel(snapshot)} · 截至 {snapshot.asOfDate ?? '尚未推进'} · 版本 {snapshot.revision} · 估值 {snapshot.valuationStatus === 'known' ? '已知' : snapshot.valuationStatus === 'unavailable' ? '缺失' : '旧记录未说明'}。研究只读取此账户；交易需在账户页明确推进。使用以下账户固定绑定，页面自由方案不参与；旧仓按入场版本管理。</p>{snapshot.bindings === undefined ? <p>旧账户未记录绑定版本，来源未知；请先迁入并绑定，不采用当前自由方案。</p> : snapshot.bindings.length === 0 ? <p>此账户尚未绑定策略，请先在账户页绑定后研究。</p> : <ul>{snapshot.bindings.map(binding => <li key={binding.id}>{binding.name} · {binding.source.kind === "dailyPlan" ? "每日方案" : "项目策略"} · 来源版本 {binding.versions.find(version => version.id === binding.currentVersionId)?.sourceVersion ?? "未知"} · {(binding.allocation * 100).toFixed(2)}% · {binding.allowNewEntries ? "允许新开仓" : "已停新开仓"}</li>)}</ul>}</>}</>}
  </section>;
}
