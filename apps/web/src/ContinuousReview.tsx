import { useEffect, useRef, useState } from "react"
import { Check, Save, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { api, json, type Block, type FormulaPart } from "@/lib/api"
import MathBlockEditor from "./MathBlockEditor"

type Candidate = { block_id: string; base_revision: number; text: string; content: FormulaPart[] }

export default function ContinuousReview({ blocks, documentId, kind, focusId, onSaved, onDirtyChange }: {
  blocks: Block[]; documentId: string; kind: string; focusId: string;
  onSaved: (blocks: Block[]) => void; onDirtyChange: (dirty: boolean) => void;
}) {
  const [base, setBase] = useState(blocks)
  const [texts, setTexts] = useState<Record<string, string>>(() => Object.fromEntries(blocks.map(b => [b.id, b.text])))
  const [selection, setSelection] = useState<string[]>([])
  const [from, setFrom] = useState(blocks[0]?.id || "")
  const [to, setTo] = useState(blocks[0]?.id || "")
  const [active, setActive] = useState(focusId || blocks[0]?.id || "")
  const [query, setQuery] = useState("")
  const [message, setMessage] = useState("")
  const [busy, setBusy] = useState(false)
  const [candidates, setCandidates] = useState<Candidate[]>([])
  useEffect(() => { if (kind === "docx") void api<Candidate[]>(`/documents/${documentId}/formula-candidates`).then(setCandidates).catch(() => {}) }, [documentId, kind])
  const left = useRef(new Map<string, HTMLElement>())
  const right = useRef(new Map<string, HTMLElement>())
  const dirty = base.filter(b => texts[b.id] !== b.text)
  const dirtyFlag = dirty.length > 0
  useEffect(() => { onDirtyChange(dirtyFlag) }, [dirtyFlag, onDirtyChange])
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirtyFlag) { event.preventDefault(); event.returnValue = "" } }
    window.addEventListener("beforeunload", warn)
    return () => window.removeEventListener("beforeunload", warn)
  }, [dirtyFlag])
  useEffect(() => {
    if (focusId && left.current.has(focusId)) {
      setActive(focusId)
      left.current.get(focusId)?.scrollIntoView({ block: "nearest" })
      right.current.get(focusId)?.scrollIntoView({ block: "nearest" })
    }
  }, [focusId])
  function locate(id: string, both = false) {
    setActive(id)
    right.current.get(id)?.scrollIntoView({ block: "nearest" })
    if (both) left.current.get(id)?.scrollIntoView({ block: "nearest" })
  }
  function findNext() {
    if (!query.trim()) return
    const matches = base.filter(b => texts[b.id].includes(query) || b.locator.includes(query))
    if (!matches.length) { setMessage("没有找到匹配内容，连续正文保持完整。"); return }
    const index = matches.findIndex(b => b.id === active)
    locate(matches[(index + 1) % matches.length].id, true)
    setMessage(`找到 ${matches.length} 处，已定位下一处；没有隐藏其他内容。`)
  }
  async function reextract() {
    setBusy(true); setMessage("")
    try { const result = await api<Candidate[]>(`/documents/${documentId}/formula-candidates`, { method: "POST" }); setCandidates(result); setMessage(`已生成 ${result.length} 个公式候选，没有覆盖当前正文。展开对应内容下的候选，对照后选择是否采用。`) }
    catch (e) { setMessage(String(e)) } finally { setBusy(false) }
  }
  function selectRange() {
    const start = base.findIndex(b => b.id === from), end = base.findIndex(b => b.id === to)
    setSelection(base.slice(Math.min(start, end), Math.max(start, end) + 1).map(b => b.id))
  }
  async function save(confirm: boolean) {
    const chosen = confirm ? base.filter(b => selection.includes(b.id)) : dirty
    if (!chosen.length) return
    setBusy(true); setMessage("")
    try {
      const result = await api<Block[]>(`/documents/${documentId}/blocks/review`, json("PUT", {
        changes: chosen.map(b => ({ id: b.id, revision: b.revision, text: texts[b.id], verified: confirm })),
      }))
      const byId = new Map(result.map(b => [b.id, b]))
      setBase(old => old.map(b => byId.get(b.id) || b))
      onSaved(result)
      setMessage(confirm ? `已保存并确认选中的 ${result.length} 个来源块。范围外的修改仍需另行保存。` : `已保存 ${result.length} 处修改，修改内容标记为待核对；不会自动确认整份资料。`)
    } catch (e) {
      setMessage(`${String(e)}。本次范围未保存，本地修改已保留。若是版本冲突，请先复制修改内容，再重新载入资料。`)
    } finally { setBusy(false) }
  }
  const selectedBlocks = base.filter(b => selection.includes(b.id))
  const selectionLabel = selectedBlocks.length ? `${selectedBlocks[0].locator} 至 ${selectedBlocks[selectedBlocks.length - 1].locator}（${selectedBlocks.length} 块，可非连续）` : "尚未选择确认范围"
  return <>
    <div className="review-toolbar surface">
      <div className="section-heading"><h2>连续核对</h2><span className="label">已核对 {base.filter(b => b.verified && texts[b.id] === b.text).length} / {base.length} 块</span></div>
      {kind === "docx" && <div className="actions"><Button variant="outline" disabled={busy} onClick={reextract}>重新提取公式候选</Button><span className="small muted">旧资料从原件恢复结构；不会自动覆盖人工修改</span></div>}
      <div className="actions"><input aria-label="查找连续内容" className="search" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => { if (e.key === "Enter") findNext() }} placeholder="查找题号或文字，不隐藏正文" /><Button variant="outline" onClick={findNext}><Search />定位下一处</Button><Button onClick={() => save(false)} disabled={busy || !dirty.length}><Save />保存修改（{dirty.length}）</Button></div>
      <div className="actions"><span className="small muted">确认范围</span><select aria-label="确认范围起点" value={from} onChange={e => setFrom(e.target.value)} disabled={busy}>{base.map(b => <option key={b.id} value={b.id}>{b.locator} · {b.text.slice(0, 16)}</option>)}</select><span>至</span><select aria-label="确认范围终点" value={to} onChange={e => setTo(e.target.value)} disabled={busy}>{base.map(b => <option key={b.id} value={b.id}>{b.locator} · {b.text.slice(0, 16)}</option>)}</select><Button variant="outline" disabled={busy} onClick={selectRange}>选择此范围</Button><Button variant="ghost" disabled={busy || !selection.length} onClick={() => setSelection([])}>清除选择</Button></div>
      <div className="actions"><span className="small">{selectionLabel}</span><Button onClick={() => save(true)} disabled={busy || !selection.length}><Check />保存并确认选中内容</Button></div>
      <p className="muted small mt-3">点击确认表示你已对照原件检查选中内容的文字、公式、图表和完整性。保存修改不等于审核通过，选中范围之外不会被确认。</p>
      {message && <p className="feedback mt-4" role="status">{message}</p>}
    </div>
    <div className="continuous-review">
      <section className="review-column" aria-label="待核对内容连续编辑">
        <div className="review-column-title"><h2>待核对内容</h2><p>文字可直接修改；点击公式进行可视化编辑，也可插入公式。</p></div>
        <div className="review-scroll">
          {base.map(b => <article key={b.id} ref={e => { if (e) left.current.set(b.id, e); else left.current.delete(b.id) }} className={`review-block ${active === b.id ? "is-active" : ""}`}>
            <div className="review-block-meta"><label className="checkline"><input aria-label={`选择 ${b.locator}`} type="checkbox" checked={selection.includes(b.id)} disabled={busy} onChange={e => setSelection(old => e.target.checked ? [...old, b.id] : old.filter(id => id !== b.id))} />{b.locator}</label><span>{texts[b.id] !== b.text ? "未保存" : b.verified ? "已核对" : "待核对"}</span></div>
            <MathBlockEditor block={b} text={texts[b.id]} disabled={busy} onFocus={() => locate(b.id)} onChange={text => setTexts(old => ({ ...old, [b.id]: text }))} />
            {candidates.filter(c => c.block_id === b.id).map(c => <details key={c.block_id} className="formula-candidate"><summary>对照原件重新提取的公式候选</summary><p className="small muted">当前正文保留在上方。采用候选会替换本来源块的全部文字，请检查是否包含人工修订。</p><div className="candidate-reading">{c.content.map((p, i) => p.type === "math" && p.mathml ? <span key={i} dangerouslySetInnerHTML={{ __html: p.mathml }} /> : <span key={i}>{p.text || p.latex}</span>)}</div><Button variant="outline" size="sm" disabled={busy || c.base_revision !== b.revision} onClick={() => { if (window.confirm("采用候选将替换本块当前文字，尚不会保存。是否已对照并保留需要的人工修改？")) setTexts(old => ({ ...old, [b.id]: c.text })) }}>采用此候选到编辑区</Button>{c.base_revision !== b.revision && <p className="small muted">来源修订已变化，请重新提取。</p>}</details>)}
            {b.assets.map(name => <img key={name} className="review-asset" src={`/api/documents/${documentId}/assets/${name}`} alt={`${b.locator} 原始配图，当前不支持编辑`} loading="lazy" />)}
          </article>)}
        </div>
      </section>
      <section className="review-column" aria-label="原始资料对照">
        <div className="review-column-title"><h2>{kind === "pdf" ? "原始 PDF 页面" : "原始提取结果与配图"}</h2><p>{kind === "pdf" ? "页面图用于对照，点击左侧内容可定位。" : "并非 Word 原页渲染，复杂排版请下载原件核对。"}</p><a href={`/api/documents/${documentId}/original`}>下载原始文件</a></div>
        <div className="review-scroll">
          {base.map(b => <article key={b.id} ref={e => { if (e) right.current.set(b.id, e); else right.current.delete(b.id) }} className={`review-block reference-block ${active === b.id ? "is-active" : ""}`}>
            <div className="review-block-meta"><button onClick={() => locate(b.id, true)}>{b.locator} · 定位左侧</button><span>原始证据</span></div>
            {kind !== "pdf" && <div className="source-preview" dangerouslySetInnerHTML={{ __html: b.preview }} />}
            {b.assets.map(name => <img key={name} className="review-asset" src={`/api/documents/${documentId}/assets/${name}`} alt={`${b.locator} 原始图像`} loading="lazy" />)}
            {b.warnings.length > 0 && <details className="review-warning"><summary>提取注意事项</summary>{b.warnings.map(w => <p key={w}>{w}</p>)}</details>}
          </article>)}
        </div>
      </section>
    </div>
  </>
}
