import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import TeachingPage from './TeachingPage'
import {api} from '@/lib/api'
vi.mock('@/lib/api',()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
vi.mock('./MathBlockEditor',()=>({default:({block,text,onChange}:{block:{locator:string};text:string;onChange:(v:string)=>void})=><textarea aria-label={block.locator} value={text} onChange={e=>onChange(e.target.value)}/>}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
const knowledge={title:'二元一次方程组',items:[{ref:'v:k',title:'加减消元',scope:'core',body:{statement:'消去一个未知数',conditions:'系数相同或相反',formula:'',positive_example:'两式相加',misconception:'漏掉常数项'}}]}
const application={id:'m1',quote:'x+y=5',knowledge_ref:'v:k',why:'两个方程可消去y',operation:'比较系数',conditions:'同一组解',approach_id:'add',step_index:0}
const analysis={given_conditions:['x+y=5','x-y=1'],goals:['求x、y'],thinking_operations:['消元'],problem_types:['解方程组'],classification_reason:'同时满足两个方程',assessed_points:[{name:'消元',knowledge_refs:['v:k'],evidence:'系数相反'}],knowledge_breakdown:[{ref:'v:k',role:'相加消去y',conditions:'同一组解'}],approaches:[{id:'add',title:'相加消元',trigger:'系数相反',steps:[{action:'两式相加',reason:'等式性质',knowledge_refs:['v:k']}],conclusion:'x=3，y=2',checks:'同时代回',limitations:'检查全部方程'}],recognition_cues:['系数相反'],common_mistakes:[],variation_prompts:[],scope_notes:[],missing_information:[]}
const phase=['read','relate','plan','solve','check']
const body={title:'方程组应用与训练',teacher_notes:'',cases:[{question_version_id:'qv',relevance:'primary',relevance_reason:'直接使用消元',analysis,applications:[application],training:phase.map(p=>({phase:p,prompt:'请先思考',mapping_ids:['m1'],hints:['先比较系数'],expected_reasoning:'选择相加',checkpoints:['同时满足两式']})),knowledge_gaps:[]}]}
const task={id:'r',revision:2,status:'completed',error:'',stale:false,created_at:'2026-11-13',knowledge,questions:[{version_id:'qv',title:'代表练习',statement:'x+y=5，x-y=1，求x、y。',diagram_description:'',answer_status:'unchecked',assets:[],sources:[{document_name:'合成练习',locator:'段落1',category:'mock'}]}],task:{reused_analysis:{}},calls:[],manuscript:{revision:1,payload:body,original_payload:body,checks:[],read_only:false,parent_version:null,blockers:[],coverage:[{ref:'v:k',title:'加减消元',status:'有应用证据',applications:[{question_version_id:'qv',mapping_id:'m1'}]}],finals:[]}}
function mock(existing=true,completeQuestion=true){vi.mocked(api).mockImplementation(async(path)=>{
 if(path==='/research/knowledge-versions')return [{id:'v',title:'二元一次方程组',count:10,stale:false,created_at:'2026-11-13'}]
 if(path==='/research/questions')return [{id:'q',revision:1,confirmed:completeQuestion,stale:false,version_id:completeQuestion?'qv':null,payload:{title:'代表练习',statement:'x+y=5，x-y=1，求x、y。',figure_status:'not_needed',answer_status:'unchecked',sources:[]}}]
 if(path==='/teaching/runs')return existing?[{id:'r',title:body.title,status:'completed',created_at:'2026-11-13'}]:[]
 if(path==='/teaching/runs/r')return structuredClone(task)
 throw Error('Unexpected '+path)
})}
it('selects the actual local ten-item final and confirmed questions without automatically calling a model',async()=>{
 mock(false);const base=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,init)=>path==='/teaching/runs'&&init?.method==='POST'?{...task,status:'queued',manuscript:null}:base(path,init))
 render(<TeachingPage onDirtyChange={vi.fn()} onOpenPaper={vi.fn()} onOpenResearch={vi.fn()}/>);
 await screen.findByText(/本次使用 10 项固定知识/)
 expect(vi.mocked(api).mock.calls.every(([,i])=>!i?.method)).toBe(true)
 fireEvent.click(screen.getByLabelText('代表题 代表练习'));fireEvent.click(screen.getByRole('button',{name:'生成应用映射、训练与解析'}))
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p,i])=>p==='/teaching/runs'&&i?.method==='POST')).toBe(true))
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([p,i])=>p==='/teaching/runs'&&i?.method==='POST')![1]!.body as string)
 expect(sent.knowledge_version_id).toBe('v');expect(sent.question_version_ids).toEqual(['qv'])
})
it('edits the application why without approving and preserves exact revision guards',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,init)=>path==='/teaching/runs/r'&&init?.method==='PUT'?{...task,manuscript:{...task.manuscript,revision:2,payload:{...body,cases:[{...body.cases[0],applications:[{...application,why:'教师解释：比较系数决定消元对象'}]}]}}}:base(path,init))
 const dirty=vi.fn();render(<TeachingPage onDirtyChange={dirty} onOpenPaper={vi.fn()} onOpenResearch={vi.fn()}/>);
 await screen.findByRole('region',{name:'应用映射与训练正文'})
 fireEvent.click(screen.getByRole('button',{name:'编辑映射、训练和解析'}));fireEvent.change(screen.getByLabelText('为什么想到这个知识'),{target:{value:'教师解释：比较系数决定消元对象'}})
 await waitFor(()=>expect(dirty).toHaveBeenLastCalledWith(true));expect((screen.getByLabelText('应用训练历史') as HTMLSelectElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'保存本轮修订'}))
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p,i])=>p==='/teaching/runs/r'&&i?.method==='PUT')).toBe(true))
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([p,i])=>p==='/teaching/runs/r'&&i?.method==='PUT')![1]!.body as string)
 expect(sent.revision).toBe(1);expect(sent.run_revision).toBe(2);expect(sent.body.cases[0].applications[0].why).toContain('教师解释')
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/finalize'))).toBe(false)
})
it('offers a fixed offline reader only after explicit teacher review',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!;let finalized=false
 vi.mocked(api).mockImplementation(async(path,init)=>{
 if(path==='/teaching/runs/r/finalize'){finalized=true;return {id:'fv'}}
 if(path==='/teaching/runs/r'&&finalized)return {...task,manuscript:{...task.manuscript,read_only:true,finals:[{id:'fv',revision:1,created_at:'2026-11-13'}]}}
 return base(path,init)
 })
 render(<TeachingPage onDirtyChange={vi.fn()} onOpenPaper={vi.fn()} onOpenResearch={vi.fn()}/>);
 await screen.findByRole('region',{name:'应用映射与训练正文'})
 const button=screen.getByRole('button',{name:'审定并生成固定读物'});expect((button as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByLabelText(/我已审定原题应用映射/));fireEvent.click(button)
 const link=await screen.findByRole('link',{name:'下载离线 HTML 读物'});expect(link.getAttribute('href')).toBe('/api/teaching/versions/fv/download')
})
it('does not mistake checked transcription for complete confirmed questions',async()=>{
 mock(false,false);const open=vi.fn();render(<TeachingPage onDirtyChange={vi.fn()} onOpenPaper={open} onOpenResearch={vi.fn()}/>);
 await screen.findByText(/暂没有已确认完整的题目/)
 expect(screen.queryByLabelText('代表题 代表练习')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'选择核对文件，分题并确认完整题目'}));expect(open).toHaveBeenCalled()
})
