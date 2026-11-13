import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import SourceReview from './SourceReview'
import SourceReviewFiles from './SourceReviewFiles'
import {api,type Block} from '@/lib/api'
vi.mock('@/lib/api',()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
vi.mock('./OriginalDocument',()=>({default:()=> <h2>原始文档 · 只读</h2>}))
const blocks:Block[]=[1,2].map(i=>({id:'b'+i,document_id:'d',locator:'文档块 '+i,text:'题目'+i,preview:'',assets:[],warnings:['提取提醒'],original_text:'原始提取'+i,verified:false,revision:1}))
const review={document_id:'d',filename:'2026-11-13_21-00-00-123456.json',created_at:'2026-11-13T21:00:00.123456+08:00',updated_at:'2026-11-13T21:00:00.123456+08:00',revision:1}
beforeEach(()=>{vi.mocked(api).mockReset();Element.prototype.scrollIntoView=vi.fn();vi.mocked(api).mockResolvedValue({review:null,blocks});})
afterEach(cleanup)
function open(){return render(<SourceReview documentId="d" kind="docx" focusId="" onSaved={vi.fn()} onDirtyChange={vi.fn()} onBusyChange={vi.fn()} onReviewSaved={vi.fn()}/>)}
it('removes the continuous toolbar and extraction notices and shows the reviewed button only for the selected block',async()=>{
 open();await screen.findByRole('textbox',{name:'提取结果 文档块 1'})
 expect(screen.getByRole('heading',{name:'核对'})).toBeTruthy();expect(screen.getByRole('heading',{name:'原始文档 · 只读'})).toBeTruthy()
 expect(screen.queryByText('连续核对')).toBeNull();expect(screen.queryByText('查看初次提取记录')).toBeNull();expect(screen.queryByText('提取注意事项')).toBeNull();expect(screen.queryByLabelText('确认范围起点')).toBeNull()
 expect(screen.queryByRole('button',{name:'已核对'})).toBeNull()
 fireEvent.focus(screen.getByRole('textbox',{name:'提取结果 文档块 1'}))
 expect(screen.getAllByRole('button',{name:'已核对'})).toHaveLength(1)
 fireEvent.click(screen.getByRole('button',{name:'选择 文档块 2'}))
 expect(screen.getAllByRole('button',{name:'已核对'})).toHaveLength(1)
})
it('confirms only the selected block without formula checks and preserves other unsaved edits',async()=>{
 let count=0
 vi.mocked(api).mockImplementation(async(path,init)=>{
  if(init?.method==='PUT'){count++;return {review:{...review,revision:count},blocks:count===1?[{...blocks[0],text:'【未转换公式】人工认可的内容',verified:true,revision:2},blocks[1]]:[{...blocks[0],text:'【未转换公式】人工认可的内容',verified:true,revision:2},{...blocks[1],text:'保留其他修改',verified:false,revision:2}]}}
  return {review:null,blocks}
 })
 open();const first=await screen.findByRole('textbox',{name:'提取结果 文档块 1'});const second=screen.getByRole('textbox',{name:'提取结果 文档块 2'})
 fireEvent.change(first,{target:{value:'【未转换公式】人工认可的内容'}});fireEvent.change(second,{target:{value:'保留其他修改'}})
 fireEvent.click(screen.getByRole('button',{name:'选择 文档块 1'}));fireEvent.click(screen.getByRole('button',{name:'已核对'}))
 await screen.findByText('已保存此内容块的人工核对结果。')
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([,i])=>i?.method==='PUT')![1]!.body as string)
 expect(sent.changes).toEqual([{id:'b1',revision:1,text:'【未转换公式】人工认可的内容',verified:true}])
 expect((second as HTMLTextAreaElement).value).toBe('保留其他修改')
 expect(vi.mocked(api).mock.calls.some(([p])=>p.includes('/formulas/'))).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'保存核对文件'}))
 await waitFor(()=>expect(vi.mocked(api).mock.calls.filter(([,i])=>i?.method==='PUT')).toHaveLength(2))
 const saved=JSON.parse(vi.mocked(api).mock.calls.filter(([,i])=>i?.method==='PUT')[1][1]!.body as string)
 expect(saved.review_revision).toBe(1);expect(saved.changes).toEqual([{id:'b2',revision:1,text:'保留其他修改',verified:false}])
 expect(screen.getByRole('link',{name:'下载核对文件'}).getAttribute('href')).toBe('/api/documents/d/source-review/download')
})
it('keeps local text on write failure without the old blanket validity/conflict paragraph',async()=>{
 vi.mocked(api).mockImplementation(async(_,init)=>{if(init?.method==='PUT')throw Error('写入失败');return {review:null,blocks}})
 open();const input=await screen.findByRole('textbox',{name:'提取结果 文档块 1'})
 fireEvent.change(input,{target:{value:'不应丢失的输入'}});fireEvent.click(screen.getByRole('button',{name:'保存核对文件'}))
 await screen.findByText('写入失败');expect((input as HTMLTextAreaElement).value).toBe('不应丢失的输入')
 expect(screen.queryByText(/本次范围未保存/)).toBeNull()
})
it('opens a saved local file and restores its text and reviewed states',async()=>{
 vi.mocked(api).mockImplementation(async(_,init)=>init?.method==='POST'?{review,blocks:[{...blocks[0],text:'文件中的核对内容',verified:true,revision:2},blocks[1]]}:{review:null,blocks})
 open();await screen.findByRole('textbox',{name:'提取结果 文档块 1'})
 const payload={schema_version:1,review,document:{id:'d'},blocks:[{...blocks[0],text:'文件中的核对内容',verified:true},blocks[1]]}
 const file=new File(['{}'],review.filename,{type:'application/json'});Object.defineProperty(file,'text',{value:async()=>JSON.stringify(payload)})
 fireEvent.change(screen.getByLabelText('选择本地核对文件'),{target:{files:[file]}})
 await screen.findByText('已打开核对文件：'+review.filename)
 expect((screen.getByRole('textbox',{name:'提取结果 文档块 1'}) as HTMLTextAreaElement).value).toBe('文件中的核对内容')
 const sent=JSON.parse(vi.mocked(api).mock.calls.find(([,i])=>i?.method==='POST')![1]!.body as string)
 expect(sent.payload.blocks[0].verified).toBe(true)
})
it('lists stable review filenames for reopening the corresponding original',async()=>{
 vi.mocked(api).mockResolvedValue([{...review,document_name:'试卷.docx'}]);const onOpen=vi.fn()
 render(<SourceReviewFiles documentId="" refreshKey={1} disabled={false} onOpen={onOpen}/>);
 await screen.findByRole('option',{name:review.filename+' · 试卷.docx'})
 fireEvent.change(screen.getByLabelText('打开核对记录'),{target:{value:'d'}})
 expect(onOpen).toHaveBeenCalledWith('d')
})
