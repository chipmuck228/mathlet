import {afterEach,expect,it,vi} from "vitest"
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react"
import PlanningAIImport from "./PlanningAIImport"
import {api} from "@/lib/api"
vi.mock("@/lib/api",()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
const doc={id:'d',name:'课程要求.docx',kind:'docx',category:'standard',status:'ready',created_at:''}
const task={id:'t',revision:1,title:'课程规划',document_id:'d',status:'queued',error:'',stale:false,plan_id:null,model:{model:'test',base_url:'https://model.example'},calls:[]}
it('previews imported text and requires consent before requesting AI planning',async()=>{
 vi.mocked(api).mockImplementation(async(path)=>{
  if(path==='/knowledge/provider')return {ready:true,model:'test',base_url:'https://model.example',output_token_budget:30000}
  if(path==='/planning-ai/runs')return []
  if(path==='/documents/d/blocks')return [{id:'b',text:'函数\t二次函数\t能画图和读图',locator:'文档块1',revision:3,verified:false}]
  throw Error(path)
 })
 render(<PlanningAIImport documents={[doc]} disabled={false} onOpen={vi.fn()}/>)
 fireEvent.change(screen.getByLabelText('AI 规划来源资料'),{target:{value:'d'}})
 await waitFor(()=>expect(screen.getByText(/函数\s+二次函数/)).toBeTruthy())
 const start=screen.getByRole('button',{name:'AI 构建待审核规划'}) as HTMLButtonElement
 expect(start.disabled).toBe(true)
 fireEvent.click(screen.getByLabelText(/确认向已保存模型发送该资料/))
 vi.mocked(api).mockResolvedValueOnce(task)
 fireEvent.click(start)
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/planning-ai/runs',expect.objectContaining({method:'POST'})))
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([path,init])=>path==='/planning-ai/runs'&&init?.method==='POST')![1]!.body as string)
 expect(sent.document_id).toBe('d');expect(sent.source_revisions).toEqual({b:3});expect(sent.consent).toBe(true)
 expect(Object.keys(sent)).not.toContain('domains')
})
it('opens a completed candidate only on request and respects unsaved parent planning edits',async()=>{
 const done={...task,status:'completed',plan_id:'p'}
 vi.mocked(api).mockImplementation(async(path)=>path==='/knowledge/provider'?{ready:true,model:'test',base_url:'https://model.example'}:[done])
 const onOpen=vi.fn().mockResolvedValue(undefined)
 render(<PlanningAIImport documents={[doc]} disabled={true} onOpen={onOpen}/>)
 await waitFor(()=>expect(screen.getByRole('option',{name:/课程规划 · completed/})).toBeTruthy())
 fireEvent.change(screen.getByLabelText('AI 规划任务'),{target:{value:'t'}})
 expect(onOpen).not.toHaveBeenCalled()
 expect((screen.getByRole('button',{name:'AI 构建待审核规划'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'打开生成规划进行核对'}))
 await waitFor(()=>expect(onOpen).toHaveBeenCalledWith('p'))
})
