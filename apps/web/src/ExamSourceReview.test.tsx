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
it('reads whole questions and original answers without block check buttons or model calls',async()=>{
 mock();page();await screen.findByText('已知x=2，求x的平方。')
 expect(screen.getByText('原文解答')).toBeTruthy();expect(screen.queryByRole('button',{name:'已核对'})).toBeNull()
 expect(screen.getByText('原文只读对照')).toBeTruthy()
 expect(vi.mocked(api).mock.calls.every(([,i])=>!i?.method)).toBe(true)
})
it('edits the complete question and chooses a replacement from all original images then saves the whole paper',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,init)=>path==='/exam-extractions/e'&&init?.method==='PUT'?{...record,revision:2,payload:JSON.parse(init.body as string).body}:base(path,init))
 page();await screen.findByText('已知x=2，求x的平方。');await waitFor(()=>expect((screen.getByRole('button',{name:'编辑整份提取稿'}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:'编辑整份提取稿'}));fireEvent.change(screen.getByLabelText('第1题题目'),{target:{value:'教师核对后的完整题目'}})
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
 expect(screen.queryByRole('button',{name:'编辑整份提取稿'})).toBeNull()
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
