import { useEffect, useRef, useState } from "react"
import type { MathfieldElement } from "mathlive"
import { Button } from "@/components/ui/button"
import { api, json } from "@/lib/api"

export default function FormulaEditor({ initial, onApply, onClose }: { initial: string; onApply: (latex: string, markup: string) => void; onClose: () => void }) {
  const host = useRef<HTMLDivElement>(null)
  const dialog = useRef<HTMLElement>(null)
  const field = useRef<MathfieldElement | null>(null)
  const [value, setValue] = useState(initial || "x^{2}")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [ready, setReady] = useState(false)
  useEffect(() => {
    let alive = true
    const previous = document.activeElement as HTMLElement | null
    void import("mathlive").then(({ MathfieldElement }) => {
      if (!alive || !host.current) return
      MathfieldElement.fontsDirectory = "/mathlive/fonts"
      MathfieldElement.soundsDirectory = null
      MathfieldElement.computeEngine = null
      const mf = new MathfieldElement()
      mf.setAttribute("aria-label", "可视化公式编辑器")
      mf.value = initial || "x^{2}"
      mf.mathVirtualKeyboardPolicy = "auto"
      mf.addEventListener("input", () => setValue(mf.value))
      host.current.append(mf); field.current = mf; setReady(true); mf.focus()
    }).catch(() => setError("可视化编辑器加载失败，可在下方 LaTeX 输入框继续编辑。"))
    return () => { alive = false; field.current?.remove(); field.current = null; previous?.focus() }
  }, [initial])
  useEffect(() => { if (field.current && field.current.value !== value) field.current.value = value }, [value])
  async function apply() {
    setBusy(true); setError("")
    try {
      const result = await api<{ latex: string; mathml: string }>("/formulas/preview", json("POST", { latex: value }))
      onApply(result.latex, result.mathml)
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  return <div className="formula-overlay"><section ref={dialog} className="formula-dialog" role="dialog" aria-modal="true" aria-labelledby="formula-dialog-title" onKeyDown={e => {
    if (e.key === "Escape") onClose()
    if (e.key === "Tab") {
      const controls = [...(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), textarea, math-field') || [])]
      const first = controls[0], last = controls[controls.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus() }
    }
  }}>
    <h2 id="formula-dialog-title">编辑数学公式</h2><p className="muted small">直接修改公式；可用键盘、数学键盘或下方模板。应用到正文后仍需保存核对结果。</p>
    <div ref={host} className="mathfield-host" />
    <div className="actions">{[["平方", "x^{2}"], ["下标", "x_{1}"], ["分式", "\\frac{1}{x}"], ["根式", "\\sqrt{x}"], ["不等号", "\\leq"]].map(([name, latex]) => <Button key={name} size="sm" variant="outline" disabled={!ready} onClick={() => { field.current?.insert(latex); if (field.current) setValue(field.current.value); field.current?.focus() }}>插入{name}</Button>)}</div>
    <label htmlFor="formula-latex">LaTeX 输入（与可视化编辑同步）</label><textarea id="formula-latex" value={value} onChange={e => setValue(e.target.value)} spellCheck={false} />
    <p className="muted small">例如：<code>{String.raw`x^2，x_1，\frac{1}{x}，\sqrt{x+1}`}</code>。语法可显示不代表数学结论正确。</p>
    {error && <p className="feedback" role="alert">{error}</p>}
    <div className="actions"><Button disabled={busy || !value.trim()} onClick={apply}>应用公式</Button><Button variant="outline" disabled={busy} onClick={onClose}>取消</Button></div>
  </section></div>
}
