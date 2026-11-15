import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
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
function page(onDirty=vi.fn()){render(<CorpusResearchPage onOpenRun={vi.fn()} onDirtyChange={onDirty}/>)}
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
it('matches selected reviewed analysis to knowledge without queuing a new solve',async()=>{
 mock();page();await screen.findByText(/exam-V1.json/);fireEvent.click(screen.getByRole('tab',{name:'知识关联'}))
 fireEvent.click(screen.getByRole('checkbox',{name:/合成卷一 · 第1题/}));fireEvent.click(screen.getByRole('checkbox',{name:/一元一次方程 · 10项/}))
 fireEvent.click(screen.getByRole('button',{name:'只生成知识关联，不重新解题'}))
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p,i])=>p==='/corpus/mappings'&&i?.method==='POST')).toBe(true))
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([p,i])=>p==='/corpus/mappings'&&i?.method==='POST')![1]!.body as string)
 expect(sent).toEqual({analysis_version_ids:['av'],version_ids:['kv']})
 expect(vi.mocked(api).mock.calls.some(([p])=>p==='/corpus/studies')).toBe(false)
})
it('lets teachers edit links and protects unsaved mapping edits from tab switching',async()=>{
 mock(true);const onDirty=vi.fn();page(onDirty);await screen.findByText(/exam-V1.json/);fireEvent.click(screen.getByRole('tab',{name:'知识关联'}))
 await screen.findByText('按实际作用匹配');fireEvent.click(screen.getByRole('button',{name:'编辑关联'}))
 fireEvent.change(screen.getByLabelText('匹配理由'),{target:{value:'教师修订的理由'}})
 await waitFor(()=>expect(onDirty).toHaveBeenLastCalledWith(true))
 expect((screen.getByRole('tab',{name:'跨题思路卡'}) as HTMLButtonElement).disabled).toBe(true)
 expect((screen.getByLabelText('确认知识关联') as HTMLInputElement).disabled).toBe(true)
 expect((screen.getByRole('button',{name:'保存关联修改'}) as HTMLButtonElement).disabled).toBe(false)
})
it('can auto-match all effective knowledge finals without requiring a preselected section',async()=>{
 mock();page();await screen.findByText(/exam-V1.json/);fireEvent.click(screen.getByRole('tab',{name:'知识关联'}))
 fireEvent.click(screen.getByRole('checkbox',{name:/合成卷一 · 第1题/}))
 fireEvent.click(screen.getByRole('button',{name:'只生成知识关联，不重新解题'}))
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p,i])=>p==='/corpus/mappings'&&i?.method==='POST')).toBe(true))
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([p,i])=>p==='/corpus/mappings'&&i?.method==='POST')![1]!.body as string)
 expect(sent.version_ids).toEqual([])
 expect(vi.mocked(api).mock.calls.some(([p])=>p==='/corpus/studies')).toBe(false)
})
