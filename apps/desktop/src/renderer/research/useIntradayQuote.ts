import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import type { IntradayPeriod, QuoteInstrument, QuoteStatus } from "../../../../../packages/contracts/src/research";
import { errorText, request } from "./state";

const flights = new Map<string, Promise<QuoteStatus>>();
export function readIntraday(instrument: QuoteInstrument, period: IntradayPeriod, refresh: boolean, autoRefresh=false, refreshIntervalSeconds=60) {
  const key = `${instrument.kind}:${instrument.symbol}:${period}:${refresh}:${autoRefresh}:${refreshIntervalSeconds}`;
  const existing = flights.get(key);
  if (existing) return existing;
  const promise = request<QuoteStatus>("market.intraday", { instrument, period, refresh, autoRefresh, refreshIntervalSeconds, limit:500 }).finally(() => { if (flights.get(key) === promise) flights.delete(key); });
  flights.set(key, promise);
  return promise;
}
export function useChartVisible(node: RefObject<HTMLElement | null>) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    let mounted = true, intersecting = false, nativeVisible = true;
    const update = () => { if (mounted) setVisible(intersecting && nativeVisible && document.visibilityState === "visible"); };
    const observer = new IntersectionObserver(entries => { intersecting = entries.some(entry => entry.isIntersecting); update(); });
    if (node.current) observer.observe(node.current);
    const off = window.v3Research?.workspace?.onChanged(event => { if (event.method === "window.visibility") { nativeVisible = event.params?.visible === true && event.params?.minimized !== true; update(); } });
    void window.v3Research?.workspace?.current().then(value => { nativeVisible = value.visible !== false && value.minimized !== true; update(); }).catch(() => { nativeVisible = false; update(); });
    document.addEventListener("visibilitychange", update);
    return () => { mounted = false; observer.disconnect(); off?.(); document.removeEventListener("visibilitychange", update); };
  }, [node]);
  return visible;
}
export function tradingHours() {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Shanghai", weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date());
  const part = (type: string) => parts.find(p => p.type === type)?.value ?? "";
  const minutes = Number(part("hour")) * 60 + Number(part("minute"));
  return !["Sat", "Sun"].includes(part("weekday")) && (minutes >= 570 && minutes <= 690 || minutes >= 780 && minutes <= 900);
}
export function useIntradayQuote(instrument: QuoteInstrument, period: IntradayPeriod, visible: boolean, paused: boolean, intervalSeconds = 60) {
  const [quote, setQuote] = useState<QuoteStatus | null>(null), [error, setError] = useState("");
  const [loading, setLoading] = useState(false), [autoFailed,setAutoFailed]=useState(false);
  const generation = useRef(0), busy = useRef(false), failedKey=useRef<string|null>(null);
  const key = `${instrument.kind}:${instrument.symbol}:${period}`;
  const refresh = useCallback(async (remote = true,automatic=false) => {
    if (busy.current) return;
    const version = generation.current; busy.current = true; setLoading(true); setError("");
    try { const next = await readIntraday(instrument, period, remote,automatic,intervalSeconds); if (version === generation.current) { setQuote(previous => next.bars.length || !previous ? next : { ...next, bars: previous.bars, coverage: previous.coverage }); if (next.status === "source_error") setError(next.message ?? "分钟行情来源暂不可用");if(remote){failedKey.current=next.status==="ready"?null:key;setAutoFailed(next.status!=="ready");} } }
    catch (e) { if (version === generation.current) {setError(errorText(e));if(remote){failedKey.current=key;setAutoFailed(true);}} }
    finally { if (version === generation.current) { busy.current = false; setLoading(false); } }
  }, [key,intervalSeconds]);
  useEffect(() => { generation.current++; busy.current = false;failedKey.current=null; setQuote(null); setError(""); setLoading(false);setAutoFailed(false); return () => { generation.current++; }; }, [key]);
  useEffect(() => { if (visible && failedKey.current!==key) void refresh(!paused,true); }, [key,visible,paused,refresh]);
  useEffect(() => { if (!visible||paused||autoFailed) return;const timer=setInterval(()=>{if(tradingHours())void refresh(true,true);},Math.max(15,intervalSeconds)*1000);return()=>clearInterval(timer); },[key,visible,paused,intervalSeconds,refresh,autoFailed]);
  return { quote, error, loading, refresh, autoFailed };
}
