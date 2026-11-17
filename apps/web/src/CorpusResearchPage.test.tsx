import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import CorpusResearchPage from './CorpusResearchPage'
import {api} from '@/lib/api'
vi.mock('@/lib/api',()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
vi.mock('./ReadableMath',()=>({default:({text}:{text:string})=><span>{text}</span>}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
const run={id:'run',status:'completed',revision:2,error:'',stale:false,problem_types:['数量关系'],identified_names:['等式性质'],finals:[{id:'av',stale:false,created_at:'2026-11-15'}]}
const catalog={exams:[{id:'ev',title:'合成卷一',filename:'exam-V1.json',category:'exam',count:2,stale:false}],questions:[{id:'ev:q1',exam_id:'ev',title:'合成卷一 · 第1题',number:'1',statement:'已知x=2求x平方',blockers:[],duplicate_count:1,runs:[run]},{id:'ev:q2',exam_id:'ev',title:'合成卷一 · 第2题',number:'2',statement:'有图题',blockers:['必要图形条件待补充'],duplicate_count:1,runs:[]}]}
const mapping={id:'map',analysis_version_id:'av',revision:1,status:'completed',run_revision:2,error:'',stale:false,read_only:false,payload:{links:[{ref:'kv:k',role:'support',reason:'用于转译条件',evidence:'已知x=2'}],gaps:['缺少乘方知识'],summary:'按实际作用匹配'},knowledge:[{ref:'kv:k',title:'等式性质',unit_title:'一元一次方程'}],finals:[]}
function mock(withMapping=false){vi.mocked(api).mockImplementation(async(path,init)=>{
 if(path==='/corpus/catalog')return catalog
 if(path==='/corpus/mappings'&&!init?.method)return withMapping?[mapping]:[]
 if(path==='/corpus/tasks')return []
 if(path==='/research/knowledge-versions')return [{id:'kv',title:'一元一次方程',count:10,stale:false}]
 if(path==='/corpus/studies')return {results:[{run_id:'run'}]}
 if(path==='/corpus/mappings'&&init?.method==='POST')return {results:[{id:'map'}]}
 throw Error('Unexpected '+path)
})}
function expand(title:string){fireEvent.click(within(screen.getByRole('region',{name:title})).getByRole('button',{name:'展开题目'}))}
function page(onDirty=vi.fn()){render(<CorpusResearchPage onDirtyChange={onDirty}/>)}
it('queues independent questions without any selected knowledge and blocks incomplete figure questions',async()=>{
 mock();page();await screen.findByText(/exam-V1.json/)
 expect(vi.mocked(api).mock.calls.every(([,i])=>!i?.method)).toBe(true)
 fireEvent.click(screen.getByRole('checkbox',{name:/合成卷一 · exam/}))
 expect((screen.getByRole('checkbox',{name:'研究 合成卷一 · 第2题'}) as HTMLInputElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('checkbox',{name:'选择当前可研究题目'}));fireEvent.click(screen.getByRole('button',{name:'批量独立研究（1题）'}))
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p,i])=>p==='/corpus/studies'&&i?.method==='POST')).toBe(true))
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([p,i])=>p==='/corpus/studies'&&i?.method==='POST')![1]!.body as string)
 expect(sent.question_ids).toEqual(['ev:q1']);expect(sent.version_ids).toBeUndefined()
})
it('keeps only question research and leaves mapping, cards and bank management to unit composition',async()=>{
 mock();page();await screen.findByText(/exam-V1.json/)
 expect(screen.queryByRole('tab')).toBeNull()
 expect(vi.mocked(api).mock.calls.map(([p])=>p)).toEqual(['/corpus/catalog'])
 fireEvent.click(screen.getByRole('checkbox',{name:/合成卷一 · exam/}));expand('合成卷一 · 第1题')
 expect(screen.queryByRole('checkbox',{name:/选择研究终稿/})).toBeNull()
 expect(screen.getByRole('link',{name:'下载研究终稿 JSON'}).getAttribute('href')).toBe('/api/research/versions/analysis/av/download')
 fireEvent.change(screen.getByLabelText('题库研究状态'),{target:{value:'conditions'}})
 expect(screen.queryByRole('region',{name:'合成卷一 · 第1题'})).toBeNull()
 expect(screen.getByRole('region',{name:'合成卷一 · 第2题'})).toBeTruthy()
})
it('opens the exact blocked question inline, without a fallback to the first study',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 const conditions={id:'exact-q2',revision:1,confirmed:false,stale:false,version_id:null,payload:{title:'指定第二题',statement:'指定第二题正文',question_block_ids:[],answer_block_ids:[],answer_status:'absent',reference_answer:'',figure_status:'pending',diagram_description:'',region:'',year:'',number:'2',notes:'',assets:[],sources:[]}}
 vi.mocked(api).mockImplementation(async(path,init)=>{
  if(path==='/corpus/catalog')return {...catalog,questions:catalog.questions.map(q=>({...q,question_id:q.number==='2'?'exact-q2':'exact-q1'}))}
  if(path==='/research/questions/exact-q2')return conditions
  if(path==='/documents')return []
  return base(path,init)
 })
 page();await screen.findByText(/exam-V1.json/);fireEvent.click(screen.getByRole('checkbox',{name:/合成卷一 · exam/}))
 expand('合成卷一 · 第2题');fireEvent.click(screen.getByRole('button',{name:'补充／编辑本题条件'}))
 await screen.findByRole('region',{name:'完整题目编辑'})
 expect(screen.getByDisplayValue('指定第二题正文')).toBeTruthy()
 expect(vi.mocked(api).mock.calls.some(([p])=>p==='/research/questions/exact-q2')).toBe(true)
 expect(vi.mocked(api).mock.calls.some(([p])=>p.startsWith('/research-editor/runs/'))).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'收起编辑区'}))
 await screen.findByText('有图题');expect((screen.getByRole('checkbox',{name:/合成卷一 · exam/}) as HTMLInputElement).checked).toBe(true)
})
it('reviews and finalizes the selected study inline and returns to the same selected exam',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 const question={title:'第一题指定研究',statement:'已知x=2求x平方',question_block_ids:[],answer_block_ids:[],answer_status:'absent',reference_answer:'',figure_status:'not_needed',diagram_description:'',region:'',year:'',number:'1',notes:'',assets:[],sources:[]}
 const body={given_conditions:['x=2'],goals:['求平方'],thinking_operations:['代入'],problem_types:['计算'],classification_reason:'已知数求平方',assessed_points:[],knowledge_breakdown:[],approaches:[],recognition_cues:['已知x'],common_mistakes:[],variation_prompts:[],scope_notes:[],missing_information:[]}
 const out={id:'output',revision:1,body,original_body:body,checks:[],final_version:null,final_blockers:[]}
 const study={id:'run',revision:2,title:question.title,status:'completed',stale:false,error:'',created_at:'2026-11-15',parent_version:null,model:{model:'mock'},task:{context_id:'ctx',question_version_id:'qv',workflow:'independent-v1'},outputs:[out],knowledge:{items:[],inherited_relations:[],version_ids:[]},question,calls:[]}
 let finalized=false
 vi.mocked(api).mockImplementation(async(path,init)=>{
  if(path==='/corpus/catalog')return {...catalog,questions:catalog.questions.map(q=>({...q,runs:q.runs.map(r=>({...r,finals:finalized?[{id:'new-final',stale:false,created_at:'2026-11-15'}]:[]}))}))}
  if(path==='/editor/profiles')return {active:'deepseek',profiles:[{id:'deepseek',label:'DeepSeek',model:'mock',ready:true}]}
  if(path==='/research-editor/runs/run')return study
  if(path==='/research-editor/runs/run/discussions')return []
  if(path==='/research-editor/runs/run/outputs/output/finalize'){finalized=true;return {id:'new-final'}}
  if(path==='/research-editor/versions/new-final')return {id:'new-final',output_id:'output',revision:2,snapshot:{analysis:body,checks:[],question,knowledge:study.knowledge,run_id:'run',run_revision:3,input:study.task,model:{model:'mock'}}}
  return base(path,init)
 })
 page();await screen.findByText(/exam-V1.json/);fireEvent.click(screen.getByRole('checkbox',{name:/合成卷一 · exam/}))
 expand('合成卷一 · 第1题');fireEvent.click(screen.getByRole('button',{name:'打开研究稿／审核定稿'}))
 await screen.findByRole('heading',{name:/第一题指定研究 · 研究工作稿/})
 expect(screen.queryByRole('combobox',{name:'已有研究'})).toBeNull()
 const confirmation=screen.getByLabelText(/我已检查整份研究稿/)
 fireEvent.click(confirmation);fireEvent.click(screen.getByRole('button',{name:'形成研究终稿'}))
 await screen.findByRole('heading',{name:/第一题指定研究 · 研究终稿/})
 expect(finalized).toBe(true)
 await waitFor(()=>expect((screen.getByRole('button',{name:'收起编辑区'}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:'收起编辑区'}))
 await screen.findByRole('link',{name:'下载研究终稿 JSON'})
 expect((screen.getByRole('checkbox',{name:/合成卷一 · exam/}) as HTMLInputElement).checked).toBe(true)
 expect(vi.mocked(api).mock.calls.some(([p])=>p==='/research-editor/runs')).toBe(false)
})
it('protects unsaved edits in the exact question and offers explicit discard',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 const target={id:'q2',revision:1,confirmed:false,stale:false,version_id:null,payload:{title:'待补第二题',statement:'第二题待修订',question_block_ids:[],answer_block_ids:[],answer_status:'absent',reference_answer:'',figure_status:'pending',diagram_description:'',region:'',year:'',number:'2',notes:'',assets:[],sources:[]}}
 vi.mocked(api).mockImplementation(async(path,init)=>path==='/corpus/catalog'?{...catalog,questions:catalog.questions.map(q=>({...q,question_id:'q2'}))}:path==='/research/questions/q2'?target:path==='/documents'?[]:base(path,init))
 page();await screen.findByText(/exam-V1.json/);fireEvent.click(screen.getByRole('checkbox',{name:/合成卷一 · exam/}));expand('合成卷一 · 第2题');fireEvent.click(screen.getByRole('button',{name:'补充／编辑本题条件'}))
 const input=await screen.findByLabelText('提取结果 完整题干');fireEvent.change(input,{target:{value:'未保存的条件修订'}})
 await waitFor(()=>expect((screen.getByRole('button',{name:'收起编辑区'}) as HTMLButtonElement).disabled).toBe(true))
 fireEvent.click(screen.getByRole('button',{name:'放弃未保存编辑'}))
 await screen.findByRole('button',{name:'补充／编辑本题条件'})
 expect(vi.mocked(api).mock.calls.some(([,i])=>i?.method==='PUT')).toBe(false)
})
it('keeps condition editing available after saving and connects confirmation to single-question generation',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 let target={id:'q2',revision:1,confirmed:false,stale:false,version_id:null as string|null,payload:{title:'第二题',statement:'第二题原文',question_block_ids:['b2'],answer_block_ids:[],answer_status:'absent',reference_answer:'',figure_status:'pending',diagram_description:'',region:'',year:'',number:'2',notes:'',assets:[],sources:[]}}
 let generated=false
 vi.mocked(api).mockImplementation(async(path,init)=>{
  if(path==='/corpus/catalog')return {...catalog,questions:[{...catalog.questions[1],question_id:'q2',statement:target.payload.statement,blockers:target.confirmed?[]:['保存后仍需确认完整性'],runs:generated?[{...run,id:'new-run',status:'queued',finals:[]}]:[]}]}
  if(path==='/documents')return []
  if(path==='/research/questions/q2'&&init?.method==='PUT'){target={...target,revision:target.revision+1,confirmed:false,payload:{...target.payload,...JSON.parse(init.body as string)}};return target}
  if(path==='/research/questions/q2')return target
  if(path==='/research/questions/q2/confirm'){target={...target,confirmed:true,version_id:'qv2'};return target}
  if(path==='/corpus/studies'){generated=true;return {results:[{run_id:'new-run',status:'queued'}]}}
  if(path==='/editor/profiles')return {active:'deepseek',profiles:[]}
  if(path==='/research-editor/runs/new-run')return {id:'new-run',revision:1,status:'queued',stale:false,outputs:[],title:'第二题',task:{},calls:[],model:{model:'mock'}}
  if(path==='/research-editor/runs/new-run/discussions')return []
  return base(path,init)
 })
 page();await screen.findByText(/exam-V1.json/);fireEvent.click(screen.getByRole('checkbox',{name:/合成卷一 · exam/}));expand('合成卷一 · 第2题')
 fireEvent.click(screen.getByRole('button',{name:'补充／编辑本题条件'}));await screen.findByLabelText('提取结果 完整题干')
 fireEvent.change(screen.getByLabelText('提取结果 图形文字条件'),{target:{value:'已核对图形条件'}})
 fireEvent.change(screen.getByLabelText('图形条件状态'),{target:{value:'described'}})
 fireEvent.click(screen.getByRole('button',{name:'保存题目草稿'}))
 await screen.findByText('条件修改已保存，尚需勾选完整性确认；也可继续编辑。')
 expect((screen.getByRole('button',{name:'生成本题研究稿'}) as HTMLButtonElement).disabled).toBe(true)
 await waitFor(()=>expect((screen.getByRole('button',{name:'收起编辑区'}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:'收起编辑区'}));fireEvent.click(screen.getByRole('button',{name:'补充／编辑本题条件'}))
 await screen.findByDisplayValue('已核对图形条件')
 fireEvent.click(screen.getByLabelText(/我已检查本题题干/));fireEvent.click(screen.getByRole('button',{name:'保存并确认完整题目'}))
 await waitFor(()=>expect((screen.getByRole('button',{name:'生成本题研究稿'}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:'生成本题研究稿'}))
 await screen.findByRole('button',{name:'打开研究稿／审核定稿'})
 expect(generated).toBe(true)
 expect(screen.queryByRole('checkbox',{name:/选择研究终稿/})).toBeNull()
})
