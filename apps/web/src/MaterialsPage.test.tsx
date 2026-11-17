import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import MaterialsPage,{destination} from './MaterialsPage'
import {api} from '@/lib/api'
vi.mock('@/lib/api',()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
const doc={id:'d1',name:'课标.docx',kind:'docx',category:'standard',status:'ready',created_at:'2026-11-17'}
it('requires category selection before upload and sends explicit category',async()=>{
 vi.mocked(api).mockResolvedValue({id:'new'});const refresh=vi.fn(async()=>{})
 render(<MaterialsPage documents={[]} onRefresh={refresh} onReview={vi.fn()}/>);const input=screen.getByLabelText('上传资料文件')
 expect(input.hasAttribute('disabled')).toBe(true)
 fireEvent.change(screen.getByLabelText('资料类别'),{target:{value:'exam'}});expect(input.hasAttribute('disabled')).toBe(false)
 fireEvent.change(input,{target:{files:[new File(['test'],'test.docx')]}})
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/documents?category=exam',expect.objectContaining({method:'POST'})))
 expect(vi.mocked(api).mock.calls[0][1]?.body).toBeInstanceOf(FormData)
 expect(destination('exam')).toBe('sources');expect(destination('mock')).toBe('sources');expect(destination('term')).toBe('sources');expect(destination('standard')).toBe('standards')
})
it('requires concrete deletion confirmation and preserves the row on cancel',async()=>{
 vi.mocked(api).mockResolvedValue({ok:true});const refresh=vi.fn(async()=>{})
 render(<MaterialsPage documents={[doc]} onRefresh={refresh} onReview={vi.fn()}/>);fireEvent.click(screen.getByRole('button',{name:'删除'}))
 expect(screen.getByRole('dialog',{name:'删除资料'})).toBeTruthy();expect(screen.getByText(/已定稿的提取文件/)).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'取消'}));expect(api).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'删除'}));fireEvent.click(screen.getByRole('button',{name:'确认删除原文件'}))
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/documents/d1',{method:'DELETE'}));await screen.findByText('原始资料已删除；已有定稿快照保留。')
})
it('classifies a historical uncategorized file before handing it to the review route',async()=>{
 const next={...doc,category:'exam'};vi.mocked(api).mockResolvedValue(next);const review=vi.fn()
 render(<MaterialsPage documents={[{...doc,category:'unknown'}]} onRefresh={async()=>{}} onReview={review}/>);fireEvent.click(screen.getByRole('button',{name:'先分类'}))
 fireEvent.change(screen.getByLabelText('已有资料类别'),{target:{value:'exam'}});fireEvent.click(screen.getByRole('button',{name:'保存类别并核对'}))
 await waitFor(()=>expect(review).toHaveBeenCalledWith(next));expect(vi.mocked(api).mock.calls[0][0]).toBe('/documents/d1/category')
})
