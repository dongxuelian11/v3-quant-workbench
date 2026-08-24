import React, { useEffect, useMemo, useState } from "react";
import { ProductDataWorkspace } from "./components/ProductDataWorkspace";
import { ProductBacktestWorkspace } from "./components/ProductBacktestWorkspace";
import { ProductFactorWorkspace } from "./components/ProductFactorWorkspace";
import { ProductResultsWorkspace } from "./components/ProductResultsWorkspace";
import { ProductRuntimePanel } from "./components/ProductRuntimePanel";
import { WindowControls } from "./components/WindowControls";
import { useProductRuntime } from "./productRuntimeStore";
import { productNavigationFor, selectCurrentProjectLabel } from "./productShellModel";

export function ProductApp() {
  const boundProject = useProductRuntime((state) => state.boundProject);
  const projects = useProductRuntime((state) => state.projects);
  const dataHome = useProductRuntime((state) => state.dataHome);
  const [activePage, setActivePage] = useState<"home" | "data" | "research" | "backtest" | "results">("home");
  const currentProjectLabel = selectCurrentProjectLabel(boundProject, projects?.projects ?? []);
  const navigation = useMemo(() => productNavigationFor(
    boundProject !== null
      && dataHome?.localImportState === "AVAILABLE"
      && typeof window.v3ProductRuntime?.chooseLocalDataSource === "function"
      && typeof window.v3ProductRuntime?.importLocalDataset === "function"
      && typeof window.v3ProductRuntime?.getProjectHome === "function",
    dataHome?.dataState === "AVAILABLE"
      && typeof window.v3ProductRuntime?.submitFactorStudy === "function"
      && typeof window.v3ProductRuntime?.getProjectHome === "function",
    dataHome?.factorState === "AVAILABLE"
      && typeof window.v3ProductRuntime?.publishResearchStrategy === "function"
      && typeof window.v3ProductRuntime?.submitResearchBacktest === "function",
    dataHome?.backtestState === "AVAILABLE"
      && dataHome.backtest?.resultState === "VALID"
      && typeof window.v3ProductRuntime?.getLatestProductResultDetails === "function"
  ), [boundProject, dataHome]);
  useEffect(() => {
    if (activePage !== "home" && !navigation.find((item) => item.id === activePage)?.available) setActivePage("home");
  }, [activePage, navigation]);

  return <div className="product-app-shell" data-testid="product-app-shell" data-product-mode="PRODUCT">
    <header className="product-titlebar" onDoubleClick={(event) => {
      if ((event.target as HTMLElement).closest("button")) return;
      void window.v3Desktop.windowControl("toggle-maximize");
    }}>
      <div className="product-brand" aria-label="V3 可用研究产品">
        <strong>V3</strong>
        <span>可用研究产品</span>
        <small>PRODUCT · PRE_ALPHA / RESEARCH_ONLY</small>
      </div>
      <nav aria-label="产品主导航">
        {navigation.map((item) => <button
          key={item.id}
          className={item.id === activePage ? "active" : undefined}
          aria-current={item.id === activePage ? "page" : undefined}
          disabled={!item.available}
          onClick={() => { if (item.available) setActivePage(item.id); }}
          title={item.reason ?? item.label}
          aria-label={item.reason === null ? item.label : `${item.label}，${item.reason}`}
          data-product-page={item.id}
          data-unavailable-reason={item.reason ?? undefined}
        >{item.label}{item.reason !== null && <small>NOT_AVAILABLE</small>}</button>)}
      </nav>
      <div className="product-current-project" aria-live="polite">
        <small>当前项目</small>
        <span title={boundProject?.projectId ?? "NO_CANONICAL_PROJECT_BOUND"}>
          {currentProjectLabel}
        </span>
      </div>
      <WindowControls />
    </header>

    {activePage === "home"
      ? <main className="product-home" data-product-page="home"><ProductRuntimePanel /></main>
      : activePage === "data" ? <ProductDataWorkspace />
        : activePage === "research" ? <ProductFactorWorkspace />
          : activePage === "backtest" ? <ProductBacktestWorkspace />
            : <ProductResultsWorkspace />}

    <footer className="product-truth-footer">
      <span>正式能力以 canonical backend read model 为准</span>
      <span>未接通页面保持 NOT_AVAILABLE，不使用开发数据替代</span>
    </footer>
  </div>;
}
