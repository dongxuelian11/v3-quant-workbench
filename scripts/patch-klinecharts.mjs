// KLineChart 10.0.3: distinct fast clicks must not disappear in the double-click branch.
// Source: EventHandlerImp._mouseUpHandler; retain native double-click and drag behavior.
import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const root = resolve(import.meta.dirname, '..');
export async function patchKlinecharts() {
  const folder = resolve(root, 'node_modules/klinecharts');
  const { version } = JSON.parse(await readFile(resolve(folder, 'package.json'), 'utf8'));
  if (version !== '10.0.3') return;
  const original = `if (manhattanDistance < ManhattanDistance.DoubleClick && !this._cancelClick) {
                this._processEvent(compatEvent, this._handler.mouseDoubleClickEvent);
            }
            this._resetClickTimeout();`;
  const repaired = `if (manhattanDistance < ManhattanDistance.DoubleClick && !this._cancelClick) {
                this._processEvent(compatEvent, this._handler.mouseDoubleClickEvent);
            }
            else if (!this._cancelClick) {
                this._processEvent(compatEvent, this._handler.mouseClickEvent);
            }
            this._resetClickTimeout();`;
  const minOriginal = 'this._mouseTouchMoveWithDownInfo(this._getCoordinate(t),this._clickCoordinate).manhattanDistance<lt&&!this._cancelClick&&this._processEvent(e,this._handler.mouseDoubleClickEvent),this._resetClickTimeout()';
  const minRepaired = '!this._cancelClick&&this._processEvent(e,this._mouseTouchMoveWithDownInfo(this._getCoordinate(t),this._clickCoordinate).manhattanDistance<lt?this._handler.mouseDoubleClickEvent:this._handler.mouseClickEvent),this._resetClickTimeout()';
  for (const file of ['index.esm.js', 'umd/klinecharts.js', 'umd/klinecharts.min.js']) {
    const path = resolve(folder, 'dist', file);
    const text = (await readFile(path, 'utf8')).replaceAll('\r\n', '\n');
    const from = file.endsWith('.min.js') ? minOriginal : original;
    const to = file.endsWith('.min.js') ? minRepaired : repaired;
    if (text.includes(to)) continue;
    // UMD is indented by an additional four spaces compared to ESM.
    const candidates = [from, from.replaceAll('\n', '\n    ')];
    const found = candidates.find(candidate => text.includes(candidate));
    if (!found) throw new Error(`KLineChart ${version} click handler changed: ${file}`);
    const replacement = found === from ? to : to.replaceAll('\n', '\n    ');
    await writeFile(path, text.replace(found, replacement));
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  await patchKlinecharts();
}
