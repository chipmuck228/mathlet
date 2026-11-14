import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import ExamSourceReview from './ExamSourceReview'
import {api} from '@/lib/api'
vi.mock('@/lib/api',()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
vi.mock('./OriginalDocument',()=>({default:()=> <p>原文只读对照</p>}))
vi.mock('./MathBlockEditor',()=>({default:({text,onChange,block}:{text:string;onChange:(v:string)=>void;block:{locator:string}})=><textarea aria-label={block.locator} value={text} onChange={e=>onChange(e.target.value)}/>}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
const assets=[{id:'b/one.png',block_id:'b',name:'one.png',hash:'hash1',url:'/api/image/1'},{id:'b/two.png',block_id:'b',name:'two.png',hash:'hash2',url:'/api/image/2'}]
const q={key:'q',number:'1',question_text:'已知x=2，求x的平方。',answer_text:'4',image_ids:['b/one.png'],answer_image_ids:[],diagram_description:'',question_spans:[{block_id:'b',start_anchor:'',end_anchor:'',start_occurrence:0,end_occurrence:0}],answer_spans:[],notes:''}
const payload={title:'合成学校2026模拟试卷',questions:[q],notes:''}
const record={id:'e',document_id:'d',revision:1,run_revision:2,status:'completed',error:'',filename:'2026-11-13_20-00-00.json',created_at:'2026-11-13',stale:false,read_only:false,payload,source:{document_name:'合成文档.docx',blocks:[{id:'b',locator:'段落2',text:'原文题目与解答',assets}]},versions:[],calls:[]}
function mock(existing=true){vi.mocked(api).mockImplementation(async path=>{
 if(path==='/documents/d/exam-extractions')return existing?[{id:'e',filename:record.filename,title:payload.title,status:'completed',final_count:0}]:[]
 if(path==='/knowledge/provider')return {ready:true,model:'test-model'}
 if(path==='/exam-extractions/e')return structuredClone(record)
 throw Error('Unexpected '+path)
})}
function page(){render(<ExamSourceReview documentId="d" kind="docx" onDirtyChange={vi.fn()} onBusyChange={vi.fn()} onReviewSaved={vi.fn()}/>)}
it('reads question-only review without answer or provenance widgets or model calls',async()=>{
 mock();page();await screen.findByText('已知x=2，求x的平方。')
 expect(screen.queryByText('原文解答')).toBeNull();expect(screen.queryByText('原文定位与补充说明')).toBeNull();expect(screen.queryByText('整卷核对说明')).toBeNull();expect(screen.queryByRole('button',{name:'已核对'})).toBeNull()
 expect(screen.getByText('原文只读对照')).toBeTruthy()
 expect(vi.mocked(api).mock.calls.every(([,i])=>!i?.method)).toBe(true)
})
it('edits the complete question and chooses a replacement from all original images then saves the whole paper',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,init)=>path==='/exam-extractions/e'&&init?.method==='PUT'?{...record,revision:2,payload:JSON.parse(init.body as string).body}:base(path,init))
 page();await screen.findByText('已知x=2，求x的平方。');await waitFor(()=>expect((screen.getByRole('button',{name:'编辑第1题'}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:'编辑第1题'}));fireEvent.change(screen.getByLabelText('第1题题目'),{target:{value:'教师核对后的完整题目'}})
 fireEvent.click(screen.getByRole('button',{name:'从全部图片选择／替换题图'}));await screen.findByRole('dialog',{name:'从原文全部图片选择'})
 fireEvent.click(screen.getByLabelText('选择图片 one.png b'));fireEvent.click(screen.getByLabelText('选择图片 two.png b'));fireEvent.click(screen.getByRole('button',{name:'应用图片选择'}))
 fireEvent.click(screen.getByRole('button',{name:'保存整份修改'}))
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p,i])=>p==='/exam-extractions/e'&&i?.method==='PUT')).toBe(true))
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([p,i])=>p==='/exam-extractions/e'&&i?.method==='PUT')![1]!.body as string)
 expect(sent.revision).toBe(1);expect(sent.body.questions[0].question_text).toBe('教师核对后的完整题目');expect(sent.body.questions[0].image_ids).toEqual(['b/two.png'])
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/finalize'))).toBe(false)
})
it('finalizes the whole transcription once and shows readonly download and explicit revision',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,init)=>path==='/exam-extraction-versions/v'?{id:'v',stale:false,snapshot:{...payload,source:record.source,assets:assets.map(a=>({...a,data_url:'data:image/png;base64,c25hcHNob3Q='})),filename:'final-V1.json',extraction_id:'e'}}:path.endsWith('/finalize')?{...record,read_only:true,versions:[{id:'v',revision:1,version_number:1,filename:'final-V1.json',created_at:'2026-11-13'}]}:base(path,init))
 page();await screen.findByText('已知x=2，求x的平方。')
 const button=screen.getByRole('button',{name:'定稿并生成原题提取文件'});expect((button as HTMLButtonElement).disabled).toBe(true)
 await waitFor(()=>expect((screen.getByLabelText(/我已核对整份试卷/) as HTMLInputElement).disabled).toBe(false))
 fireEvent.click(screen.getByLabelText(/我已核对整份试卷/));fireEvent.click(button)
 await screen.findByRole('button',{name:'基于终稿继续修订'})
 expect(screen.queryByRole('button',{name:'编辑第1题'})).toBeNull()
 const link=screen.getByRole('link',{name:'下载核对完成的原题提取文件'});expect(link.getAttribute('href')).toBe('/api/exam-extraction-versions/v/download')
 await waitFor(()=>expect(screen.getByAltText('第1题配图').getAttribute('src')).toBe('data:image/png;base64,c25hcHNob3Q='))
})
it('starts AI extraction without a prior block-review workflow',async()=>{
 mock(false);const base=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,init)=>path==='/exam-extractions'&&init?.method==='POST'?{...record,status:'queued',payload:null}:base(path,init))
 page();const button=await screen.findByRole('button',{name:'AI提取整份试卷'});await waitFor(()=>expect((button as HTMLButtonElement).disabled).toBe(false));fireEvent.click(button)
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p,i])=>p==='/exam-extractions'&&i?.method==='POST')).toBe(true))
 expect(vi.mocked(api).mock.calls.some(([p])=>p.includes('/source-review'))).toBe(false)
})
it('toggles each question independently and keeps edits when returning to browse',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,init)=>path==='/exam-extractions/e'&&!init?.method?{...record,payload:{...payload,questions:[q,{...q,key:'q2',number:'2',question_text:'第二题正文'}]}}:path==='/exam-extractions/e'&&init?.method==='PUT'?{...record,revision:2,payload:JSON.parse(init.body as string).body}:base(path,init))
 page();await screen.findByText('第二题正文')
 fireEvent.click(screen.getByRole('button',{name:'编辑第1题'}))
 fireEvent.change(screen.getByLabelText('第1题题目'),{target:{value:'第一题修订'}})
 expect(screen.queryByLabelText('第2题题目')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'浏览第1题'}))
 expect(screen.getByText('第一题修订')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'编辑第2题'}))
 expect(screen.queryByLabelText('第1题题目')).toBeNull()
 fireEvent.change(screen.getByLabelText('第2题题目'),{target:{value:'第二题修订'}})
 fireEvent.click(screen.getByRole('button',{name:'保存整份修改'}))
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([,i])=>i?.method==='PUT')).toBe(true))
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([,i])=>i?.method==='PUT')![1]!.body as string)
 expect(sent.body.questions.map((x:typeof q)=>x.question_text)).toEqual(['第一题修订','第二题修订'])
 expect(sent.body.questions[0].answer_text).toBe('4')
})
it.each(['questions_only','legacy'])('allows confirmation after removing questions and saving a real-shaped %s response',async mode=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 const items=[{...q,answer_text:''},{...q,key:'q2',number:'2',answer_text:'',question_text:'第二题正文'},{...q,key:'q3',number:'3',answer_text:'',question_text:'第三题正文'}]
 const initial=mode==='questions_only'?{content_mode:'questions_only',...payload,questions:items}:{...payload,questions:items}
 vi.mocked(api).mockImplementation(async(path,init)=>{
  if(path==='/exam-extractions/e'&&init?.method==='PUT'){
   const sent=JSON.parse(init.body as string).body
   // Pydantic serializes content_mode first, including the default for legacy drafts.
   return {...record,revision:2,payload:{content_mode:mode==='legacy'?'with_answers':'questions_only',title:sent.title,questions:sent.questions,notes:sent.notes}}
  }
  if(path==='/exam-extractions/e'&&!init?.method)return {...record,payload:initial}
  if(path.endsWith('/finalize'))return {...record,revision:2,payload:{...payload,questions:[items[0]]},read_only:true,versions:[]}
  return base(path,init)
 })
 page();await screen.findByText('第三题正文')
 await waitFor(()=>expect((screen.getByRole('button',{name:'编辑第2题'}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:'编辑第2题'}));fireEvent.click(screen.getByRole('button',{name:'移除此题'}))
 fireEvent.click(screen.getByRole('button',{name:'编辑第3题'}));fireEvent.click(screen.getByRole('button',{name:'移除此题'}))
 expect((screen.getByLabelText(/我已核对整份试卷/) as HTMLInputElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'保存整份修改'}));await screen.findByText('已保存整份提取稿；尚未定稿。')
 await waitFor(()=>expect((screen.getByLabelText(/我已核对整份试卷/) as HTMLInputElement).disabled).toBe(false))
 expect(screen.queryByText('请先保存整份修改，再定稿。')).toBeNull()
 fireEvent.click(screen.getByLabelText(/我已核对整份试卷/));fireEvent.click(screen.getByRole('button',{name:'定稿并生成原题提取文件'}))
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p,i])=>p.endsWith('/finalize')&&JSON.parse(i!.body as string).revision===2)).toBe(true))
})
