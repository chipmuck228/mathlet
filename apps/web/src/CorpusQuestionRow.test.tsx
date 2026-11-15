import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import CorpusQuestionRow,{type CorpusQuestion} from './CorpusQuestionRow'
afterEach(cleanup)
const base:CorpusQuestion={id:'q',question_id:'qid',exam_id:'e',title:'测试题',statement:'题目正文',number:'1',blockers:[],duplicate_count:1,runs:[]}
const run={id:'r',status:'completed',revision:1,error:'',stale:false,problem_types:[],identified_names:[],finals:[]}
it.each([
 ['conditions',{...base,blockers:['待确认']},'待完善／确认条件'],
 ['ready',base,'条件已确认，待研究'],
 ['running',{...base,runs:[{...run,status:'running'}]},'排队／研究中'],
 ['review',{...base,runs:[run]},'研究稿待审核'],
 ['final',{...base,runs:[{...run,finals:[{id:'f',stale:false,created_at:''}]}]},'研究已审定'],
 ['failed',{...base,runs:[{...run,status:'failed'}]},'研究失败／中断'],
] as const)('uses %s color and text while allowing clean expand/collapse',(state,question,label)=>{
 const {container}=render(<CorpusQuestionRow question={question as CorpusQuestion} selected={false} finals={[]} blocked={false} onSelect={vi.fn()} onFinalSelect={vi.fn()} onGenerate={vi.fn()} onRetry={vi.fn()} onRefresh={vi.fn()} onDirty={vi.fn()} onBusy={vi.fn()}/>)
 expect(container.querySelector('.corpus-state-'+state)).toBeTruthy();expect(screen.getByText(label)).toBeTruthy()
 const open=screen.getByRole('button',{name:'展开题目'});expect(open.getAttribute('aria-expanded')).toBe('false');fireEvent.click(open)
 expect(screen.getByRole('button',{name:'折叠题目'}).getAttribute('aria-expanded')).toBe('true')
 fireEvent.click(screen.getByRole('button',{name:'折叠题目'}));expect(screen.getByRole('button',{name:'展开题目'})).toBeTruthy()
})
