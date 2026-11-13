import {useEffect,useState,type ReactNode} from 'react'
import {Button} from '@/components/ui/button'
import MathBlockEditor from './MathBlockEditor'
import ReadableMath from './ReadableMath'
import {mathBlock,orderedResearchKeys,researchLabels as labels,type Output,type Knowledge} from './ResearchManuscriptTypes'

export default function ResearchBodyEditor({output,knowledge,readOnly,onDraft,onSave}:{output:Output;knowledge:Knowledge;readOnly:boolean;onDraft:(value:Record<string,unknown>,dirty:boolean)=>void;onSave:(value:Record<string,unknown>)=>Promise<void>}){
 const [value,setValue]=useState(output.body),[editing,setEditing]=useState(false),[saving,setSaving]=useState(false),[error,setError]=useState('')
 const dirty=JSON.stringify(value)!==JSON.stringify(output.body)
 useEffect(()=>{onDraft(value,dirty)},[value,dirty,onDraft])
 function replace(path:string[],next:unknown){const cloned=structuredClone(value);let at=cloned;for(const key of path.slice(0,-1))at=at[key] as Record<string,unknown>;at[path[path.length-1]]=next;setValue(cloned)}
 function name(ref:string){const item=knowledge.items.find(i=>i.ref===ref);return item?`${item.unit_title} / ${item.title}`:ref}
 function template(key:string):unknown{
  if(key==='assessed_points')return {name:'新考察点',knowledge_refs:[],evidence:''}
  if(key==='knowledge_breakdown')return {ref:knowledge.items[0]?.ref||'',role:'',conditions:''}
  if(key==='steps')return {action:'',reason:'',knowledge_refs:[]}
  if(key==='approaches')return {id:crypto.randomUUID(),title:'新思路',trigger:'',steps:[{action:'',reason:'',knowledge_refs:[]}],conclusion:'',checks:'',limitations:''}
  if(key==='knowledge_refs')return knowledge.items[0]?.ref||''
  return ''
 }
 function field(node:unknown,path:string[]):ReactNode{
  const key=path[path.length-1]||'';const ref=key==='ref'||path.includes('knowledge_refs')
  if(Array.isArray(node))return <div>{node.map((child,i)=><div key={i} className="research-array-item">{field(child,[...path,String(i)])}{editing&&<Button variant="ghost" disabled={saving} onClick={()=>replace(path,node.filter((_,j)=>i!==j))}>移除此项</Button>}</div>)}{editing&&<Button variant="outline" disabled={saving} onClick={()=>replace(path,[...node,template(key)])}>增加{labels[key]||'一项'}</Button>}{!node.length&&!editing&&<p className="small muted">无</p>}</div>
  if(node&&typeof node==='object')return <div>{Object.entries(node).map(([k,v])=><div key={k}><label>{labels[k]||k}</label>{field(v,[...path,k])}</div>)}</div>
  const text=String(node??'')
  if(editing&&ref)return <select aria-label="研究知识引用" disabled={saving} value={text} onChange={e=>replace(path,e.target.value)}>{knowledge.items.map(i=><option key={i.ref} value={i.ref}>{i.unit_title} / {i.title}</option>)}</select>
  if(editing&&key!=='id')return <MathBlockEditor block={mathBlock(output.id+'-'+path.join('-'),text,labels[key]||labels[path[path.length-2]]||key,output.revision)} text={text} disabled={saving} onFocus={()=>{}} onChange={text=>replace(path,text)}/>
  return <div className="block-reading"><ReadableMath text={ref?name(text):text}/></div>
 }
 return <section className="manuscript-body" aria-label="研究正文"><div className="section-heading"><h2>题目—分类—考察点—知识—思路</h2><span className="small muted">{readOnly?'终稿 · 只读':dirty?'有未保存修改':'已保存'} · 修订 {output.revision}</span></div><div className="actions"><Button variant="outline" disabled={readOnly||saving} onClick={()=>setEditing(!editing)}>{editing?'浏览':'编辑'}</Button><span className="small muted">保存只更新工作稿，不形成终稿。</span></div>
 {orderedResearchKeys(value).map(key=><section key={key} id={'research-section-'+key} className="manuscript-field"><h3>{labels[key]||key}</h3>{field(value[key],[key])}</section>)}
 {editing&&<div className="actions"><Button disabled={!dirty||saving} onClick={async()=>{setSaving(true);setError('');try{await onSave(value)}catch(e){setError(String(e))}finally{setSaving(false)}}}>保存研究稿修改</Button><Button variant="ghost" disabled={saving} onClick={()=>{setValue(output.body);setEditing(false);setError('')}}>取消本次修改</Button></div>}{error&&<p role="alert">{error}；输入保留。</p>}
 <details><summary>模型最初研究稿</summary><pre className="knowledge-json">{JSON.stringify(output.original_body,null,2)}</pre></details></section>
}
