import {useState} from 'react'
import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {QuestionTablesEditor,type DataTable} from './QuestionTables'
import ExamTableSuggestion from './ExamTableSuggestion'
import {api} from '@/lib/api'
vi.mock('@/lib/api',()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
vi.mock('./ReadableMath',()=>({default:({text}:{text:string})=><span>{text}</span>}))
vi.mock('./MathBlockEditor',()=>({default:({text,onChange}:{text:string;onChange:(s:string)=>void})=><textarea aria-label="单元格内容" value={text} onChange={e=>onChange(e.target.value)}/>}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
const table:DataTable={key:'t',caption:'人数表',header_rows:1,rows:[['类别','人数'],['甲','']],source_block_ids:[],source_note:''}
it('edits blank cells and formulas, maintains rectangular rows and columns',()=>{
 function Editor(){const [tables,setTables]=useState([table]);return <><QuestionTablesEditor tables={tables} onChange={setTables}/><output>{JSON.stringify(tables)}</output></>}
 render(<Editor/>);fireEvent.click(screen.getByRole('button',{name:'表1第2行第2列'}));expect((screen.getByLabelText('单元格内容') as HTMLTextAreaElement).value).toBe('')
 fireEvent.change(screen.getByLabelText('单元格内容'),{target:{value:'\\(\\frac{1}{x}\\)'}})
 expect(JSON.parse(screen.getByRole('status').textContent!)[0].rows[1][1]).toBe('\\(\\frac{1}{x}\\)')
 fireEvent.click(screen.getByRole('button',{name:'在所选行后加行'}));let t=JSON.parse(screen.getByRole('status').textContent!)[0];expect(t.rows[2]).toEqual(['',''])
 fireEvent.click(screen.getByRole('button',{name:'在所选列后加列'}));t=JSON.parse(screen.getByRole('status').textContent!)[0];expect(t.rows.every((r:string[])=>r.length===3)).toBe(true)
 fireEvent.click(screen.getByRole('button',{name:'删除所选列'}));fireEvent.click(screen.getByRole('button',{name:'删除所选行'}));t=JSON.parse(screen.getByRole('status').textContent!)[0];expect(t.rows).toHaveLength(2);expect(t.rows[1][1]).toBe('\\(\\frac{1}{x}\\)')
})
const task={id:'task',status:'completed',stale:false,error:'',original_text:'根据表回答',original_tables:[table],result:{tables:[table],suggested_text:'根据表回答',remove_fragments:[],uncertainties:[],limitations:'未读取图片'}}
it('requires explicit adoption and rechecks server state',async()=>{
 vi.mocked(api).mockResolvedValue(task);const apply=vi.fn();render(<ExamTableSuggestion extractionId="e" revision={1} questionKey="q" text="根据表回答" tables={[table]} disabled={false} onApply={apply}/>);
 fireEvent.click(screen.getByRole('button',{name:'AI整理本题表格'}));await screen.findByText('表格建议');expect(apply).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'采用表格建议并编辑'}));await waitFor(()=>expect(apply).toHaveBeenCalledWith('根据表回答',[table]));expect(vi.mocked(api).mock.calls[1][0]).toBe('/exam-table-suggestions/task')
})
it('does not apply a suggestion after a local table edit',async()=>{
 vi.mocked(api).mockResolvedValue(task);const apply=vi.fn();const props={extractionId:'e',revision:1,questionKey:'q',text:'根据表回答',disabled:false,onApply:apply};const view=render(<ExamTableSuggestion {...props} tables={[table]}/>);
 fireEvent.click(screen.getByRole('button',{name:'AI整理本题表格'}));await screen.findByText('表格建议');view.rerender(<ExamTableSuggestion {...props} tables={[{...table,caption:'新标题'}]}/>);
 expect((screen.getByRole('button',{name:'采用表格建议并编辑'}) as HTMLButtonElement).disabled).toBe(true);expect(apply).not.toHaveBeenCalled()
})
