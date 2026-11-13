import {useEffect,useRef,useState} from 'react'
import {Button} from '@/components/ui/button'
import {api,json,type Block} from '@/lib/api'
import MathBlockEditor from './MathBlockEditor'
import OriginalDocument from './OriginalDocument'

type Review={document_id:string;filename:string;created_at:string;updated_at:string;revision:number}
type Result={review:Review|null;blocks:Block[];file_saved?:boolean;file_error?:string}
export default function SourceReview({documentId,kind,focusId,onSaved,onDirtyChange,onBusyChange,onReviewSaved}:{documentId:string;kind:string;focusId:string;onSaved:(blocks:Block[])=>void;onDirtyChange:(dirty:boolean)=>void;onBusyChange:(busy:boolean)=>void;onReviewSaved:()=>void}){
 const [base,setBase]=useState<Block[]>([]),[texts,setTexts]=useState<Record<string,string>>({}),[review,setReview]=useState<Review|null>(null),[active,setActive]=useState('')
 const [loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[message,setMessage]=useState('')
 const fileInput=useRef<HTMLInputElement>(null),left=useRef(new Map<string,HTMLElement>()),alive=useRef(true)
 const dirty=base.filter(b=>texts[b.id]!==b.text)
 const dirtyFlag=dirty.length>0
 useEffect(()=>{onDirtyChange(dirtyFlag);return()=>onDirtyChange(false)},[dirtyFlag,onDirtyChange])
 useEffect(()=>{onBusyChange(busy||loading);return()=>onBusyChange(false)},[busy,loading,onBusyChange])
 useEffect(()=>{alive.current=true;return()=>{alive.current=false}},[])
 useEffect(()=>{const warn=(e:BeforeUnloadEvent)=>{if(dirtyFlag){e.preventDefault();e.returnValue=''}};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn)},[dirtyFlag])
 function replace(value:Result){setBase(value.blocks);setTexts(Object.fromEntries(value.blocks.map(b=>[b.id,b.text])));setReview(value.review);onSaved(value.blocks);if(value.file_error)setMessage(value.file_error)}
 useEffect(()=>{let current=true;setLoading(true);void api<Result>(`/documents/${documentId}/source-review`).then(value=>{if(current)replace(value)}).catch(e=>{if(current)setMessage(String(e))}).finally(()=>{if(current)setLoading(false)});return()=>{current=false}},[documentId])
 useEffect(()=>{if(!loading&&focusId&&left.current.has(focusId)){setActive(focusId);left.current.get(focusId)?.scrollIntoView({block:'nearest'})}},[loading,focusId])
 async function save(id?:string){
  const chosen=id?base.filter(b=>b.id===id):dirty
  const changes=chosen.map(b=>({id:b.id,revision:b.revision,text:texts[b.id],verified:!!id}))
  setBusy(true);setMessage('')
  try{const value=await api<Result>(`/documents/${documentId}/source-review`,json('PUT',{review_revision:review?.revision??null,changes}));if(!alive.current)return;const submitted=new Set(chosen.map(b=>b.id));setBase(value.blocks);setReview(value.review);setTexts(old=>Object.fromEntries(value.blocks.map(b=>[b.id,submitted.has(b.id)?b.text:old[b.id]??b.text])));onSaved(value.blocks);onReviewSaved();setMessage(value.file_error||(id?'已保存此内容块的人工核对结果。':`已保存核对文件：${value.review?.filename}`))}catch(e){if(alive.current)setMessage(String(e).replace(/^Error: /,''))}finally{if(alive.current)setBusy(false)}
 }
 async function reload(){if(dirtyFlag&&!window.confirm('重新打开会放弃尚未保存的修改，继续？'))return;setBusy(true);setMessage('');try{const value=await api<Result>(`/documents/${documentId}/source-review`);if(alive.current){replace(value);setMessage('已重新打开核对记录。')}}catch(e){if(alive.current)setMessage(String(e))}finally{if(alive.current)setBusy(false)}}
 async function openFile(file:File){
  if(dirtyFlag&&!window.confirm('打开文件将替换当前未保存的正文与核对状态，继续？'))return
  if(file.size>20*1024*1024){setMessage('核对文件超过20MB，请选择工作台保存的JSON文件。');return}
  setBusy(true);setMessage('')
  try{const payload=JSON.parse(await file.text());const value=await api<Result>(`/documents/${documentId}/source-review/open`,json('POST',{review_revision:review?.revision??null,payload}));if(alive.current){replace(value);onReviewSaved();setMessage(value.file_error||`已打开核对文件：${value.review?.filename}`)}}catch(e){if(alive.current)setMessage(String(e).replace(/^Error: /,''))}finally{if(alive.current)setBusy(false)}
 }
 const locked=busy||loading
 return <>
 <div className="source-review-filebar"><p>{review?`核对文件：${review.filename}`:'首次保存后，自动以日期时间创建核对文件。'}<span className="small muted"> · 已核对 {base.filter(b=>b.verified&&texts[b.id]===b.text).length} / {base.length} 块{dirtyFlag?` · 未保存 ${dirty.length} 块`:''}</span></p><div className="actions"><Button disabled={locked} onClick={()=>void save()}>保存核对文件</Button><Button variant="outline" disabled={locked} onClick={()=>void reload()}>重新打开核对记录</Button><Button variant="outline" disabled={locked} onClick={()=>fileInput.current?.click()}>打开本地核对文件</Button>{review&&<a href={`/api/documents/${documentId}/source-review/download`}>下载核对文件</a>}<input ref={fileInput} aria-label="选择本地核对文件" type="file" accept=".json,application/json" hidden onChange={e=>{const file=e.target.files?.[0];if(file)void openFile(file);e.target.value=''}}/></div>{message&&<p role="status" className="feedback">{message}</p>}</div>
 <div className="continuous-review source-review-columns"><section className="review-column" aria-label="核对内容"><div className="review-column-title"><h2>核对</h2><p>点选内容块后可编辑，并点击“已核对”保存该块。保存核对文件会保存全部修改，文件名始终保持不变。</p></div><div className="review-scroll">{loading?<p>正在打开核对内容…</p>:base.map(b=><article key={b.id} ref={e=>{if(e)left.current.set(b.id,e);else left.current.delete(b.id)}} className={`review-block ${active===b.id?'is-active':''}`} onClick={()=>setActive(b.id)}><div className="review-block-meta"><button type="button" aria-label={`选择 ${b.locator}`} onClick={()=>setActive(b.id)}>{b.locator}</button><span>{texts[b.id]!==b.text?'未保存':b.verified?'已核对':'待核对'}</span>{active===b.id&&<Button size="sm" className="source-reviewed-button" disabled={locked} onClick={()=>void save(b.id)}>已核对</Button>}</div><MathBlockEditor block={b} text={texts[b.id]??b.text} disabled={locked} onFocus={()=>setActive(b.id)} onChange={text=>setTexts(old=>({...old,[b.id]:text}))} saveHint="应用后点击本块“已核对”，或点击“保存核对文件”。"/>{kind!=='pdf'&&b.assets.map(name=><img className="review-asset" key={name} src={`/api/documents/${documentId}/assets/${name}`} alt={`${b.locator} 配图`} loading="lazy"/>)}</article>)}</div></section><section className="review-column" aria-label="原始资料对照"><OriginalDocument key={documentId} documentId={documentId} kind={kind}/></section></div>
 </>
}
