import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import KnowledgeCoveragePanel,{type CoverageData} from './KnowledgeCoveragePanel'
import {api} from '@/lib/api'
vi.mock('@/lib/api',()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
export const sample:CoverageData={state:'current',source_hash:'body-hash',result_id:'result1',targets:[{id:'goal:g1',kind:'objective',text:'能解释同时满足两个方程'}],items:[{knowledge_id:'k1',name:'方程组的解',fields:['statement','conditions','positive_example']}],result:{origin:'ai',generated_at:'2026-11-18',error:'',report:{rows:[{target_id:'goal:g1',status:'partial',links:[{knowledge_id:'k1',fields:['statement','positive_example'],explanation:'已有概念和例子'}],gap:'缺少只满足一个方程的反例',guidance:'补充反例并解释为什么不成立'}],issues:[],teacher_note:''}},tasks:[]}
const props={runId:'r1',revision:3,initial:sample,readOnly:false,disabled:false,onDirtyChange:vi.fn(),onBusyChange:vi.fn(),onSaved:vi.fn().mockResolvedValue(undefined),onSelect:vi.fn(),onDiscuss:vi.fn()}
it('shows readable objective-to-content evidence and directs a gap to the same-page supplement',()=>{
 const select=vi.fn(),discuss=vi.fn();render(<KnowledgeCoveragePanel {...props} onSelect={select} onDiscuss={discuss}/>);
 expect(screen.getByText('部分涉及')).toBeTruthy();expect(screen.getByText('正例',{exact:false})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'方程组的解'}));expect(select).toHaveBeenCalledWith('k1')
 fireEvent.click(screen.getByRole('button',{name:'带入右侧AI补充'}));expect(discuss).toHaveBeenCalledWith(expect.stringContaining('缺少只满足一个方程的反例'))
 expect(api).not.toHaveBeenCalled()
})
it('edits and saves a teacher judgment without an AI call or separate approval',async()=>{
 vi.mocked(api).mockResolvedValue({...sample,result:{...sample.result,origin:'teacher'}})
 const saved=vi.fn().mockResolvedValue(undefined);render(<KnowledgeCoveragePanel {...props} onSaved={saved}/>);
 fireEvent.click(screen.getByRole('button',{name:'编辑覆盖判断'}));fireEvent.change(screen.getByLabelText('覆盖表教师处理说明'),{target:{value:'反例安排在下一小节'}})
 fireEvent.change(screen.getByLabelText('目标 1 安排情况'),{target:{value:'covered'}})
 fireEvent.click(screen.getByRole('button',{name:'保存覆盖判断'}));await waitFor(()=>expect(saved).toHaveBeenCalled())
 const call=vi.mocked(api).mock.calls.find(([,i])=>i?.method==='PUT')!
 const data=JSON.parse(call[1]!.body as string);expect(data.revision).toBe(3);expect(data.result_id).toBe('result1');expect(data.source_hash).toBe('body-hash');expect(data.report.rows[0].status).toBe('covered');expect(data.report.teacher_note).toContain('下一小节')
 expect(vi.mocked(api).mock.calls.every(([,i])=>i?.method!=='POST')).toBe(true)
})
it('keeps unsaved teacher judgment after a version conflict',async()=>{
 vi.mocked(api).mockRejectedValue(new Error('覆盖记录已经更新'))
 render(<KnowledgeCoveragePanel {...props}/>);fireEvent.click(screen.getByRole('button',{name:'编辑覆盖判断'}))
 fireEvent.change(screen.getByLabelText('覆盖表教师处理说明'),{target:{value:'保留我的修改'}});fireEvent.click(screen.getByRole('button',{name:'保存覆盖判断'}))
 await screen.findByRole('alert');expect((screen.getByLabelText('覆盖表教师处理说明') as HTMLTextAreaElement).value).toBe('保留我的修改')
})
it('marks old results as stale and leaves frozen coverage read-only',()=>{
 render(<KnowledgeCoveragePanel {...props} initial={{...sample,state:'stale'}} readOnly={true}/>);
 expect(screen.getByText(/旧覆盖结果仅供参考/)).toBeTruthy();expect(screen.getByText('旧判断：部分涉及')).toBeTruthy()
 expect(screen.queryByRole('button',{name:'编辑覆盖判断'})).toBeNull();expect(screen.queryByRole('button',{name:'带入右侧AI补充'})).toBeNull();expect(api).not.toHaveBeenCalled()
})
it('queues a recheck only on request and binds it to the current revision',async()=>{
 vi.mocked(api).mockImplementation(async(_path,init)=>init?.method?{id:'task1'}:{...sample,tasks:[{id:'task1',status:'queued',stale:false,error:''}]})
 render(<KnowledgeCoveragePanel {...props}/>);expect(api).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'AI重新检查覆盖'}));await screen.findByText('覆盖检查已排队，请保持Worker运行。')
 const sent=vi.mocked(api).mock.calls.find(([,i])=>i?.method==='POST')!;expect(JSON.parse(sent[1]!.body as string)).toEqual({revision:3})
 expect(screen.getByText('已有概念和例子')).toBeTruthy()
})
