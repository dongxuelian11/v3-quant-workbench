import React, { useRef, useState } from "react";
import type { ResearchConversation } from "../../../../../packages/contracts/src/research";
import { request, errorText, useResearch } from "./state";
import { object } from "./configuration";

export function LegacyConversations() {
  const s = useResearch();
  const [items, setItems] = useState<ResearchConversation[]>([]), [preview, setPreview] = useState<ResearchConversation | null>(null);
  const [target, setTarget] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const serial = useRef(0);
  const load = async () => { setBusy(true); setError(""); try { setItems(await request("ai.conversations.list", { unassigned: true })); } catch (e) { setError(errorText(e)); } finally { setBusy(false); } };
  const inspect = async (id: string) => { const run = ++serial.current; setPreview(null); setTarget(""); setError(""); try { const value = await request<ResearchConversation>("ai.conversations.get", { conversationId: id }); if (run === serial.current) setPreview(value); } catch (e) { if (run === serial.current) setError(errorText(e)); } };
  const assign = async () => {
    if (!preview || !target) return;
    setBusy(true); setError("");
    try {
      await request("ai.conversations.save", { conversation: { id: preview.id, projectId: target === "global" ? null : target } });
      setItems(values => values.filter(value => value.id !== preview.id)); setPreview(null); setTarget("");
      window.dispatchEvent(new Event("v3-conversation-list-refresh"));
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  };
  const messages = object(preview?.state).messages;
  return <details className="r-legacy-conversations" onToggle={e => { if (e.currentTarget.open) void load(); }}><summary>未归类历史</summary>{error && <p role="alert">{error}</p>}<p className="r-note">旧消息和关联对象保留。选择归属后，才会进入对应的历史列表。</p><select aria-label="预览未归类会话" disabled={busy} value={preview?.id ?? ""} onChange={e => void inspect(e.target.value)}><option value="" disabled>选择旧会话，只读预览</option>{items.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>{!busy && !items.length && <p className="r-note">没有未归类历史。</p>}{preview && <><div style={{ maxHeight: "30vh", overflow: "auto", whiteSpace: "pre-wrap" }}><h4>{preview.name}</h4>{Array.isArray(messages) && messages.map((value, i) => { const message = object(value); return <p key={i}><strong>{message.role === "user" ? "你" : "研究助手"}</strong><br/>{String(message.content ?? "")}</p>; })}<h4>原始关联对象</h4>{preview.context.map((ref, i) => <p key={i}>{ref.title ?? ref.kind} · {ref.projectId ?? "全局对象"}</p>)}</div><select aria-label="旧会话归属" disabled={busy} value={target} onChange={e => setTarget(e.target.value)}><option value="" disabled>明确选择归属</option><option value="global">全局会话</option>{s.projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select><button disabled={busy || !target} onClick={() => void assign()}>确认归属并保留原记录</button></>}</details>;
}
