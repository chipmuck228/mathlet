import {useEffect,useRef,useState} from 'react'
import {Button} from '@/components/ui/button'
import {api,json} from '@/lib/api'
import ReadableMath from './ReadableMath'
type Result={changes:{before:string;after:string;reason:string;evidence:string}[];uncertainties:string[];suggested_text:string;limitations:string}
type Task={id:string;status:string;error:string;stale:boolean;original_text:string;result:Result|null}
export default function ExamFormulaSuggestion({extractionId,revision,questionKey,text,disabled,onApply}:{extractionId:string;revision:number;questionKey:string;text:string;disabled:boolean;onApply:(text:string)=>void}){
 const [task,setTask]=useState<Task|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const live=useRef(true),latest=useRef(text);latest.current=text
 useEffect(()=>{live.current=true;return()=>{live.current=false}},[])
 const pending=task&&['queued','running'].includes(task.status)
 useEffect(()=>{if(!pending||!task)return;let active=true;let polling=false
 const timer=setInterval(async()=>{if(polling)return;polling=true;try{const next=await api<Task>('/exam-formula-suggestions/'+task.id);if(active){setTask(next);setError('')}}catch(e){if(active)setError(String(e))}finally{polling=false}},1500)
 return()=>{active=false;clearInterval(timer)}
 },[task?.id,pending])
 const changed=!!task&&task.original_text!==text
 async function start(){setBusy(true);setError('');try{const next=await api<Task>('/exam-extractions/'+extractionId+'/formula-suggestions',json('POST',{revision,question_key:questionKey,text}));if(live.current)setTask(next)}catch(e){if(live.current)setError(String(e))}finally{if(live.current)setBusy(false)}}
 async function adopt(){if(!task)return;setBusy(true);setError('');try{const next=await api<Task>('/exam-formula-suggestions/'+task.id);if(!live.current)return;setTask(next);if(next.stale||next.original_text!==latest.current||next.status!=='completed'||!next.result)throw Error('题目或来源已变化，请重新生成建议');onApply(next.result.suggested_text);setTask(null)}catch(e){if(live.current)setError(String(e))}finally{if(live.current)setBusy(false)}}
 return <section className="exam-formula-suggestion" aria-label="AI公式修正">
 <Button variant="outline" size="sm" disabled={disabled||busy||!!pending||!text.trim()} onClick={()=>void start()}>AI 修正公式</Button>
 {error&&<p role="alert">{error}</p>}
 {pending&&<p role="status">AI正在检查本题公式；仅提出建议，不修改正文。{error&&'读取进度失败，将继续重试。'}</p>}
 {task&&<div className="review-block">
 {(changed||task.stale)&&<p role="alert">题目或来源已变化，本建议不能采用，请重新生成。</p>}
 {task.status==='failed'||task.status==='interrupted'?<p role="alert">公式修正未完成：{task.error}。可再次点击生成新建议。</p>:null}
 {task.result&&<><p className="small muted">AI建议尚未采用。{task.result.limitations}</p>
 <h4>修正前</h4><ReadableMath text={task.original_text}/><h4>修正建议</h4><ReadableMath text={task.result.suggested_text}/>
 {task.result.changes.map((c,i)=><div key={i}><strong>修改 {i+1}</strong><p>原片段：<code>{c.before}</code></p><p>建议片段：<code>{c.after}</code></p><ReadableMath text={'理由：'+c.reason}/><ReadableMath text={'依据：'+c.evidence}/></div>)}
 {!task.result.changes.length&&<p>未提出可确定的公式修正。</p>}
 {!!task.result.uncertainties.length&&<><h4>仍需人工核对</h4>{task.result.uncertainties.map((s,i)=><ReadableMath key={i} text={s}/>)}</>}
 <Button disabled={disabled||busy||changed||task.stale||!task.result.changes.length} onClick={()=>void adopt()}>采用修正并编辑</Button>
 </>}
 <Button variant="ghost" disabled={busy} onClick={()=>{setTask(null);setError('')}}>{pending?'关闭建议（后台任务继续）':'放弃建议'}</Button>
 </div>}
 </section>
}
