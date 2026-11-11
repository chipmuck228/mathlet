import { afterEach, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import KnowledgePage from "./KnowledgePage"
import { api } from "@/lib/api"
vi.mock("@/lib/api",()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
vi.mock("./MathBlockEditor",()=>({default:({text,onChange,block}:{text:string;onChange:(s:string)=>void;block:{locator:string}})=><textarea aria-label={block.locator} value={text} onChange={e=>onChange(e.target.value)}/>}))
afterEach(()=>{cleanup();vi.useRealTimers();vi.mocked(api).mockReset()})
const provider={base_url:"https://model.example/v1",model:"test-model",api_key_configured:true,ready:true,json_mode:true,token_parameter:"auto",timeout:90,max_calls:16,output_token_budget:30000}
const unit={id:"u",title:"方程",chapters:["一元一次方程"],target:"初中复习",notes:"",revision:1,stale:false}
const body={name:"一元一次方程",kind:"concept",statement:"完整定义",conditions:"整式方程且一次项系数不为零",formula:"",positive_example:"2x+1=3",misconception:"遗漏整式条件",mastery:"能识别并解释条件",method_steps:"",uncertainty:""}
const item={id:"i",knowledge_id:"k",body,original_body:body,scope:"core",review_state:"pending",revision:1,reviewer:"",review_note:"",warnings:[],formula_mathml:"",origin:"model_prior"}
function mock(run?:Record<string,unknown>){vi.mocked(api).mockImplementation(async(path,init)=>{
 if(path==="/knowledge/provider")return provider
 if(path==="/knowledge/units")return [unit]
 if(path==="/plans")return []
 if(path==="/knowledge/units/u/versions")return []
 if(path==="/knowledge/units/u/runs"&&init?.method==="POST")return {id:"r",status:"queued",stage:"catalog",input_json:unit,model_json:provider,catalog:[],items:[],checks:[],calls:[],revision:1}
 if(path==="/knowledge/units/u/runs")return run?[{id:"r",status:run.status,created_at:"2026-11-10"}]:[]
 if(path==="/knowledge/runs/r")return structuredClone(run)
 if(path==="/knowledge/runs/r/expand")return {...run,status:"queued"}
 if(path==="/knowledge/runs/r/review")return {...run,revision:2,items:[{...item,review_state:"approved"}]}
 throw new Error("Unexpected test request "+path)
})}
it("requires saved model settings, explicit unit selection and transmission consent",async()=>{
 mock();render(<KnowledgePage onDirtyChange={vi.fn()}/>)
 fireEvent.click(screen.getByText("已有知识单元与历史批次"))
 await waitFor(()=>expect(screen.getByRole("option",{name:"方程 · 修订 1"})).toBeTruthy())
 fireEvent.change(screen.getByLabelText("已有知识单元"),{target:{value:"u"}})
 const generate=screen.getByRole("button",{name:"生成知识清单"}) as HTMLButtonElement
 expect(generate.disabled).toBe(true)
 fireEvent.click(screen.getByLabelText(/我确认向已保存的模型服务/))
 expect(generate.disabled).toBe(false)
 fireEvent.click(generate)
 await waitFor(()=>expect(vi.mocked(api)).toHaveBeenCalledWith("/knowledge/units/u/runs",expect.objectContaining({method:"POST"})))
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([p,init])=>p==="/knowledge/units/u/runs"&&init?.method==="POST")![1]!.body as string)
 expect(sent.consent).toBe(true);expect(sent.unit_revision).toBe(1)
})
it("selects catalog items explicitly before expansion",async()=>{
 const run={id:"r",status:"awaiting_selection",stage:"details",stale:false,revision:2,input_json:unit,model_json:provider,catalog:[{id:"k",name:"一元一次方程",kind:"concept",reason:"复习定义"}],selected_ids:[],items:[],checks:[],calls:[]}
 mock(run);render(<KnowledgePage onDirtyChange={vi.fn()}/>)
 fireEvent.click(screen.getByText("已有知识单元与历史批次"))
 await waitFor(()=>expect(screen.getByRole("option",{name:"方程 · 修订 1"})).toBeTruthy())
 fireEvent.change(screen.getByLabelText("已有知识单元"),{target:{value:"u"}})
 await waitFor(()=>expect(screen.getByLabelText("知识候选批次").querySelector('option[value="r"]')).toBeTruthy())
 fireEvent.change(screen.getByLabelText("知识候选批次"),{target:{value:"r"}})
 await waitFor(()=>expect(screen.getByText("复习定义",{exact:false})).toBeTruthy())
 expect((screen.getByRole("button",{name:"展开选中的 0 项知识草案"}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole("button",{name:"选择整个清单"}))
 fireEvent.click(screen.getByRole("button",{name:"展开选中的 1 项知识草案"}))
 await waitFor(()=>expect(vi.mocked(api)).toHaveBeenCalledWith("/knowledge/runs/r/expand",expect.objectContaining({method:"POST"})))
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([p])=>p.endsWith('/expand'))![1]!.body as string)
 expect(sent.selected_ids).toEqual(["k"])
})
it("does not approve unselected or unsaved content and submits exact revisions",async()=>{
 const run={id:"r",status:"completed",stage:"completed",stale:false,revision:4,input_json:unit,model_json:provider,catalog:[],selected_ids:["k"],items:[item],checks:[],calls:[]}
 mock(run);render(<KnowledgePage onDirtyChange={vi.fn()}/>)
 fireEvent.click(screen.getByText("已有知识单元与历史批次"))
 await waitFor(()=>expect(screen.getByRole("option",{name:"方程 · 修订 1"})).toBeTruthy())
 fireEvent.change(screen.getByLabelText("已有知识单元"),{target:{value:"u"}})
 await waitFor(()=>expect(screen.getByLabelText("知识候选批次").querySelector('option[value="r"]')).toBeTruthy())
 fireEvent.change(screen.getByLabelText("知识候选批次"),{target:{value:"r"}})
 await waitFor(()=>expect(screen.getByLabelText("选择知识 一元一次方程")).toBeTruthy())
 fireEvent.click(screen.getByLabelText("选择知识 一元一次方程"))
 fireEvent.change(screen.getByLabelText("审核人"),{target:{value:"教师"}})
 fireEvent.click(screen.getByLabelText(/我已检查选中条目的表述/))
 const approve=screen.getByRole("button",{name:"确认选中 1 项"}) as HTMLButtonElement
 expect(approve.disabled).toBe(false)
 fireEvent.click(screen.getByRole("button",{name:"编辑知识内容"}))
 fireEvent.change(screen.getByLabelText("准确表述"),{target:{value:"教师尚未保存的修改"}})
 expect(approve.disabled).toBe(true)
 expect(screen.getByText(/未保存；保存会撤销/)).toBeTruthy()
})
it("does not send a task to stale saved settings while provider edits are unsaved",async()=>{
 mock();render(<KnowledgePage onDirtyChange={vi.fn()}/>)
 fireEvent.click(screen.getByText("已有知识单元与历史批次"))
 await waitFor(()=>expect(screen.getByRole("option",{name:"方程 · 修订 1"})).toBeTruthy())
 fireEvent.change(screen.getByLabelText("已有知识单元"),{target:{value:"u"}})
 fireEvent.click(screen.getByLabelText(/我确认向已保存的模型服务/))
 fireEvent.change(screen.getByLabelText("模型名称"),{target:{value:"another-model"}})
 fireEvent.click(screen.getByLabelText(/我确认向已保存的模型服务/))
 expect((screen.getByRole("button",{name:"生成知识清单"}) as HTMLButtonElement).disabled).toBe(true)
 expect(vi.mocked(api).mock.calls.some(([p,init])=>p.endsWith('/runs')&&init?.method==='POST')).toBe(false)
})

it("preserves an unsaved local item when polling receives an external revision",async()=>{
 const run={id:"r",status:"completed",stage:"completed",stale:false,revision:4,input_json:unit,model_json:provider,catalog:[],selected_ids:["k"],items:[item],checks:[],calls:[]}
 mock(run);render(<KnowledgePage onDirtyChange={vi.fn()}/>)
 fireEvent.click(screen.getByText("已有知识单元与历史批次"))
 await waitFor(()=>expect(screen.getByRole("option",{name:"方程 · 修订 1"})).toBeTruthy())
 fireEvent.change(screen.getByLabelText("已有知识单元"),{target:{value:"u"}})
 await waitFor(()=>expect(screen.getByLabelText("知识候选批次").querySelector('option[value="r"]')).toBeTruthy())
 vi.useFakeTimers()
 await act(async()=>{fireEvent.change(screen.getByLabelText("知识候选批次"),{target:{value:"r"}})})
 fireEvent.click(screen.getByRole("button",{name:"编辑知识内容"}))
 const input=screen.getByLabelText("准确表述") as HTMLTextAreaElement
 fireEvent.change(input,{target:{value:"尚未保存的教师文字"}})
 run.items=[{...item,revision:2,body:{...body,statement:"其他页面的新修订"}}];run.revision=5
 await act(async()=>{await vi.advanceTimersByTimeAsync(3000)})
 expect((screen.getByLabelText("准确表述") as HTMLTextAreaElement).value).toBe("尚未保存的教师文字")
 expect(screen.getByText(/未保存；保存会撤销/)).toBeTruthy()
})

it("starts from a confirmed planning topic without a pilot or default example",async()=>{
 const plan={id:'p',title:'中考规划',confirmed:true,revision:3,payload:{mode:'ai_curriculum',nodes:[{id:'domain',parent_id:null,included:true,title:'函数'},{id:'topic',parent_id:'domain',included:true,title:'二次函数'}],units:[{id:'pt',title:'二次函数',volume:'函数',goals:'画图并分析变化',node_ids:['topic']}],requirements:[{text:'能画图和读图',unit_ids:['pt'],origin:'source_excerpt'}]}}
 const plannedUnit={...unit,title:'二次函数',chapters:['二次函数'],notes:'画图并分析变化',origin_info:{plan_id:'p',unit_id:'pt',plan_revision:3,domain:'函数',learning_requirements:[{text:'能画图和读图',origin:'source_excerpt'}]}}
 vi.mocked(api).mockImplementation(async(path,init)=>{
  if(path==='/knowledge/provider')return provider
  if(path==='/plans')return [plan,{...plan,id:'unconfirmed',title:'未确认规划',confirmed:false}]
  if(path==='/knowledge/units')return []
  if(path==='/knowledge/units/from-plan')return plannedUnit
  if(path==='/knowledge/units/u/versions')return []
  if(path==='/knowledge/units/u/runs'&&init?.method==='POST')return {id:'r',status:'queued',stage:'catalog',input_json:plannedUnit,model_json:provider,catalog:[],selected_ids:[],items:[],checks:[],calls:[],revision:1}
  if(path==='/knowledge/units/u/runs')return []
  if(path==='/knowledge/runs/r')return {id:'r',status:'queued',stage:'catalog',input_json:plannedUnit,model_json:provider,catalog:[],selected_ids:[],items:[],checks:[],calls:[],revision:1}
  throw Error(path)
 })
 render(<KnowledgePage onDirtyChange={vi.fn()}/>)
 await waitFor(()=>expect(screen.getByRole('option',{name:'中考规划 · 规划修订 3'})).toBeTruthy())
 expect(screen.queryByRole('button',{name:/试点|对照：/})).toBeNull()
 expect((screen.getByLabelText('单元名称') as HTMLInputElement).value).toBe('')
 expect(screen.queryByRole('option',{name:/未确认规划/})).toBeNull()
 fireEvent.change(screen.getByLabelText('二级主题'),{target:{value:'pt'}})
 expect((screen.getByLabelText('单元名称') as HTMLInputElement).value).toBe('二次函数')
 expect((screen.getByLabelText('章节或知识范围（一行一项）') as HTMLTextAreaElement).value).toBe('二次函数')
 expect(screen.getByText('能画图和读图')).toBeTruthy()
 expect(vi.mocked(api).mock.calls.some(([path,init])=>path==='/knowledge/units/from-plan'&&init?.method==='POST')).toBe(false)
 expect((screen.getByRole('button',{name:'生成知识清单'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'创建知识单元'}))
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/knowledge/units/from-plan',expect.objectContaining({method:'POST'})))
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([path])=>path==='/knowledge/units/from-plan')![1]!.body as string)
 expect(sent).toEqual({plan_id:'p',unit_id:'pt',plan_revision:3})
 await waitFor(()=>expect(screen.getByText(/当前知识单元已建立/)).toBeTruthy())
 fireEvent.click(screen.getByLabelText(/我确认向已保存的模型服务/))
 expect((screen.getByRole('button',{name:'生成知识清单'}) as HTMLButtonElement).disabled).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'生成知识清单'}))
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/knowledge/units/u/runs',expect.objectContaining({method:'POST'})))
 expect(vi.mocked(api).mock.calls.some(([path,init])=>path==='/knowledge/units'&&init?.method==='POST')).toBe(false)
})
it("explains that saving a plan alone does not confirm it",async()=>{
 mock();render(<KnowledgePage onDirtyChange={vi.fn()}/>)
 await waitFor(()=>expect(screen.getByText(/暂无已确认的内容规划/)).toBeTruthy())
 expect((screen.getByRole('button',{name:'创建知识单元'}) as HTMLButtonElement).disabled).toBe(true)
 expect((screen.getByRole('button',{name:'生成知识清单'}) as HTMLButtonElement).disabled).toBe(true)
})

it("shows named readiness blockers beside approval and permits selecting only checked ready items",async()=>{
 const good={...item,review_blockers:[]}
 const bad={...item,id:'bad',knowledge_id:'bad-k',body:{...body,name:'反比例函数增减性'},review_blockers:['缺少正例']}
 const run={id:'r',status:'completed',stage:'completed',stale:false,revision:4,input_json:unit,model_json:provider,catalog:[],selected_ids:['k','bad-k'],items:[good,bad],checks:[],calls:[]}
 mock(run);render(<KnowledgePage onDirtyChange={vi.fn()}/>)
 fireEvent.click(screen.getByText('已有知识单元与历史批次'))
 await waitFor(()=>expect(screen.getByRole('option',{name:'方程 · 修订 1'})).toBeTruthy())
 fireEvent.change(screen.getByLabelText('已有知识单元'),{target:{value:'u'}})
 await waitFor(()=>expect(screen.getByLabelText('知识候选批次').querySelector('option[value="r"]')).toBeTruthy())
 fireEvent.change(screen.getByLabelText('知识候选批次'),{target:{value:'r'}})
 await waitFor(()=>expect(screen.getByLabelText('选择知识 反比例函数增减性')).toBeTruthy())
 fireEvent.click(screen.getByRole('button',{name:'选择当前显示条目'}))
 fireEvent.change(screen.getByLabelText('审核人'),{target:{value:'教师'}})
 fireEvent.click(screen.getByLabelText(/我已检查选中条目的表述/))
 expect((screen.getByRole('button',{name:'确认选中 2 项'}) as HTMLButtonElement).disabled).toBe(true)
 expect(screen.getAllByText('缺少正例').length).toBeGreaterThan(0)
 fireEvent.click(screen.getByRole('button',{name:'仅保留所选中可确认的条目'}))
 fireEvent.click(screen.getByLabelText(/我已检查选中条目的表述/))
 expect((screen.getByRole('button',{name:'确认选中 1 项'}) as HTMLButtonElement).disabled).toBe(false)
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/review'))).toBe(false)
})

it("shows backend rejection next to review controls instead of claiming success",async()=>{
 const run={id:'r',status:'completed',stage:'completed',stale:false,revision:4,input_json:unit,model_json:provider,catalog:[],selected_ids:['k'],items:[{...item,review_blockers:[]}],checks:[],calls:[]}
 mock(run);const original=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,init)=>{if(path.endsWith('/review'))throw Error('此条目有AI复核意见，请填写教师处理说明后确认');return original(path,init)})
 render(<KnowledgePage onDirtyChange={vi.fn()}/>)
 fireEvent.click(screen.getByText('已有知识单元与历史批次'))
 await waitFor(()=>expect(screen.getByRole('option',{name:'方程 · 修订 1'})).toBeTruthy())
 fireEvent.change(screen.getByLabelText('已有知识单元'),{target:{value:'u'}})
 await waitFor(()=>expect(screen.getByLabelText('知识候选批次').querySelector('option[value="r"]')).toBeTruthy())
 fireEvent.change(screen.getByLabelText('知识候选批次'),{target:{value:'r'}})
 await waitFor(()=>expect(screen.getByLabelText('选择知识 一元一次方程')).toBeTruthy())
 fireEvent.click(screen.getByLabelText('选择知识 一元一次方程'))
 fireEvent.change(screen.getByLabelText('审核人'),{target:{value:'教师'}})
 fireEvent.click(screen.getByLabelText(/我已检查选中条目的表述/))
 fireEvent.click(screen.getByRole('button',{name:'确认选中 1 项'}))
 await waitFor(()=>expect(screen.getByRole('alert').textContent).toContain('请填写教师处理说明'))
 expect(screen.queryByText(/教师已审核/)).toBeNull()
 expect((screen.getByRole('button',{name:'固定已审核知识版本'}) as HTMLButtonElement).disabled).toBe(true)
})

it("does not let a late older poll roll back successful approval",async()=>{
 const run={id:'r',status:'completed',stage:'completed',stale:false,revision:4,input_json:unit,model_json:provider,catalog:[],selected_ids:['k'],items:[{...item,review_blockers:[]}],checks:[],calls:[]}
 const approved={...run,revision:5,items:[{...item,revision:2,review_state:'approved',review_blockers:[]}]}
 mock(run);const original=vi.mocked(api).getMockImplementation()!
 let resolvePoll!:(value:unknown)=>void;let reads=0
 vi.mocked(api).mockImplementation(async(path,init)=>{if(path==='/knowledge/runs/r'){reads++;if(reads===1)return run;return new Promise(resolve=>{resolvePoll=resolve})}if(path.endsWith('/review'))return approved;return original(path,init)})
 render(<KnowledgePage onDirtyChange={vi.fn()}/>)
 fireEvent.click(screen.getByText('已有知识单元与历史批次'))
 await waitFor(()=>expect(screen.getByRole('option',{name:'方程 · 修订 1'})).toBeTruthy())
 fireEvent.change(screen.getByLabelText('已有知识单元'),{target:{value:'u'}})
 await waitFor(()=>expect(screen.getByLabelText('知识候选批次').querySelector('option[value="r"]')).toBeTruthy())
 vi.useFakeTimers()
 await act(async()=>{fireEvent.change(screen.getByLabelText('知识候选批次'),{target:{value:'r'}})})
 await act(async()=>{await vi.advanceTimersByTimeAsync(3000)})
 fireEvent.click(screen.getByLabelText('选择知识 一元一次方程'))
 fireEvent.change(screen.getByLabelText('审核人'),{target:{value:'教师'}})
 fireEvent.click(screen.getByLabelText(/我已检查选中条目的表述/))
 await act(async()=>{fireEvent.click(screen.getByRole('button',{name:'确认选中 1 项'}))})
 expect(screen.getByText(/教师已审核/)).toBeTruthy()
 await act(async()=>{resolvePoll(run)})
 expect(screen.getByText(/教师已审核/)).toBeTruthy()
 expect((screen.getByRole('button',{name:'固定已审核知识版本'}) as HTMLButtonElement).disabled).toBe(false)
})
