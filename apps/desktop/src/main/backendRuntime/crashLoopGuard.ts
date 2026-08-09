export class CrashLoopGuard {
  private readonly crashes: number[] = [];

  constructor(private readonly limit: number, private readonly windowMs: number) {
    if (!Number.isInteger(limit) || limit < 1 || !Number.isFinite(windowMs) || windowMs <= 0) {
      throw new RangeError("crash-loop limits must be positive");
    }
  }

  recordCrash(now = Date.now()): boolean {
    this.crashes.push(now);
    this.prune(now);
    return this.crashes.length <= this.limit;
  }

  get count(): number {
    this.prune(Date.now());
    return this.crashes.length;
  }

  reset(): void {
    this.crashes.length = 0;
  }

  private prune(now: number): void {
    while (this.crashes.length > 0 && now - (this.crashes[0] ?? now) > this.windowMs) this.crashes.shift();
  }
}
