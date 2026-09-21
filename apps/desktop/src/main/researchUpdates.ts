import { readFile, writeFile } from "node:fs/promises";

export interface UpdateStatus { checkedAt: string; currentVersion: string; latestVersion?: string; available: boolean; prerelease?: boolean; url?: string; error?: string; }
/** Public release metadata only. Installation is always initiated by the user. */
export class ResearchUpdates {
  private pending?: Promise<UpdateStatus>;
  constructor(private file: string, private version: string) {}
  async check(manual = false): Promise<UpdateStatus> {
    if (this.pending) return this.pending;
    if (!manual) {
      try {
        const old = JSON.parse(await readFile(this.file, "utf8")) as UpdateStatus;
        if (Date.now() - Date.parse(old.checkedAt) < 86_400_000 && old.currentVersion === this.version) return old;
      } catch { /* No cached attempt yet. */ }
    }
    this.pending = this.fetch();
    try { return await this.pending; } finally { this.pending = undefined; }
  }
  private async fetch(): Promise<UpdateStatus> {
    const status: UpdateStatus = { checkedAt: new Date().toISOString(), currentVersion: this.version, available: false };
    try {
      const response = await fetch("https://api.github.com/repos/dongxuelian11/v3-quant-workbench/releases?per_page=20", {
        headers: { Accept: "application/vnd.github+json" }, signal: AbortSignal.timeout(15_000),
      });
      if (!response.ok) throw new Error(`发布服务返回 ${response.status}`);
      const releases = await response.json() as { tag_name?: string; html_url?: string; draft?: boolean; prerelease?: boolean }[];
      // V3's current public channel is a research preview. GitHub /latest excludes it.
      const release = releases.filter(item => !item.draft && /^v?\d+\.\d+\.\d+$/.test(item.tag_name ?? ""))
        .sort((a, b) => { const x = a.tag_name!.replace(/^v/, "").split(".").map(Number), y = b.tag_name!.replace(/^v/, "").split(".").map(Number); return y[0]-x[0] || y[1]-x[1] || y[2]-x[2]; })[0];
      if (!release) throw new Error("没有可识别的公开版本");
      const latest = release.tag_name?.replace(/^v/, "");
      if (!latest) throw new Error("没有可识别的公开版本");
      const current = this.version.split(".").map(Number), candidate = latest.split(".").map(Number);
      const different = candidate.findIndex((part, i) => part !== current[i]);
      status.latestVersion = latest;
      status.available = different >= 0 && candidate[different] > current[different];
      status.prerelease = Boolean(release.prerelease);
      status.url = `https://github.com/dongxuelian11/v3-quant-workbench/releases/tag/${encodeURIComponent(release.tag_name!)}`;
    } catch (error) { status.error = error instanceof Error ? error.message : String(error); }
    await writeFile(this.file, JSON.stringify(status), "utf8");
    return status;
  }
}
