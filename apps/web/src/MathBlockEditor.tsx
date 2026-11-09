import { lazy, Suspense, useLayoutEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { mathParts, putFormula } from "@/lib/math-content"
import type { Block } from "@/lib/api"

const FormulaEditor = lazy(() => import("./FormulaEditor"))

function TextPiece({ text, label, disabled, onChange, onFocus, onSelect }: { text: string; label: string; disabled: boolean; onChange: (s: string) => void; onFocus: () => void; onSelect: (start: number, end: number) => void }) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => {
    const e = ref.current
    if (!e) return
    const size = () => { e.style.height = "auto"; e.style.height = `${e.scrollHeight + 2}px` }
    size(); let width = e.clientWidth
    const observer = new ResizeObserver(() => { if (e.clientWidth !== width) { width = e.clientWidth; size() } }); observer.observe(e)
    return () => observer.disconnect()
  }, [text])
  const width = text.includes("\n") || text.length > 60 ? "100%" : `${Math.max(4, [...text].reduce((n, c) => n + (c.charCodeAt(0) > 255 ? 2 : 1), 0) + 3)}ch`
  return <textarea ref={ref} value={text} aria-label={label} disabled={disabled} rows={1} style={{ width, maxWidth: "100%", display: "inline-block", verticalAlign: "middle" }} className="continuous-text" onFocus={onFocus} onChange={e => onChange(e.target.value)} onSelect={e => onSelect(e.currentTarget.selectionStart, e.currentTarget.selectionEnd)} />
}

export default function MathBlockEditor({ block, text, disabled, onChange, onFocus }: { block: Block; text: string; disabled: boolean; onChange: (text: string) => void; onFocus: () => void }) {
  const [editing, setEditing] = useState<{ start: number; end: number; latex: string } | null>(null)
  const [caret, setCaret] = useState<{ start: number; end: number } | null>(null)
  const [rendered, setRendered] = useState<Record<string, string>>({})
  const parts = mathParts(text)
  return <div className="mixed-content">
    {parts.map((part, index) => part.type === "text" ? <TextPiece key={`t-${index}`} text={part.text} disabled={disabled} label={`待核对内容 ${block.locator}${index ? ` 文字${index + 1}` : ""}`} onFocus={onFocus} onSelect={(start, end) => setCaret({ start: part.start + start, end: part.start + end })} onChange={next => { onChange(text.slice(0, part.start) + next + text.slice(part.end)); setCaret(null) }} /> : (() => {
      const source = block.content?.find(p => p.type === "math" && p.latex === part.latex)
      const markup = rendered[part.latex] || source?.mathml
      return <button key={`m-${index}`} type="button" className="inline-formula" disabled={disabled} aria-label={`编辑公式 ${part.latex}`} onClick={() => { onFocus(); setEditing({ start: part.start, end: part.end, latex: part.latex }) }}>
        {markup ? <span dangerouslySetInnerHTML={{ __html: markup }} /> : <span>{part.latex}（点击修正或预览）</span>}<small>编辑公式</small>
      </button>
    })())}
    <div className="actions math-block-actions"><Button variant="ghost" size="sm" disabled={disabled} onClick={() => { onFocus(); const at = caret || { start: text.length, end: text.length }; setEditing({ ...at, latex: "" }) }}>插入公式{caret && caret.start !== caret.end ? "并替换选中文字" : ""}</Button><span className="small muted">普通文字与公式分开编辑</span></div>
    {editing && <Suspense fallback={<p role="status">正在加载公式编辑器…</p>}><FormulaEditor initial={editing.latex} onClose={() => setEditing(null)} onApply={(latex, markup) => { setRendered(old => ({ ...old, [latex]: markup })); onChange(putFormula(text, editing.start, editing.end, latex)); setCaret(null); setEditing(null) }} /></Suspense>}
  </div>
}
