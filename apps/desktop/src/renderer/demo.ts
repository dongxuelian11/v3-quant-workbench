import type { ModelFamily, UniverseMode } from "../../../../packages/contracts/src/index";

export const universeModes: { id: UniverseMode; name: string; detail: string }[] = [
  { id: "all-shares", name: "全部股票", detail: "全市场 · 5,184" },
  { id: "index", name: "指数成分", detail: "沪深300@2026-06-30" },
  { id: "industry", name: "行业", detail: "中信一级 / 电子" },
  { id: "concept", name: "概念", detail: "高股息 + AI 基础设施" },
  { id: "custom-symbols", name: "自定义代码", detail: "逐项解析与校验" },
  { id: "nested-condition", name: "嵌套条件", detail: "AND / OR 条件树" },
  { id: "factor-top-bottom", name: "因子头部 / 尾部 N", detail: "动量前 50" },
  { id: "saved-reference", name: "已保存引用 / 版本", detail: "UniverseVersion/demo-v12" },
  { id: "csv-tsv-import", name: "CSV/TSV 导入", detail: "预览未解析代码" }
];

export const modelFamilies: ModelFamily[] = ["LightGBM", "XGBoost", "CatBoost", "sklearn-linear", "sklearn-tree-ensemble", "PyTorch-deep", "custom-plugin"];

export const researchSeries = Array.from({ length: 72 }, (_, index) => {
  const wave = Math.sin(index / 5) * 5 + Math.cos(index / 11) * 3;
  return { date: `202${3 + Math.floor(index / 24)}-${String((index % 12) + 1).padStart(2, "0")}`, value: 3160 + index * 17 + wave * 11, benchmark: 3100 + index * 11 + Math.sin(index / 7) * 45 };
});

export const researchBars = researchSeries.map((point, index) => {
  const open = point.value + Math.sin(index * 1.7) * 22;
  const close = point.value + Math.cos(index * 1.13) * 26;
  const low = Math.min(open, close) - 18 - (index % 5) * 4;
  const high = Math.max(open, close) + 20 + (index % 7) * 3;
  const volume = 28 + ((index * 17) % 64) + Math.round(Math.abs(close - open));
  return { ...point, open: Math.round(open), close: Math.round(close), low: Math.round(low), high: Math.round(high), volume };
});

export const researchEvents = [
  { id: "evt-earnings", date: "2025-10", label: "业绩窗口", detail: "超预期 +3.2σ", available: "2025-10-29 18:02" },
  { id: "evt-rebalance", date: "2025-12", label: "月度调仓", detail: "目标权重 3.8%", available: "2025-12-31 15:05" },
  { id: "evt-ledger", date: "2026-03", label: "异常成交", detail: "Ledger L-8821", available: "2026-03-18 10:41" }
];

export const runs = [
  { id: "RUN-018", family: "LightGBM", score: "0.084", state: "BEST", duration: "04:18" },
  { id: "RUN-017", family: "XGBoost", score: "0.079", state: "COMPLETE", duration: "05:42" },
  { id: "RUN-016", family: "CatBoost", score: "0.076", state: "COMPLETE", duration: "06:11" },
  { id: "RUN-015", family: "sklearn-linear", score: "0.052", state: "COMPLETE", duration: "00:48" },
  { id: "RUN-014", family: "PyTorch-deep", score: "0.073", state: "CHECKPOINT", duration: "12:31" }
];

export const symbols = [
  ["600519.SH", "贵州茅台", "+1.28%", "0.92"], ["300750.SZ", "宁德时代", "+2.43%", "0.88"],
  ["601318.SH", "中国平安", "+0.74%", "0.81"], ["000858.SZ", "五粮液", "-0.36%", "0.77"],
  ["688981.SH", "中芯国际", "+3.12%", "0.75"], ["INVALID-X", "未解析", "—", "—"]
];

export const strategyProposal = `# Deterministic proposal · DEMO
- signal = rank(momentum_12m) * 0.65 + rank(quality) * 0.35
+ signal = rank(momentum_12m) * 0.55 + rank(quality) * 0.45
- portfolio = top_n(signal, 50).equal_weight()
+ portfolio = top_n(signal, 40).risk_parity(max_weight=0.04)`;
