import {useState} from 'react'
import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import UnitGoalPaths from './UnitGoalPaths'
import type {Unit,UnitBody} from './ReviewUnitTypes'
vi.mock('./ReadableMath',()=>({default:({text}:{text:string})=><span>{text}</span>}))
afterEach(cleanup)
const goal={target_id:'goal:g1',student_goal:'怎样选消元方法？',knowledge_refs:['k1'],analysis_ids:['a1'],card_indices:[0],training_indices:[0,1,2],expected_phases:['basic','thinking','solve'],assessment:'arranged',gap_types:[],explanation:'已有基础和研究证据',guidance:'',}
const body:UnitBody={title:'方程组',introduction:'',goals:[],mappings:[{analysis_id:'a1',relevance:'core',reason:'使用消元',links:[{analysis_id:'a1',approach_id:'add',step_index:0,quote:'两式相加',knowledge_ref:'k1',role:'core',explanation:'消去y',conditions:'系数相反'}],gaps:[]}],selected_analysis_ids:['a1'],cards:[{title:'比较系数',cues:[],structure:'',steps:[],conditions:[],alternatives:[],mistakes:[],knowledge_refs:['k1'],evidence:[{analysis_id:'a1',approach_id:'add',step_index:0,quote:'两式相加'}],doubts:[]}],training:['basic','thinking','solve'].map((phase,i)=>({phase,kind:'original',title:'训练'+i,source_analysis_ids:['a1'],knowledge_refs:['k1'],prompt:'',hints:[],answer:'',reasoning:'',checkpoints:[]})),summary:'',goal_coverage:{source_hash:'h',origin:'ai',generated_at:'',error:'',report:{rows:[goal],teacher_note:''}}}
const unit={id:'u',revision:1,body,read_only:false,knowledge:{items:[{ref:'k1',title:'加减消元法'}]},sources:[{id:'a1',title:'代表题一'}],goal_context:{state:'current',targets:[{id:'goal:g1',kind:'objective',text:'能根据系数选择消元'}],foundation:[{target_id:'goal:g1',status:'covered',knowledge_refs:['k1'],catalog_hints:[],note:'',guidance:''}],row_states:[{target_id:'goal:g1',status:'arranged',gaps:[]}]}} as unknown as Unit
it('links readable target evidence, cards and exercises without exposing internal IDs',()=>{
 const nav=vi.fn(),evidence=vi.fn();render(<UnitGoalPaths unit={unit} body={body} editing={false} onChange={vi.fn()} onNavigate={nav} onEvidence={evidence}/>);
 expect(screen.getByText('已安排路径')).toBeTruthy();expect(screen.queryByText('goal:g1')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'代表题一'}));expect(evidence).toHaveBeenCalledWith('a1')
 fireEvent.click(screen.getByRole('button',{name:'加减消元法'}));expect(nav).toHaveBeenCalledWith('basics',0)
 fireEvent.click(screen.getByRole('button',{name:'训练2'}));expect(nav).toHaveBeenCalledWith('training',2)
 expect(screen.getByText('迁移练习（可选）')).toBeTruthy()
})
it('edits correspondence inline and prunes dependent exercise refs when knowledge is removed',()=>{
 const change=vi.fn();render(<UnitGoalPaths unit={unit} body={body} editing={true} onChange={change}/>);
 fireEvent.click(screen.getByLabelText('加减消元法'))
 const next=change.mock.calls.at(-1)![0] as UnitBody;expect(next.goal_coverage?.report?.rows[0].knowledge_refs).toEqual([])
 expect(next.goal_coverage?.report?.rows[0].analysis_ids).toEqual([]);expect(next.goal_coverage?.report?.rows[0].training_indices).toEqual([])
})
it('keeps successive local edits when replacing a stale report with a current arrangement',()=>{
 function Wrapper(){const [b,setB]=useState(body);return <UnitGoalPaths unit={{...unit,goal_context:{...unit.goal_context!,state:'stale'}}} body={b} editing onChange={setB}/>}
 render(<Wrapper/>);fireEvent.change(screen.getByLabelText('目标 1 安排依据'),{target:{value:'教师重新判断基础内容'}})
 fireEvent.change(screen.getByLabelText('目标 1 学生问句'),{target:{value:'你会如何选择？'}})
 expect((screen.getByLabelText('目标 1 安排依据') as HTMLTextAreaElement).value).toBe('教师重新判断基础内容')
})
it('does not invent structured goals for older source knowledge',()=>{
 render(<UnitGoalPaths unit={{...unit,goal_context:undefined}} body={body} editing={false} onChange={vi.fn()}/>);
 expect(screen.getByText(/未带入结构化主题规格/)).toBeTruthy();expect(screen.queryByText('已安排路径')).toBeNull()
})
