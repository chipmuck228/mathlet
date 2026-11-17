import {useEffect,useState} from 'react'
import {BookOpen,Download,RefreshCw} from 'lucide-react'
import {api} from '@/lib/api'
import {Button} from '@/components/ui/button'
type Booklet={id:string;title:string;revision:number;created_at:string;knowledge_count:number;question_count:number;training_count:number}
export default function PublishedBookletsPage(){
 const [items,setItems]=useState<Booklet[]>([]),[query,setQuery]=useState(''),[loading,setLoading]=useState(true),[error,setError]=useState('')
 async function load(){setLoading(true);setError('');try{setItems(await api<Booklet[]>('/review-units/published'))}catch(e){setError(String(e))}finally{setLoading(false)}}
 useEffect(()=>{void load()},[])
 const shown=items.filter(x=>x.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
 return <section className="published-library"><p>把学过的知识重新串起来。选一本打开阅读，也可以下载留存。</p><p className="muted small">这里展示教师已确认定稿的交付版本，按发布时间倒序排列；同一本的不同版本分别保留。阅读页可通过浏览器“打印 → 存储为 PDF”保存。</p><div className="actions"><label htmlFor="booklet-search">查找小册子</label><input id="booklet-search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="输入小册子名称"/><Button variant="outline" disabled={loading} onClick={()=>void load()}><RefreshCw size={16}/>刷新小册子</Button></div>{error&&<p role="alert">{error}</p>}{loading?<p role="status">正在加载小册子…</p>:!error&&<><p className="muted small">共 {shown.length} 个已发布版本</p>{shown.length? <div className="published-grid">{shown.map(b=><article className="published-booklet" key={b.id}><BookOpen aria-hidden="true" size={30}/><h2>{b.title}</h2><p className="muted small">{new Date(b.created_at).toLocaleString('zh-CN')} · 修订 {b.revision}</p><p>{b.knowledge_count} 项知识 · {b.question_count} 道例题 · {b.training_count} 项训练</p><div className="actions"><a href={`/api/review-units/versions/${b.id}/reader`} target="_blank" rel="noreferrer">打开阅读 ↗</a><a href={`/api/review-units/versions/${b.id}/download`}><Download size={15} aria-hidden="true"/>下载离线读物</a></div></article>)}</div>:<p className="empty">{items.length?'没有找到这个名称的小册子。':'还没有已发布小册子。在“复习单元编制”中完成审核并形成终稿后，会自动展示在这里。'}</p>}</>}</section>
}
