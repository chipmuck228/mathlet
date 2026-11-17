import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import ReviewUnitPage from './ReviewUnitPage'
import {api} from '@/lib/api'
import type {Unit} from './ReviewUnitTypes'
vi.mock('@/lib/api',()=>({api:vi.fn(),json:(method:string,data:unknown)=>({method,body:JSON.stringify(data)})}))
vi.mock('./ReadableMath',()=>({default:({text}:{text:string})=><span>{text}</span>}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
const body={title:'二元一次方程组',introduction:'从数量关系到等量关系',goals:['建立两个独立等量关系'],mappings:[{analysis_id:'a1',relevance:'core',reason:'求解时使用消元',links:[{analysis_id:'a1',approach_id:'add',step_index:0,quote:'两式相加',knowledge_ref:'k1',role:'core',explanation:'消去y',conditions:'系数互为相反数'}],gaps:[]}],selected_analysis_ids:['a1'],cards:[],training:[{phase:'basic',kind:'original',title:'唤起知识',source_analysis_ids:['a1'],knowledge_refs:['k1'],prompt:'为什么两式可以相加？',hints:['比较系数'],answer:'等式性质',reasoning:'同解相加',checkpoints:['检验']}],summary:'并非只有一种解法'}
const unit:Unit={id:'u1',status:'completed',stage:'completed',revision:1,run_revision:2,error:'',stale:false,title:body.title,body,knowledge:{version_id:'kv',title:body.title,items:[{ref:'k1',title:'加减消元',scope:'core',body:{statement:'将两个方程相加或相减',conditions:'先使系数相同或互为相反数'}}]},sources:[{id:'a1',title:'代表题一',hash:'h'}],studies:[{id:'a1',question:{title:'代表题一',statement:'x+y=5，x-y=1',diagram_description:'',assets:[],sources:[],question_block_ids:[]},analysis:{approaches:[{id:'add',title:'加减法',trigger:'系数互为相反数',steps:[{action:'两式相加',reason:'等式性质'}],conclusion:'x=3，y=2',checks:'代回两式',limitations:'同一组未知数'}]}}],advice:[{section:'training',message:'提示是否过早给出方法？',guidance:'可编辑提示，也可以由教师判断现有提示合适。'}],read_only:false,versions:[],parent_version:null,representative_limit:4,skipped_duplicates:0,calls:[]}
function setup(handler?:(path:string,init?:RequestInit)=>unknown){vi.mocked(api).mockImplementation(async(path,init)=>{
 const custom=handler?.(path,init);if(custom!==undefined)return custom
 if(path==='/review-units/catalog')return {knowledge_versions:[{id:'kv',title:'二元一次方程组10项',count:10,stale:false,created_at:'2026-11-17'}],studies:unit.sources,skipped_duplicates:0}
 if(path==='/review-units/runs'&&!init)return [{id:'u1',title:unit.title,status:'completed',created_at:'2026-11-17'}]
 if(path.endsWith('/discussions'))return []
 return structuredClone(unit)
 });const dirty=vi.fn();render(<ReviewUnitPage onDirtyChange={dirty} onOpenKnowledge={vi.fn()}/>);return dirty}
async function open(){await screen.findByRole('option',{name:/二元一次方程组 · 草案已完成/});fireEvent.change(screen.getByLabelText('已有复习单元'),{target:{value:'u1'}});await screen.findByRole('heading',{name:'阅读与审核'})}
it('starts from one knowledge final and automatically uses the complete valid study bank',async()=>{
 setup();await screen.findByRole('option',{name:'二元一次方程组10项 · 10项'});fireEvent.change(screen.getByLabelText('复习单元知识终稿'),{target:{value:'kv'}})
 fireEvent.click(screen.getByRole('button',{name:'生成完整复习单元草案'}));await screen.findByRole('heading',{name:'阅读与审核'})
 const call=vi.mocked(api).mock.calls.find(([p,i])=>p==='/review-units/runs'&&i?.method==='POST')!;const request=JSON.parse(String(call[1]?.body));expect(request.knowledge_version_id).toBe('kv');expect(request.analysis_version_ids).toBeNull();expect(request.request_key).toBeTruthy()
 expect(screen.getByText('从数量关系到等量关系')).toBeTruthy()
})
it('AI opinions do not veto teacher confirmation and optional notes submit with the final',async()=>{
 setup((path,init)=>path.endsWith('/finalize')?{id:'f1'}:undefined);await open()
 fireEvent.click(screen.getByRole('button',{name:'分层训练 ·'}));expect(screen.getAllByText('提示是否过早给出方法？').length).toBeGreaterThan(0)
 fireEvent.change(screen.getByLabelText('单元审核说明'),{target:{value:'教师认可当前提示。'}});fireEvent.click(screen.getByLabelText('整体确认复习单元'))
 const button=screen.getByRole('button',{name:'形成复习单元终稿'});expect(button.hasAttribute('disabled')).toBe(false);fireEvent.click(button)
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/finalize'))).toBe(true))
 const request=JSON.parse(String(vi.mocked(api).mock.calls.find(([p])=>p.endsWith('/finalize'))![1]?.body));expect(request.note).toBe('教师认可当前提示。');expect(request.confirmed).toBe(true)
})
it('inline editing protects unsaved work and save does not finalize or erase a teacher note',async()=>{
 const dirty=setup((path,init)=>path==='/review-units/runs/u1'&&init?.method==='PUT'?{...unit,revision:2,body:JSON.parse(String(init.body)).body}:undefined);await open()
 fireEvent.click(screen.getByRole('button',{name:'编辑'}));fireEvent.change(screen.getByLabelText('导读'),{target:{value:'教师修改的导读'}})
 await waitFor(()=>expect(dirty).toHaveBeenLastCalledWith(true));expect(screen.getByLabelText('整体确认复习单元').hasAttribute('disabled')).toBe(true)
 fireEvent.change(screen.getByLabelText('单元审核说明'),{target:{value:'保留审核说明'}});fireEvent.click(screen.getByRole('button',{name:'保存单元修改'}));await screen.findByText('单元修改已保存，尚未定稿。')
 expect((screen.getByLabelText('单元审核说明') as HTMLTextAreaElement).value).toBe('保留审核说明');expect(screen.getByText('教师修改的导读')).toBeTruthy();expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/finalize'))).toBe(false)
})
it('stale sources keep historical reader links but disable saving and finalization',async()=>{
 setup(path=>path==='/review-units/runs/u1'?{...unit,stale:true,read_only:true,versions:[{id:'f1',revision:1,created_at:'2026-11-17'}]}:undefined);await open()
 expect(screen.getByText(/知识或研究依据已变化/)).toBeTruthy();expect(screen.getByRole('link',{name:'下载离线读物 HTML'}).getAttribute('href')).toBe('/api/review-units/versions/f1/download')
 expect(screen.getByRole('button',{name:'基于此终稿继续修订'}).hasAttribute('disabled')).toBe(true)
})
it('AI discussion sends the current unsaved section but never applies its reply automatically',async()=>{
 setup();await open();fireEvent.click(screen.getByRole('button',{name:'编辑'}));fireEvent.change(screen.getByLabelText('导读'),{target:{value:'尚未保存的导读'}})
 fireEvent.change(screen.getByLabelText('复习单元AI讨论'),{target:{value:'请检查这个导读'}});fireEvent.click(screen.getByRole('button',{name:'发送讨论'}))
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p,i])=>p.endsWith('/discussions')&&i?.method==='POST')).toBe(true))
 const c=vi.mocked(api).mock.calls.find(([p,i])=>p.endsWith('/discussions')&&i?.method==='POST')!;expect(JSON.parse(String(c[1]?.body)).body.introduction).toBe('尚未保存的导读')
 expect(vi.mocked(api).mock.calls.some(([,i])=>i?.method==='PUT')).toBe(false)
})
