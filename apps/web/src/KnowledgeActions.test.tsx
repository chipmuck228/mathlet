import { afterEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import KnowledgeActions from "./KnowledgeActions"
import { api } from "@/lib/api"
vi.mock("@/lib/api",()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
vi.mock("./MathBlockEditor",()=>({default:({text,onChange,block}:{text:string;onChange:(text:string)=>void;block:{locator:string}})=><textarea aria-label={block.locator} value={text} onChange={e=>onChange(e.target.value)}/>}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
const item={id:"i",knowledge_id:"k",revision:1,body:{name:"最值",kind:"property",statement:"原稿",conditions:"给定区间",formula:"",positive_example:"例子",misconception:"反例",mastery:"会分析",method_steps:"",uncertainty:""}}
const run={id:"r",revision:5,status:"completed",stale:false,items:[item],checks:[{id:"c",knowledge_id:"k",message:"补充分情况讨论",category:"teaching"}],tasks:[{id:"t",status:"completed",input_json:JSON.stringify({action_task:{action:"supplement"}})}],relations:[]}
const task={id:"t",revision:2,status:"completed",stale:false,error:"",input_json:{action_task:{action:"supplement",base_run_id:"r",base_revision:5,candidate_id:"i",sources:[item]}},outputs:[{id:"o",type:"knowledge",body:{body:{...item.body,name:"闭区间最值",statement:"新内容"},reason:"补充讨论"},original_body:{body:item.body,reason:"补充讨论"},state:"pending",revision:1,note:""}],checks:[],calls:[]}
it("sends selected classified feedback and a short instruction without requiring full content",async()=>{
 vi.mocked(api).mockResolvedValue(task)
 const refresh=vi.fn().mockResolvedValue(undefined)
 render(<KnowledgeActions run={run} disabled={false} onRefresh={refresh} onDirty={vi.fn()}/>)
 fireEvent.change(screen.getByLabelText(/针对的知识/),{target:{value:"i"}})
 fireEvent.change(screen.getByLabelText("任务类型"),{target:{value:"split"}})
 fireEvent.click(screen.getByLabelText("选择意见 1"))
 const start=screen.getByRole('button',{name:'开始定向 AI 任务'}) as HTMLButtonElement
 expect(start.disabled).toBe(true)
 fireEvent.click(screen.getByLabelText(/确认向已保存模型发送/))
 fireEvent.click(start)
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/knowledge/runs/r/actions',expect.objectContaining({method:'POST'})))
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([path])=>path.endsWith('/actions'))![1]!.body as string)
 expect(sent.action).toBe('split');expect(sent.candidate_id).toBe('i');expect(sent.issue_ids).toEqual(['c']);expect(sent.instruction).toBe('')
})
it("requires explicit adoption and blocks adoption while proposal edits are unsaved",async()=>{
 vi.mocked(api).mockResolvedValue(task)
 render(<KnowledgeActions run={run} disabled={false} onRefresh={vi.fn().mockResolvedValue(undefined)} onDirty={vi.fn()}/>)
 fireEvent.change(screen.getByLabelText('已生成的完善任务'),{target:{value:'t'}})
 await waitFor(()=>expect(screen.getByRole('button',{name:'编辑此候选'})).toBeTruthy())
 fireEvent.click(screen.getByLabelText('选择候选 o'))
 const adopt=screen.getByRole('button',{name:'采纳选中知识为待审核修订'}) as HTMLButtonElement
 expect(adopt.disabled).toBe(true)
 fireEvent.change(screen.getByLabelText('候选处理人'),{target:{value:'老师'}})
 fireEvent.change(screen.getByLabelText('采纳或退回说明'),{target:{value:'采用补充，仍待审核'}})
 fireEvent.click(screen.getByLabelText(/已对照原稿与候选/))
 expect(adopt.disabled).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'编辑此候选'}))
 fireEvent.change(screen.getByLabelText('准确表述'),{target:{value:'尚未保存的教师修改'}})
 expect(adopt.disabled).toBe(true)
 expect((screen.getByRole('button',{name:'保存候选修改'}) as HTMLButtonElement).disabled).toBe(false)
 expect(vi.mocked(api).mock.calls.some(([path])=>path.endsWith('/apply'))).toBe(false)
})
it("records the teacher's issue classification separately from mathematical approval",async()=>{
 vi.mocked(api).mockResolvedValue(run)
 render(<KnowledgeActions run={run} disabled={false} onRefresh={vi.fn().mockResolvedValue(undefined)} onDirty={vi.fn()}/>)
 fireEvent.change(screen.getByLabelText('意见分类 1'),{target:{value:'scope'}})
 fireEvent.change(screen.getByLabelText('分类处理依据 1'),{target:{value:'属于选读范围'}})
 fireEvent.click(screen.getByRole('button',{name:'保存意见分类'}))
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/knowledge/runs/r/classify',expect.objectContaining({method:'POST'})))
 const sent=JSON.parse(vi.mocked(api).mock.calls[0][1]!.body as string)
 expect(sent).toEqual({revision:5,issue_id:'c',category:'scope',note:'属于选读范围'})
 expect(vi.mocked(api).mock.calls.some(([path])=>path.endsWith('/review'))).toBe(false)
})
