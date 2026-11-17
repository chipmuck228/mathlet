import {lazy,Suspense,useRef,useState,type ReactNode} from 'react'
import {Button} from '@/components/ui/button'
import ReadableMath from './ReadableMath'
import {mathParts,putFormula} from '@/lib/math-content'
import {roles,phases,type UnitBody,type Unit} from './ReviewUnitTypes'
const FormulaEditor=lazy(()=>import('./FormulaEditor'))
const labels:Record<string,string>={plain_explanation:'先这样理解',memory_hint:'记住这一点',self_check:'合上讲解，问问自己',student_lead:'学生导语',card_index:'思路卡索引（从0起）',training_index:'训练索引（从0起）',knowledge:'逐条知识讲解',review_notes:'表达Agent待核查意见',knowledge_connections:'知识连接',source_ref:'起点知识',target_ref:'目标知识',relation_type:'关系类型',example:'具体例子',title:'标题',introduction:'导读',goals:'学习目标',mappings:'知识映射',selected_analysis_ids:'代表题',cards:'思路卡',training:'训练',summary:'回顾与边界',analysis_id:'研究终稿',relevance:'关联角色',reason:'匹配依据',links:'使用知识的具体步骤',gaps:'知识缺口／疑问',knowledge_ref:'知识条目',role:'使用角色',explanation:'为什么使用',conditions:'成立条件／边界',approach_id:'解法编号',step_index:'步骤索引（从0起）',quote:'步骤原文证据',cues:'识别线索',structure:'共同数学结构',steps:'思考操作',alternatives:'其他可行路径',mistakes:'易错点',knowledge_refs:'涉及知识',evidence:'跨题证据',doubts:'待关注意见',phase:'训练阶段',kind:'训练来源',source_analysis_ids:'依据题目',prompt:'学生任务',hints:'递进提示',answer:'参考答案',reasoning:'思考与推理',checkpoints:'检查要点'}
function InlineText({value,onChange,label}:{value:string;onChange:(s:string)=>void;label:string}){
 const input=useRef<HTMLTextAreaElement>(null),[formula,setFormula]=useState<{start:number;end:number;latex:string}|null>(null)
 return <div className="unit-inline"><textarea ref={input} aria-label={label} value={value} rows={Math.max(2,Math.min(10,value.split('\n').length+1))} onChange={e=>onChange(e.target.value)}/><Button size="sm" variant="ghost" onMouseDown={e=>e.preventDefault()} onClick={()=>{const el=input.current;if(el){const part=mathParts(value).find(p=>p.type==='math'&&el.selectionStart>=p.start&&el.selectionEnd<=p.end);setFormula(part?.type==='math'?{start:part.start,end:part.end,latex:part.latex}:{start:el.selectionStart,end:el.selectionEnd,latex:value.slice(el.selectionStart,el.selectionEnd)})}}}>插入／替换选区公式</Button><ReadableMath text={value}/>{formula&&<Suspense fallback={<p>加载公式编辑器…</p>}><FormulaEditor initial={formula.latex} onClose={()=>setFormula(null)} onApply={latex=>{onChange(putFormula(value,formula.start,formula.end,latex));setFormula(null)}}/></Suspense>}</div>
}
export default function ReviewUnitEditor({unit,body,section,editing,onChange}:{unit:Unit;body:UnitBody;section:string;editing:boolean;onChange:(body:UnitBody)=>void}){
 const sources=unit.sources,knowledge=unit.knowledge.items
 const sourceName=(id:string)=>sources.find(s=>s.id===id)?.title||id
 const knowledgeName=(ref:string)=>knowledge.find(k=>k.ref===ref)?.title||ref
 function replace(path:string[],next:unknown){const cloned=structuredClone(body) as unknown as Record<string,unknown>;let at=cloned;for(const k of path.slice(0,-1))at=at[k] as Record<string,unknown>;at[path.at(-1)!]=next;onChange(cloned as unknown as UnitBody)}
 function template(key:string):unknown{
  const id=body.selected_analysis_ids[0]||'',ref=knowledge[0]?.ref||'',s=unit.studies.find(s=>s.id===id),a=s?.analysis.approaches[0]
  const ev={analysis_id:id,approach_id:a?.id||'',step_index:0,quote:a?.steps[0]?.action||''}
  if(key==='knowledge')return {knowledge_ref:ref,plain_explanation:'',memory_hint:'',self_check:''}
  if(key==='knowledge_connections')return {source_ref:ref,target_ref:knowledge[1]?.ref||ref,relation_type:'uses',explanation:'',conditions:'',example:''}
  if(key==='cards')return {title:'新思路卡',cues:[''],structure:'',steps:[''],conditions:[''],alternatives:[],mistakes:[],knowledge_refs:[ref],evidence:[ev],doubts:[]}
  if(key==='training')return {phase:'thinking',kind:'original',title:'新训练',source_analysis_ids:[id],knowledge_refs:[ref],prompt:'',hints:[],answer:'',reasoning:'',checkpoints:['']}
  if(key==='links')return {...ev,knowledge_ref:ref,role:'support',explanation:'',conditions:''}
  if(key==='evidence')return ev
  if(key==='knowledge_refs')return ref
  if(key==='source_analysis_ids')return id
  return ''
 }
 function field(value:unknown,path:string[]):ReactNode{
  const key=path.at(-1)!,parent=path.at(-2)||''
  if(key==='source_hash')return null
  if(path[0]==='presentation'&&key==='agent'){const info=value as {model?:string;prompt_version?:string}|null;return info?<p className="small muted">表达来源：学生阅读表达Agent · {info.model} · {info.prompt_version}</p>:null}
  if(Array.isArray(value)){const sourceBound=path[0]==='presentation'&&['knowledge','cards','training'].includes(key);return <div>{value.map((v,i)=><div className="unit-edit-item" key={i}>{field(v,[...path,String(i)])}{editing&&!sourceBound&&!['mappings','selected_analysis_ids'].includes(key)&&<Button size="sm" variant="ghost" onClick={()=>replace(path,value.filter((_,j)=>j!==i))}>移除此项</Button>}</div>)}{editing&&!sourceBound&&!['mappings','selected_analysis_ids'].includes(key)&&<Button variant="outline" size="sm" onClick={()=>replace(path,[...value,template(key)])}>增加{labels[key]||'一项'}</Button>}{!value.length&&<p className="muted small">无</p>}</div>}
  if(value&&typeof value==='object')return <div>{Object.entries(value).map(([k,v])=><div key={k}><label>{labels[k]||k}</label>{field(v,[...path,k])}</div>)}</div>
  const text=String(value??'')
  if(path[0]==='presentation'&&['knowledge_ref','card_index','training_index'].includes(key))return <p>{key==='knowledge_ref'?knowledgeName(text):'第'+(Number(value)+1)+'项'}</p>
  const isKnowledge=['knowledge_ref','source_ref','target_ref'].includes(key)||parent==='knowledge_refs',isSource=key==='analysis_id'||['source_analysis_ids','selected_analysis_ids'].includes(parent)
  const options=isKnowledge?knowledge.map(k=>[k.ref,k.title]):isSource?sources.map(s=>[s.id,s.title]):key==='relation_type'?Object.entries({prerequisite:'前置知识',derives:'条件推导',uses:'方法使用',contrast:'概念对照',representation:'表示转化'}):key==='relevance'?Object.entries(roles):key==='role'?Object.entries(roles).filter(([k])=>!['none','uncertain'].includes(k)):key==='phase'?Object.entries(phases):key==='kind'?[['original','围绕原题'],['designed','自编练习']]:null
  if(editing&&options)return <select aria-label={labels[key]||labels[parent]||key} value={text} onChange={e=>replace(path,e.target.value)}>{options.map(([k,v])=><option key={k} value={k}>{v}</option>)}</select>
  if(!editing&&options)return <p>{options.find(([k])=>k===text)?.[1]||text}</p>
  if(editing&&typeof value==='number')return <input type="number" aria-label={labels[key]||key} min={0} value={value} onChange={e=>replace(path,Number(e.target.value))}/>
  if(editing)return <InlineText label={labels[key]||labels[parent]||key} value={text} onChange={v=>replace(path,v)}/>
  return <ReadableMath text={isKnowledge?knowledgeName(text):isSource?sourceName(text):text}/>
 }
 if(section==='basics')return <section><p className="muted small">直接引用知识终稿，本页不重复修改。需要调整基础知识时，请回“知识与关系”修订并形成新版本。</p>{knowledge.map(k=><article key={k.ref}><h3>{k.title}</h3>{Object.entries(k.body).filter(([key])=>!['name','kind','uncertainty'].includes(key)).map(([key,value])=><div key={key}><strong>{{statement:'准确表述',conditions:'成立条件',formula:'公式',positive_example:'正例',misconception:'反例与易错点',mastery:'掌握表现',method_steps:'方法步骤'}[key]||key}</strong><ReadableMath text={key==='formula'&&value?`\\(${value}\\)`:value}/></div>)}</article>)}{unit.knowledge.relations?.length? <><h3>知识之间怎样连接</h3>{unit.knowledge.relations.map((r,i)=><div key={i}><p>{knowledgeName(unit.knowledge.version_id+':'+r.body.source_id)} → {knowledgeName(unit.knowledge.version_id+':'+r.body.target_id)}</p><ReadableMath text={r.body.reason}/><ReadableMath text={r.body.conditions}/>{r.body.example&&<ReadableMath text={r.body.example}/>}</div>)}</>:null}</section>
 if(section==='solutions')return <section><p className="muted small">原题与解析直接引用研究终稿；AI编排不会覆盖这些已审定内容。</p>{unit.studies.map(s=><article key={s.id}><h3>{s.question.title}</h3><ReadableMath text={s.question.statement}/><ReadableMath text={s.question.diagram_description}/>{s.question.assets.map(a=><img key={a.name} className="research-figure" src={a.data_url||a.url} alt="原题配图"/>)}{s.analysis.approaches.map(a=><details key={a.id}><summary>{a.title}</summary><ReadableMath text={a.trigger}/>{a.steps.map((step,i)=><div key={i}><h4>第{i+1}步</h4><ReadableMath text={step.action}/><ReadableMath text={step.reason}/></div>)}<ReadableMath text={a.conclusion}/><ReadableMath text={a.checks}/><ReadableMath text={a.limitations}/></details>)}</article>)}</section>
 if(section==='mappings')return <section><p>已检查 {body.mappings.length} 道不同题。代表题最多 {unit.representative_limit} 道；本次自动合并 {unit.skipped_duplicates} 道重复题。</p>{body.mappings.map((m,i)=><details key={m.analysis_id} className={'unit-mapping unit-role-'+m.relevance}><summary>{sourceName(m.analysis_id)} · {roles[m.relevance]}{body.selected_analysis_ids.includes(m.analysis_id)?' · 已选代表题':''}</summary>{editing&&<label className="checkline"><input type="checkbox" checked={body.selected_analysis_ids.includes(m.analysis_id)} onChange={e=>onChange({...body,selected_analysis_ids:e.target.checked?[...body.selected_analysis_ids,m.analysis_id]:body.selected_analysis_ids.filter(id=>id!==m.analysis_id)})}/>纳入本单元代表题（变更后须同时检查思路卡与训练引用）</label>}{field(m,['mappings',String(i)])}</details>)}</section>
 if(section==='presentation')return <section><p className="small muted">学生阅读表达Agent生成的导读、自查问题和思考导语。只是阅读层，原定义、条件、公式和正反例仍完整保留。可直接编辑，随单元整体审定。</p>{body.presentation?<>{field(body.presentation,['presentation'])}{editing&&<Button variant="ghost" onClick={()=>onChange({...body,presentation:null})}>不用本次学生表达，保留原文</Button>}</>:<p>尚未生成学生表达，可点击上方“优化学生表达与版式”。原文仍可正常预览。</p>}</section>
 if(section==='knowledge_connections')return <section><p className="small muted">AI结合当前知识与代表题组织的连接，随本单元整体审核；可以为空，不是基础知识定稿的前置步骤。</p>{field(body.knowledge_connections||[],['knowledge_connections'])}</section>
 if(!(section in body))return null
 return <section>{section==='introduction'&&<><label>单元标题</label>{field(body.title,['title'])}</>}{field(body[section as keyof UnitBody],[section])}</section>
}
