import {Button} from '@/components/ui/button'
import ReadableMath from './ReadableMath'
import type {ReviewAdvisory,TeacherReview} from './ResearchManuscriptTypes'
export default function ResearchReviewAdvice({items,readOnly,note,onNote,disabled,review}:{items:ReviewAdvisory[];readOnly:boolean;note:string;onNote:(value:string)=>void;disabled:boolean;review?:TeacherReview}){
 if(!items.length&&!review)return null
 return <section className="research-review-advice" aria-label="教师核查与处理"><h4>{readOnly?'教师核查记录':'AI核查意见 · 不自动阻断定稿'}</h4><p className="small muted">以下是需要核对的具体意见，不代表AI判断必然正确。无需再次调用AI，也可直接编辑或作出教师判断。</p>
 {items.map((item,i)=><details key={i} open={item.kind==='missing_information'}><summary>{item.title}</summary><ReadableMath text={item.message}/><p>处理方式：{item.guidance}</p>{!readOnly&&<Button variant="ghost" size="sm" onClick={()=>document.getElementById('research-section-'+item.path)?.scrollIntoView({block:'start',behavior:'smooth'})}>定位相关正文</Button>}</details>)}
 {readOnly?<>{review&&<><p>教师决定：已核查并认可本研究稿。</p><ReadableMath text={review.note}/></>}</>:<><p>若认可当前研究稿，可直接勾选下方“确认定稿”。若需修改，在中央正文点击“编辑”，处理“条件／信息核查意见”或相关解法，然后保存。确实需补原题条件时，先完善并确认本题，再为新版本生成研究。</p><label>教师审核说明（选填）<textarea aria-label="教师审核说明（选填）" disabled={disabled} value={note} onChange={e=>onNote(e.target.value)} placeholder="例如：该条件已在原题中给出，AI判断不适用；或说明采用／不采用该意见的依据。"/></label>{note&&<Button variant="ghost" disabled={disabled} onClick={()=>onNote('')}>清空未保存的审核说明</Button>}</>}
 </section>
}
