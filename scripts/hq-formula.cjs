// Thin offline adapter around HQChart's original TDX parser and evaluator.
// stdin: one JSON request; stdout: one JSON result. Prices are already adjusted by the caller.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadEngine() {
  const candidates = [path.join(__dirname, 'hqchart.node.js'), path.resolve(__dirname, '../node_modules/hqchart/src/jscommon/umychart.node/umychart.node.js')];
  const file = candidates.find(p => fs.existsSync(p));
  if (!file) throw new Error('未找到 HQChart 原生公式运行环境');
  const module = { exports: {} };
  vm.runInNewContext(fs.readFileSync(file, 'utf8') + '\nmodule.exports.V3={Parser:JSComplier,ChartData,HistoryData};', {
    module,
    require(name) {
      if (name !== 'request') throw new Error(`HQChart 依赖不可用：${name}`);
      return () => { throw new Error('此公式需要当前输入之外的数据，请先接入对应数据'); };
    },
    console: { log() {}, warn() {}, error() {} }, setTimeout, clearTimeout, setInterval, clearInterval,
  }, { filename: file });
  return module.exports;
}

const causalFunctions = new Set(('ABS ACOS ASIN ATAN CEILING COS EXP FLOOR INTPART LN LOG MAX MIN MOD POW ROUND ROUND2 SGN SIN SQRT TAN ' +
  'IF IFF IFN NOT BETWEEN RANGE MA EMA SMA DMA WMA EXPMA EXPMEMA MEMA TMA SUM SUMBARS COUNT EVERY EXIST LAST ' +
  'HHV LLV HHVBARS LLVBARS FINDHIGH FINDLOW FINDHIGHBARS FINDLOWBARS HOD LOD HDAY LDAY ' +
  'STD STDP VAR VARP AVEDEV DEVSQ SLOPE FORCAST WMA CROSS LONGCROSS BARSLAST BARSSINCE BARSSINCEN BARSLASTCOUNT BARSCOUNT ' +
  'FILTER VALUEWHEN REF REFV CORR COVAR ZTPRICE DTPRICE').split(/\s+/));
const repaintFunctions = new Set('BACKSET BARSNEXT REFX REFXV REFX1 REFDATE ZIG ZIGA PEAK PEAKBARS TROUGH TROUGHBARS CONST FILTERX ALIGNRIGHT FFT'.split(' '));
const repaintVariables = new Set('CURRBARSCOUNT TOTALBARSCOUNT ISLASTBAR FINANCE CAPITAL TOTALCAPITAL DYNAINFO'.split(' '));
const suppliedVariables = new Set('C CLOSE O OPEN H HIGH L LOW V VOL VOLUME AMO AMOUNT DATE YEAR MONTH DAY WEEK WEEKDAY TIME HOUR MINUTE DRAWNULL NULL'.split(' '));
const drawFunctions = /^(DRAW|STICKLINE$|PLOYLINE$|POLYLINE$|SUPERDRAWTEXT$)/;

function assess(ast, parameters) {
  const reasons = new Set(), functions = new Set(), assigned = new Set(parameters.map(p => p.name.toUpperCase()));
  function assignments(node) {
    if (!node || typeof node !== 'object') return;
    if (node.Type === 'AssignmentExpression' && node.Left?.Name) assigned.add(node.Left.Name.toUpperCase());
    for (const value of Object.values(node)) if (value && typeof value === 'object') Array.isArray(value) ? value.forEach(assignments) : assignments(value);
  }
  assignments(ast);
  const constant = node => node?.Type === 'Literal' ? node.Value
    : node?.Type === 'Identifier' ? parameters.find(p => p.name.toUpperCase() === node.Name.toUpperCase())?.value : undefined;
  function walk(node) {
    if (!node || typeof node !== 'object') return;
    if (node.Type === 'CallExpression') {
      const name = String(node.Callee?.Name || '').toUpperCase(); functions.add(name);
      if (repaintFunctions.has(name)) reasons.add(`${name} 使用后续行情或可能改写历史值`);
      else if (!causalFunctions.has(name) && !drawFunctions.test(name)) reasons.add(`${name} 的历史研究口径尚未支持`);
      if (/^REF(R?V?|A)$/.test(name)) {
        const lag = node.Arguments?.[1];
        const literal = constant(lag);
        if (typeof literal !== 'number' || literal < 0) reasons.add(`${name} 的偏移必须是已知非负数才能用于历史研究`);
      }
      if (/^(FINDHIGH|FINDLOW|FINDHIGHBARS|FINDLOWBARS|LAST)$/.test(name)) {
        for (const arg of node.Arguments.slice(1)) {
          if (!Number.isInteger(constant(arg)) || constant(arg) < 0) reasons.add(`${name} 的回看区间必须是已知非负整数才能用于历史研究`);
        }
      }
      // Drawing expressions cannot contribute numeric research output.
      if (drawFunctions.test(name)) return;
    }
    if (node.Type === 'Identifier' && !assigned.has(node.Name?.toUpperCase()) && !suppliedVariables.has(node.Name?.toUpperCase())) {
      reasons.add(repaintVariables.has(node.Name?.toUpperCase()) ? `${node.Name} 依赖末端或最新状态，不能作为历史信号` : `${node.Name} 的历史数据口径尚未提供`);
    }
    for (const [key, value] of Object.entries(node)) {
      if (key === 'Callee' || key === 'Left' || key === 'Marker') continue;
      if (value && typeof value === 'object') Array.isArray(value) ? value.forEach(walk) : walk(value);
    }
  }
  walk(ast);
  return { researchAllowed: reasons.size === 0, reasons: [...reasons], functions: [...functions], volumeUnit: '手（100股）', amountUnit: '元', priceBasis: '沿用输入行情口径' };
}

function symbolOf(symbol) {
  const s = String(symbol).toUpperCase();
  const match = /^(SH|SZ|BJ)(\d{6})$/.exec(s);
  return match ? `${match[2]}.${match[1].toLowerCase()}` : String(symbol).toLowerCase();
}

async function evaluate(request) {
  const engine = loadEngine();
  const formula = request.formula || {};
  if (typeof formula.script !== 'string' || !formula.script.trim()) throw new Error('请填写通达信公式');
  const parameters = formula.parameters || [];
  if (!Array.isArray(parameters) || parameters.some(p => !p || typeof p.name !== 'string' || !Number.isFinite(p.value))) throw new Error('公式参数需要名称和有效数值');
  // Parameters are native evaluator arguments, not string substitutions.
  const ast = engine.V3.Parser.Parse(formula.script);
  const assessment = assess(ast, parameters);
  if (request.purpose === 'research' && !assessment.researchAllowed) return { ok: false, error: assessment.reasons.join('；'), assessment };
  if (!Array.isArray(request.series) || request.series.length === 0) throw new Error('请提供需要计算的行情');
  const series = [];
  for (const source of request.series) {
    if (!Array.isArray(source.bars) || !source.bars.length) throw new Error(`${source.symbol} 没有可计算的行情`);
    const chart = new engine.V3.ChartData(); chart.Symbol = symbolOf(source.symbol);
    let previousDate = 0;
    chart.Data = source.bars.map(bar => {
      const date = Number(String(bar.date).slice(0, 10).replaceAll('-', ''));
      if (!Number.isInteger(date) || date <= previousDate) throw new Error('日线数据必须按日期递增且不重复');
      previousDate = date;
      if (['open', 'high', 'low', 'close', 'volume'].some(key => !Number.isFinite(bar[key]))) throw new Error(`${source.symbol} ${bar.date} 缺少价格或成交量`);
      return Object.assign(new engine.V3.HistoryData(), { Date: date, Open: bar.open, High: bar.high, Low: bar.low, Close: bar.close,
        Vol: bar.volume, Amount: Number.isFinite(bar.amount) ? bar.amount : null, YClose: Number.isFinite(bar.previousClose) ? bar.previousClose : null });
    });
    const result = await new Promise((resolve, reject) => {
      const instance = new engine.ScriptIndexConsole({ Name: formula.name || '自定义公式', Script: formula.script,
        Args: parameters.map(p => ({ Name: p.name, Value: p.value })),
        ErrorCallback: error => reject(new Error(error?.Message || error?.message || String(error))), FinishCallback: resolve,
        NetworkFilter: data => { data.PreventDefault = true; throw new Error(`公式需要尚未提供的数据：${data.Name || '外部数据'}`); },
      });
      instance.ExecuteScript({ HQDataType: engine.HQ_DATA_TYPE.KLINE_ID, Stock: { Name: source.name || source.symbol, Symbol: chart.Symbol },
        Period: 0, Right: 0, Request: { MaxDataCount: chart.Data.length }, Data: chart });
    });
    const outputs = (result.Out || []).filter(item => item.Type === 0 && Array.isArray(item.Data)).map(item => ({ name: item.Name, values: item.Data.map(value => typeof value === 'number' && Number.isFinite(value) ? value : null) }));
    if (formula.output && !outputs.some(item => item.name === formula.output)) throw new Error(`没有数值输出 ${formula.output}，可选：${outputs.map(item => item.name).join('、') || '无'}`);
    series.push({ symbol: source.symbol, dates: result.Date.map(d => `${String(d).slice(0, 4)}-${String(d).slice(4, 6)}-${String(d).slice(6, 8)}`), outputs,
      drawings: (result.Out || []).filter(item => item.Type !== 0), selectedOutput: formula.output || null });
  }
  // Return plain JSON values instead of objects carrying the native VM's prototypes.
  return JSON.parse(JSON.stringify({ ok: true, engine: 'HQChart 1.1.15923', assessment, series }));
}

module.exports = { evaluate, assess, loadEngine };
if (require.main === module) {
  let input = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => { input += chunk; });
  process.stdin.on('end', async () => {
    try { process.stdout.write(JSON.stringify(await evaluate(JSON.parse(input)))); }
    catch (error) { process.stdout.write(JSON.stringify({ ok: false, error: error?.Message || error?.message || String(error) })); }
  });
}
