import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import ExamFormulaSuggestion from './ExamFormulaSuggestion'
import {api} from '@/lib/api'
vi.mock('@/lib/api',()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
vi.mock('./ReadableMath',()=>({default:({text}:{text:string})=><p>{text}</p>}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
const result={id:'t',status:'completed',error:'',stale:false,original_text:'x2=4',result:{changes:[{before:'x2',after:'\\(x^2\\)',reason:'原生公式为平方',evidence:'DOCX结构'}],uncertainties:['需要对照原文'],suggested_text:'\\(x^2\\)=4',limitations:'未读取图片'}}
function page(text='x2=4',onApply=vi.fn()){return render(<ExamFormulaSuggestion extractionId="e" revision={1} questionKey="q" text={text} disabled={false} onApply={onApply}/>)}
it('shows evidence and before/after, adopts only after explicit choice and rechecks status',async()=>{
 vi.mocked(api).mockResolvedValue(result);const apply=vi.fn();page('x2=4',apply)
 fireEvent.click(screen.getByRole('button',{name:'AI 修正公式'}));await screen.findByText('修正建议')
 expect(apply).not.toHaveBeenCalled();expect(screen.getByText('未读取图片',{exact:false})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'采用修正并编辑'}))
 await waitFor(()=>expect(apply).toHaveBeenCalledWith('\\(x^2\\)=4'))
 expect(vi.mocked(api).mock.calls[1][0]).toBe('/exam-formula-suggestions/t')
})
it('rejects adoption after local changes and permits discard without changing text',async()=>{
 vi.mocked(api).mockResolvedValue(result);const apply=vi.fn();const view=page('x2=4',apply)
 fireEvent.click(screen.getByRole('button',{name:'AI 修正公式'}));await screen.findByText('修正建议')
 view.rerender(<ExamFormulaSuggestion extractionId="e" revision={1} questionKey="q" text="教师改题" disabled={false} onApply={apply}/>)
 expect((screen.getByRole('button',{name:'采用修正并编辑'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'放弃建议'}));expect(apply).not.toHaveBeenCalled();expect(screen.queryByText('修正建议')).toBeNull()
})
it('rechecks server staleness before adoption',async()=>{
 vi.mocked(api).mockResolvedValueOnce(result).mockResolvedValueOnce({...result,stale:true});const apply=vi.fn();page('x2=4',apply)
 fireEvent.click(screen.getByRole('button',{name:'AI 修正公式'}));await screen.findByText('修正建议');fireEvent.click(screen.getByRole('button',{name:'采用修正并编辑'}))
 await screen.findByText('Error: 题目或来源已变化，请重新生成建议');expect(apply).not.toHaveBeenCalled()
})
it('shows call failure and leaves original untouched',async()=>{
 vi.mocked(api).mockRejectedValue(Error('模型不可用'));const apply=vi.fn();page('x2=4',apply)
 fireEvent.click(screen.getByRole('button',{name:'AI 修正公式'}));await screen.findByRole('alert');expect(apply).not.toHaveBeenCalled()
})
it('polls the queued worker and shows completed suggestions without applying',async()=>{
 vi.mocked(api).mockImplementation(async path=>path.includes('/exam-extractions/')?{...result,status:'queued',result:null}:result)
 const apply=vi.fn();page('x2=4',apply);fireEvent.click(screen.getByRole('button',{name:'AI 修正公式'}))
 await screen.findByRole('status');await screen.findByText('修正建议',{}, {timeout:3000});expect(apply).not.toHaveBeenCalled()
})
