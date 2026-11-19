import {expect,it} from 'vitest'
import {examWarnings} from './examWarnings'
const original='题中有未转换公式占位，需对照原件核对。'
it('uses the current text for formula placeholder warnings and leaves historical notes unchanged',()=>{
 const question={question_text:'求值：【未转换公式，请对照原件并替换】',notes:original,image_ids:[]}
 expect(examWarnings(question)).toContain('含未转换或未识别的公式，请对照原件替换。')
 expect(examWarnings({...question,question_text:String.raw`求值：\(x^2+1\)`})).toEqual([])
 expect(question.notes).toBe(original)
})
it('keeps independent extraction issues in mixed notes after formula repair',()=>{
 const base={question_text:String.raw`\(x^2\)`,image_ids:[]}
 for(const notes of [original+'；题干续页边界不明确','公式未转换且选项缺失','公式识别失败，题图模糊']){
  const warnings=examWarnings({...base,notes});expect(warnings.length).toBeGreaterThan(0)
  expect(warnings.join('')).toMatch(/边界|选项|题图/)
 }
})
it('still warns for broken current formula delimiters, other placeholders and missing selected images',()=>{
 const warnings=examWarnings({question_text:String.raw`\(x^2【未转换公式，请替换】`,notes:original,image_ids:['lost']},[])
 expect(warnings).toContain('公式起止标记不配对，请检查公式是否提取完整。')
 expect(warnings).toContain('所选题图丢失或不可读取，请重新选择配图。')
 expect(warnings).toContain('含未转换或未识别的公式，请对照原件替换。')
})
