import { lazy, Suspense, useLayoutEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { mathParts, putFormula } from "@/lib/math-content"
import type { Block } from "@/lib/api"

const FormulaEditor = lazy(() => import("./FormulaEditor"))

function TextPiece({ text, label, disabled, onChange, onFocus, onSelect }: { text: string; label: string; disabled: boolean; onChange: (s: string, start: number, end: number) => void; onFocus: () => void; onSelect: (start: number, end: number) => void }) {
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
  return <textarea ref={ref} value={text} aria-label={label} disabled={disabled} rows={1} style={{ width, maxWidth: "100%", display: "inline-block", verticalAlign: "middle" }} className="continuous-text" onFocus={e => { onFocus(); onSelect(e.currentTarget.selectionStart, e.currentTarget.selectionEnd) }} onChange={e => onChange(e.target.value, e.target.selectionStart, e.target.selectionEnd)} onSelect={e => onSelect(e.currentTarget.selectionStart, e.currentTarget.selectionEnd)} onBlur={e => onSelect(e.currentTarget.selectionStart, e.currentTarget.selectionEnd)} />
}

export default function MathBlockEditor({ block, text, disabled, onChange, onFocus }: { block: Block; text: string; disabled: boolean; onChange: (text: string) => void; onFocus: () => void }) {
  const [editing, setEditing] = useState<{ start: number; end: number; latex: string } | null>(null)
  const [caret, setCaret] = useState<{ start: number; end: number } | null>(null)
  const caretRef = useRef<{ start: number; end: number } | null>(null)
  const caretText = useRef(text)
  function remember(start: number, end: number, context = text) { caretRef.current = { start, end }; caretText.current = context; setCaret(caretRef.current) }
  const [rendered, setRendered] = useState<Record<string, string>>({})
  const parts = mathParts(text)
  const currentCaret = caretText.current === text ? caret : null
  return <div className="mixed-content">
    {parts.map((part, index) => part.type === "text" ? <TextPiece key={`t-${index}`} text={part.text} disabled={disabled} label={`待核对内容 ${block.locator}${index ? ` 文字${index + 1}` : ""}`} onFocus={onFocus} onSelect={(start, end) => remember(part.start + start, part.start + end)} onChange={(next, start, end) => { const updated = text.slice(0, part.start) + next + text.slice(part.end); remember(part.start + start, part.start + end, updated); onChange(updated) }} /> : (() => {
      const source = block.content?.find(p => p.type === "math" && p.latex === part.latex)
      const markup = rendered[part.latex] || source?.mathml
      return <button key={`m-${index}`} type="button" className="inline-formula" disabled={disabled} aria-label={`编辑公式 ${part.latex}`} onClick={() => { onFocus(); setEditing({ start: part.start, end: part.end, latex: part.latex }) }}>
        {markup ? <span dangerouslySetInnerHTML={{ __html: markup }} /> : <span>{part.latex}（点击修正或预览）</span>}<small>编辑公式</small>
      </button>
    })())}
    <div className="actions math-block-actions"><Button variant="ghost" size="sm" disabled={disabled} onMouseDown={e => { if (e.button === 0) e.preventDefault() }} onClick={() => { onFocus(); const at = (caretText.current === text ? caretRef.current : null) || { start: text.length, end: text.length }; setEditing({ ...at, latex: text.slice(at.start, at.end) }) }}>插入公式{currentCaret && currentCaret.start !== currentCaret.end ? "并替换选中文字" : ""}</Button><span className="small muted">光标处插入；选中片段会带入编辑，其余文字保留</span></div>
    {editing && <Suspense fallback={<p role="status">正在加载公式编辑器…</p>}><FormulaEditor initial={editing.latex} onClose={() => setEditing(null)} onApply={(latex, markup) => { setRendered(old => ({ ...old, [latex]: markup })); const updated = putFormula(text, editing.start, editing.end, latex); onChange(updated); const next = editing.start + latex.length + 4; remember(next, next, updated); setEditing(null) }} /></Suspense>}
  </div>
}
