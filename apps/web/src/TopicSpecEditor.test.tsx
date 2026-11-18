import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import TopicSpecEditor,{type TopicSpec} from './TopicSpecEditor'
import {api} from '@/lib/api'
vi.mock('@/lib/api',()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
const spec:TopicSpec={objectives:[{id:'g1',text:'理解同时满足的含义',requirement_ids:['r1']}],required_content:['方程组的解'],boundary_notes:'先讨论基本解法',extension_candidates:['含参数问题'],prerequisites:['一元一次方程'],connections:[{topic:'一次函数',reason:'交点坐标同时满足两个解析式'}],difficulties:['只满足一个方程'],presentation_hints:['正反例对照'],evidence:[{source_id:'b1',quote:'理解方程组的解'}],notes:'教研建议'}
const task={id:'t1',revision:2,plan_revision:3,status:'completed',error:'',stale:false,proposal:spec,calls:[]}
const props={planId:'p1',unitId:'u1',revision:3,requirements:[{id:'r1',text:'理解方程组的解'}],confirmed:true,dirty:false,disabled:false,openSource:vi.fn(),onChange:vi.fn()}
it('reads a saved spec, edits inline without AI and preserves evidence',async()=>{
 vi.mocked(api).mockResolvedValue([]);const change=vi.fn();render(<TopicSpecEditor {...props} spec={spec} onChange={change}/>);
 expect(screen.getByText('随当前规划已确认')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'编辑规格'}));fireEvent.change(screen.getByLabelText('基础内容与使用边界'),{target:{value:'教师直接修订'}})
 expect(change).toHaveBeenCalledWith({...spec,boundary_notes:'教师直接修订'})
 expect(vi.mocked(api).mock.calls.every(([,init])=>!init?.method)).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'对照来源'}));expect(props.openSource).toHaveBeenCalledWith('b1')
})
it('does not apply an AI proposal until explicitly requested',async()=>{
 vi.mocked(api).mockResolvedValue([task]);const change=vi.fn();render(<TopicSpecEditor {...props} onChange={change}/>);
 await screen.findByText('建议已生成，尚未采用');expect(change).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'采用建议到编辑区'}));expect(change).toHaveBeenCalledWith(spec)
 expect(screen.getByText('建议已带入编辑区；尚未保存、确认。')).toBeTruthy()
})
it('prevents applying a stale proposal or generating against unsaved edits',async()=>{
 vi.mocked(api).mockResolvedValue([{...task,stale:true}]);render(<TopicSpecEditor {...props} dirty={true}/>);
 await screen.findByText('建议已生成，尚未采用')
 expect((screen.getByRole('button',{name:'采用建议到编辑区'}) as HTMLButtonElement).disabled).toBe(true)
 expect((screen.getByRole('button',{name:'AI生成主题规格建议'}) as HTMLButtonElement).disabled).toBe(true)
})
it('starts a source-bound proposal and keeps it out of the editable spec',async()=>{
 const change=vi.fn();vi.mocked(api).mockImplementation(async(path,init)=>init?.method?{...task,status:'queued',proposal:null}:[])
 render(<TopicSpecEditor {...props} onChange={change}/>);
 await waitFor(()=>expect(api).toHaveBeenCalled())
 fireEvent.click(screen.getByRole('button',{name:'AI生成主题规格建议'}))
 await screen.findByText('等待Worker生成')
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([,i])=>i?.method==='POST')![1]!.body as string)
 expect(sent).toEqual({plan_id:'p1',unit_id:'u1',plan_revision:3,instruction:''});expect(change).not.toHaveBeenCalled()
})
