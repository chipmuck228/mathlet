import {useCallback,useEffect,useId,useRef,useState} from 'react'
import {api,type Document} from '@/lib/api'
import {Button} from '@/components/ui/button'
import ReadableMath from './ReadableMath'
import CompleteQuestionEditor from './CompleteQuestionEditor'
import ResearchManuscriptPage from './ResearchManuscriptPage'
import type {Question as CompleteQuestion} from './ResearchManuscriptTypes'
export type CorpusRun={id:string;status:string;revision:number;error:string;stale:boolean;problem_types:string[];identified_names:string[];finals:{id:string;stale:boolean;created_at:string}[]}
export type CorpusQuestion={question_id?:string|null;condition_confirmed?:boolean;id:string;exam_id:string;title:string;statement:string;number:string;blockers:string[];duplicate_count:number;runs:CorpusRun[]}
export function questionState(q:CorpusQuestion){
 const runs=q.runs.filter(r=>!r.stale)
 if(q.blockers.length)return {id:'conditions',label:'待完善／确认条件'}
 if(runs.some(r=>['queued','running'].includes(r.status)))return {id:'running',label:'排队／研究中'}
 if(runs.some(r=>r.finals.some(f=>!f.stale)))return {id:'final',label:'研究已审定'}
 if(runs.some(r=>r.status==='completed'))return {id:'review',label:'研究稿待审核'}
 if(runs.some(r=>['failed','interrupted'].includes(r.status)))return {id:'failed',label:'研究失败／中断'}
 return {id:'ready',label:'条件已确认，待研究'}
}
const labels:Record<string,string>={queued:'排队中',running:'研究中',completed:'研究稿已就绪',failed:'失败',interrupted:'中断'}
export default function CorpusQuestionRow({question:q,selected,finals,blocked,onSelect,onFinalSelect,onGenerate,onRetry,onRefresh,onDirty,onBusy}:{question:CorpusQuestion;selected:boolean;finals:string[];blocked:boolean;onSelect:(value:boolean)=>void;onFinalSelect:(id:string,value:boolean)=>void;onGenerate:()=>Promise<string>;onRetry:(run:CorpusRun)=>Promise<void>;onRefresh:()=>Promise<void>;onDirty:(id:string,value:boolean)=>void;onBusy:(id:string,value:boolean)=>void}){
 const [expanded,setExpanded]=useState(false),[editor,setEditor]=useState<{kind:'question'|'study';id:string}|null>(null),[target,setTarget]=useState<CompleteQuestion|null>(null),[documents,setDocuments]=useState<Document[]>([]),[dirty,setDirty]=useState(false),[busy,setBusy]=useState(false),[childBusy,setChildBusy]=useState(false),[message,setMessage]=useState('')
 const id=useId(),serial=useRef(0),alive=useRef(true),key='question:'+q.id
 const locked=blocked||busy||childBusy
 const status=questionState(q),hasFinal=q.runs.some(r=>r.finals.some(f=>!f.stale)&&!r.stale)
 const reportDirty=useCallback((value:boolean)=>setDirty(value),[]),reportBusy=useCallback((value:boolean)=>setChildBusy(value),[])
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;serial.current++}},[])
 useEffect(()=>{onDirty(key,dirty);return()=>onDirty(key,false)},[key,dirty,onDirty])
 useEffect(()=>{onBusy(key,busy||childBusy);return()=>onBusy(key,false)},[key,busy,childBusy,onBusy])
 function openStudy(runId:string){if(locked||dirty)return;serial.current++;setExpanded(true);setEditor({kind:'study',id:runId});setMessage('')}
 async function editConditions(){
  if(locked||dirty||!q.question_id)return
  const n=++serial.current;setExpanded(true);setBusy(true);setMessage('')
  try{const [value,docs]=await Promise.all([api<CompleteQuestion>('/research/questions/'+q.question_id),api<Document[]>('/documents')]);if(!alive.current||n!==serial.current)return;setTarget(value);setDocuments(docs);setEditor({kind:'question',id:value.id})}catch(e){if(alive.current)setMessage(String(e))}finally{if(alive.current&&n===serial.current)setBusy(false)}
 }
 async function generate(){if(locked||dirty)return;setBusy(true);setMessage('');try{const runId=await onGenerate();if(alive.current){setEditor({kind:'study',id:runId});setExpanded(true)}}catch(e){if(alive.current)setMessage(String(e))}finally{if(alive.current)setBusy(false)}}
 async function refresh(){try{await onRefresh()}catch(e){if(alive.current)setMessage(String(e))}}
 function discard(){if(locked)return;serial.current++;setEditor(null);setTarget(null);setDirty(false);setMessage('已放弃未保存编辑；已保存内容保留。')}
 return <section className={'surface corpus-question corpus-state-'+status.id} aria-label={q.title}>
 <div className="section-heading"><label className="checkline"><input type="checkbox" aria-label={'研究 '+q.title} disabled={locked||dirty||!!q.blockers.length&&!selected} checked={selected} onChange={e=>onSelect(e.target.checked)}/><strong>{q.title}</strong></label><span className="corpus-state-label">{status.label}</span><Button variant="outline" aria-expanded={expanded} aria-controls={id} disabled={locked||dirty} onClick={()=>setExpanded(!expanded)}>{expanded?'折叠题目':'展开题目'}</Button></div>
 <p className="small muted">{q.runs.length} 份研究记录 · {q.runs.flatMap(r=>r.finals).length} 份研究终稿</p>
 <div id={id} hidden={!expanded}>
 <ReadableMath text={q.statement}/>{q.duplicate_count>1&&<p className="small muted">有 {q.duplicate_count} 份相同内容候选，保留各自来源；不自动合并。</p>}
 {q.blockers.map((b,i)=><p role="alert" key={i}>{b}</p>)}
 <div className="actions"><Button variant="outline" disabled={locked||dirty||!q.question_id} onClick={()=>void editConditions()}>补充／编辑本题条件</Button><Button disabled={locked||dirty||!!q.blockers.length} onClick={()=>void generate()}>{q.runs.some(r=>!r.stale)?'生成／复用本题研究稿':'生成本题研究稿'}</Button></div>
 {!q.blockers.length&&!q.runs.some(r=>!r.stale)&&<p className="small muted">条件已确认；请生成本题研究稿，再核验解答并形成研究终稿。</p>}
 {q.runs.map(r=><div key={r.id} className="corpus-run"><p>{r.stale?'历史研究，题目依据已变化':labels[r.status]||r.status}</p>{r.problem_types.length>0&&<p>题型：{r.problem_types.join('、')}；知识：{r.identified_names.join('、')}</p>}{r.error&&<p role="alert">{r.error}</p>}<Button variant="outline" disabled={locked||dirty} onClick={()=>openStudy(r.id)}>{r.stale?'查看历史研究稿':'打开研究稿／审核定稿'}</Button>{['failed','interrupted'].includes(r.status)&&<Button disabled={locked||dirty||r.stale} onClick={()=>void (async()=>{setBusy(true);try{await onRetry(r)}catch(e){setMessage(String(e))}finally{setBusy(false)}})()}>重试未完成研究</Button>}
 {r.finals.map(f=><label className="checkline" key={f.id}><input type="checkbox" aria-label={'选择研究终稿 '+q.title} disabled={locked||dirty||r.stale||f.stale} checked={finals.includes(f.id)} onChange={e=>onFinalSelect(f.id,e.target.checked)}/>选择此研究终稿用于关联／归纳{r.stale||f.stale?'（历史版本，当前不可用于匹配）':''}</label>)}</div>)}
 {!hasFinal&&<p className="small muted">尚无有效研究终稿。人工核验、定稿后，才可选择用于知识关联／思路归纳。</p>}
 {editor&&<section className="corpus-question-editor" aria-label="题目内核验"><div className="section-heading"><h3>{editor.kind==='question'?'完善本题条件':'本题研究核验与定稿'}</h3><Button variant="ghost" disabled={locked||dirty} onClick={()=>setEditor(null)}>收起编辑区</Button>{dirty&&<Button variant="outline" disabled={locked} onClick={discard}>放弃未保存编辑</Button>}</div>
 {editor.kind==='study'?<ResearchManuscriptPage key={editor.id} embedded initialRunId={editor.id} documents={[]} openKnowledge={()=>{}} disabled={blocked} onDirtyChange={reportDirty} onBusyChange={reportBusy} onChanged={()=>void refresh()}/>:target&&<CompleteQuestionEditor key={target.id+'-'+target.revision} initial={target} documents={documents} disabled={blocked||busy} onDirty={reportDirty} onBusyChange={reportBusy} onSaved={value=>{setTarget(value);setDirty(false);setMessage(value.confirmed?'本题条件已确认，可以生成或打开当前研究。':'条件修改已保存，尚需勾选完整性确认；也可继续编辑。');void refresh()}}/>}
 </section>}{busy&&<p role="status">正在处理本题请求，请稍候…</p>}{message&&<p role="status" className="feedback">{message}</p>}
 </div></section>
}
