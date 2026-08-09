import type { CommandReceipt, DesktopCommandEnvelope } from "../../../../packages/contracts/src/index";

export class CommandRegistry {
  private readonly inflight = new Map<string, Promise<CommandReceipt>>();
  execute(name: DesktopCommandEnvelope["name"], id: string): Promise<CommandReceipt> {
    const existing = this.inflight.get(id); if (existing) return existing;
    const command: DesktopCommandEnvelope = { id, name, issuedAt: new Date().toISOString() };
    const pending = window.v3Desktop.executeCommand(command).finally(() => this.inflight.delete(id));
    this.inflight.set(id, pending); return pending;
  }
}
export const commandRegistry = new CommandRegistry();
