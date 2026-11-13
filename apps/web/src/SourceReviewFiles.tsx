import {useEffect,useState} from 'react'
import {api} from '@/lib/api'
type RecordFile={document_id:string;filename:string;document_name:string}
export default function SourceReviewFiles({documentId,refreshKey,disabled,onOpen}:{documentId:string;refreshKey:number;disabled:boolean;onOpen:(id:string)=>void}){
 const [records,setRecords]=useState<RecordFile[]>([]),[error,setError]=useState('')
 useEffect(()=>{let alive=true;void api<RecordFile[]>('/source-reviews').then(value=>{if(alive){setRecords(value);setError('')}}).catch(e=>{if(alive)setError(String(e))});return()=>{alive=false}},[refreshKey])
 return <><select aria-label="打开核对记录" value={records.some(r=>r.document_id===documentId)?documentId:''} disabled={disabled} onChange={e=>{if(e.target.value)onOpen(e.target.value)}}><option value="">打开已保存的核对文件</option>{records.map(r=><option key={r.document_id} value={r.document_id}>{r.filename} · {r.document_name}</option>)}</select>{error&&<span role="alert">{error}</span>}</>
}
