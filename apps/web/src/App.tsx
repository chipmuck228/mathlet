import { useCallback, useEffect, useState } from "react"
import { BookOpen, Check, FileCheck2, Files, GitBranch, Loader2, MessageSquare, Package, Plus, RefreshCw, Upload } from "lucide-react"
import { Button } from "@/components/ui/button"
import { api, json, type Block, type Comment, type Document, type Draft, type Job, type Release } from "@/lib/api"

const stages = [
  { id: "materials", label: "资料包", icon: Files },
  { id: "sources", label: "原题核对", icon: FileCheck2 },
  { id: "tasks", label: "任务与生成", icon: GitBranch },
  { id: "editor", label: "编辑与评审", icon: MessageSquare },
  { id: "preview", label: "小册子预览", icon: BookOpen },
  { id: "releases", label: "交付版本", icon: Package },
]
const statuses: Record<string, string> = { queued: "排队中", running: "读取中", ready: "待核对", completed: "已提取", failed: "失败" }
const categories = { unknown: "待分类", standard: "课标／考纲", textbook: "教材／知识资料", exam: "中考真题", mock: "模拟题", term: "学期试卷" }

function date(value: string) { return new Date(value).toLocaleString("zh-CN") }
function Message({ value }: { value: string }) { return value ? <p className="feedback" role="status">{value}</p> : null }

function SourceEditor({ block, onSaved }: { block: Block; onSaved: (b: Block) => void }) {
  const [current, setCurrent] = useState(block)
  const [text, setText] = useState(block.text)
  const [confirmed, setConfirmed] = useState(block.verified)
  const [message, setMessage] = useState("")
  const [busy, setBusy] = useState(false)
  async function save() {
    setBusy(true)
    try {
      const result = await api<Block>(`/blocks/${block.id}`, json("PUT", { revision: current.revision, text, verified: confirmed }))
      setCurrent(result); onSaved(result); setMessage("已保存。关联草稿的旧审核已撤销；原始证据仍保留。")
    } catch (e) { setMessage(String(e)) } finally { setBusy(false) }
  }
  return <div className="two-column">
    <section className="surface min-w-0">
      <div className="section-heading"><h2>原件提取预览</h2><span className="label">{block.locator}</span></div>
      <p className="muted small">DOCX 为结构预览，PDF 为原页图。此处始终保留最初提取结果，不随人工文字修正而改变。</p>
      <div className="source-preview" dangerouslySetInnerHTML={{ __html: block.preview }} />
      {block.assets.map(name => <img className="source-image" key={name} src={`/api/documents/${block.document_id}/assets/${name}`} alt={`${block.locator} 原件配图或页面`} />)}
      <div className="warnings">{block.warnings.map(w => <p key={w}>{w}</p>)}</div>
      <Button variant="outline" asChild><a href={`/api/documents/${block.document_id}/original`}>下载原件核对</a></Button>
    </section>
    <section className="surface min-w-0">
      <div className="section-heading"><h2>核对与修正</h2><span className="label">修订 {current.revision}</span></div>
      <p className="muted small">纯文字会丢失分数等公式结构。请对照左侧与原件，必要时手工改写为明确的形式，例如 k/x。确认的是当前文本与配图的组合。</p>
      <label htmlFor="source-text">经核对的题干／内容</label>
      <textarea id="source-text" className="source-input" value={text} onChange={e => { setText(e.target.value); setConfirmed(false) }} />
      <label className="checkline"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />我已核对条件、公式、点名、图表及内容完整性</label>
      <Button onClick={save} disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : <Check />}保存核对结果</Button>
      <Message value={message} />
    </section>
  </div>
}

function DraftEditor({ draft, onSaved }: { draft: Draft; onSaved: () => void }) {
  const [base, setBase] = useState(draft)
  const [title, setTitle] = useState(draft.title)
  const [content, setContent] = useState(draft.content)
  const [reviewer, setReviewer] = useState("")
  const [confirmed, setConfirmed] = useState(false)
  const [note, setNote] = useState("")
  const [comments, setComments] = useState<Comment[]>([])
  const [message, setMessage] = useState("")
  const [busy, setBusy] = useState(false)
  const dirty = title !== base.title || content !== base.content
  const loadComments = useCallback(() => api<Comment[]>(`/drafts/${draft.id}/comments`).then(setComments).catch(e => setMessage(String(e))), [draft.id])
  useEffect(() => { void loadComments() }, [loadComments])
  async function act(action: "save" | "approve" | "comment") {
    setBusy(true); setMessage("")
    try {
      if (action === "save") {
        const result = await api<Draft>(`/drafts/${base.id}`, json("PUT", { revision: base.revision, title, content }))
        setBase(result); setConfirmed(false); setMessage("新修订已保存，需要重新审核。")
      } else if (action === "approve") {
        const result = await api<Draft>(`/drafts/${base.id}/approve`, json("POST", { revision: base.revision, reviewer, confirmed }))
        setBase(result); setMessage("已批准当前修订，可创建本地交付版本。")
      } else {
        await api(`/drafts/${base.id}/comments`, json("POST", { revision: base.revision, author: reviewer, body: note }))
        setNote(""); await loadComments(); setMessage("批注已保存，并关联到当前修订。")
      }
      onSaved()
    } catch (e) { setMessage(String(e)) } finally { setBusy(false) }
  }
  return <div className="editor-grid">
    <section className="surface min-w-0">
      <div className="section-heading"><h2>内容编辑</h2><span className="label">修订 {base.revision} · {base.approved && !dirty ? "已批准" : "待审核"}</span></div>
      <p className="muted small">初始内容是编辑提纲，不是 AI 解答。请补充准确知识、推理依据及练习后审核。所有输入按纯文本显示，不执行 HTML。</p>
      <label htmlFor="draft-title">单元标题</label><input id="draft-title" value={title} maxLength={120} onChange={e => { setTitle(e.target.value); setConfirmed(false) }} />
      <label htmlFor="draft-content">讲解、连接、思考与训练</label><textarea id="draft-content" className="draft-input" value={content} onChange={e => { setContent(e.target.value); setConfirmed(false) }} />
      <div className="actions"><Button onClick={() => act("save")} disabled={busy || !dirty}>保存新修订</Button><span className="muted small">{dirty ? "有尚未保存的修改" : "内容已保存"}</span></div>
    </section>
    <section className="surface min-w-0">
      <h2>人工评审</h2><p className="muted small">知识准确、关系有据、路径开放。审核声明不意味着系统已经验证数学正确性。</p>
      <label htmlFor="reviewer">编辑／审核人</label><input id="reviewer" value={reviewer} onChange={e => setReviewer(e.target.value)} placeholder="填写姓名或工作标识" maxLength={80} />
      <label htmlFor="comment">批注</label><textarea id="comment" value={note} onChange={e => setNote(e.target.value)} placeholder="指出具体条件、推理或表达需要怎样调整。" />
      <Button variant="outline" onClick={() => act("comment")} disabled={busy || !note.trim() || !reviewer.trim() || dirty}>保存批注</Button>
      <label className="checkline mt-6"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />我已审核当前修订的概念、性质、推理、范围及答案</label>
      <Button onClick={() => act("approve")} disabled={busy || dirty || !confirmed || !reviewer.trim()}>批准当前修订</Button>
      <Message value={message} />
      <div className="comments">{comments.map(c => <div key={c.id}><span className="muted small">{c.author} · 修订 {c.revision} · {date(c.created_at)}</span><p className="whitespace-pre-wrap">{c.body}</p></div>)}</div>
      <p className="muted small">若他人或来源更新导致版本冲突，请先保留本地修改，再重新进入本单元。系统会拒绝覆盖较新的修订。</p>
    </section>
  </div>
}

export default function App() {
  const [stage, setStage] = useState("materials")
  const [documents, setDocuments] = useState<Document[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [releases, setReleases] = useState<Release[]>([])
  const [documentId, setDocumentId] = useState("")
  const [blocks, setBlocks] = useState<Block[]>([])
  const [blockId, setBlockId] = useState("")
  const [draftId, setDraftId] = useState("")
  const [selected, setSelected] = useState<string[]>([])
  const [category, setCategory] = useState("unknown")
  const [title, setTitle] = useState("")
  const [query, setQuery] = useState("")
  const [message, setMessage] = useState("")
  const [busy, setBusy] = useState(false)
  const [online, setOnline] = useState(false)
  const refresh = useCallback(async () => {
    try {
      const [docs, j, d, r] = await Promise.all([api<Document[]>("/documents"), api<Job[]>("/jobs"), api<Draft[]>("/drafts"), api<Release[]>("/releases")])
      setDocuments(docs); setJobs(j); setDrafts(d); setReleases(r); setOnline(true)
    } catch { setOnline(false) }
  }, [])
  useEffect(() => { void refresh(); const id = setInterval(() => void refresh(), 3000); return () => clearInterval(id) }, [refresh])
  const document = documents.find(d => d.id === documentId)
  const draft = drafts.find(d => d.id === draftId)
  const block = blocks.find(b => b.id === blockId)
  const docStatus = document?.status
  useEffect(() => {
    let active = true
    setBlocks([]); setBlockId(""); setSelected([])
    if (documentId) api<Block[]>(`/documents/${documentId}/blocks`).then(b => {
      if (active) { setBlocks(b); setBlockId(b[0]?.id || "") }
    }).catch(e => { if (active) setMessage(String(e)) })
    return () => { active = false }
  }, [documentId, docStatus])
  async function upload(files: FileList | null) {
    if (!files?.length) return
    setBusy(true); setMessage("")
    let imported = 0
    try {
      for (const file of Array.from(files)) {
        const form = new FormData(); form.append("file", file)
        const result = await api<{ id: string }>(`/documents?category=${category}`, { method: "POST", body: form })
        setDocumentId(result.id); imported++
      }
      setMessage(`${imported} 份资料已保存在本机并加入读取队列。请保持 Worker 运行。`)
    } catch (e) { setMessage(`已接收 ${imported} 份；${String(e)}`) }
    finally { setBusy(false); await refresh() }
  }
  async function createDraft() {
    setBusy(true)
    try {
      const d = await api<Draft>("/drafts", json("POST", { title, source_ids: selected }))
      await refresh(); setDraftId(d.id); setStage("editor"); setMessage("编辑提纲已创建，尚未调用 AI。")
    } catch (e) { setMessage(String(e)) } finally { setBusy(false) }
  }
  async function release() {
    if (!draft) return
    setBusy(true)
    try {
      await api(`/drafts/${draft.id}/releases`, json("POST", { revision: draft.revision }))
      await refresh(); setMessage("本地交付快照已保存。后续修改不会改变这个版本。")
    } catch (e) { setMessage(String(e)) } finally { setBusy(false) }
  }
  function navigate(next: string) {
    if (stage === "editor" && next !== stage && !window.confirm("离开编辑页前，请确认修改已经保存。继续切换？")) return
    setStage(next); setMessage("")
  }
  const draftPicker = <select aria-label="选择小册子单元" value={draftId} onChange={e => { if (stage !== "editor" || window.confirm("请确认已保存当前单元。继续切换？")) setDraftId(e.target.value) }}><option value="">选择一个单元</option>{drafts.map(d => <option key={d.id} value={d.id}>{d.title} · 修订 {d.revision}</option>)}</select>
  return <div className="app-shell">
    <aside className="sidebar"><a className="brand" href="/">mathlet<span>数学小册子编辑工作台</span></a>
      <div className="sidebar-caption">内容生产</div><nav aria-label="工作区">{stages.map(({ id, label, icon: Icon }, i) => <button key={id} className={stage === id ? "active" : ""} onClick={() => navigate(id)} aria-current={stage === id ? "page" : undefined}><Icon size={17} /><span>{label}</span><small>0{i + 1}</small></button>)}</nav>
      <div className="sidebar-footer"><span className={online ? "dot online" : "dot"} />{online ? "本地服务已连接" : "等待本地 API"}<p>资料留存在本机<br />代码通过 GitHub 管理</p></div></aside>
    <div className="workspace"><header className="workspace-header"><span>Mathlet / {stages.find(s => s.id === stage)?.label}</span><span className="label">本地版 · 0.1</span></header>
      <main><div className="intro"><div><p className="eyebrow">理解知识 · 发现连接 · 建立思路</p><h1>{({ materials: "从可信资料开始。", sources: "让每个条件都准确。", tasks: "把生成过程留在记录里。", editor: "让思路经得起检查。", preview: "回到学生的阅读视角。", releases: "交付一个确定的版本。" } as Record<string, string>)[stage]}</h1></div><Button variant="outline" size="sm" onClick={() => void refresh()}><RefreshCw />刷新列表</Button></div>
      {!online && <div className="notice" role="alert">尚未连接 API。请按 README 启动 FastAPI（8000）和 Worker；前端通过 Vite 代理访问。</div>}
      <Message value={message} />
      {stage === "materials" && <>
        <div className="upload-area"><Upload size={25} /><h2>加入你的资料包</h2><p className="muted">DOCX 或 PDF，单份不超过30MB。保留原件，不要求先整理教材版本。</p><div className="actions"><select aria-label="资料类别" value={category} onChange={e => setCategory(e.target.value)}>{Object.entries(categories).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select><label className={`upload-label ${busy ? "opacity-50" : ""}`}>选择文件<input aria-label="上传资料文件" type="file" accept=".docx,.pdf" multiple disabled={busy || !online} onChange={e => { void upload(e.target.files); e.target.value = "" }} /></label></div></div>
        <div className="section-heading mt-8"><h2>本机资料</h2><span className="muted small">{documents.length} 份</span></div>
        {!documents.length ? <div className="empty"><Files /><h3>还没有资料</h3><p>可以先上传你提供的模拟试卷，测试题干、公式与配图的核对流程。</p></div> : <div className="document-list">{documents.map(d => <div className="document-row" key={d.id}><div className="file-symbol">{d.kind.toUpperCase()}</div><div className="min-w-0 flex-1"><h3>{d.name}</h3><p className="muted small">{categories[d.category as keyof typeof categories]} · {date(d.created_at)}</p></div><span className="label">{statuses[d.status]}</span><Button variant="outline" size="sm" onClick={() => { setDocumentId(d.id); setStage("sources") }}>核对</Button></div>)}</div>}
        <p className="muted small mt-6">原件、数据库和交付文件位于本地 data 目录，默认不会进入 Git。当前版本未接入模型或外部 OCR，不会自动发送资料。</p>
      </>}
      {stage === "sources" && <>
        <div className="actions mb-5"><select aria-label="选择资料" value={documentId} onChange={e => { if (!block || window.confirm("请确认核对修改已保存。继续切换？")) setDocumentId(e.target.value) }}><option value="">选择资料</option>{documents.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select><input className="search" aria-label="筛选内容块" value={query} onChange={e => setQuery(e.target.value)} placeholder="查找题号或文字…" /></div>
        {document && docStatus !== "ready" && <div className="notice">资料状态：{statuses[docStatus || ""]}。请查看任务页了解读取进度。</div>}
        {blocks.length > 0 && <><div className="block-selector">{blocks.filter(b => b.text.includes(query)).map(b => <button key={b.id} className={b.id === blockId ? "selected" : ""} onClick={() => { if (b.id === blockId || window.confirm("请确认当前内容已保存。继续切换？")) setBlockId(b.id) }}><span>{b.verified ? "✓ " : ""}{b.locator}</span><small>{b.text.slice(0, 35) || "图片内容"}</small></button>)}</div>{block && <SourceEditor key={block.id} block={block} onSaved={b => { setBlocks(old => old.map(x => x.id === b.id ? b : x)); void refresh() }} />}</>}
        {!document && <div className="empty"><FileCheck2 /><p>先选择一份资料，再对照原件逐块核对。DOCX 按段落／表格分块，PDF 按页分块。</p></div>}
      </>}
      {stage === "tasks" && <>
        <div className="notice">本阶段自动执行真实文件读取。数学 Agent、OCR 和自动分题尚未接入；“创建提纲”只组织人工已确认的来源，不生成解答。</div>
        <section className="surface"><h2>文件读取任务</h2>{jobs.length ? jobs.map(j => <div className="job" key={j.id}><div><h3>{j.name}</h3><p className="muted small">{j.message}</p></div><span className="label">{statuses[j.status]}</span>{j.status === "failed" && <Button variant="outline" size="sm" onClick={async () => { try { await api(`/jobs/${j.id}/retry`, { method: "POST" }); await refresh() } catch (e) { setMessage(String(e)) } }}>重试</Button>}</div>) : <p className="muted">上传资料后，任务会保存在本机数据库中。</p>}</section>
        <section className="surface"><h2>从已核对内容建立单元</h2><p className="muted small">来源选择与“原题核对”页当前资料一致。支持跨内容块组合；跨文档组合将在后续完善。</p>
          <select aria-label="选择提纲来源资料" value={documentId} onChange={e => setDocumentId(e.target.value)}><option value="">选择资料</option>{documents.filter(d => d.status === "ready").map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
          <div className="source-choices">{blocks.filter(b => b.verified).map(b => <label className="checkline" key={b.id}><input type="checkbox" checked={selected.includes(b.id)} onChange={e => setSelected(old => e.target.checked ? [...old, b.id] : old.filter(id => id !== b.id))} /><span>{b.locator} · {b.text.slice(0, 85)}</span></label>)}{!blocks.some(b => b.verified) && <p className="muted">当前资料暂无已确认内容，请先进行原题核对。</p>}</div>
          <label htmlFor="new-title">单元标题</label><input id="new-title" value={title} maxLength={120} onChange={e => setTitle(e.target.value)} placeholder="例如：反比例函数与面积最值" /><div className="actions"><Button onClick={createDraft} disabled={busy || !title.trim() || !selected.length}><Plus />创建编辑提纲</Button></div>
        </section>
      </>}
      {stage === "editor" && <><div className="mb-5">{draftPicker}</div>{draft ? <DraftEditor key={draft.id} draft={draft} onSaved={() => void refresh()} /> : <div className="empty"><MessageSquare /><p>从任务页选取已核对来源，创建第一个单元。</p></div>}</>}
      {stage === "preview" && <><div className="actions mb-5">{draftPicker}{draft && <Button variant="outline" asChild><a href={`/api/drafts/${draft.id}/preview`} target="_blank" rel="noreferrer">打开阅读版 / 浏览器打印 PDF</a></Button>}</div>{draft ? <><p className="muted small">显示已保存内容。此预览尚未提供专业分页、公式输入器与图形重绘。</p><iframe className="book-preview" title="小册子阅读预览" key={`${draft.id}-${draft.revision}-${draft.approved}`} src={`/api/drafts/${draft.id}/preview`} sandbox="allow-same-origin allow-modals" /></> : <div className="empty"><BookOpen /><p>选择一个单元查看学生阅读版。</p></div>}</>}
      {stage === "releases" && <><section className="surface"><h2>创建本地交付版本</h2><p className="muted">审核通过后固定内容与来源快照。此操作不向互联网发布；下载的 HTML 可离线打开、留存或打印。</p><div className="actions">{draftPicker}<Button onClick={release} disabled={busy || !draft?.approved}>保存交付快照</Button></div><p className="muted small mt-4">当前状态：{draft ? `修订 ${draft.revision} · ${draft.approved ? "已批准" : "待审核"}` : "尚未选择单元"}</p></section><h2 className="mt-8">已保存版本</h2>{releases.map(r => <div className="document-row" key={r.id}><Package size={21} /><div className="flex-1 min-w-0"><h3>{drafts.find(d => d.id === r.draft_id)?.title || "小册子"} · 修订 {r.revision}</h3><p className="muted small">{date(r.created_at)} · {r.id.slice(0, 8)}</p></div><Button variant="outline" asChild><a href={`/api/releases/${r.id}/download`}>下载离线读物</a></Button></div>)}{!releases.length && <div className="empty"><Package /><p>尚无交付版本。先完成编辑与人工审核。</p></div>}</>}
      </main><footer className="workspace-footer">Mathlet · 知识准确，关系有据，路径开放。<span>本地单工作区 · 无联网发布</span></footer>
    </div>
  </div>
}
