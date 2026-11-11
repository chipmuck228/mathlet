import {afterEach,expect,it,vi} from 'vitest'
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import ResearchPage from './ResearchPage'
import {api} from '@/lib/api'
vi.mock('@/lib/api',()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
vi.mock('./MathBlockEditor',()=>({default:({text,onChange,block}:{text:string;onChange:(s:string)=>void;block:{locator:string}})=><textarea aria-label={block.locator} value={text} onChange={e=>onChange(e.target.value)}/>}))
afterEach(()=>{cleanup();vi.useRealTimers();vi.restoreAllMocks();vi.mocked(api).mockReset()})
const body={title:'求反比例函数系数',question_block_ids:['b'],answer_block_ids:[],statement:'图象经过(2,3)，求k。',answer_status:'unchecked',reference_answer:'未核对答案',figure_status:'not_needed',diagram_description:'',region:'',year:'',number:'',notes:''}
const q={id:'q',revision:1,confirmed:true,stale:false,version_id:'qv',payload:{...body,assets:[],sources:[]}}
const context={id:'c',title:'反比例函数知识集',revision:1,stale:false,version_ids:['v'],snapshot:{items:[{ref:'ref',title:'反比例函数',unit_title:'函数',scope:'core',body:{statement:'函数定义',conditions:'k和x均非零'}}],inherited_relations:[]}}
function mock(questions:()=>unknown[]=()=>[],tasks:unknown[]=[]){vi.mocked(api).mockImplementation(async(path,init)=>{
 if(path==='/research/knowledge-versions')return [{id:'v',title:'反比例函数',run_revision:3,count:1,stale:false}]
 if(path==='/research/contexts')return init?.method==='POST'?context:[context]
 if(path==='/research/questions')return questions()
 if(path==='/research/runs')return init?.method==='POST'?{id:'new'}:tasks
 if(['/research/graph-versions','/research/analysis-versions','/research/contexts/c/relations'].includes(path))return []
 if(path==='/research/questions/q')throw Error('409 内容已变化')
 throw Error(path)
})}
it('uses fixed reviewed versions to create a research context',async()=>{
 mock();render(<ResearchPage documents={[]} onDirtyChange={vi.fn()} openKnowledge={vi.fn()}/>)
 await waitFor(()=>expect(screen.getByText(/反比例函数 · 候选修订 3/)).toBeTruthy())
 expect((screen.getByRole('button',{name:'建立研究知识集'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByLabelText(/反比例函数 · 候选修订 3/))
 fireEvent.change(screen.getByLabelText('研究知识集名称'),{target:{value:'函数研究'}})
 fireEvent.click(screen.getByRole('button',{name:'建立研究知识集'}))
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/research/contexts',expect.objectContaining({method:'POST'})))
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([p,init])=>p==='/research/contexts'&&init?.method==='POST')![1]!.body as string)
 expect(sent).toEqual({title:'函数研究',version_ids:['v']})
})
it('requires an explicitly selected confirmed question and consent to start analysis',async()=>{
 mock(()=>[q]);render(<ResearchPage documents={[]} onDirtyChange={vi.fn()} openKnowledge={vi.fn()}/>)
 await waitFor(()=>expect(screen.getByRole('option',{name:/反比例函数知识集/})).toBeTruthy())
 fireEvent.change(screen.getByLabelText('当前研究知识集'),{target:{value:'c'}})
 fireEvent.change(screen.getByLabelText('研究任务'),{target:{value:'analysis'}})
 const start=screen.getByRole('button',{name:'开始研究任务'}) as HTMLButtonElement
 expect(start.disabled).toBe(true)
 fireEvent.change(screen.getByLabelText('已有题目'),{target:{value:'q'}})
 expect(start.disabled).toBe(true)
 expect(screen.getByLabelText('参考答案状态')).toHaveProperty('value','unchecked')
 fireEvent.click(screen.getByLabelText(/确认向已保存模型发送上述研究资料/))
 expect(start.disabled).toBe(false)
 fireEvent.click(start)
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/research/runs',expect.objectContaining({method:'POST'})))
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([p,init])=>p==='/research/runs'&&init?.method==='POST')![1]!.body as string)
 expect(sent.question_version_id).toBe('qv');expect(sent.context_revision).toBe(1);expect(sent.consent).toBe(true)
 expect(sent.reference_answer).toBeUndefined()
})
it('preserves unsaved question text and its original revision across polling updates',async()=>{
 let tick=()=>{};const nativeInterval=globalThis.setInterval;vi.spyOn(globalThis,'setInterval').mockImplementation((callback,delay,...args)=>{if(delay===3000){tick=callback as ()=>void;return 123 as unknown as ReturnType<typeof setInterval>}return nativeInterval(callback,delay,...args)})
 let current=structuredClone(q);mock(()=>[current]);render(<ResearchPage documents={[]} onDirtyChange={vi.fn()} openKnowledge={vi.fn()}/>)
 await waitFor(()=>expect(screen.getByRole('option',{name:/求反比例函数系数/})).toBeTruthy())
 fireEvent.change(screen.getByLabelText('已有题目'),{target:{value:'q'}})
 fireEvent.change(screen.getByLabelText('完整题干'),{target:{value:'教师尚未保存的完整题干'}})
 current={...q,revision:2,payload:{...q.payload,statement:'其他页面修改'}}
 await act(async()=>{tick();await new Promise(resolve=>setTimeout(resolve,0))})
 expect((screen.getByLabelText('完整题干') as HTMLTextAreaElement).value).toBe('教师尚未保存的完整题干')
 expect(screen.getByText(/题目已被其他页面修订/)).toBeTruthy()
 await act(async()=>{fireEvent.click(screen.getByRole('button',{name:'保存题目新修订'}))})
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([p])=>p==='/research/questions/q')![1]!.body as string)
 expect(sent.revision).toBe(1)
 expect((screen.getByLabelText('完整题干') as HTMLTextAreaElement).value).toBe('教师尚未保存的完整题干')
})
it('keeps research approval disabled while a candidate edit is unsaved',async()=>{
 const task={id:'t',revision:1,status:'completed',stale:false,error:'',task:{context_id:'c',context_revision:1,kind:'analysis',question_version_id:'qv'},outputs:[{id:'o',revision:1,kind:'analysis',state:'pending',body:{problem_types:['求系数'],classification_reason:'已知点坐标',missing_information:[]},original_body:{problem_types:['求系数'],classification_reason:'已知点坐标',missing_information:[]},checks:[],reviewer:'',note:''}],calls:[]}
 mock(()=>[],[task]);render(<ResearchPage documents={[]} onDirtyChange={vi.fn()} openKnowledge={vi.fn()}/>)
 await waitFor(()=>expect(screen.getByRole('option',{name:/反比例函数知识集/})).toBeTruthy())
 fireEvent.change(screen.getByLabelText('当前研究知识集'),{target:{value:'c'}})
 fireEvent.change(screen.getByLabelText('研究任务记录'),{target:{value:'t'}})
 fireEvent.click(screen.getByRole('button',{name:'选择本任务全部候选'}))
 fireEvent.change(screen.getByLabelText('审核人／处理人'),{target:{value:'老师'}})
 fireEvent.change(screen.getByLabelText('审核与处理说明'),{target:{value:'已核对思路'}})
 fireEvent.click(screen.getByLabelText(/我已核对当前操作/))
 const approve=screen.getByRole('button',{name:'确认选中研究候选'}) as HTMLButtonElement
 expect(approve.disabled).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'编辑研究候选'}))
 fireEvent.change(screen.getByLabelText('分类依据'),{target:{value:'新的分类依据'}})
 expect(approve.disabled).toBe(true)
 expect((screen.getByRole('button',{name:'保存研究修订'}) as HTMLButtonElement).disabled).toBe(false)
})
