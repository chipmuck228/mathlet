import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import QuestionBankPage from './QuestionBankPage'
import {api} from '@/lib/api'
vi.mock('@/lib/api',()=>({api:vi.fn()}))
vi.mock('./ReadableMath',()=>({default:({text}:{text:string})=><span>{text}</span>}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
it('filters structured reviewed questions and opens their exact study or condition record',async()=>{
 const item={id:'q2',title:'第二题已审',statement:'方程组题目',status:'research_reviewed',reusable:true,problem_types:['方程组应用'],knowledge_names:['消元'],knowledge_units:['二元一次方程组'],source_categories:['exam'],source_titles:['合成中考试卷'],research_count:1,mapping_count:0,current_analysis_ids:['av'],stale:false}
 vi.mocked(api).mockImplementation(async path=>path==='/corpus/bank'?[item,{...item,id:'q1',title:'第一题待研究',status:'question_confirmed',reusable:false,problem_types:[],knowledge_units:[],research_count:0}]:{id:'q2',status:item.status,reusable:true,question_version_id:'qv2',question:{title:item.title,statement:item.statement,diagram_description:'',assets:[]},sources:[],origins:[],research_versions:[{id:'av',revision:1,run_id:'exact-run',current:true,created_at:'2026-11-15',reviewer:'教师',analysis:{problem_types:['方程组应用'],recognition_cues:['两个数量关系'],approaches:[],common_mistakes:[]}}],mapping_versions:[]})
 const open=vi.fn(),edit=vi.fn();render(<QuestionBankPage refreshKey={0} onOpenRun={open} onEditQuestion={edit}/>)
 await screen.findByRole('button',{name:'第二题已审'})
 fireEvent.change(screen.getByLabelText('题库知识小节'),{target:{value:'二元一次方程组'}})
 expect(screen.queryByRole('button',{name:'第一题待研究'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'第二题已审'}));await screen.findByText('题目编号：q2 · 原题版本：qv2')
 fireEvent.click(screen.getByRole('button',{name:'在本页核验／查看研究终稿'}));expect(open).toHaveBeenCalledWith('exact-run','第二题已审')
 fireEvent.click(screen.getByRole('button',{name:'在本页补充／核对原题条件'}));expect(edit).toHaveBeenCalledWith('q2','第二题已审')
 expect(screen.getByRole('link',{name:'下载结构化题目 JSON'}).getAttribute('href')).toBe('/api/corpus/bank/q2/download')
 expect(vi.mocked(api).mock.calls.every(([,init])=>!init?.method)).toBe(true)
})
