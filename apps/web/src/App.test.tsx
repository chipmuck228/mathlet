import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react'
import App from './App'
import {api} from '@/lib/api'
vi.mock('@/lib/api',()=>({api:vi.fn(),json:vi.fn()}))
vi.mock('./ExamSourceReview',()=>({default:({documentId}:{documentId:string})=><div>试卷核对 {documentId}</div>}))
vi.mock('./SourceReview',()=>({default:({documentId}:{documentId:string})=><div>课标核对 {documentId}</div>}))
vi.mock('./PlanningPage',()=>({default:()=> <div>领域与主题规划正文</div>}))
vi.mock('./EditorialKnowledgePage',()=>({default:()=> <div>知识正文</div>}))
vi.mock('./CorpusResearchPage',()=>({default:()=> <div>题库正文</div>}))
vi.mock('./ReviewUnitPage',()=>({default:()=> <div>复习单元正文</div>}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
it('groups six workflow destinations and routes document review by category',async()=>{
 const docs=['standard','exam','mock','term'].map((category,i)=>({id:'d'+i,name:category+'.docx',category,kind:'docx',status:'ready',created_at:'2026-11-17'}))
 vi.mocked(api).mockImplementation(async path=>path==='/documents'?docs:[])
 render(<App/>);await screen.findByText('standard.docx')
 const nav=screen.getByRole('navigation',{name:'工作区'})
 expect(within(nav).getAllByRole('button').map(b=>b.textContent)).toEqual(['资料包','原题核对','课标/考纲整理','知识与关系','题库研究','复习单元编制'])
 expect(within(nav).getByRole('heading',{name:'资料整理'})).toBeTruthy()
 expect(screen.queryByRole('button',{name:'题目与研究'})).toBeNull()
 for(const [i,category] of ['standard','exam','mock','term'].entries()){
  if(i)fireEvent.click(within(nav).getByRole('button',{name:'资料包'}))
  const row=screen.getByText(category+'.docx').closest('.document-row') as HTMLElement
  fireEvent.click(within(row).getByRole('button',{name:'核对'}))
  await screen.findByText((i?'试卷核对 ':'课标核对 ')+'d'+i)
  expect(within(nav).getByRole('button',{name:i?'原题核对':'课标/考纲整理'}).getAttribute('aria-current')).toBe('page')
 }
 fireEvent.click(within(nav).getByRole('button',{name:'课标/考纲整理'}));fireEvent.click(screen.getByRole('tab',{name:'领域与主题规划'}));await screen.findByText('领域与主题规划正文')
})
