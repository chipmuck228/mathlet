import {useCallback,useEffect,useRef,useState} from 'react'
import {api,json,type Document} from '@/lib/api'
import {Button} from '@/components/ui/button'
import ReadableMath from './ReadableMath'
import CompleteQuestionEditor from './CompleteQuestionEditor'
import ResearchManuscriptPage from './ResearchManuscriptPage'
import QuestionBankPage from './QuestionBankPage'
import type {Question as CompleteQuestion} from './ResearchManuscriptTypes'
import CorpusQuestionRow,{type CorpusQuestion} from './CorpusQuestionRow'
import {CardEditor,type Card} from './PaperResearchPage'
type Question=CorpusQuestion
type Catalog={exams:{id:string;title:string;filename:string;category:string;count:number;stale:boolean}[];questions:Question[]}
type Link={ref:string;role:'primary'|'support'|'method'|'check';reason:string;evidence:string}
type MappingBody={links:Link[];gaps:string[];summary:string}
type Mapping={question_title?:string;id:string;analysis_version_id:string;revision:number;status:string;error:string;stale:boolean;read_only:boolean;payload:MappingBody|null;run_revision:number;finals:{id:string;revision:number}[];knowledge:{ref:string;title:string;unit_title:string}[]}
type Task={summary?:string;id:string;revision:number;status:string;error:string;stale:boolean;cards:(Card&{project_id:string})[]}
const states:Record<string,string>={queued:'排队中',running:'研究中',completed:'研究稿已就绪',failed:'失败',interrupted:'中断'}
const roles={primary:'主要考察',support:'辅助知识',method:'思考方法',check:'结果检验'}
function MappingEditor({mapping,onDirty,onReload,blocked=false}:{blocked?:boolean;mapping:Mapping;onDirty:(id:string,value:boolean)=>void;onReload:()=>Promise<void>}){
 const [body,setBody]=useState(mapping.payload!),[confirm,setConfirm]=useState(false),[busy,setBusy]=useState(false),[editing,setEditing]=useState(false),[error,setError]=useState('')
 const dirty=JSON.stringify(body)!==JSON.stringify(mapping.payload),locked=blocked||busy||mapping.stale||mapping.read_only
 useEffect(()=>{onDirty(mapping.id,dirty);return()=>onDirty(mapping.id,false)},[mapping.id,dirty,onDirty])
 function change(value:MappingBody){setBody(value);setConfirm(false)}
 async function act(action:()=>Promise<unknown>){setBusy(true);setError('');try{await action();await onReload()}catch(e){setError(String(e))}finally{setBusy(false)}}
 return <section className="surface"><h3>知识关联 · {mapping.read_only?'终稿':'工作稿'}</h3><p className="small muted">研究终稿：{mapping.question_title||mapping.analysis_version_id}；关联单独保存，不修改解题研究。</p>{mapping.stale&&<p role="alert">研究或知识依据已变化；请选择新版本重新匹配，无需重新解题。</p>}
 <Button variant="outline" disabled={locked} onClick={()=>setEditing(!editing)}>{editing?'浏览关联':'编辑关联'}</Button>
 {editing?<><label>关联总结<textarea aria-label="关联总结" disabled={locked} value={body.summary} onChange={e=>change({...body,summary:e.target.value})}/></label>
 {body.links.map((link,i)=><fieldset key={i} disabled={locked}><legend>关联 {i+1}</legend><label>知识<select aria-label="关联知识" value={link.ref} onChange={e=>change({...body,links:body.links.map((x,j)=>j===i?{...x,ref:e.target.value}:x)})}>{mapping.knowledge.map(k=><option key={k.ref} value={k.ref}>{k.unit_title} / {k.title}</option>)}</select></label><label>作用<select aria-label="关联作用" value={link.role} onChange={e=>change({...body,links:body.links.map((x,j)=>j===i?{...x,role:e.target.value as Link['role']}:x)})}>{Object.entries(roles).map(([v,label])=><option key={v} value={v}>{label}</option>)}</select></label><label>匹配理由<textarea aria-label="匹配理由" value={link.reason} onChange={e=>change({...body,links:body.links.map((x,j)=>j===i?{...x,reason:e.target.value}:x)})}/></label><label>题目或研究中的依据<textarea aria-label="匹配依据" value={link.evidence} onChange={e=>change({...body,links:body.links.map((x,j)=>j===i?{...x,evidence:e.target.value}:x)})}/></label><Button variant="ghost" onClick={()=>change({...body,links:body.links.filter((_,j)=>j!==i)})}>移除此关联</Button></fieldset>)}
 <Button variant="outline" disabled={locked||!mapping.knowledge.length} onClick={()=>change({...body,links:[...body.links,{ref:mapping.knowledge[0].ref,role:'support',reason:'',evidence:''}]})}>增加知识关联</Button>
 <label>知识缺口（每行一项，不自动修改知识终稿）<textarea aria-label="知识缺口" disabled={locked} value={body.gaps.join('\n')} onChange={e=>change({...body,gaps:e.target.value.split('\n').filter(Boolean)})}/></label></>:<><ReadableMath text={body.summary}/>{body.links.map((l,i)=><article key={i}><h4>{mapping.knowledge.find(k=>k.ref===l.ref)?.unit_title} / {mapping.knowledge.find(k=>k.ref===l.ref)?.title} · {roles[l.role]}</h4><ReadableMath text={l.reason}/><blockquote><ReadableMath text={l.evidence}/></blockquote></article>)}{body.gaps.map((g,i)=><p className="notice" key={i}>知识缺口：<ReadableMath text={g}/></p>)}</>}

 <Button disabled={locked||!dirty} onClick={()=>void act(()=>api('/corpus/mappings/'+mapping.id,json('PUT',{revision:mapping.revision,body})))}>保存关联修改</Button>
 {!mapping.read_only?<><label className="checkline"><input type="checkbox" aria-label="确认知识关联" disabled={busy||mapping.stale||dirty} checked={confirm} onChange={e=>setConfirm(e.target.checked)}/>我已核对知识作用、依据与缺口</label><Button disabled={busy||mapping.stale||dirty||!confirm} onClick={()=>void act(()=>api('/corpus/mappings/'+mapping.id+'/finalize',json('POST',{revision:mapping.revision,confirmed:true})))}>形成关联终稿</Button></>:<Button disabled={busy||mapping.stale} onClick={()=>void act(()=>api('/corpus/mappings/'+mapping.id+'/revise',json('POST',{revision:mapping.revision,confirmed:true})))}>继续修订关联</Button>}
 {mapping.finals.map(f=><p key={f.id}><a href={'/api/corpus/mapping-versions/'+f.id+'/download'}>下载关联终稿 · 修订 {f.revision}</a></p>)}{error&&<p role="alert">{error}；修改保留。</p>}</section>
}
export default function CorpusResearchPage({onDirtyChange,onBusyChange}:{onBusyChange?:(busy:boolean)=>void;onDirtyChange:(value:boolean)=>void}){
 const [panel,setPanel]=useState<{kind:'question'|'study';id:string;title:string}|null>(null),[panelQuestion,setPanelQuestion]=useState<CompleteQuestion|null>(null),[panelDocuments,setPanelDocuments]=useState<Document[]>([]),[panelDirty,setPanelDirty]=useState(false),[panelBusy,setPanelBusy]=useState(false),[bankRefresh,setBankRefresh]=useState(0)
 const panelSerial=useRef(0)
 const [rowBusyIds,setRowBusyIds]=useState<Record<string,boolean>>({})
 const rowsBusy=Object.values(rowBusyIds).some(Boolean)
 const reportRowBusy=useCallback((id:string,value:boolean)=>setRowBusyIds(s=>s[id]===value?s:{...s,[id]:value}),[])
 const [catalog,setCatalog]=useState<Catalog>({exams:[],questions:[]}),[mappings,setMappings]=useState<Mapping[]>([]),[tasks,setTasks]=useState<Task[]>([]),[versions,setVersions]=useState<{id:string;title:string;count:number;stale:boolean}[]>([])
 const [tab,setTab]=useState('questions'),[examIds,setExamIds]=useState<string[]>([]),[selected,setSelected]=useState<string[]>([]),[finals,setFinals]=useState<string[]>([]),[versionIds,setVersionIds]=useState<string[]>([]),[search,setSearch]=useState(''),[unitFilter,setUnitFilter]=useState(''),[instruction,setInstruction]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[dirtyIds,setDirtyIds]=useState<Record<string,boolean>>({})
 const dirty=panelDirty||Object.values(dirtyIds).some(Boolean),dirtyRef=useRef(false),alive=useRef(true),serial=useRef(0),busyRef=useRef(false);busyRef.current=busy||rowsBusy;dirtyRef.current=dirty
 const report=useCallback((id:string,value:boolean)=>setDirtyIds(s=>s[id]===value?s:{...s,[id]:value}),[])
 useEffect(()=>{onBusyChange?.(busy||panelBusy||rowsBusy);return()=>onBusyChange?.(false)},[busy,panelBusy,rowsBusy,onBusyChange])
 useEffect(()=>{onDirtyChange(dirty);return()=>onDirtyChange(false)},[dirty,onDirtyChange])
 useEffect(()=>{const warn=(e:BeforeUnloadEvent)=>{if(dirty||panelBusy||rowsBusy){e.preventDefault();e.returnValue=''}};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn)},[dirty,panelBusy,rowsBusy])
 const load=useCallback(async(force=false)=>{const n=++serial.current;const [c,m,t,v]=await Promise.all([api<Catalog>('/corpus/catalog'),api<Mapping[]>('/corpus/mappings'),api<Task[]>('/corpus/tasks'),api<typeof versions>('/research/knowledge-versions')]);if(!alive.current||n!==serial.current||dirtyRef.current&&!force)return;setCatalog(c);setMappings(m);setTasks(t);setVersions(v)},[])
 useEffect(()=>{alive.current=true;void load().catch(e=>setMessage(String(e)));return()=>{alive.current=false;serial.current++}},[load])
 const pending=catalog.questions.some(q=>q.runs.some(r=>['queued','running'].includes(r.status)))||mappings.some(m=>['queued','running'].includes(m.status))||tasks.some(t=>['queued','running'].includes(t.status))
 useEffect(()=>{if(!pending||dirty)return;let polling=false;const timer=setInterval(async()=>{if(polling||busyRef.current)return;polling=true;try{await load()}catch(e){if(alive.current)setMessage(String(e))}finally{polling=false}},2500);return()=>clearInterval(timer)},[pending,dirty,load])
 async function act(f:()=>Promise<unknown>){setBusy(true);setMessage('');serial.current++;try{const result=await f();await load(true);return result}catch(e){setMessage(String(e))}finally{setBusy(false)}}
 const visible=catalog.questions.filter(q=>examIds.includes(q.exam_id)&&(!search||(q.title+q.statement+q.runs.flatMap(r=>[...r.problem_types,...r.identified_names]).join(' ')).includes(search)))
 const eligible=visible.filter(q=>!q.blockers.length),validFinals=catalog.questions.flatMap(q=>q.runs.filter(r=>!r.stale).flatMap(r=>r.finals.filter(f=>!f.stale).map(f=>({...f,question:q,run:r}))))
 const validSelected=finals.filter(id=>validFinals.some(f=>f.id===id))
 const reportPanelDirty=useCallback((value:boolean)=>setPanelDirty(value),[])
 const reportPanelBusy=useCallback((value:boolean)=>setPanelBusy(value),[])
 function openStudy(id:string,title='单题研究'){
  if(dirty||busy||panelBusy||rowsBusy)return
  serial.current++;setPanelDirty(false);setPanelQuestion(null);setPanel({kind:'study',id,title})
 }
 async function openConditions(id:string,title:string){
  if(dirty||busy||panelBusy||rowsBusy)return
  const n=++panelSerial.current;setBusy(true);serial.current++;setMessage('')
  try{const [question,documents]=await Promise.all([api<CompleteQuestion>('/research/questions/'+id),api<Document[]>('/documents')]);if(!alive.current||n!==panelSerial.current)return;setPanelQuestion(question);setPanelDocuments(documents);setPanelDirty(false);setPanel({kind:'question',id,title})}catch(e){if(alive.current)setMessage(String(e))}finally{if(alive.current&&n===panelSerial.current)setBusy(false)}
 }
 async function closePanel(discard=false){
  if(panelBusy||panelDirty&&!discard)return
  panelSerial.current++;setPanel(null);setPanelQuestion(null);setPanelDirty(false);setBankRefresh(n=>n+1);await act(()=>load(true))
 }
 async function generateQuestion(q:Question){
  const value=await api<{results:{run_id?:string;error?:string}[]}>('/corpus/studies',json('POST',{question_ids:[q.id],instruction}))
  const result=value.results[0]
  if(!result?.run_id)throw Error(result?.error||'未建立研究任务，请刷新题目状态')
  await load(true);setBankRefresh(n=>n+1);return result.run_id
 }
 async function refreshQuestion(){await load(true);setBankRefresh(n=>n+1)}
 const changed=useCallback(()=>{setBankRefresh(n=>n+1)},[])
 const inlinePanel=panel?<section className="corpus-inline-review" aria-label="题库页内核验"><div className="surface"><h1>{panel.kind==='question'?'核对指定题目条件':'单题研究核验与定稿'}</h1><p>{panel.title}</p><div className="actions"><Button disabled={panelDirty||panelBusy} onClick={()=>void closePanel()}>返回题库研究列表</Button>{panelDirty&&<Button variant="outline" disabled={panelBusy} onClick={()=>void closePanel(true)}>放弃未保存编辑并返回</Button>}</div><p className="small muted">保存、确认和定稿均在本页完成；返回后保留试卷选择、筛选和批次。</p></div>
 {panel.kind==='study'?<ResearchManuscriptPage key={panel.id} embedded initialRunId={panel.id} documents={[]} openKnowledge={()=>{}} onDirtyChange={reportPanelDirty} onBusyChange={reportPanelBusy} onChanged={changed}/>:panelQuestion&&<><CompleteQuestionEditor key={panelQuestion.id+'-'+panelQuestion.revision} initial={panelQuestion} documents={panelDocuments} disabled={busy} onBusyChange={reportPanelBusy} onDirty={reportPanelDirty} onSaved={q=>{setPanelQuestion(q);setPanelDirty(false);setMessage(q.confirmed?'当前题目已确认，返回后可发起研究。':'当前题目修改已保存，请继续确认完整性。');changed()}}/></>}{message&&<p role="status" className="feedback">{message}</p>}</section>:null
 return <>{inlinePanel}<div hidden={!!panel}><h1>题库研究</h1><p>先从题目独立求解与归纳，再匹配知识终稿。逐题保存、审核，不必等全部试卷完成。</p><div className="actions" role="tablist">{[['questions','试卷与单题研究'],['mapping','知识关联'],['cards','跨题思路卡'],['bank','统一题库']].map(([id,label])=><Button key={id} role="tab" aria-selected={tab===id} disabled={dirty||busy||rowsBusy} variant={tab===id?'default':'outline'} onClick={()=>setTab(id)}>{label}</Button>)}<Button variant="ghost" disabled={dirty||busy||rowsBusy} onClick={()=>void act(()=>load())}>刷新目录与进度</Button></div>
 {tab==='questions'&&<><section className="surface"><h2>选择已核对试卷终稿</h2>{catalog.exams.map(e=><label className="checkline" key={e.id}><input type="checkbox" disabled={busy||dirty||rowsBusy||e.stale} checked={examIds.includes(e.id)} onChange={event=>{setExamIds(event.target.checked?[...examIds,e.id]:examIds.filter(x=>x!==e.id));setSelected([])}}/>{e.title} · {e.category} · {e.count}题 · {e.filename}{e.stale?' · 来源已变化':''}</label>)}{!catalog.exams.length&&<p>尚无试卷终稿，请先在原题核对中定稿；本地JSON可在那里打开。</p>}<label>搜索题目、已识别知识或题型<input aria-label="搜索题库" disabled={busy||dirty||rowsBusy} value={search} onChange={e=>setSearch(e.target.value)}/></label><label>本批研究要求（可留空，不预设知识范围）<textarea value={instruction} onChange={e=>setInstruction(e.target.value)}/></label>
 <label className="checkline"><input type="checkbox" aria-label="选择当前可研究题目" disabled={busy||dirty||rowsBusy||!eligible.length} checked={!!eligible.length&&eligible.every(q=>selected.includes(q.id))} onChange={e=>setSelected(e.target.checked?eligible.map(q=>q.id):[])}/>选择当前可研究题目</label><Button disabled={busy||dirty||rowsBusy||!selected.length} onClick={()=>void act(async()=>{const r=await api<{results:{error?:string}[]}>('/corpus/studies',json('POST',{question_ids:selected,instruction}));setMessage('已逐题排队或复用现有研究。'+r.results.filter(x=>x.error).map(x=>x.error).join('；'))})}>批量独立研究（{selected.length}题）</Button><p className="small muted">每题两次独立求解＋一次比较，最多3次调用，预留19000输出tokens；不发送知识目录、图片像素或参考答案，不自动定稿。相同答案不代表已证明正确。有图题需先在“题目与研究”补全必要文字条件。</p></section>
 <div className="corpus-status-legend" aria-label="题目状态颜色说明">{[['conditions','待完善条件'],['ready','待研究'],['running','研究中'],['review','待审核'],['final','已审定'],['failed','失败／中断']].map(([id,label])=><span key={id} className={'corpus-state-'+id}><span className="corpus-state-label">{label}</span></span>)}</div>
 {visible.map(q=><CorpusQuestionRow key={q.id} question={q} selected={selected.includes(q.id)} finals={finals}
 blocked={busy||panelBusy||Object.entries(rowBusyIds).some(([id,value])=>id!=='question:'+q.id&&value)||Object.entries(dirtyIds).some(([id,value])=>id!=='question:'+q.id&&value)}
 onSelect={value=>setSelected(value?[...selected,q.id]:selected.filter(x=>x!==q.id))} onFinalSelect={(id,value)=>setFinals(value?[...finals,id]:finals.filter(x=>x!==id))}
 onGenerate={()=>generateQuestion(q)} onRefresh={refreshQuestion} onRetry={async r=>{await api('/research/runs/'+r.id+'/retry',json('POST',{revision:r.revision}));await refreshQuestion()}} onDirty={report} onBusy={reportRowBusy}/>)}</>}
 {['mapping','cards'].includes(tab)&&<section className="surface"><h2>选择已审定单题研究</h2>{validFinals.map(f=><label className="checkline" key={f.id}><input type="checkbox" disabled={dirty||busy||rowsBusy} checked={finals.includes(f.id)} onChange={e=>setFinals(e.target.checked?[...finals,f.id]:finals.filter(x=>x!==f.id))}/>{f.question.title} · {new Date(f.created_at).toLocaleString()}<Button variant="ghost" disabled={dirty} onClick={()=>openStudy(f.run.id,f.question.title)}>查看研究</Button></label>)}{!validFinals.length&&<p>请先完成至少一道单题研究的人工定稿；其他题目可继续排队。</p>}</section>}
 {tab==='mapping'&&<><section className="surface"><h2>自动匹配知识终稿，也可选择缩小范围</h2>{!versions.some(v=>!v.stale)&&<p>暂无有效知识终稿。可以先继续研究题目，知识定稿后再关联。</p>}{versions.map(v=><label className="checkline" key={v.id}><input type="checkbox" disabled={busy||dirty||v.stale} checked={versionIds.includes(v.id)} onChange={e=>setVersionIds(e.target.checked?[...versionIds,v.id]:versionIds.filter(x=>x!==v.id))}/>{v.title} · {v.count}项{v.stale?' · 已过期':''}</label>)}<Button disabled={busy||dirty||!validSelected.length||!versions.some(v=>!v.stale)} onClick={()=>void act(()=>api('/corpus/mappings',json('POST',{analysis_version_ids:validSelected,version_ids:versionIds})))}>只生成知识关联，不重新解题</Button><p className="small muted">未勾选知识版本时自动使用全部有效知识终稿；目录较长自动分批匹配并汇总，每步预留5000输出tokens。匹配不到的知识列为缺口；更换知识版本后重新匹配，不修改研究终稿。</p><label>按小节查看已有匹配<input aria-label="按小节筛选关联" value={unitFilter} disabled={dirty} onChange={e=>setUnitFilter(e.target.value)}/></label></section>
 {mappings.filter(m=>!unitFilter||m.payload?.links.some(l=>m.knowledge.some(k=>k.ref===l.ref&&(k.title+k.unit_title).includes(unitFilter)))).map(m=>m.payload?<MappingEditor key={m.id+':'+m.revision+':'+m.read_only} mapping={m} blocked={busy||Object.entries(dirtyIds).some(([id,value])=>id!==m.id&&value)} onDirty={report} onReload={()=>load(true)}/>:<section className="surface" key={m.id}><p>知识关联：{states[m.status]||m.status}</p>{m.error&&<p role="alert">{m.error}</p>}{['failed','interrupted'].includes(m.status)&&<Button disabled={busy||m.stale} onClick={()=>void act(()=>api('/corpus/tasks/'+m.id+'/retry',json('POST',{revision:m.run_revision,confirmed:true})))}>重试关联</Button>}</section>)}</>}
 {tab==='cards'&&<><section className="surface"><h2>跨试卷归纳共同思路</h2><p>选择2—10道不同题的研究终稿；引用具体题目，说明边界，自编迁移练习明确标注。不宣称覆盖全部题型。</p><Button disabled={busy||dirty||validSelected.length<2||validSelected.length>10} onClick={()=>void act(()=>api('/corpus/cards',json('POST',{analysis_version_ids:validSelected})))}>归纳思路卡与训练建议</Button></section>{tasks.map(t=><section key={t.id}><p>{states[t.status]||t.status}</p>{t.summary&&<p>{t.summary}</p>}{t.error&&<p role="alert">{t.error}</p>}{['failed','interrupted'].includes(t.status)&&<Button disabled={busy||dirty||t.stale} onClick={()=>void act(()=>api('/corpus/tasks/'+t.id+'/retry',json('POST',{revision:t.revision,confirmed:true})))}>重试归纳</Button>}{t.cards.map(card=><CardEditor key={card.id+':'+card.revision+':'+card.finals.length} card={card} onDirty={report} disabled={busy||Object.entries(dirtyIds).some(([id,value])=>id!==card.id&&value)} onSave={async body=>{await act(()=>api(`/papers/${card.project_id}/cards/${card.id}`,json('PUT',{revision:card.revision,body})))}} onFinal={async()=>{await act(()=>api(`/papers/${card.project_id}/cards/${card.id}/finalize`,json('POST',{revision:card.revision,confirmed:true})))}} onRevise={async id=>{await act(()=>api('/papers/card-versions/'+id+'/revise',json('POST',{})))}}/>)}</section>)}</>}
 {tab==='bank'&&<QuestionBankPage refreshKey={bankRefresh} onOpenRun={openStudy} onEditQuestion={(id,title)=>void openConditions(id,title)}/>}
 {message&&<p role="status" className="feedback">{message}</p>}</div></>
}
