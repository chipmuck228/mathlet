import { lazy, Suspense, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { mathParts, putFormula } from "@/lib/math-content"
import { api, json, type Block } from "@/lib/api"

const FormulaEditor = lazy(() => import("./FormulaEditor"))

export default function MathBlockEditor({ block, text, disabled, onChange, onFocus }: { block: Block; text: string; disabled: boolean; onChange: (text: string) => void; onFocus: () => void }) {
  const [draft, setDraft] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ start: number; end: number; latex: string } | null>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const [previewError, setPreviewError] = useState("")
  const [previewBusy, setPreviewBusy] = useState(false)
  async function refreshPreview() {
    if (draft === null) return
    setPreviewBusy(true); setPreviewError("")
    try {
      const formulas = mathParts(draft).filter(p => p.type === "math")
      const results = await Promise.all(formulas.map(async p => { const result = await api<{ mathml: string }>("/formulas/preview", json("POST", { latex: p.latex })); return [p.latex, result.mathml] as const }))
      setRendered(old => ({ ...old, ...Object.fromEntries(results) }))
    } catch (e) { setPreviewError(`公式预览失败，请检查公式标记与语法：${String(e)}`) } finally { setPreviewBusy(false) }
  }
  const [rendered, setRendered] = useState<Record<string, string>>({})
  function preview(value: string, editable = false) {
    return mathParts(value).map((part, index) => {
      if (part.type === "text") return <span key={index}>{part.text}</span>
      const markup = rendered[part.latex] || block.content?.find(p => p.type === "math" && p.latex === part.latex)?.mathml
      const body = markup ? <span dangerouslySetInnerHTML={{ __html: markup }} /> : <span>{part.latex}</span>
      return editable ? <button type="button" key={index} aria-label={`编辑公式 ${part.latex}`} className="reading-formula" onClick={() => setEditing({ start: part.start, end: part.end, latex: part.latex })}>{body}</button> : <span key={index} className="reading-formula">{body}</span>
    })
  }
  function insert() {
    const el = input.current
    if (!el || draft === null) return
    const start = el.selectionStart, end = el.selectionEnd
    const formula = mathParts(draft).find(p => p.type === "math" && start >= p.start && end <= p.end)
    setEditing(formula?.type === "math" ? { start: formula.start, end: formula.end, latex: formula.latex } : { start, end, latex: draft.slice(start, end) })
  }
  return <div className="mixed-content">
    {mathParts(text).some(p => p.type === "math") ? <div className="block-reading">{preview(text)}</div> : <textarea className="continuous-text" aria-label={`提取结果 ${block.locator}`} value={text} disabled={disabled} rows={Math.max(2, text.split("\n").length)} onFocus={onFocus} onChange={e => onChange(e.target.value)} />}
    <div className="actions math-block-actions"><Button variant="ghost" size="sm" disabled={disabled} onClick={() => { onFocus(); setPreviewError(""); setDraft(text) }}>插入公式</Button><span className="small muted">打开完整正文，统一编辑文字与公式</span></div>
    {draft !== null && <div className="formula-overlay"><section className="formula-dialog" role="dialog" aria-modal="true" aria-labelledby="full-content-title" onKeyDown={e => { if (e.key === "Escape" && !editing) setDraft(null) }}>
      <h2 id="full-content-title">编辑完整内容</h2>
      <p className="muted small">已带入当前内容块的全部文字与公式。可直接修改正文，选中需要修正的片段后点击“编辑选区公式”；已有公式也可点击下方预览修改。</p>
      <label htmlFor={`full-content-${block.id}`}>完整正文</label>
      <textarea autoFocus ref={input} id={`full-content-${block.id}`} value={draft} rows={8} onChange={e => setDraft(e.target.value)} spellCheck={false} />
      <div className="actions"><Button variant="outline" onMouseDown={e => e.preventDefault()} onClick={insert}>编辑选区公式／在光标处新增</Button></div>
      <p className="muted small">正文中的公式用 {String.raw`\( … \)`} 标记；标记内可直接输入 x^2 或 {String.raw`\frac{1}{x}`}。普通文字不需要标记。</p>
      <div className="actions"><h3>连续阅读预览</h3><Button variant="outline" disabled={previewBusy} onClick={refreshPreview}>{previewBusy ? "正在预览…" : "刷新公式预览"}</Button></div>{previewError && <p role="alert">{previewError}</p>}<div className="block-reading">{preview(draft, true)}</div>
      <div className="actions"><Button onClick={() => { onChange(draft); setDraft(null) }}>应用完整内容</Button><Button variant="outline" onClick={() => setDraft(null)}>取消修改</Button></div>
      <p className="muted small">应用后仍需在审核页面“保存核对结果”。取消不会更改原文。</p>
    </section></div>}
    {editing && draft !== null && <Suspense fallback={<p role="status">正在加载公式编辑器…</p>}><FormulaEditor initial={editing.latex} onClose={() => setEditing(null)} onApply={(latex, markup) => { setRendered(old => ({ ...old, [latex]: markup })); setDraft(putFormula(draft, editing.start, editing.end, latex)); setEditing(null) }} /></Suspense>}
  </div>
}
