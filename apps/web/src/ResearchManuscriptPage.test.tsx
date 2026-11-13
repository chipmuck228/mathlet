import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import ResearchManuscriptPage from './ResearchManuscriptPage'
import CompleteQuestionEditor from './CompleteQuestionEditor'
import {api} from '@/lib/api'
vi.mock('@/lib/api',()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
vi.mock('./MathBlockEditor',()=>({default:({text,onChange,block}:{text:string;onChange:(value:string)=>void;block:{locator:string}})=><textarea aria-label={block.locator} value={text} onChange={e=>onChange(e.target.value)}/>}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
const questionBody={title:'反比例函数求系数',statement:'图象经过(2,3)，求k。',question_block_ids:['b'],answer_block_ids:[],answer_status:'unchecked',reference_answer:'未核对答案',figure_status:'not_needed',diagram_description:'',region:'',year:'',number:'',notes:'',assets:[],sources:[]}
const question={id:'q',revision:1,confirmed:true,stale:false,version_id:'qv',payload:questionBody}
const knowledge={items:[{ref:'kv:k',title:'反比例函数',unit_title:'函数',scope:'core',body:{statement:'定义',conditions:'非零系数'}}],inherited_relations:[],version_ids:['kv'],advisory_relations:[]}
const analysis={given_conditions:['图象经过点(2,3)'],goals:['求k'],thinking_operations:['代入'],problem_types:['已知点求系数'],classification_reason:'点在图象上',assessed_points:[{name:'点满足表达式',knowledge_refs:['kv:k'],evidence:'经过点'}],knowledge_breakdown:[{ref:'kv:k',role:'建立方程',conditions:'非零横坐标'}],approaches:[{id:'a',title:'代入',trigger:'已知点',steps:[{action:'代入坐标',reason:'点满足表达式',knowledge_refs:['kv:k']}],conclusion:'k=6',checks:'代回检验',limitations:''}],recognition_cues:['点在图象上'],common_mistakes:['交换坐标'],variation_prompts:['改变点'],scope_notes:[],missing_information:[]}
const output={id:'o',revision:1,kind:'analysis',state:'pending',body:analysis,original_body:analysis,checks:[{approach_id:'',category:'teaching',message:'是否增加迁移训练'}],final_version:null,final_blockers:[]}
const task={id:'r',revision:3,title:questionBody.title,status:'completed',stale:false,error:'',created_at:'2026-11-13',parent_version:null,model:{model:'test-model'},task:{context_id:'c',question_version_id:'qv',workflow:'manuscript-v1'},outputs:[output],knowledge,question:questionBody,calls:[]}
const profiles={active:'deepseek',profiles:[{id:'deepseek',label:'DeepSeek',model:'test-model',ready:true}]}
function mock(existing=true){vi.mocked(api).mockImplementation(async(path)=>{
 if(path==='/research/knowledge-versions')return [{id:'kv',title:'反比例函数知识终稿',count:1,stale:false,created_at:'2026-11-13'}]
 if(path==='/research/questions')return [question]
 if(path==='/research-editor/runs')return existing?[task]:[]
 if(path==='/research-editor/runs/r')return structuredClone(task)
 if(path==='/research/analysis-versions')return []
 if(path==='/editor/profiles')return profiles
 if(path==='/research-editor/runs/r/discussions')return []
 if(path.startsWith('/research-editor/relation-references?'))return [{id:'advice',version_id:'kv',title:'反比例函数',edges:[],created_at:'2026-11-13',teacher_verified:false}]
 throw new Error('Unexpected '+path)
})}
it('starts directly from knowledge finals and complete question without a context creation step',async()=>{
 mock(false);const base=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,init)=>path==='/research-editor/runs'&&init?.method==='POST'?{...task,status:'queued',outputs:[]}:base(path,init))
 render(<ResearchManuscriptPage documents={[]} onDirtyChange={vi.fn()} openKnowledge={vi.fn()}/>);
 await screen.findByRole('option',{name:/反比例函数求系数/})
 fireEvent.click(screen.getByLabelText(/反比例函数知识终稿/));fireEvent.change(screen.getByLabelText('已有完整题目'),{target:{value:'q'}})
 fireEvent.click(screen.getByRole('button',{name:'生成研究稿'}))
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p,i])=>p==='/research-editor/runs'&&i?.method==='POST')).toBe(true))
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([p,i])=>p==='/research-editor/runs'&&i?.method==='POST')![1]!.body as string)
 expect(sent.version_ids).toEqual(['kv']);expect(sent.question_version_id).toBe('qv');expect(sent.relation_message_ids).toEqual([])
 expect(vi.mocked(api).mock.calls.some(([p])=>p==='/research/contexts')).toBe(false)
})
it('opens history without model calls, edits inline and sends unsaved analysis as discussion context',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,init)=>{
  if(path==='/research-editor/runs/r/discussions'&&init?.method==='POST')return {id:'d',output_id:'o',version_id:null,status:'completed',error:'',response:'建议明确非零条件',model:{model:'test-model'},payload:{instruction:'检查条件',output_revision:1,source_version:null,uses_unsaved_body:true}}
  if(path==='/research-editor/runs/r/outputs/o')return {...task,revision:4,outputs:[{...output,revision:2,body:{...analysis,classification_reason:'教师未保存的修改'}}]}
  return base(path,init)
 })
 render(<ResearchManuscriptPage documents={[]} onDirtyChange={vi.fn()} openKnowledge={vi.fn()}/>);
 await screen.findByRole('navigation',{name:'研究目录'})
 expect(vi.mocked(api).mock.calls.every(([,i])=>!i?.method)).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'编辑'}));fireEvent.change(screen.getByLabelText('分类依据'),{target:{value:'教师未保存的修改'}})
 expect((screen.getByLabelText('已有研究') as HTMLSelectElement).disabled).toBe(true)
 fireEvent.change(screen.getByLabelText('给 AI 的问题或修订要求'),{target:{value:'检查条件'}})
 await waitFor(()=>expect((screen.getByRole('button',{name:'发送'}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:'发送'}))
 await screen.findAllByText('建议明确非零条件')
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([p,i])=>p.endsWith('/discussions')&&i?.method==='POST')![1]!.body as string)
 expect(sent.body.classification_reason).toBe('教师未保存的修改');expect(sent.profile_id).toBe('deepseek')
 fireEvent.click(screen.getByRole('button',{name:'保存研究稿修改'}))
 await waitFor(()=>expect(screen.queryByRole('button',{name:'保存研究稿修改'})).toBeNull())
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/finalize'))).toBe(false)
})
it('confirms the whole manuscript, reads final, then opens a separate revision without regeneration',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 const frozen={id:'av',output_id:'o',revision:2,created_at:'2026-11-13',snapshot:{analysis,checks:output.checks,question:questionBody,knowledge,run_id:'r',run_revision:4,input:task.task,model:task.model}}
 vi.mocked(api).mockImplementation(async(path,init)=>{
  if(path==='/research-editor/runs/r/outputs/o/finalize')return {id:'av'}
  if(path==='/research-editor/versions/av')return frozen
  if(path==='/research-editor/versions/av/revise')return {...task,id:'fork',revision:1,parent_version:'av',outputs:[{...output,id:'new-output'}]}
  if(path==='/research-editor/runs/fork/discussions')return []
  return base(path,init)
 })
 render(<ResearchManuscriptPage documents={[]} onDirtyChange={vi.fn()} openKnowledge={vi.fn()}/>);
 const finalButton=await screen.findByRole('button',{name:'形成研究终稿'}) as HTMLButtonElement
 expect(finalButton.disabled).toBe(true)
 fireEvent.click(screen.getByLabelText(/我已检查整份研究稿/));fireEvent.click(finalButton)
 await screen.findByRole('button',{name:'基于终稿继续修订'})
 expect((screen.getByRole('button',{name:'编辑'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'基于终稿继续修订'}))
 await waitFor(()=>expect((screen.getByRole('button',{name:'编辑'}) as HTMLButtonElement).disabled).toBe(false))
 expect(vi.mocked(api).mock.calls.some(([p,i])=>p==='/research-editor/runs'&&i?.method==='POST')).toBe(false)
})
it('preserves unsaved research text when a stale save is rejected',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,init)=>{if(path==='/research-editor/runs/r/outputs/o')throw Error('依据已经变化');return base(path,init)})
 render(<ResearchManuscriptPage documents={[]} onDirtyChange={vi.fn()} openKnowledge={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'编辑'}));fireEvent.change(screen.getByLabelText('分类依据'),{target:{value:'需要保留的输入'}});fireEvent.click(screen.getByRole('button',{name:'保存研究稿修改'}))
 await screen.findByRole('alert')
 expect((screen.getByLabelText('分类依据') as HTMLTextAreaElement).value).toBe('需要保留的输入')
 expect((screen.getByRole('button',{name:'形成研究终稿'}) as HTMLButtonElement).disabled).toBe(true)
})
it('confirming an unchanged complete question does not re-save or invalidate its prior version',async()=>{
 vi.mocked(api).mockResolvedValue(question)
 render(<CompleteQuestionEditor initial={question} documents={[]} disabled={false} onDirty={vi.fn()} onSaved={vi.fn()}/>);
 fireEvent.click(screen.getByLabelText(/我已检查本题题干/));fireEvent.click(screen.getByRole('button',{name:'保存并确认完整题目'}))
 await waitFor(()=>expect(vi.mocked(api)).toHaveBeenCalledWith('/research/questions/q/confirm',expect.objectContaining({method:'POST'})))
 expect(vi.mocked(api).mock.calls.some(([p,i])=>p==='/research/questions/q'&&i?.method==='PUT')).toBe(false)
})

it('opens the exact research run selected from the paper workflow instead of the latest run',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,init)=>path==='/research-editor/runs/selected'?{...task,id:'selected',title:'整卷中选定的题目'}:base(path,init))
 render(<ResearchManuscriptPage initialRunId="selected" documents={[]} onDirtyChange={vi.fn()} openKnowledge={vi.fn()}/>);
 await screen.findByRole('navigation',{name:'研究目录'})
 expect(vi.mocked(api).mock.calls.some(([p])=>p==='/research-editor/runs/selected')).toBe(true)
 expect(vi.mocked(api).mock.calls.some(([p])=>p==='/research-editor/runs/r')).toBe(false)
})
