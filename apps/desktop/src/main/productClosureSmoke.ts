import type { BrowserWindow } from "electron";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import type { BackendRuntimeResolution } from "./backendRuntime/runtimeResolver";
import type { BackendSupervisor } from "./backendRuntime/supervisor";

export type ProductClosureSmokePhase =
  | "create-submit"
  | "reopen-discover"
  | "provider-unavailable"
  | "v1-1-journey-a-create"
  | "v1-1-journey-a-reopen"
  | "v1-1-journey-a-visual"
  | "v1-1-journey-b-create"
  | "v1-1-journey-b-reopen";

const PRODUCT_CLOSURE_SMOKE_PHASES = new Set<ProductClosureSmokePhase>([
  "create-submit",
  "reopen-discover",
  "provider-unavailable",
  "v1-1-journey-a-create",
  "v1-1-journey-a-reopen",
  "v1-1-journey-a-visual",
  "v1-1-journey-b-create",
  "v1-1-journey-b-reopen",
]);

export function parseProductClosureSmokePhase(value: string): ProductClosureSmokePhase {
  if (PRODUCT_CLOSURE_SMOKE_PHASES.has(value as ProductClosureSmokePhase)) {
    return value as ProductClosureSmokePhase;
  }
  throw new Error("unknown product closure smoke phase: " + value);
}

export function productClosureSmokeSourceBoundary(phase: ProductClosureSmokePhase):
  | "LOCAL_USER_SUPPLIED"
  | "TEST_EXTERNAL_PROVIDER_BOUNDARY_SUCCESS"
  | "TEST_EXTERNAL_PROVIDER_BOUNDARY_UNAVAILABLE" {
  if (phase.startsWith("v1-1-journey-")) return "LOCAL_USER_SUPPLIED";
  return phase === "provider-unavailable"
    ? "TEST_EXTERNAL_PROVIDER_BOUNDARY_UNAVAILABLE"
    : "TEST_EXTERNAL_PROVIDER_BOUNDARY_SUCCESS";
}

export function productClosureSmokeRendererStoreInstance(phase: ProductClosureSmokePhase):
  | "FIRST_PROCESS"
  | "NEW_PROCESS"
  | "ISOLATED_UNAVAILABLE_PROCESS" {
  if (phase === "create-submit" || phase.endsWith("-create")) return "FIRST_PROCESS";
  if (phase === "reopen-discover" || phase.endsWith("-reopen") || phase.endsWith("-visual")) return "NEW_PROCESS";
  return "ISOLATED_UNAVAILABLE_PROCESS";
}

export interface ProductVisualMatrixCase {
  readonly width: number;
  readonly height: number;
  readonly scalePercent: 100 | 125 | 150;
}

export const PRODUCT_VISUAL_MATRIX_CASES: readonly ProductVisualMatrixCase[] = Object.freeze(
  [
    [1366, 768], [1440, 900], [1920, 1080], [2560, 1440],
  ].flatMap(([width, height]) => [100, 125, 150].map((scalePercent) => Object.freeze({
    width,
    height,
    scalePercent: scalePercent as 100 | 125 | 150,
  }))),
);

export function productVisualMatrixEvidenceClass(): "EMULATED_ELECTRON_ZOOM_NOT_PHYSICAL_WINDOWS_SCALING" {
  return "EMULATED_ELECTRON_ZOOM_NOT_PHYSICAL_WINDOWS_SCALING";
}

export interface ProductClosureSmokeOptions {
  readonly window: BrowserWindow;
  readonly startup: Promise<void>;
  readonly phase: ProductClosureSmokePhase;
  readonly outputPath: string;
  readonly runtime: BackendRuntimeResolution;
  readonly supervisor: BackendSupervisor;
  readonly electronVersion: string;
  readonly appPath: string;
  readonly resourcesPath: string;
}

interface RendererEvidence {
  readonly initialRendererState: {
    readonly lastResearch: unknown;
    readonly task: unknown;
    readonly result: unknown;
    readonly artifactDescriptor: unknown;
  };
  readonly currentRendererState: {
    readonly lastResearch: unknown;
    readonly task: {
      readonly taskId: string;
      readonly runId: string;
      readonly resultId: string | null;
      readonly outputs: Readonly<Record<string, string>>;
    } | null;
    readonly result: {
      readonly resultId: string;
      readonly backtestRunId: string;
      readonly resultArtifact: {
        readonly artifactId: string;
        readonly sha256: string;
        readonly byteSize: number;
      } | null;
    } | null;
    readonly artifactDescriptor: {
      readonly artifactId: string;
      readonly sha256: string;
      readonly byteSize: number;
    } | null;
    readonly researchDiscoveryState: string;
    readonly recoveredResearchTaskId: string | null;
    readonly surface: string;
    readonly boundProject: {
      readonly projectId: string;
      readonly projectContextRevisionId: string;
    } | null;
    readonly errorMessage: string | null;
  };
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

const RENDERER_QUERY_TIMEOUT_MS = 5_000;
const RENDERER_OPERATION_TIMEOUT_MS = 120_000;

async function executeRenderer<T>(
  window: BrowserWindow,
  source: string,
  timeoutMilliseconds = RENDERER_OPERATION_TIMEOUT_MS,
): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      window.webContents.executeJavaScript("(async () => {" + source + "\n})()", true) as Promise<T>,
      new Promise<T>((_resolve, reject) => {
        timer = setTimeout(
          () => reject(new Error(`renderer JavaScript probe timed out after ${timeoutMilliseconds} milliseconds`)),
          timeoutMilliseconds,
        );
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

async function waitForRenderer(window: BrowserWindow): Promise<void> {
  const deadline = Date.now() + 60_000;
  let lastError = "renderer did not become ready";
  while (Date.now() < deadline) {
    if (window.isDestroyed() || window.webContents.isDestroyed()) {
      throw new Error("renderer was destroyed before product closure smoke became ready");
    }
    try {
      const ready = await executeRenderer<boolean>(
        window,
        "return document.readyState === \"complete\" && typeof window.v3ProductClosureEvidence === \"function\";",
        RENDERER_QUERY_TIMEOUT_MS,
      );
      if (ready) return;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await sleep(250);
  }
  throw new Error(lastError);
}

async function waitForRecoveredRenderer(window: BrowserWindow): Promise<RendererEvidence> {
  const deadline = Date.now() + 120_000;
  let lastEvidence: RendererEvidence | null = null;
  while (Date.now() < deadline) {
    lastEvidence = await executeRenderer<RendererEvidence>(
      window,
      "return window.v3ProductClosureEvidence();",
      RENDERER_QUERY_TIMEOUT_MS,
    );
    if (lastEvidence.currentRendererState.researchDiscoveryState === "RECOVERED") {
      return lastEvidence;
    }
    if (lastEvidence.currentRendererState.researchDiscoveryState === "ERROR") {
      throw new Error(lastEvidence.currentRendererState.errorMessage ?? "renderer cold research recovery failed");
    }
    await sleep(250);
  }
  throw new Error("renderer did not automatically recover canonical research within 120 seconds");
}

async function runCreateSubmit(window: BrowserWindow): Promise<Record<string, unknown>> {
  return await executeRenderer<Record<string, unknown>>(
    window,
    "if (typeof window.v3ProductClosureRunFirst !== \"function\") throw new Error(\"renderer first-phase smoke action is unavailable\");" +
    "await window.v3ProductClosureRunFirst({" +
    "displayName: \"V1 Product Release Acceptance\"," +
    "notes: \"TEST_EXTERNAL_PROVIDER_BOUNDARY_COLD_RESTART\"," +
    "intent: { symbol: \"600519\", startDate: \"20260106\", endDate: \"20260107\" }" +
    "});" +
    "const evidence = window.v3ProductClosureEvidence();" +
    "const current = evidence.currentRendererState;" +
    "if (current.surface !== \"RESULT_AVAILABLE\" || current.lastResearch === null || current.task === null || current.result === null || current.artifactDescriptor === null) throw new Error(\"first renderer store did not reach RESULT_AVAILABLE\");" +
    "const bridge = window.v3ProductRuntime;" +
    "const status = await bridge.getProductStatus();" +
    "const projectContext = await bridge.getProjectContext();" +
    "const task = await bridge.getTask(current.task.taskId);" +
    "if (task.state !== \"SUCCEEDED\" || task.resultId === null || typeof task.outputs.BACKTEST_RUN_RESULT !== \"string\") throw new Error(\"first canonical Task is not a successful research task\");" +
    "const result = await bridge.getResult(task.resultId);" +
    "const artifactDescriptor = await bridge.getArtifactDescriptor(task.outputs.BACKTEST_RUN_RESULT);" +
    "return { phase: \"create-submit\", status, projectContext, task, result, artifactDescriptor, rendererEvidence: evidence };"
  );
}

async function runProviderUnavailable(window: BrowserWindow): Promise<Record<string, unknown>> {
  return await executeRenderer<Record<string, unknown>>(
    window,
    "if (typeof window.v3ProductClosureRunUnavailable !== \"function\") throw new Error(\"renderer provider-unavailable smoke action is unavailable\");" +
    "await window.v3ProductClosureRunUnavailable({" +
    "displayName: \"V1 Provider Unavailable Acceptance\"," +
    "notes: \"TEST_EXTERNAL_PROVIDER_BOUNDARY_UNAVAILABLE\"," +
    "intent: { symbol: \"600519\", startDate: \"20260106\", endDate: \"20260107\" }" +
    "});" +
    "const evidence = window.v3ProductClosureEvidence();" +
    "const current = evidence.currentRendererState;" +
    "if (current.surface !== \"ERROR\" || typeof current.errorMessage !== \"string\" || !current.errorMessage.includes(\"CAPABILITY_UNAVAILABLE\") || !current.errorMessage.includes(\"PROVIDER_ACQUISITION_UNAVAILABLE\")) throw new Error(\"provider-unavailable renderer error is not explicit\");" +
    "if (current.lastResearch !== null || current.task !== null || current.result !== null || current.artifactDescriptor !== null) throw new Error(\"provider-unavailable renderer exposed a successful chain\");" +
    "const bridge = window.v3ProductRuntime;" +
    "const status = await bridge.getProductStatus();" +
    "const projectContext = await bridge.getProjectContext();" +
    "const projects = await bridge.listProjects();" +
    "const tasks = await bridge.listTasks();" +
    "if (status.backendState !== \"READY\" || status.bindingState !== \"PROJECT_BOUND\") throw new Error(\"application was not usable after provider failure\");" +
    "if (!Array.isArray(tasks.tasks) || tasks.tasks.length !== 1 || tasks.hasMore !== false || tasks.nextCursor !== null) throw new Error(\"provider failure did not preserve exactly one durable failed Task\");" +
    "const failedTask = tasks.tasks[0];" +
    "const failedOutputRoles = Object.keys(failedTask.outputs);" +
    "if (failedTask.projectId !== projectContext.projectId || failedTask.operationId !== \"ProductEntryService.v1.submitResearch\" || failedTask.state !== \"FAILED\" || failedTask.resultId !== null || failedOutputRoles.length !== 1 || failedOutputRoles[0] !== \"EXECUTION_CONTEXT\" || typeof failedTask.outputs.EXECUTION_CONTEXT !== \"string\" || !failedTask.outputs.EXECUTION_CONTEXT.startsWith(\"art_sha256_\")) throw new Error(\"provider failure Task identity or terminal truth is invalid\");" +
    "if (failedTask.attempt === null || failedTask.attempt.state !== \"FAILED\" || failedTask.attempt.errorCategory !== \"INVALID_ARGUMENT\" || failedTask.attempt.reasonCode !== \"PROVIDER_ACQUISITION_UNAVAILABLE\") throw new Error(\"provider failure Task lost its exact terminal reason\");" +
    "return { phase: \"provider-unavailable\", status, projectContext, projects, tasks, failedTask, rendererEvidence: evidence, retry_later: true, successful_canonical_chain_count: 0 };"
  );
}

async function runReopenDiscover(window: BrowserWindow): Promise<Record<string, unknown>> {
  const evidence = await waitForRecoveredRenderer(window);
  return await executeRenderer<Record<string, unknown>>(
    window,
    "const evidence = window.v3ProductClosureEvidence();" +
    "const initial = evidence.initialRendererState;" +
    "if (initial.lastResearch !== null || initial.task !== null || initial.result !== null || initial.artifactDescriptor !== null) throw new Error(\"new renderer did not start with an empty research state\");" +
    "const current = evidence.currentRendererState;" +
    "if (current.lastResearch !== null || current.researchDiscoveryState !== \"RECOVERED\" || current.surface !== \"RESULT_AVAILABLE\" || current.recoveredResearchTaskId === null || current.task === null || current.result === null || current.artifactDescriptor === null) throw new Error(\"cold renderer did not recover canonical research automatically\");" +
    "const bridge = window.v3ProductRuntime;" +
    "const status = await bridge.getProductStatus();" +
    "const projectContext = await bridge.getProjectContext();" +
    "const task = await bridge.getTask(current.recoveredResearchTaskId);" +
    "if (task.state !== \"SUCCEEDED\" || task.resultId === null || typeof task.outputs.BACKTEST_RUN_RESULT !== \"string\") throw new Error(\"recovered task is not canonical successful research\");" +
    "const result = await bridge.getResult(task.resultId);" +
    "const artifactDescriptor = await bridge.getArtifactDescriptor(task.outputs.BACKTEST_RUN_RESULT);" +
    "return { phase: \"reopen-discover\", status, projectContext, task, result, artifactDescriptor, rendererEvidence: evidence, awaitedEvidence: " + JSON.stringify(evidence) + " };"
  );
}

type V11Journey = "A" | "B";

async function waitForV11Renderer(window: BrowserWindow, journey: V11Journey): Promise<void> {
  const deadline = Date.now() + 120_000;
  let lastError = "V1.1 renderer did not recover canonical owners";
  while (Date.now() < deadline) {
    try {
      const ready = await executeRenderer<boolean>(
        window,
        "if (typeof window.v3ProductV11Evidence !== \"function\") return false;" +
        "const evidence = window.v3ProductV11Evidence();" +
        "if (evidence.errorMessage !== null || evidence.surface === \"ERROR\") throw new Error(evidence.errorMessage ?? \"V1.1 renderer recovery entered ERROR\");" +
        (journey === "A"
          ? "return evidence.data !== null && evidence.factor !== null && evidence.strategy !== null && evidence.backtest?.resultState === \"VALID\" && evidence.result?.resultState === \"VALID\";"
          : "return evidence.data?.instrumentCount === 20 && evidence.factor?.aggregate?.validDates >= 20;"),
        RENDERER_QUERY_TIMEOUT_MS,
      );
      if (ready) return;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await sleep(250);
  }
  throw new Error(lastError);
}

async function runV11Journey(
  window: BrowserWindow,
  journey: V11Journey,
  mode: "create" | "reopen",
): Promise<Record<string, unknown>> {
  if (mode === "create") {
    await executeRenderer<void>(
      window,
      `const run = window.v3ProductV11RunJourney${journey};` +
      `if (typeof run !== "function") throw new Error("V1.1 Journey ${journey} renderer action is unavailable");` +
      "await run();",
    );
  } else {
    await waitForV11Renderer(window, journey);
  }
  return await executeRenderer<Record<string, unknown>>(
    window,
    "const evidence = window.v3ProductV11Evidence();" +
    "const bridge = window.v3ProductRuntime;" +
    "const status = await bridge.getProductStatus();" +
    "const projectContext = await bridge.getProjectContext();" +
    "const home = await bridge.getProjectHome();" +
    "const tasks = await bridge.listTasks({ filter: { service: \"ProductEntryService\" } });" +
    "if (status.backendState !== \"READY\" || status.bindingState !== \"PROJECT_BOUND\") throw new Error(\"V1.1 packaged journey runtime is not READY/PROJECT_BOUND\");" +
    "if (home.projectId !== projectContext.projectId || home.projectContextRevisionId !== projectContext.projectContextRevisionId) throw new Error(\"V1.1 Home/ProjectContext binding drifted\");" +
    "if (home.truth !== \"NOT_FORMAL\" || home.admission !== \"PRE_ALPHA\" || home.data?.sourceType !== \"LOCAL_USER_SUPPLIED\") throw new Error(\"V1.1 packaged journey truth boundary drifted\");" +
    (journey === "A"
      ? "if (home.data?.instrumentCount !== 1 || home.factor?.analysis.aggregate.icMean.reason !== \"CROSS_SECTION_REQUIRES_AT_LEAST_20_INSTRUMENTS\" || home.strategyState !== \"AVAILABLE\" || home.backtest?.resultState !== \"VALID\" || evidence.result?.resultState !== \"VALID\") throw new Error(\"Journey A canonical read model is incomplete\");"
      : "if (home.data?.instrumentCount !== 20 || home.factor?.analysis.aggregate.validDates < 20 || home.factor?.analysis.aggregate.icMean.status !== \"AVAILABLE\" || home.factor?.analysis.aggregate.rankIcMean.status !== \"AVAILABLE\" || home.strategyState !== \"EMPTY\" || home.backtestState !== \"EMPTY\") throw new Error(\"Journey B canonical Factor Analysis read model is incomplete\");") +
    "return { status, projectContext, home, tasks, rendererEvidence: evidence };",
  );
}

type ProductVisualPage = "home" | "data" | "research" | "backtest" | "results";

const PRODUCT_VISUAL_PAGES: readonly ProductVisualPage[] = ["home", "data", "research", "backtest", "results"];

async function probeProductVisualPage(
  window: BrowserWindow,
  page: ProductVisualPage,
): Promise<Record<string, unknown>> {
  return await executeRenderer<Record<string, unknown>>(
    window,
    `const pageId = ${JSON.stringify(page)};
const navButton = document.querySelector('header.product-titlebar button[data-product-page="' + pageId + '"]');
if (!(navButton instanceof HTMLButtonElement) || navButton.disabled) throw new Error('Product visual page is unavailable: ' + pageId);
navButton.click();
await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
const main = document.querySelector('main[data-product-page="' + pageId + '"]');
const shell = document.querySelector('.product-app-shell');
if (!(main instanceof HTMLElement) || !(shell instanceof HTMLElement)) throw new Error('Product visual page did not render: ' + pageId);
main.scrollTo({ top: 0, left: 0, behavior: 'instant' });
const visible = (element) => {
  const style = getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
};
const accessibleName = (element) => {
  const labelledBy = element.getAttribute('aria-labelledby');
  const labelled = labelledBy === null ? '' : labelledBy.split(/\\s+/).map((id) => document.getElementById(id)?.textContent ?? '').join(' ');
  const parentLabels = 'labels' in element && element.labels !== null ? [...element.labels].map((label) => label.textContent ?? '').join(' ') : '';
  return [element.getAttribute('aria-label'), labelled, parentLabels, element.textContent, element.getAttribute('title')].find((value) => (value ?? '').trim().length > 0)?.trim() ?? '';
};
const interactive = [...document.querySelectorAll('button, input, select, textarea, summary, a[href], [tabindex]')].filter((element) => visible(element) && !element.hasAttribute('disabled') && element.getAttribute('tabindex') !== '-1');
const unnamedControls = interactive.filter((element) => accessibleName(element).length === 0).map((element) => element.tagName + '.' + element.className).slice(0, 20);
const unlabelledFormControls = [...main.querySelectorAll('input, select, textarea')].filter((element) => visible(element) && element.labels?.length === 0 && !element.hasAttribute('aria-label') && !element.hasAttribute('aria-labelledby')).map((element) => element.tagName + '.' + element.className).slice(0, 20);
const clippedInteractives = interactive.filter((element) => {
  const rect = element.getBoundingClientRect();
  return rect.left < -1 || rect.right > innerWidth + 1;
}).map((element) => ({ tag: element.tagName, text: accessibleName(element).slice(0, 80), rect: element.getBoundingClientRect().toJSON() })).slice(0, 20);
const metadataSelector = 'small, code, table, th, td, .factor-row, .analysis-list > div, .product-truth-footer, .product-current-project, .product-c3-badges, .product-c3-lineage, .product-result-lineage, .product-data-lineage, .product-data-limit, .factor-lineage, .factor-chart figcaption, .action-receipt, .product-readout';
const undersizedPrimaryText = [...main.querySelectorAll('*')].filter((element) => {
  if (!visible(element) || element.matches(metadataSelector) || element.closest(metadataSelector)) return false;
  const directText = [...element.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && (node.textContent ?? '').trim().length > 0);
  return directText && Number.parseFloat(getComputedStyle(element).fontSize) < 13;
}).map((element) => ({ tag: element.tagName, className: element.className, fontSize: getComputedStyle(element).fontSize, text: (element.textContent ?? '').trim().slice(0, 100) })).slice(0, 30);
const tableFonts = [...main.querySelectorAll('table, th, td, .factor-row, .analysis-list > div')].filter(visible).map((element) => Number.parseFloat(getComputedStyle(element).fontSize));
const chartFailures = [...main.querySelectorAll('figure')].filter(visible).flatMap((figure) => {
  const failures = [];
  if ((figure.getAttribute('aria-label') ?? '').trim().length === 0 || figure.querySelector('figcaption') === null) failures.push('FIGURE_TEXT_ALTERNATIVE_MISSING');
  for (const svg of figure.querySelectorAll('svg')) if (svg.getAttribute('role') !== 'img' || ((svg.getAttribute('aria-label') ?? svg.querySelector('title')?.textContent ?? '').trim().length === 0)) failures.push('SVG_TEXT_ALTERNATIVE_MISSING');
  return failures;
});
const statuses = [...main.querySelectorAll('[role="status"], [aria-live], .truth-state')].filter(visible).map((element) => (element.textContent ?? '').trim()).filter(Boolean);
const shellRect = shell.getBoundingClientRect();
const mainStyle = getComputedStyle(main);
return {
  page: pageId,
  document_language: document.documentElement.lang,
  active_navigation: document.querySelector('header.product-titlebar button[aria-current="page"]')?.getAttribute('data-product-page') ?? null,
  viewport: { width: innerWidth, height: innerHeight, device_pixel_ratio: devicePixelRatio },
  shell: { rect: shellRect.toJSON(), client_width: shell.clientWidth, scroll_width: shell.scrollWidth, client_height: shell.clientHeight, scroll_height: shell.scrollHeight },
  main: { client_width: main.clientWidth, scroll_width: main.scrollWidth, client_height: main.clientHeight, scroll_height: main.scrollHeight, overflow_x: mainStyle.overflowX, overflow_y: mainStyle.overflowY },
  focusable_count: interactive.length,
  focus_order: interactive.map((element) => accessibleName(element).slice(0, 80)).slice(0, 80),
  unnamed_controls: unnamedControls,
  unlabelled_form_controls: unlabelledFormControls,
  horizontally_clipped_interactives: clippedInteractives,
  undersized_primary_text: undersizedPrimaryText,
  important_table_min_font_px: tableFonts.length === 0 ? null : Math.min(...tableFonts),
  chart_text_alternative_failures: chartFailures,
  textual_statuses: statuses,
  page_horizontal_scroll_available: main.scrollWidth > main.clientWidth && ['auto', 'scroll'].includes(mainStyle.overflowX),
};`,
  );
}

async function probeKeyboardNavigation(window: BrowserWindow): Promise<Record<string, unknown>> {
  const pages: Record<string, unknown>[] = [];
  await executeRenderer<void>(
    window,
    `const button = document.querySelector('header.product-titlebar button[data-product-page="home"]');
if (!(button instanceof HTMLButtonElement) || button.disabled) throw new Error('Keyboard navigation seed unavailable');
button.focus();`,
  );
  const homeFocusEvidence = await executeRenderer<Record<string, unknown>>(
    window,
    `const focused = document.activeElement;
const style = focused instanceof HTMLElement ? getComputedStyle(focused) : null;
return { requested: "home", focused_page: focused?.getAttribute('data-product-page') ?? null, focused_name: focused?.getAttribute('aria-label') ?? focused?.textContent?.trim() ?? null, focus_visible_outline: style === null ? false : style.outlineStyle !== 'none' && Number.parseFloat(style.outlineWidth) >= 2 };`,
  );
  window.webContents.sendInputEvent({ type: "rawKeyDown", keyCode: "Return" });
  window.webContents.sendInputEvent({ type: "char", keyCode: "\r" });
  window.webContents.sendInputEvent({ type: "keyUp", keyCode: "Return" });
  await sleep(100);
  const homeActivationEvidence = await executeRenderer<Record<string, unknown>>(
    window,
    `return { active: document.querySelector('header.product-titlebar button[aria-current="page"]')?.getAttribute('data-product-page') ?? null };`,
  );
  pages.push({ ...homeFocusEvidence, ...homeActivationEvidence });
  for (const page of ["data", "research", "backtest", "results"] as const) {
    window.webContents.sendInputEvent({ type: "keyDown", keyCode: "Tab" });
    window.webContents.sendInputEvent({ type: "keyUp", keyCode: "Tab" });
    await sleep(50);
    const focusEvidence = await executeRenderer<Record<string, unknown>>(
      window,
      `const focused = document.activeElement;
const style = focused instanceof HTMLElement ? getComputedStyle(focused) : null;
return { requested: ${JSON.stringify(page)}, focused_page: focused?.getAttribute('data-product-page') ?? null, focused_name: focused?.getAttribute('aria-label') ?? focused?.textContent?.trim() ?? null, focus_visible_outline: style === null ? false : style.outlineStyle !== 'none' && Number.parseFloat(style.outlineWidth) >= 2 };`,
    );
    window.webContents.sendInputEvent({ type: "rawKeyDown", keyCode: "Return" });
    window.webContents.sendInputEvent({ type: "char", keyCode: "\r" });
    window.webContents.sendInputEvent({ type: "keyUp", keyCode: "Return" });
    await sleep(100);
    const activationEvidence = await executeRenderer<Record<string, unknown>>(
      window,
      `return { active: document.querySelector('header.product-titlebar button[aria-current="page"]')?.getAttribute('data-product-page') ?? null };`,
    );
    pages.push({ ...focusEvidence, ...activationEvidence });
  }
  return { input_method: "ELECTRON_SEND_INPUT_EVENT_ENTER", pages };
}

async function captureProductVisualMatrix(
  window: BrowserWindow,
  outputPath: string,
): Promise<Record<string, unknown>> {
  await waitForV11Renderer(window, "A");
  const outputDirectory = join(dirname(outputPath), "Visual Matrix");
  await mkdir(outputDirectory, { recursive: true });
  window.webContents.setBackgroundThrottling(false);
  const captures: Record<string, unknown>[] = [];
  for (const matrixCase of PRODUCT_VISUAL_MATRIX_CASES) {
    window.webContents.setZoomFactor(1);
    window.setContentSize(matrixCase.width, matrixCase.height, false);
    window.webContents.setZoomFactor(matrixCase.scalePercent / 100);
    await sleep(250);
    for (const page of PRODUCT_VISUAL_PAGES) {
      const audit = await probeProductVisualPage(window, page);
      const filename = `${page}-${matrixCase.width}x${matrixCase.height}-${matrixCase.scalePercent}.png`;
      const screenshotPath = join(outputDirectory, filename);
      const image = await window.webContents.capturePage();
      if (image.isEmpty()) throw new Error(`Product visual screenshot is empty: ${filename}`);
      await writeFile(screenshotPath, image.toPNG());
      captures.push({ matrix_case: matrixCase, screenshot_path: screenshotPath, screenshot_size: image.getSize(), audit });
    }
  }
  window.webContents.setZoomFactor(1);
  window.setContentSize(1366, 768, false);
  window.show();
  window.webContents.focus();
  await sleep(250);
  const keyboard = await probeKeyboardNavigation(window);
  window.hide();
  const failures: string[] = [];
  for (const capture of captures) {
    const audit = capture.audit as Record<string, unknown>;
    const shell = audit.shell as { client_width: number; scroll_width: number };
    if (shell.scroll_width > shell.client_width + 1) failures.push(`${audit.page}:SHELL_HORIZONTAL_OVERFLOW`);
    for (const key of ["unnamed_controls", "unlabelled_form_controls", "horizontally_clipped_interactives", "undersized_primary_text", "chart_text_alternative_failures"] as const) {
      if ((audit[key] as unknown[]).length > 0) failures.push(`${audit.page}:${key}`);
    }
    const minimumTableFont = audit.important_table_min_font_px;
    if (typeof minimumTableFont === "number" && minimumTableFont < 12) failures.push(`${audit.page}:IMPORTANT_TABLE_FONT_LT_12`);
  }
  for (const page of keyboard.pages as Array<Record<string, unknown>>) {
    if (page.active !== page.requested) failures.push(`${page.requested}:KEYBOARD_ACTIVATION_FAILED`);
    if (page.focus_visible_outline !== true) failures.push(`${page.requested}:FOCUS_NOT_VISIBLE`);
  }
  return {
    evidence_class: productVisualMatrixEvidenceClass(),
    physical_windows_scaling: "NOT_RUN",
    user_visual_acceptance: "PENDING_USER_REVIEW",
    output_directory: outputDirectory,
    matrix_case_count: PRODUCT_VISUAL_MATRIX_CASES.length,
    page_count_per_case: PRODUCT_VISUAL_PAGES.length,
    screenshot_count: captures.length,
    keyboard,
    failures: [...new Set(failures)],
    machine_baseline: failures.length === 0 ? "PASS" : "FAIL",
    captures,
  };
}

async function writeEvidence(path: string, evidence: Record<string, unknown>): Promise<void> {
  await mkdir(path.substring(0, Math.max(path.lastIndexOf("\\"), path.lastIndexOf("/"))), { recursive: true });
  await writeFile(path, JSON.stringify(evidence, null, 2) + "\n", "utf8");
}

export async function runProductClosureSmoke(options: ProductClosureSmokeOptions): Promise<void> {
  if (!options.outputPath || !/^[A-Za-z]:[\\/]/.test(options.outputPath)) {
    throw new Error("V3_PRODUCT_CLOSURE_SMOKE_OUTPUT must be an absolute Windows path");
  }
  const phase = parseProductClosureSmokePhase(options.phase);
  const baseEvidence: Record<string, unknown> = {
    schema_version: "v3.product-closure-packaged-e2e/1.0.0",
    success: false,
    phase,
    process_id: process.pid,
    app_is_packaged: true,
    electron_version: options.electronVersion,
    app_path: options.appPath,
    resources_path: options.resourcesPath,
    backend_runtime_mode: options.runtime.mode,
    backend_executable: options.runtime.executable,
    backend_working_directory: options.runtime.workingDirectory,
    backend_resource_root: options.runtime.backendResourceRoot,
    backend_python_root: options.runtime.pythonRoot,
    backend_pid: options.supervisor.backendPid,
    build_manifest_id: options.runtime.buildManifestId,
    resource_manifest_sha256: options.runtime.manifestSha256
  };
  try {
    await options.startup;
    await waitForRenderer(options.window);
    const flow = phase === "create-submit"
      ? await runCreateSubmit(options.window)
      : phase === "reopen-discover"
        ? await runReopenDiscover(options.window)
        : phase === "provider-unavailable"
          ? await runProviderUnavailable(options.window)
          : phase === "v1-1-journey-a-create"
            ? await runV11Journey(options.window, "A", "create")
            : phase === "v1-1-journey-a-reopen"
              ? await runV11Journey(options.window, "A", "reopen")
              : phase === "v1-1-journey-a-visual"
                ? await captureProductVisualMatrix(options.window, options.outputPath)
              : phase === "v1-1-journey-b-create"
                ? await runV11Journey(options.window, "B", "create")
                : await runV11Journey(options.window, "B", "reopen");
    await writeEvidence(options.outputPath, {
      ...baseEvidence,
      success: true,
      flow,
      shutdown_expected: "GRACEFUL_SHUTDOWN_REQUIRED",
      known_id_injection: false,
      renderer_store_instance: productClosureSmokeRendererStoreInstance(phase),
      provider_boundary: productClosureSmokeSourceBoundary(phase),
      source_truth_ceiling: "PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE"
    });
    console.error(JSON.stringify({ level: "INFO", code: "PRODUCT_CLOSURE_PACKAGED_SMOKE_PASS", phase }));
  } catch (error) {
    await writeEvidence(options.outputPath, {
      ...baseEvidence,
      error: error instanceof Error ? error.message : String(error)
    });
    throw error;
  }
}
