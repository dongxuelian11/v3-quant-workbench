# V3 Quant Research Workbench

[简体中文](README.md) · [Windows installer](https://github.com/dongxuelian11/v3-quant-workbench/releases/tag/v1.7.2) · [Status and approved roadmap](docs/V3_REBUILD.md)

A Windows desktop for Shanghai and Shenzhen A-share research. Its Chinese-language interface connects open-source Python engines for data preparation, factors, models, daily strategies, backtests and research reports in one local workspace.

**Current version: 1.7.2, research preview.** Selected real-data and installed-application journeys have been checked; data-source and AI execution limitations remain. A complete A-share historical database or report corpus is not included. Download or import data after installation. The next daily-research workspace and reliability improvements are approved but not implemented.

## Features

| Area | Implemented capabilities |
|---|---|
| Charts and data | Stock, index and sector entry points, free providers and file imports, daily and available minute data, custom N-trading-day bars, drawing tools and multiple windows |
| Factors | Price/volume and financial factors, expressions, direction, MAD processing, standardization, optional neutralization, IC, Rank IC, grouped performance and coverage |
| Models and portfolios | Ridge, LightGBM, chronological and rolling validation, Optuna; equal, score, risk-parity and mean-variance allocation |
| Strategies and backtests | Daily trading rules, costs and execution restrictions, benchmarks, holdings and simulated trade markers for every recorded stock |
| Daily selection | Multi-strategy allocations, global holdings imports, target portfolios and consolidated rebalance lists, daily paper accounts; generating a list does not change actual holdings |
| Reports and AI | PDF/URL imports, full-text search, subscriptions, page references, optional OCR, reproduction plans, project conversations, real research tools and OpenUI forms |
| Results | Separate experiments and configuration records, comparisons, CSV/Excel, chart images and PDF preview reports |

Minute data is for charting. Training, backtests and paper accounts use daily data. There is no broker order submission.

## Install and start researching

Download `v3-quant-workbench-1.7.2-x64.exe` from the [v1.7.2 release](https://github.com/dongxuelian11/v3-quant-workbench/releases/tag/v1.7.2) for Windows x64. Python and core research dependencies are bundled. OCR models are installed on demand; AI model weights are not bundled.

1. Open or create a project from the clean startup page and specify securities and dates.
2. Download available data or import files, then inspect actual coverage.
3. Analyze factors, configure a strategy or model, and run a daily backtest.
4. Inspect benchmarks, holdings and individual trade markers; compare and export experiments.
5. For daily selection, explicitly apply the strategy, allocation and current holdings before generating a rebalance list.

Configure the AI endpoint, model and key in application settings. Research does not require AI. If a provider fails, inspect its error and cached coverage, retry or import files. A security directory is not evidence that its price history has been downloaded.

## Data and calculation conventions

- Basic CSV/Parquet price columns: `symbol,date,open,high,low,close,volume`; volume is in shares. Use exchange-qualified codes such as `SH600000` and `SZ000001`. The Shanghai Composite is `SH000001`.
- Forward-adjusted imports need `factor=adjusted_price/raw_price` to recover execution prices and share quantities. Financial records need `symbol,announcementDate,reportDate`; a quarter-end date cannot replace the publication date.
- Historical membership imports use `symbol,startDate,endDate`; industry imports use `symbol,effectiveDate,industry`. Provider snapshots take effect on their recorded dates and are not presented as complete history.
- Holdings CSV/Excel columns: `证券代码,持仓数量,可卖数量,成本价,可用资金,日期` (security, shares held, sellable shares, optional cost price, cash, date). Dates use `YYYY-MM-DD`.
- Backtests use daily signals and next-session opening execution with slippage, commission, minimum commission, historical stamp duty and trading restrictions. This is not order-book simulation; other costs follow the saved configuration.
- Projects contain configurations and experiments. Shared data, holdings, conversations and reports use local application storage. Published source and installers exclude personal projects, API keys, market datasets and report documents.

## Verification and limitations

Installed-app checks covered a real 20-page text report, OCR of image-derived pages, reproduction-plan editing and execution, comparison and native exports. All 43 trades in a six-stock real-data backtest were checked against saved dates, sides and prices. Version 1.7.2 fixed and rechecked plan refresh, preservation of unsaved edits and synchronization when reopening tabs.

This does not establish full-market data completeness, strategy effectiveness or defect-free operation:

- Online retrieval of the exact TDX microcap index `880823` failed during verification. Local TDX data and file import remain available; no different index is substituted.
- Free-provider history, memberships, industries, financial revisions and alternative datasets have source-dependent coverage. No complete research database from 2015 onward is preloaded.
- Ling read a real report and saved a plan, but also returned missing parameters and invalid references. Supervision is required. Some installed OpenUI checks replayed a real plan offline rather than proving a stable autonomous online workflow.
- Complete multi-round RD-Agent recovery and the tray menu's Stop action remain unverified. Background continuation after closing the window and return from the tray were checked.
- Closing immediately after requesting a run, before submission, may save only the plan; reopen it and explicitly run. PDF export contains metric/table previews, not all raw rows.

## Run from source

On Windows, use Node.js from `.node-version` (currently 24.16.0) and Python 3.12:

```powershell
npm ci
npm run setup:research
npm start
```

To select a Python installation:

```powershell
npm run setup:research -- --python "C:/Python312/python.exe"
```

`npm run dev` enables hot reload. `npm run build` checks types and builds the desktop. `npm run package:win` creates the installer in `artifacts/package`. The local runtime is prepared under `runtime/research-python`.

Use focused checks for calculation/persistence changes and the actual interface for UI changes. `npm test` runs the research integration suite; repeated full-suite runs are not required for small edits. See [contributing](CONTRIBUTING.md).

## Architecture and open source

The Electron/React desktop connects to one local Python research service. Engines include Qlib, Alphalens, BaoStock, AKShare, Optuna, LightGBM, scikit-learn and PydanticAI. UI components include Dockview, TanStack Table, Monaco, ECharts, KLineChart, HQChart, PDF.js and OpenUI. Reports use pdfplumber and optional RapidOCR; TDX dependencies are isolated.

Shared contracts live in `packages/contracts/src/research.ts`, the desktop entry in `apps/desktop/src/researchMain.ts`, and the research service in `apps/backend/src/v3_backend/research`.

## Project status and license

Public `main` starts a new history from the rebuilt software. Superseded development branches and releases are backed up locally by the maintainer. The [roadmap](docs/V3_REBUILD.md) separates delivered behavior from approved future work.

Licensed under [Apache-2.0](LICENSE). Upstream components and data retain their own licenses and terms; this software license does not grant redistribution rights to third-party reports or datasets.
