import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { api, json, type Block, type Document } from "@/lib/api"

type Task={id:string;revision:number;title:string;document_id:string;status:string;error:string;stale:boolean;plan_id:string|null;model:{model:string;base_url:string};calls:{step:string;status:string;reserved_tokens:number;error:string}[]}
export default function PlanningAIImport({documents,disabled,onOpen}:{documents:Document[];disabled:boolean;onOpen:(id:string)=>Promise<void>}){
  const [doc,setDoc]=useState(""),[title,setTitle]=useState("初中数学领域与主题规划"),[instruction,setInstruction]=useState(""),[consent,setConsent]=useState(false),[limit,setLimit]=useState(80)
  const [tasks,setTasks]=useState<Task[]>([]),[taskId,setTaskId]=useState(""),[blocks,setBlocks]=useState<Block[]>([]),[loadedDoc,setLoadedDoc]=useState("")
  const [busy,setBusy]=useState(false),[message,setMessage]=useState("")
  const [provider,setProvider]=useState<{ready:boolean;model:string;base_url:string;output_token_budget:number}|null>(null)
  useEffect(()=>{let alive=true;async function load(){try{const [p,t]=await Promise.all([api<typeof provider>("/knowledge/provider"),api<Task[]>("/planning-ai/runs")]);if(alive){setProvider(old=>{if(old&&p&&(old.model!==p.model||old.base_url!==p.base_url))setConsent(false);return p});setTasks(t)}}catch(e){if(alive)setMessage(String(e))}}void load();const timer=setInterval(()=>void load(),3000);return()=>{alive=false;clearInterval(timer)}},[])
  useEffect(()=>{let alive=true;setLoadedDoc("");setBlocks([]);setConsent(false);if(doc)void api<Block[]>(`/documents/${doc}/blocks`).then(value=>{if(alive){setBlocks(value);setLoadedDoc(doc)}}).catch(e=>{if(alive)setMessage(String(e))});return()=>{alive=false}},[doc])
  const task=tasks.find(x=>x.id===taskId)
  async function act(fn:()=>Promise<void>){setBusy(true);setMessage("");try{await fn()}catch(e){setMessage(String(e))}finally{setBusy(false)}}
  return <section className="surface"><h2>用 AI 构建领域与二级主题</h2><p className="muted small">读取已导入资料的全部提取正文，生成可核对、可编辑、可定稿的分类和主题。学习要求保留来源引文，目标拆解单独作为 AI 建议。每次生成建立新规划，保留旧规划。</p>
    <label htmlFor="ai-plan-source">AI 规划来源资料</label><select id="ai-plan-source" value={doc} disabled={busy||disabled} onChange={e=>setDoc(e.target.value)}><option value="">选择已读取的课标摘要、教材或知识资料</option>{documents.filter(x=>x.status==="ready").map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select>
    <label htmlFor="ai-plan-title">AI 规划名称</label><input id="ai-plan-title" value={title} disabled={busy||disabled} onChange={e=>setTitle(e.target.value)}/>
    <label htmlFor="ai-plan-instruction">分类要求（可留空）</label><textarea id="ai-plan-instruction" value={instruction} disabled={busy||disabled} onChange={e=>setInstruction(e.target.value)} placeholder="例如：以领域作为一级分类，将主要内容组织为适合复习的二级主题，保留对应学习要求。"/>
    <label htmlFor="ai-plan-limit">二级主题数量上限</label><input id="ai-plan-limit" type="number" min={1} max={120} value={limit} disabled={busy||disabled} onChange={e=>setLimit(Number(e.target.value))}/>
    <p className="small muted">模型：{provider?.ready?`${provider.model} · ${provider.base_url}`:"尚未配置，请先在“知识与关系”中保存模型服务"}。本任务预留8000输出 tokens；不是完整性标准，也不代表官方课标核验。</p>
    {loadedDoc===doc&&doc&&<details><summary>本次将发送的提取正文 · {blocks.length} 个块／{blocks.reduce((n,b)=>n+b.text.length,0)} 字符</summary>{blocks.map(b=><div key={b.id} className="bridge"><p>{b.locator} · {b.verified?"来源已核对":"来源尚未核对"}</p><pre className="knowledge-json">{b.text}</pre></div>)}</details>}
    <Button variant="ghost" disabled={busy||disabled||!doc} onClick={()=>act(async()=>{setConsent(false);setBlocks(await api<Block[]>(`/documents/${doc}/blocks`));setLoadedDoc(doc)})}>刷新待发送正文</Button>
    <label className="checkline"><input type="checkbox" checked={consent} disabled={busy||disabled||!doc||loadedDoc!==doc} onChange={e=>setConsent(e.target.checked)}/>确认向已保存模型发送该资料的全部提取正文与规划要求</label>
    <Button disabled={busy||disabled||!consent||!title.trim()||!doc||loadedDoc!==doc||!provider?.ready} onClick={()=>act(async()=>{const result=await api<Task>("/planning-ai/runs",json("POST",{document_id:doc,source_revisions:Object.fromEntries(blocks.map(b=>[b.id,b.revision])),title,instruction,max_topics:limit,consent}));setTasks(old=>[result,...old]);setTaskId(result.id);setConsent(false)})}>AI 构建待审核规划</Button>
    <label htmlFor="ai-plan-task">AI 规划任务</label><select id="ai-plan-task" value={taskId} onChange={e=>setTaskId(e.target.value)}><option value="">选择构建任务</option>{tasks.map(t=><option key={t.id} value={t.id}>{t.title} · {t.status} · {t.id.slice(0,6)}</option>)}</select>
    {task&&<><p role="status">{task.status==="completed"?"候选规划已生成，尚未定稿":task.status==="running"?"模型正在构建规划":task.status==="queued"?"已排队":task.status==="interrupted"?"任务已中断": "构建失败"}</p>{task.stale&&<p className="notice">来源已有变化，旧任务只供参考，请重新构建。</p>}{task.error&&<p role="alert">{task.error}</p>}{task.plan_id&&<Button disabled={busy} onClick={()=>act(()=>onOpen(task.plan_id!))}>打开生成规划进行核对</Button>}{["failed","interrupted"].includes(task.status)&&<Button variant="outline" disabled={busy||task.stale} onClick={()=>act(async()=>{const value=await api<Task>(`/planning-ai/runs/${task.id}/retry`,json("POST",{revision:task.revision}));setTasks(old=>old.map(t=>t.id===value.id?value:t))})}>重试未完成的构建</Button>}<details><summary>调用与预算记录</summary>{task.calls.map((c,i)=><p key={i}>{c.step} · {c.status} · 预留 {c.reserved_tokens} tokens · {c.error}</p>)}<a href={`/api/knowledge/runs/${task.id}/artifacts`} target="_blank" rel="noreferrer">查看输入快照与模型原始返回</a></details></>}
    {message&&<p className="feedback" role="alert">{message}</p>}
  </section>
}
