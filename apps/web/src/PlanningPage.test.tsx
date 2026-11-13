import {afterEach,expect,it,vi} from "vitest"
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react"
import PlanningPage from "./PlanningPage"
import {api} from "@/lib/api"
vi.mock("@/lib/api",()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
vi.mock('./PlanningAIImport',()=>({default:()=>null}))
vi.mock('./EditorialKnowledgePage',()=>({default:({initialUnitId,workflow}:{initialUnitId:string;workflow:boolean})=><p>小节内编制 {initialUnitId} {workflow?'逐步审定':''}</p>}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
const plan={id:'p',title:'数学规划',revision:1,confirmed:true,warnings:[],stale_sources:[],reviewer:'老师',draft_links:[],payload:{mode:'ai_curriculum',document_id:'d',notes:'',skipped_lines:0,nodes:[{id:'domain',parent_id:null,kind:'domain',title:'函数',source_id:'b',source_url:'',source_excerpt:'函数',included:true},{id:'topic',parent_id:'domain',kind:'topic',title:'二次函数',source_id:'b',source_url:'',source_excerpt:'二次函数',included:true}],units:[{id:'u',title:'二次函数',volume:'函数',kind:'foundation',goals:'画图与读图',node_ids:['topic']}],requirements:[{id:'req',origin:'source_excerpt',text:'能画图和读图',source_id:'b',unit_ids:['u']}]}}
async function choose(){await waitFor(()=>expect(screen.getByRole('option',{name:'数学规划 · 修订 1'})).toBeTruthy());fireEvent.change(screen.getByLabelText('选择内容规划'),{target:{value:'p'}})}
it('edits AI topic names and learning targets while preserving source quotes',async()=>{
 vi.mocked(api).mockImplementation(async(path,init)=>path==='/plans'?[plan]:{...plan,revision:2,confirmed:false,payload:JSON.parse(init!.body as string)})
 render(<PlanningPage documents={[]} openSource={vi.fn()} openDraft={vi.fn()}/>)
 await choose();fireEvent.click(screen.getByRole('button',{name:/二次函数 二级主题/}))
 expect(screen.getByLabelText('本主题学习目标对应建议（AI 起草，可编辑）')).toBeTruthy()
 fireEvent.change(screen.getByLabelText('名称'),{target:{value:'二次函数复习'}})
 fireEvent.change(screen.getByLabelText('本主题学习目标对应建议（AI 起草，可编辑）'),{target:{value:'解释图象的变化规律'}})
 fireEvent.click(screen.getByRole('button',{name:'保存规划修改'}))
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/plans/p',expect.objectContaining({method:'PUT'})))
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([path])=>path==='/plans/p')![1]!.body as string)
 expect(sent.nodes[1].source_excerpt).toBe('二次函数');expect(sent.units[0].title).toBe('二次函数复习');expect(sent.units[0].goals).toBe('解释图象的变化规律')
 expect(sent.requirements[0].text).toBe('能画图和读图')
})
it('opens knowledge generation for a confirmed topic using the planning revision',async()=>{
 vi.mocked(api).mockImplementation(async path=>path==='/plans'?[plan]:{id:'knowledge-unit'})
 const open=vi.fn();render(<PlanningPage documents={[]} openSource={vi.fn()} openDraft={vi.fn()} openKnowledge={open}/>)
 await choose();fireEvent.click(screen.getByRole('button',{name:'2 主题目标与知识生成'}))
 fireEvent.click(screen.getByRole('button',{name:'打开本小节基础内容'}))
 await screen.findByText('小节内编制 knowledge-unit 逐步审定');expect(open).not.toHaveBeenCalled()
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([path])=>path==='/knowledge/units/from-plan')![1]!.body as string)
 expect(sent).toEqual({plan_id:'p',unit_id:'u',plan_revision:1})
})

it('replaces the unavailable textbook control in AI mode and routes saved plans through confirmation',async()=>{
 let current={...plan,confirmed:false};const open=vi.fn()
 vi.mocked(api).mockImplementation(async(path,init)=>{
  if(path==='/plans')return [current]
  if(path==='/plans/p/confirm'){const sent=JSON.parse(init!.body as string);expect(sent.revision).toBe(1);expect(sent.acknowledged).toBe(true);current={...current,confirmed:true};return current}
  if(path==='/knowledge/units/from-plan')return {id:'knowledge-unit'}
  throw new Error(path)
 })
 render(<PlanningPage documents={[]} openSource={vi.fn()} openDraft={vi.fn()} openKnowledge={open}/>);await choose()
 fireEvent.click(screen.getByRole('button',{name:'2 主题目标与知识生成'}))
 expect(screen.queryByLabelText('增加教材知识关联')).toBeNull()
 expect(screen.getByText('对应的二级主题')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'打开本小节基础内容'}))
 expect(open).not.toHaveBeenCalled();expect(screen.getByLabelText('确认人')).toBeTruthy()
 expect(vi.mocked(api).mock.calls.some(([p])=>p==='/knowledge/units/from-plan')).toBe(false)
 fireEvent.click(screen.getByLabelText(/我已核对领域、二级主题/));fireEvent.click(screen.getByRole('button',{name:'确认当前规划'}))
 await screen.findByText('当前规划已确认，可以继续。')
 fireEvent.click(screen.getByRole('button',{name:'打开本小节基础内容'}));await screen.findByText('小节内编制 knowledge-unit 逐步审定');expect(open).not.toHaveBeenCalled()
})
it('does not send an unsaved or stale planning revision to either downstream entry',async()=>{
 vi.mocked(api).mockImplementation(async()=>[plan]);const open=vi.fn(),draft=vi.fn()
 render(<PlanningPage documents={[]} openSource={vi.fn()} openDraft={draft} openKnowledge={open}/>);await choose()
 fireEvent.click(screen.getByRole('button',{name:'2 主题目标与知识生成'}))
 fireEvent.change(screen.getByLabelText('学习目标与编写说明'),{target:{value:'尚未保存的目标'}})
 fireEvent.click(screen.getByRole('button',{name:'打开本小节基础内容'}))
 expect(open).not.toHaveBeenCalled();expect(draft).not.toHaveBeenCalled();expect(vi.mocked(api).mock.calls.every(([,i])=>!i?.method)).toBe(true)
 expect(screen.getByRole('button',{name:'保存当前主题修改'})).toBeTruthy()
 cleanup();vi.mocked(api).mockImplementation(async()=>[{...plan,stale_sources:['b'],confirmed:false}])
 render(<PlanningPage documents={[]} openSource={vi.fn()} openDraft={draft} openKnowledge={open}/>);await choose()
 fireEvent.click(screen.getByRole('button',{name:'2 主题目标与知识生成'}))
 fireEvent.click(screen.getByRole('button',{name:'打开本小节基础内容'}))
 expect(screen.getByText(/规划来源已变化，请重新载入/)).toBeTruthy();expect(draft).not.toHaveBeenCalled()
})
it('collapses AI import, removes the directory importer and retains old plans',async()=>{
 vi.mocked(api).mockImplementation(async()=>[plan]);render(<PlanningPage documents={[]} openSource={vi.fn()} openDraft={vi.fn()}/>);await choose()
 const summary=screen.getByText('用 AI 构建领域与二级主题');expect((summary.parentElement as HTMLDetailsElement).open).toBe(false)
 expect(screen.queryByText('导入教材目录')).toBeNull();expect(screen.queryByLabelText('目录来源')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'2 主题目标与知识生成'}));expect(screen.getByRole('button',{name:'打开本小节基础内容'})).toBeTruthy()
})
