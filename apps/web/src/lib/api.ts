export type Document = { id: string; name: string; kind: string; category: string; status: string; created_at: string }
export type Block = { id: string; document_id: string; locator: string; text: string; preview: string; assets: string[]; warnings: string[]; verified: boolean; revision: number }
export type Job = { id: string; name: string; status: string; message: string; updated_at: string }
export type Draft = { id: string; title: string; content: string; source_ids: string[]; revision: number; approved: boolean; reviewer: string | null }
export type Comment = { id: string; revision: number; author: string; body: string; created_at: string }
export type Release = { id: string; draft_id: string; revision: number; created_at: string }
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init)
  if (!response.ok) {
    let detail: unknown = response.statusText
    try { detail = (await response.json()).detail } catch { /* keep status */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail))
  }
  return response.json()
}
export function json(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
}
