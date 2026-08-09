import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { join, relative, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(import.meta.dirname, ".."); const raw = resolve(root, "deliverables", "raw"); await mkdir(raw, { recursive: true });
async function hashes(directory) { const result = {}; async function walk(dir) { for (const entry of await readdir(dir, { withFileTypes: true })) { const path = join(dir, entry.name); if (entry.isDirectory()) await walk(path); else result[relative(directory, path).replaceAll("\\", "/")] = createHash("sha256").update(await readFile(path)).digest("hex"); } } await walk(directory); return result; }
const records=[];
for(let run=1;run<=2;run++){
  const result=spawnSync(process.platform === "win32" ? "npm.cmd" : "npm", ["run","build"], {cwd:root,encoding:"utf8",shell:process.platform === "win32",maxBuffer:32*1024*1024});
  const record={run,exitCode:result.status,stdout:result.stdout,stderr:result.stderr};records.push(record);
  await writeFile(resolve(raw,`build-run-${run}.txt`),`exit_code=${result.status}\nSTDOUT\n${result.stdout}\nSTDERR\n${result.stderr}`);
  if(result.status!==0)process.exit(result.status??1); record.hashes=await hashes(resolve(root,"dist"));
}
const differing=[];for(const [file,hash] of Object.entries(records[0].hashes)){if(records[1].hashes[file]!==hash)differing.push(file)}
for(const file of Object.keys(records[1].hashes)){if(!(file in records[0].hashes))differing.push(file)}
const summary={pass:differing.length===0,fileCount:Object.keys(records[0].hashes).length,differing:[...new Set(differing)].sort(),run1:records[0].hashes,run2:records[1].hashes};
await writeFile(resolve(raw,"deterministic-build.json"),JSON.stringify(summary,null,2));
if(!summary.pass){console.error(`Deterministic build failed: ${summary.differing.join(", ")}`);process.exit(1)}
console.log(`Deterministic build PASS: ${summary.fileCount} production files have identical SHA-256 across two builds.`);
