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
 expect(screen.queryByRole('tab',{name:'知识关系'})).toBeNull()
 expect(screen.queryByLabelText('适用范围')).toBeNull()
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
 fireEvent.click(screen.getByLabelText(/我已检查纳入条目/));expect(button.disabled).toBe(false);fireEvent.click(button)
 await screen.findByRole('button',{name:'基于终稿继续修订'})
 expect((screen.getByRole('button',{name:'编辑'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'基于终稿继续修订'}))
 await waitFor(()=>expect((screen.getByRole('button',{name:'编辑'}) as HTMLButtonElement).disabled).toBe(false))
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/runs') )).toBe(true) // archive reads only, no generation
 expect(vi.mocked(api).mock.calls.some(([p,i])=>p.endsWith('/runs')&&i?.method==='POST')).toBe(false)
})
it('allows a pending-scope section to finalize without generating relations',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 const pendingItem={...item,scope:'pending'}
 const frozen={id:'section-final',run_id:'r',run_revision:4,snapshot:{unit,items:[pendingItem],checks:[],relations:[],run_id:'r',run_revision:4}}
 vi.mocked(api).mockImplementation(async(path,init)=>{
  if(path==='/editor/runs/r')return {...run,items:[pendingItem]}
  if(path==='/editor/runs/r/finalize')return {id:'section-final'}
  if(path==='/editor/versions/section-final')return frozen
  return base(path,init)
 })
 render(<EditorialKnowledgePage workflow initialUnitId="u" onDirtyChange={vi.fn()}/>);
 await screen.findByRole('region',{name:'知识正文'})
 expect(screen.queryByRole('tab',{name:'知识关系'})).toBeNull()
 expect(screen.queryByLabelText('小节待定条目范围')).toBeNull()
 fireEvent.click(screen.getByLabelText(/我已检查纳入条目/));fireEvent.click(screen.getByRole('button',{name:'形成终稿'}))
 await screen.findByRole('button',{name:'基于终稿继续修订'})
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([p])=>p.endsWith('/finalize'))![1]!.body as string)
 expect(sent).toEqual({revision:3,confirmed:true})
 expect(vi.mocked(api).mock.calls.some(([p,i])=>p.endsWith('/messages')&&i?.method==='POST')).toBe(false)
})
it('shows previously reviewed relations as collapsed history without a new generation action',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,init)=>path==='/editor/runs/r'?{...run,historical_relations:[{id:'old-edge',body:{source_id:'k',target_id:'k2',relation_type:'uses',reason:'历史使用理由',conditions:'历史条件',example:'历史例子'}}]}:base(path,init))
 await open();expect(screen.getByText('历史知识关系（仅供参考）')).toBeTruthy()
 expect(screen.queryByRole('button',{name:'生成知识关系'})).toBeNull()
 expect(screen.getByText('历史使用理由')).toBeTruthy()
 expect(vi.mocked(api).mock.calls.every(([,i])=>!i?.method)).toBe(true)
})
it('pauses after catalog generation for human selection instead of auto-expanding in the section workflow',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!;let generated=false
 const catalog={...run,status:'awaiting_selection',items:[],catalog:[{id:'k',name:'反比例函数的定义',kind:'concept'}]}
 vi.mocked(api).mockImplementation(async(path,init)=>{
  if(path==='/knowledge/units/u/runs'&&init?.method==='POST'){generated=true;return {id:'r'}}
  if(path==='/knowledge/units/u/runs')return generated?[{id:'r',status:'awaiting_selection',revision:3,created_at:'2026-11-13'}]:[]
  if(path==='/editor/runs/r')return catalog
  if(path==='/knowledge/runs/r/expand')return {id:'r'}
  return base(path,init)
 })
 render(<EditorialKnowledgePage workflow initialUnitId="u" onDirtyChange={vi.fn()}/>);
 const generate=await screen.findByRole('button',{name:'生成本小节知识清单'})
 await waitFor(()=>expect((generate as HTMLButtonElement).disabled).toBe(false));fireEvent.click(generate)
 await screen.findByRole('heading',{name:'核对清单，选择要展开的知识'})
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/expand'))).toBe(false)
 fireEvent.click(screen.getByLabelText('选中整个知识清单'));fireEvent.click(screen.getByRole('button',{name:'生成选中知识正文'}))
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/expand'))).toBe(true))
})
it('recognizes knowledge-only finals as complete without requiring relations or paid calls',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 const old={id:'old-final',run_id:'r',run_revision:4,created_at:'2026-11-12',snapshot:{unit,items:[item],checks:[],relations:[],editorial:{relations_teacher_confirmed:false},run_id:'r',run_revision:4}}
 vi.mocked(api).mockImplementation(async(path,init)=>{
  if(path==='/editor/runs/r')return {...run,final_version:{id:'old-final'}}
  if(path==='/editor/versions/old-final')return old
  return base(path,init)
 })
 render(<EditorialKnowledgePage workflow initialUnitId="u" onDirtyChange={vi.fn()}/>);
 await screen.findByText('3 基础知识定稿 · 已完成')
 expect(screen.getByRole('button',{name:'基于终稿继续修订'})).toBeTruthy()
 expect(vi.mocked(api).mock.calls.every(([,i])=>!i?.method)).toBe(true)
})

it('takes a coverage gap into the existing discussion and waits for the teacher to send',async()=>{
 mock();const previous=vi.mocked(api).getMockImplementation()!
 const target={state:'current',source_hash:'hash',result_id:'out',targets:[{id:'goal:g',kind:'objective',text:'解释同一分支的比较条件'}],items:[{knowledge_id:'k',name:body.name,fields:['statement']}],result:{origin:'ai',error:'',generated_at:'2026-11-18',report:{rows:[{target_id:'goal:g',status:'partial',links:[{knowledge_id:'k',fields:['statement'],explanation:'有性质表述'}],gap:'还缺少跨象限的反例',guidance:'补充反例并解释比较条件'}],issues:[],teacher_note:''}},tasks:[]}
 vi.mocked(api).mockImplementation(async(path,init)=>path==='/editor/runs/r'?{...structuredClone(run),topic_coverage:target}:previous(path,init))
 render(<EditorialKnowledgePage onDirtyChange={vi.fn()}/>);
 await screen.findByRole('option',{name:'反比例函数'});fireEvent.change(screen.getByLabelText('已有知识单元'),{target:{value:'u'}})
 await screen.findByText('解释同一分支的比较条件')
 fireEvent.click(screen.getByRole('button',{name:'带入右侧AI补充'}));expect((screen.getByLabelText('讨论方式') as HTMLSelectElement).value).toBe('supplement')
 expect((screen.getByLabelText('给 AI 的问题或要求') as HTMLTextAreaElement).value).toContain('还缺少跨象限的反例')
 expect(vi.mocked(api).mock.calls.some(([,i])=>i?.method==='POST')).toBe(false)
})
