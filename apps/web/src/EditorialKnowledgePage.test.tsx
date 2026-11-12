import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import EditorialKnowledgePage from './EditorialKnowledgePage'
import {api} from '@/lib/api'
vi.mock('@/lib/api',()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
vi.mock('./MathBlockEditor',()=>({default:({text,onChange,block}:{text:string;onChange:(s:string)=>void;block:{locator:string}})=><textarea aria-label={block.locator} value={text} onChange={e=>onChange(e.target.value)}/>}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
const unit={id:'u',title:'反比例函数',revision:1,stale:false,chapters:['反比例函数'],target:'初中复习',notes:''}
const profile={id:'deepseek',label:'DeepSeek',base_url:'https://api.deepseek.com',model:'test-model',ready:true,api_key_configured:true,json_mode:true,thinking_mode:'auto',token_parameter:'auto',timeout:90,max_calls:16,output_token_budget:30000}
const body={name:'反比例函数性质',kind:'property',statement:'完整表述',conditions:'非零系数',formula:'',positive_example:'正确例子',misconception:'反例与解释',mastery:'能描述性质',method_steps:'',uncertainty:'模型认为需要教师判断范围'}
const item={id:'i',knowledge_id:'k',revision:1,body,scope:'core',review_note:'',original_body:body,warnings:[]}
const run={id:'r',unit_id:'u',revision:3,status:'completed',stage:'completed',stale:false,error:'',items:[item],catalog:[],calls:[],removed:{},parent_version:null,final_version:null,final_blockers:[],checks:[{knowledge_id:'k',message:'条件是否完整'}]}
function mock(){vi.mocked(api).mockImplementation(async(path)=>{
 if(path==='/plans')return []
 if(path==='/knowledge/units')return [unit]
 if(path==='/editor/profiles')return {active:'deepseek',profiles:[profile]}
 if(path==='/knowledge/units/u/runs')return [{id:'r',revision:3,status:'completed',created_at:'2026-11-12'}]
 if(path==='/knowledge/units/u/versions')return []
 if(path==='/editor/runs/r')return structuredClone(run)
 if(path==='/editor/runs/r/messages')return []
 throw Error('Unexpected '+path)
})}
async function open(){render(<EditorialKnowledgePage onDirtyChange={vi.fn()}/>);await waitFor(()=>expect(screen.getByRole('option',{name:'反比例函数'})).toBeTruthy());fireEvent.change(screen.getByLabelText('已有知识单元'),{target:{value:'u'}});await screen.findByRole('navigation',{name:'知识清单'})}
it('opens saved manuscript without paid generation or repeated review controls',async()=>{
 mock();await open()
 expect(screen.getByRole('region',{name:'知识正文'})).toBeTruthy()
 expect(screen.getByRole('complementary',{name:'AI 讨论'})).toBeTruthy()
 expect(screen.queryByText('教师审核')).toBeNull()
 expect(screen.queryByText('补充一个知识条目')).toBeNull()
 expect(vi.mocked(api).mock.calls.every(([,init])=>!init?.method||init.method==='GET')).toBe(true)
})
it('edits inline, sends unsaved context to AI, and saves without finalizing',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,init)=>{
  if(path==='/editor/runs/r/messages'&&init?.method==='POST')return {id:'m',candidate_id:'i',action:'chat',status:'completed',response:'建议补充定义域',error:'',model:{model:'test-model'},payload:{instruction:'请核查',context_revision:3,uses_unsaved_body:true}}
  if(path==='/editor/runs/r/items/i')return {...run,revision:4,items:[{...item,revision:2,body:{...body,statement:'教师新表述'}}]}
  return base(path,init)
 })
 await open();fireEvent.click(screen.getByRole('button',{name:'编辑'}))
 fireEvent.change(screen.getByLabelText('准确表述'),{target:{value:'教师新表述'}})
 expect((screen.getByRole('tab',{name:'知识关系'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.change(screen.getByLabelText('给 AI 的问题或要求'),{target:{value:'请核查'}})
 fireEvent.click(screen.getByRole('button',{name:'发送'}))
 await screen.findAllByText('建议补充定义域')
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([p,i])=>p==='/editor/runs/r/messages'&&i?.method==='POST')![1]!.body as string)
 expect(sent.body.statement).toBe('教师新表述');expect(sent.profile_id).toBe('deepseek')
 fireEvent.click(screen.getByRole('button',{name:'保存条目修改'}))
 await waitFor(()=>expect(screen.queryByText('有未保存修改')).toBeNull())
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/finalize'))).toBe(false)
})
it('forms a whole-manuscript final even with AI questions and opens a separate revision',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 const frozen={id:'v',run_id:'r',run_revision:4,created_at:'2026-11-12',snapshot:{unit,items:[item],checks:run.checks,run_id:'r',run_revision:4}}
 vi.mocked(api).mockImplementation(async(path,init)=>{
  if(path==='/editor/runs/r/finalize')return {id:'v'}
  if(path==='/editor/versions/v')return frozen
  if(path==='/editor/versions/v/revise')return {...run,id:'r2',parent_version:'v'}
  if(path==='/editor/runs/r2/messages')return []
  return base(path,init)
 })
 await open();const button=screen.getByRole('button',{name:'形成终稿'}) as HTMLButtonElement
 expect(button.disabled).toBe(true)
 fireEvent.click(screen.getByLabelText(/我已检查整份清单/));expect(button.disabled).toBe(false);fireEvent.click(button)
 await screen.findByRole('button',{name:'基于终稿继续修订'})
 expect((screen.getByRole('button',{name:'编辑'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'基于终稿继续修订'}))
 await waitFor(()=>expect((screen.getByRole('button',{name:'编辑'}) as HTMLButtonElement).disabled).toBe(false))
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/runs') )).toBe(true) // archive reads only, no generation
 expect(vi.mocked(api).mock.calls.some(([p,i])=>p.endsWith('/runs')&&i?.method==='POST')).toBe(false)
})
it('generates unverified relations directly without approval controls',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,init)=>{
  if(path==='/editor/runs/r/messages'&&init?.method==='POST')return {id:'m',candidate_id:null,action:'relations',status:'completed',error:'',response:'',model:{model:'test-model'},payload:{instruction:'生成关系',context_revision:3,uses_unsaved_body:false},result:{relations:[]}}
  return base(path,init)
 })
 await open();fireEvent.click(screen.getByRole('tab',{name:'知识关系'}));fireEvent.click(screen.getByRole('button',{name:'生成知识关系'}))
 await screen.findByText('本轮没有生成关系，不代表知识之间没有连接。')
 expect(screen.queryByText('确认并采纳选中关系')).toBeNull()
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([p,i])=>p==='/editor/runs/r/messages'&&i?.method==='POST')![1]!.body as string)
 expect(sent.action).toBe('relations')
})
