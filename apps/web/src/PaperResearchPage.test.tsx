import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import PaperResearchPage from './PaperResearchPage'
import {api} from '@/lib/api'
vi.mock('@/lib/api',()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
vi.mock('./MathBlockEditor',()=>({default:()=>null}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
const payload={title:'第一题',number:'1',question_spans:[{block_id:'b',start_anchor:'1.',end_anchor:'',start_occurrence:0,end_occurrence:0}],answer_spans:[],asset_ids:[],answer_status:'absent',figure_status:'not_needed',diagram_description:'',region:'',year:'',boundary_note:'',knowledge_refs:['kv:k'],recommendations:[{ref:'kv:k',reason:'坐标满足表达式',evidence:'图象经过'}],knowledge_gaps:[]}
const item={id:'i',revision:1,payload,resolved:{statement:'1. 图象经过(2,3)，求k。',reference_answer:'',errors:[],ranges:[],assets:[]},question:{confirmed:true,stale:false},run_id:'run',runs:[{id:'run',status:'completed',error:'',finals:[{id:'av1',created_at:'2026-11-13'}]}]}
const card={id:'card',revision:1,payload:{title:'代入点坐标建立关系',recognition_cues:['图象上的点'],common_structure:'坐标满足关系式',strategy_steps:[{action:'将点代入',reason:'函数图象的定义',conditions:'自变量取值合法',analysis_ids:['av1','av2']}],alternative_paths:[],boundaries:['需要已知函数关系'],common_mistakes:['横纵坐标互换'],examples:[{analysis_id:'av1',reason:'同一结构'},{analysis_id:'av2',reason:'条件变化'}],transfer_training:[{kind:'designed',prompt:'已知图象经过(1,2)，求k。',skill_goal:'代入与检验',hints:['先看自变量'],checkpoints:['检验参数非零'],analysis_ids:['av1','av2']}],unresolved:[]},sources:[{id:'av1',title:'第一题'},{id:'av2',title:'第二题'}],checks:[{message:'请教师检查边界'}],stale:false,read_only:false,blockers:[],finals:[],parent_version:null}
const project={id:'p',title:'合成试卷',revision:1,stale:false,source:{document_id:'d',document_name:'合成试卷',review:{filename:'2026-11-13.json'},blocks:[{id:'b',locator:'段落2',text:'1. 图象经过(2,3)，求k。',verified:true,assets:[]}]},items:[item],archived:[],knowledge:[{ref:'kv:k',version_id:'kv',title:'反比例函数',unit_title:'函数',scope:'core',stale:false},{ref:'kv:k2',version_id:'kv',title:'点的坐标',unit_title:'坐标系',scope:'core',stale:false}],tasks:[],notes:[],cards:[card],coverage:{unassigned:[],overlaps:[],unchecked_blocks:[],unassigned_assets:[]}}
function mock(p=project){vi.mocked(api).mockImplementation(async(path)=>{if(path==='/source-reviews')return [{document_id:'d',filename:'2026-11-13.json',document_name:'合成试卷'}];if(path==='/papers')return [{id:'p',title:p.title}];if(path==='/papers/p')return structuredClone(p);throw new Error('Unexpected '+path)})}
it('opens reviewed paper with source and knowledge reasons, edits mappings, then launches batch using the existing research workbench',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!;const open=vi.fn()
 vi.mocked(api).mockImplementation(async(path,init)=>{if(path==='/papers/p/items/i'&&init?.method==='PUT'){const value=JSON.parse(init.body as string);return {...project,revision:2,items:[{...item,revision:2,payload:value.body}]}};if(path==='/papers/p/analyses')return {results:[{item_id:'i',run_id:'run',status:'completed'}]};return base(path,init)})
 render(<PaperResearchPage onDirtyChange={vi.fn()} onOpenRun={open}/>);
 await screen.findByRole('navigation',{name:'整卷题目列表'});expect(screen.getAllByText('坐标满足表达式').length).toBeGreaterThan(0)
 expect(vi.mocked(api).mock.calls.every(([,i])=>!i?.method)).toBe(true)
 fireEvent.click(await screen.findByLabelText(/坐标系 \/ 点的坐标/));expect((screen.getByLabelText('已有整卷记录') as HTMLSelectElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'保存分题与知识选择'}))
 await waitFor(()=>expect((screen.getByLabelText('已有整卷记录') as HTMLSelectElement).disabled).toBe(false))
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([p,i])=>p==='/papers/p/items/i'&&i?.method==='PUT')![1]!.body as string);expect(sent.body.knowledge_refs).toEqual(['kv:k','kv:k2'])
 fireEvent.click(screen.getByLabelText('选择 第一题'));fireEvent.click(screen.getByRole('button',{name:'批量生成单题研究稿（1 题）'}))
 await screen.findByText(/重复提交复用原任务/)
 await waitFor(()=>expect((screen.getByRole('button',{name:/打开研究终稿 · 打开研究稿/}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:/打开研究终稿 · 打开研究稿/}));expect(open).toHaveBeenCalledWith('run')
})
it('creates a source-bound paper before starting an explicit AI split job',async()=>{
 const empty={...project,items:[],cards:[]};mock(empty);const base=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,init)=>{if(path==='/papers/p/split')return {id:'t'};return base(path,init)})
 render(<PaperResearchPage onDirtyChange={vi.fn()} onOpenRun={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'自动分题建议'}));await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p,i])=>p==='/papers/p/split'&&i?.method==='POST')).toBe(true))
 expect(vi.mocked(api).mock.calls.some(([p])=>p==='/papers/p/analyses')).toBe(false)
})
it('keeps cards as drafts until explicit teacher confirmation and offers inline revision',async()=>{
 mock();const base=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,init)=>{if(path==='/papers/p/cards/card'&&init?.method==='PUT')return {...card,revision:2};return base(path,init)})
 render(<PaperResearchPage onDirtyChange={vi.fn()} onOpenRun={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'跨题思路卡'}));await screen.findByText('代入点坐标建立关系 · 思路卡草稿')
 expect((screen.getByRole('button',{name:'形成思路卡终稿'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'编辑'}));fireEvent.change(screen.getByLabelText('卡片标题'),{target:{value:'教师修订标题'}})
 expect((screen.getByRole('button',{name:'分题与研究'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'保存思路卡修订'}));await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p,i])=>p==='/papers/p/cards/card'&&i?.method==='PUT')).toBe(true))
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/finalize'))).toBe(false)
})
