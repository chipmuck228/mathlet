import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,render,screen,fireEvent} from '@testing-library/react'
import PublishedBookletsPage from './PublishedBookletsPage'
import {api} from '@/lib/api'
vi.mock('@/lib/api',()=>({api:vi.fn()}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
it('lists finalized deliveries with reading and offline download, and filters titles',async()=>{
 vi.mocked(api).mockResolvedValue([{id:'v1',title:'二元一次方程组',revision:2,created_at:'2026-11-17T10:00:00Z',knowledge_count:10,question_count:3,training_count:5}])
 render(<PublishedBookletsPage/>);await screen.findByRole('heading',{name:'二元一次方程组'})
 expect(screen.getByRole('link',{name:/打开阅读/}).getAttribute('href')).toBe('/api/review-units/versions/v1/reader')
 expect(screen.getByRole('link',{name:'下载离线读物'}).getAttribute('href')).toBe('/api/review-units/versions/v1/download')
 fireEvent.change(screen.getByLabelText('查找小册子'),{target:{value:'圆'}});expect(screen.getByText('没有找到这个名称的小册子。')).toBeTruthy()
})
it('shows empty shelf guidance',async()=>{vi.mocked(api).mockResolvedValue([]);render(<PublishedBookletsPage/>);expect(await screen.findByText(/还没有已发布小册子/)).toBeTruthy()})
