import { useEffect, useState, type ReactNode } from "react"
import { Check, ListTree, Plus, Save } from "lucide-react"
import PlanningAIImport from "./PlanningAIImport"
import { Button } from "@/components/ui/button"
import { api, json, type Block, type Document, type Draft } from "@/lib/api"

type Node = { id: string; parent_id: string | null; kind: "book" | "chapter" | "section" | "topic" | "activity" | "domain"; title: string; source_id: string | null; source_url: string; included: boolean; source_excerpt?:string }
type Unit = { id: string; title: string; kind: "foundation" | "connection" | "practice"; volume: string; goals: string; node_ids: string[] }
type Requirement = { origin?:"source_excerpt"|"official_excerpt"; id: string; text: string; source_id: string; unit_ids: string[] }
type Payload = { mode?:string; document_id: string; nodes: Node[]; units: Unit[]; requirements: Requirement[]; notes: string; skipped_lines: number; skipped_entries?: { source_id: string; text: string; locator: string }[] }
type Plan = { id: string; title: string; payload: Payload; revision: number; confirmed: boolean; warnings: string[]; stale_sources: string[]; reviewer: string | null; draft_links: { unit_id: string; draft_id: string; plan_revision: number }[] }
const names = { book: "册次", chapter: "章", section: "节", topic: "小节", activity: "学习栏目", domain:"领域" }
const unitNames = { foundation: "基础复习", connection: "跨章连接", practice: "综合训练" }

export default function PlanningPage({ documents, openSource, openDraft, openKnowledge, onDirtyChange }: { onDirtyChange?:(dirty:boolean)=>void; openKnowledge?: (id:string)=>void; documents: Document[]; openSource: (doc: string, block: string) => void; openDraft: (draft: Draft) => void }) {
  const [plans, setPlans] = useState<Plan[]>([])
  const [plan, setPlan] = useState<Plan | null>(null)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  const [documentId, setDocumentId] = useState("")
  const [importTitle, setImportTitle] = useState("初中数学复习内容规划")
  const [tab, setTab] = useState("tree")
  const [selected, setSelected] = useState("")
  const [unitId, setUnitId] = useState("")
  const [reviewer, setReviewer] = useState("")
  const [ack, setAck] = useState(false)
  const [standardDoc, setStandardDoc] = useState("")
  const [standardBlocks, setStandardBlocks] = useState<Block[]>([])
  const [standardId, setStandardId] = useState("")
  const [quote, setQuote] = useState("")
  useEffect(()=>{onDirtyChange?.(dirty);return()=>onDirtyChange?.(false)},[dirty,onDirtyChange])
  useEffect(()=>{const warn=(e:BeforeUnloadEvent)=>{if(dirty){e.preventDefault();e.returnValue=""}};window.addEventListener("beforeunload",warn);return()=>window.removeEventListener("beforeunload",warn)},[dirty])
  async function reload() {
    const result = await api<Plan[]>("/plans"); setPlans(result); return result
  }
  useEffect(() => { void reload().catch(e => setMessage(String(e))) }, [])
  useEffect(() => {
    let live = true; setStandardBlocks([]); setStandardId(""); setQuote("")
    if (standardDoc) api<Block[]>(`/documents/${standardDoc}/blocks`).then(b => { if (live) setStandardBlocks(b) }).catch(e => setMessage(String(e)))
    return () => { live = false }
  }, [standardDoc])
  const payload = plan?.payload
  const aiMode=payload?.mode==="ai_curriculum"
  const node = payload?.nodes.find(n => n.id === selected)
  const unit = payload?.units.find(u => u.id === unitId)
  function change(fn: (p: Payload) => Payload) {
    setPlan(old => old ? { ...old, payload: fn(old.payload), confirmed: false } : old); setDirty(true); setAck(false)
  }
  function setNode(patch: Partial<Node>) { change(p => {const nodes=p.nodes.map(n => n.id===selected?{...n,...patch}:n);return {...p,nodes,units:p.mode==="ai_curriculum"?p.units.map(u=>{const topic=nodes.find(n=>u.node_ids.includes(n.id));return topic?{...u,title:topic.title,volume:nodes.find(n=>n.id===topic.parent_id)?.title||""}:u}):p.units}}) }
  function moveNode(direction:number){change(p=>{const list=[...p.nodes];const peers=list.filter(n=>n.parent_id===node?.parent_id);const index=peers.findIndex(n=>n.id===selected);const other=peers[index+direction];if(!other)return p;const a=list.findIndex(n=>n.id===selected),b=list.findIndex(n=>n.id===other.id);[list[a],list[b]]=[list[b],list[a]];return {...p,nodes:list}})}
  function addNode(kind:"domain"|"topic"){const id=crypto.randomUUID();change(p=>({...p,nodes:[...p.nodes,{id,parent_id:kind==="domain"?null:node!.id,kind,title:kind==="domain"?"新增领域":"新增二级主题",source_id:null,source_url:"",source_excerpt:"",included:true}],units:kind==="topic"?[...p.units,{id:crypto.randomUUID(),title:"新增二级主题",kind:"foundation",volume:node!.title,goals:"",node_ids:[id]}]:p.units}));setSelected(id)}
  function setUnit(patch: Partial<Unit>) { change(p => ({ ...p, units: p.units.map(u => u.id === unitId ? { ...u, ...patch } : u) })) }
  function choose(p: Plan) { setPlan(p); setDirty(false); setSelected(p.payload.nodes[0]?.id || ""); setUnitId(p.payload.units[0]?.id || ""); setAck(false); setMessage("") }
  async function action(kind: "import" | "save" | "confirm" | "draft") {
    setBusy(true); setMessage("")
    try {
      if (kind === "import") {
        if (dirty && !window.confirm("当前规划有未保存修改。仍要导入新规划？")) return
        const result = await api<Plan>("/plans", json("POST", { document_id: documentId, title: importTitle })); choose(result); await reload()
        setMessage("已按目录编号识别候选树。未自动合并重复章号，请对照原件确认。")
      } else if (plan && kind === "save") {
        const result = await api<Plan>(`/plans/${plan.id}`, json("PUT", { revision: plan.revision, title: plan.title, ...plan.payload }))
        setPlan(result); setDirty(false); setAck(false); await reload(); setMessage("规划已保存；结构确认和关联草稿的旧批准已撤销。")
      } else if (plan && kind === "confirm") {
        const result = await api<Plan>(`/plans/${plan.id}/confirm`, json("POST", { revision: plan.revision, reviewer, acknowledged: ack }))
        setPlan(result); await reload(); setMessage("当前规划已确认。此状态不表示课标全部覆盖或数学正文已审核。")
      } else if (plan && unit) {
        const result = await api<Draft>(`/plans/${plan.id}/units/${unit.id}/draft`, json("POST", { revision: plan.revision }))
        openDraft(result)
      }
    } catch (e) { setMessage(String(e)) } finally { setBusy(false) }
  }
  function tree(parent: string | null): ReactNode {
    return payload?.nodes.filter(n => n.parent_id === parent).map(n => {
      const children = payload.nodes.some(c => c.parent_id === n.id)
      const title = <button className={`tree-node ${n.id === selected ? "chosen" : ""} ${!n.included ? "excluded" : ""}`} onClick={() => {setSelected(n.id);const u=payload.units.find(u=>u.node_ids.includes(n.id));if(u)setUnitId(u.id)}}><span>{n.title}</span><small>{!n.included ? "不纳入" : aiMode&&n.kind==="topic"?"二级主题":names[n.kind]}</small></button>
      return children ? <details key={n.id} open={n.kind === "book"||n.kind==="domain"}><summary>{title}</summary><div className="tree-children">{tree(n.id)}</div></details> : <div key={n.id} className="tree-leaf">{title}</div>
    })
  }
  function isDescendant(id: string, ancestor: string): boolean {
    let at: string | null = id
    while (at) { if (at === ancestor) return true; at = payload?.nodes.find(n => n.id === at)?.parent_id || null }
    return false
  }
  return <>
    <p className="muted mb-5">用 AI 从导入资料提出领域、二级主题与学习要求对应，核对编辑后定稿，再按主题生成知识。教材目录规则识别作为另一种导入方式保留。</p>
    <PlanningAIImport documents={documents} disabled={busy||dirty} onOpen={async id=>{if(dirty&&!window.confirm("当前规划有未保存修改，放弃后打开新规划？"))return;const list=await reload();const next=list.find(p=>p.id===id);if(next){choose(next);setTab("tree")}}}/>
    <section className="surface"><h2>导入教材目录</h2><p className="muted small">使用已完成读取的 DOCX/PDF。识别“七年级上册”“第X章”“1.2 / 1.2.1”等分行标题；不会访问文件里的网页链接。重复导入创建新规划，原规划保留。</p>
      <div className="actions"><select aria-label="目录来源" value={documentId} onChange={e => setDocumentId(e.target.value)}><option value="">选择已读取的目录资料</option>{documents.filter(d => d.status === "ready").map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select><input aria-label="新规划名称" className="search" value={importTitle} onChange={e => setImportTitle(e.target.value)} /><Button onClick={() => action("import")} disabled={busy || !documentId || !importTitle.trim()}><ListTree />识别目录树</Button></div>
    </section>
    {plans.length > 0 && <div className="actions mb-5"><select aria-label="选择内容规划" value={plan?.id || ""} onChange={e => { if (!dirty || window.confirm("有未保存修改，是否放弃并切换？")) { const p = plans.find(x => x.id === e.target.value); if (p) choose(p) } }}><option value="">选择已有规划</option>{plans.map(p => <option key={p.id} value={p.id}>{p.title} · 修订 {p.revision}</option>)}</select><Button variant="outline" disabled={busy} onClick={async () => { if (dirty && !window.confirm("重新载入将放弃未保存修改，继续？")) return; try { const list = await reload(); const next = list.find(p => p.id === plan?.id); if (next) choose(next) } catch (e) { setMessage(String(e)) } }}>重新载入</Button></div>}
    {message && <p className="feedback" role="status">{message}</p>}
    {plan && payload ? <>
      {plan.stale_sources.length > 0 && <div className="notice" role="alert">来源已有修改，当前规划不能继续确认或创建新稿。请保留需要的规划内容，重新导入资料建立新规划；旧规划不删除。</div>}
      <section className="surface"><div className="section-heading"><h2>{plan.title}</h2><span className="label">修订 {plan.revision} · {dirty ? "修改未保存" : plan.confirmed ? "结构已确认" : "待确认"}</span></div><div className="planning-tabs" aria-label="规划步骤">{[["tree", aiMode?"1 领域与二级主题":"1 教材章节树"], ["units", aiMode?"2 主题目标与知识生成":"2 小册子单元"], ["coverage", aiMode?"3 来源学习要求":"3 课标对应"], ["confirm", "4 核对与确认"]].map(([id, title]) => <Button key={id} variant={tab === id ? "default" : "outline"} onClick={() => setTab(id)}>{title}</Button>)}</div></section>
      {tab === "tree" && <div className="two-column"><section className="surface"><h2>{aiMode?"领域与二级主题":"教材原有目录"}</h2>{aiMode&&<Button variant="outline" onClick={()=>addNode("domain")}>新增领域</Button>}<p className="muted small">{payload.nodes.length} 个条目。点击条目核对、编辑归属与名称；引用保留供对照。</p><div className="catalog-tree">{tree(null)}</div></section><section className="surface planning-detail"><h2>条目调整</h2>{node ? <><label htmlFor="node-title">名称</label><input id="node-title" value={node.title} onChange={e => setNode({ title: e.target.value })} /><label htmlFor="node-kind">类型</label><select id="node-kind" disabled={aiMode} value={node.kind} onChange={e => setNode({ kind: e.target.value as Node["kind"] })}>{Object.entries(names).filter(([k])=>!aiMode||["domain","topic"].includes(k)).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select><label htmlFor="node-parent">上级条目</label><select id="node-parent" disabled={aiMode&&node.kind==="domain"} value={node.parent_id || ""} onChange={e => setNode({ parent_id: e.target.value || null })}><option value="">顶层</option>{payload.nodes.filter(n => !isDescendant(n.id, node.id)&&(!aiMode||n.kind==="domain")).map(n => <option key={n.id} value={n.id}>{n.title}</option>)}</select><label className="checkline"><input type="checkbox" checked={node.included} onChange={e => setNode({ included: e.target.checked })} />{aiMode?"纳入本条目（所属领域未纳入时，该主题也不进入知识生成）":"纳入本条目（不自动排除下级；有关联单元时需先解除关联）"}</label>{node.source_url && <a href={node.source_url} target="_blank" rel="noreferrer">打开教材网页链接</a>}<div className="actions">{node.source_id && <Button variant="outline" onClick={() => { if (!dirty || window.confirm("请先保存规划修改。仍要进入来源核对？")) openSource(payload.document_id, node.source_id!) }}>查看对应来源块</Button>}<Button variant="outline" disabled={aiMode&&node.kind!=="domain"} onClick={() => { if(aiMode){addNode("topic");return} const id = crypto.randomUUID(); change(p => ({ ...p, nodes: [...p.nodes, { id, parent_id: node.id, kind: "topic", title: "人工补充条目", source_id: null, source_url: "", included: true }] })); setSelected(id) }}><Plus />补充下级条目</Button>{aiMode&&<><Button variant="ghost" onClick={()=>moveNode(-1)}>上移条目</Button><Button variant="ghost" onClick={()=>moveNode(1)}>下移条目</Button></>}</div>{aiMode&&<><label>来源对应文字</label><p className="whitespace-pre-wrap">{node.source_excerpt||"人工补充；无来源引文"}</p>{node.kind==="topic"&&(()=>{const u=payload.units.find(u=>u.node_ids.includes(node.id));return u?<><label htmlFor="topic-goals">本主题学习目标对应建议（AI 起草，可编辑）</label><textarea id="topic-goals" value={u.goals} onChange={e=>change(p=>({...p,units:p.units.map(x=>x.id===u.id?{...x,goals:e.target.value}:x)}))}/><label>关联的来源学习要求</label>{payload.requirements.map(req=><label className="checkline" key={req.id}><input type="checkbox" checked={req.unit_ids.includes(u.id)} onChange={e=>change(p=>({...p,requirements:p.requirements.map(r=>r.id===req.id?{...r,unit_ids:e.target.checked?[...r.unit_ids,u.id]:r.unit_ids.filter(id=>id!==u.id)}:r)}))}/>{req.text}</label>)}</>:null})()}</>}
<p className="muted small mt-4">{node.source_id ? "来源绑定保留，编辑标题不会改动原始材料。" : "人工补充，无教材原文来源；不能当作已核实知识。"}</p></> : <p>选择一个条目。</p>}</section></div>}
      {tab === "units" && <div className="two-column"><section className="surface"><div className="section-heading"><h2>小册子的阅读结构</h2><Button size="sm" variant="outline" disabled={aiMode} onClick={() => { const id = crypto.randomUUID(); change(p => ({ ...p, units: [...p.units, { id, title: "新单元", kind: "foundation", volume: "", goals: "", node_ids: [] }] })); setUnitId(id) }}><Plus />增加单元</Button></div><p className="muted small">{aiMode?"每个二级主题对应一个知识生成单元；名称和所属领域在分类树中维护，学习目标在此核对。":"一个单元可以连接多个教材章节；多个单元也可引用同一知识。按下方顺序编排，不强制照搬教材。"}</p>{payload.units.map((u, index) => <div key={u.id} className="unit-row"><button className={unitId === u.id ? "selected-unit" : ""} onClick={() => setUnitId(u.id)}>{u.title}<small>{u.volume || "分册待填"} · {unitNames[u.kind]} · {u.node_ids.length} 项关联</small></button><Button variant="ghost" size="sm" disabled={index === 0} onClick={() => change(p => { const list = [...p.units]; [list[index - 1], list[index]] = [list[index], list[index - 1]]; return { ...p, units: list } })}>上移</Button></div>)}{!payload.units.length && <div className="empty">从一个基础单元或跨章专题开始。</div>}</section><section className="surface">{unit ? <><h2>{aiMode?"二级主题安排":"单元安排"}</h2><label htmlFor="unit-title">单元标题</label><input id="unit-title" disabled={aiMode} value={unit.title} onChange={e => setUnit({ title: e.target.value })} /><label htmlFor="unit-volume">{aiMode?"所属领域":"所属分册"}</label><input id="unit-volume" disabled={aiMode} value={unit.volume} onChange={e => setUnit({ volume: e.target.value })} placeholder="例如：函数与图像" /><label htmlFor="unit-kind">单元类型</label><select id="unit-kind" value={unit.kind} onChange={e => setUnit({ kind: e.target.value as Unit["kind"] })}>{Object.entries(unitNames).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select><label htmlFor="unit-goals">学习目标与编写说明</label><textarea id="unit-goals" value={unit.goals} onChange={e => setUnit({ goals: e.target.value })} placeholder="例如：能解释对角线中点相同如何建立坐标关系。" /><label htmlFor="unit-link">增加教材知识关联</label><select id="unit-link" disabled={aiMode} value="" onChange={e => { if (e.target.value) setUnit({ node_ids: [...new Set([...unit.node_ids, e.target.value])] }) }}><option value="">选择条目，可跨章关联</option>{payload.nodes.filter(n => n.included && n.kind !== "book").map(n => <option key={n.id} value={n.id}>{n.title}</option>)}</select><div className="linked-items">{unit.node_ids.map(id => <div key={id}><span>{payload.nodes.find(n => n.id === id)?.title}</span><Button variant="ghost" size="sm" disabled={aiMode} onClick={() => setUnit({ node_ids: unit.node_ids.filter(x => x !== id) })}>解除</Button></div>)}</div>{openKnowledge&&<Button disabled={busy||dirty||!plan.confirmed} onClick={async()=>{setBusy(true);try{const result=await api<{id:string}>("/knowledge/units/from-plan",json("POST",{plan_id:plan.id,unit_id:unit.id,plan_revision:plan.revision}));openKnowledge(result.id)}catch(e){setMessage(String(e))}finally{setBusy(false)}}}>按此主题进入知识生成</Button>}<Button disabled={busy || dirty || !plan.confirmed} onClick={() => action("draft")}>进入编辑提纲</Button><p className="muted small mt-4">先保存并确认规划，再核对关联来源。已有提纲只打开原稿，不覆盖人工修改。修改规划后请在原稿中人工同步。</p></> : <p className="muted">新建或选择一个单元。</p>}</section></div>}
      {tab === "coverage" && <>
        <div className="notice">这里记录“课标要求计划由哪些单元承接”，不表示学生已掌握或教学覆盖已审核。没有录入要求时，系统不能判断全册覆盖率。</div>
        <section className="surface"><h2>从已核对课标摘录要求</h2><div className="actions"><select aria-label="课标资料" value={standardDoc} onChange={e => setStandardDoc(e.target.value)}><option value="">选择课标／考纲资料</option>{documents.filter(d => d.category === "standard" && d.status === "ready").map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select><select aria-label="课标来源块" value={standardId} onChange={e => { setStandardId(e.target.value); setQuote(standardBlocks.find(b => b.id === e.target.value)?.text || "") }}><option value="">选择已核对内容块</option>{standardBlocks.filter(b => b.verified).map(b => <option key={b.id} value={b.id}>{b.locator} · {b.text.slice(0, 50)}</option>)}</select></div><p className="muted small">请先在资料包中以“课标／考纲”类别上传，并在原题核对页确认。可选取原文的一部分，但不得改写为自拟课标。</p><label htmlFor="requirement-quote">要求原文</label><textarea id="requirement-quote" value={quote} onChange={e => setQuote(e.target.value)} /><Button disabled={!standardId || !quote.trim()} onClick={() => { const source = standardBlocks.find(b => b.id === standardId); if (!source?.text.includes(quote)) { setMessage("请逐字摘录已核对来源中的文字。"); return } change(p => ({ ...p, requirements: [...p.requirements, { id: crypto.randomUUID(), source_id: standardId, text: quote, unit_ids: [] }] })); setQuote("") }}>加入待对应要求</Button></section>
        {payload.requirements.map(req => <section className="surface" key={req.id}><div className="section-heading"><h2>{req.unit_ids.length ? "已安排单元" : "尚未安排"}</h2><span>{req.origin==="source_excerpt"?"导入资料中的学习要求摘录；不是自动核验的官方原文":"已核对课标摘录"}</span><span className="label">计划对应 · 未评估内容质量</span></div><p className="whitespace-pre-wrap">{req.text}</p>{payload.units.map(u => <label key={u.id} className="checkline"><input type="checkbox" checked={req.unit_ids.includes(u.id)} onChange={e => change(p => ({ ...p, requirements: p.requirements.map(r => r.id === req.id ? { ...r, unit_ids: e.target.checked ? [...r.unit_ids, u.id] : r.unit_ids.filter(id => id !== u.id) } : r) }))} />{u.title}</label>)}{!payload.units.length && <p className="muted">请先建立小册子单元。</p>}</section>)}
      </>}
      {tab === "confirm" && <section className="surface"><h2>疑问与范围记录</h2><div className="warnings">{plan.warnings.map(w => <p key={w}>{w}</p>)}</div><p className="muted small">提示来自上次保存后的结构；修改后请先保存，以重新计算。条目被排除只影响当前规划，不代表该内容不属于中考范围。</p><details className="my-5"><summary>查看未识别行（含说明文字）</summary>{payload.skipped_entries?.map((item, i) => <div key={i} className="bridge"><p className="small">{item.text}</p><Button variant="ghost" size="sm" onClick={() => { if (!dirty || window.confirm("请先保存修改。仍要核对来源？")) openSource(payload.document_id, item.source_id) }}>{item.locator} · 查看来源</Button></div>)}</details><label htmlFor="plan-notes">人工判断与待补材料</label><textarea id="plan-notes" value={payload.notes} onChange={e => change(p => ({ ...p, notes: e.target.value }))} placeholder="例如：九下来源版本待确认；概率单元资料待补。" /><label htmlFor="planner">确认人</label><input id="planner" value={reviewer} onChange={e => setReviewer(e.target.value)} /><label className="checkline"><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} />{aiMode?"我已核对领域、二级主题、来源引文与学习要求对应；此确认不代表全册课标完整或数学正文正确":"我已核对结构、了解重复号及遗漏提示；此确认不代表全册课标完整或数学内容正确"}</label><Button disabled={busy || dirty || !ack || !reviewer.trim() || !!plan.stale_sources.length} onClick={() => action("confirm")}><Check />确认当前规划</Button></section>}
      <div className="actions planning-save"><Button onClick={() => action("save")} disabled={busy || !dirty || !!plan.stale_sources.length}><Save />保存规划修改</Button><span className="muted small">{dirty ? "修改尚未保存，确认前请保存。" : "当前修改已保存。"}</span></div>
    </> : <div className="empty"><ListTree /><p>先上传资料，读取完成后用 AI 构建领域与主题，或选择传统目录识别。</p></div>}
  </>
}
