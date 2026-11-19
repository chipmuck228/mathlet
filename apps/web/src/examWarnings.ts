// Evidence of extraction problems only; do not guess whether the mathematics is correct.
const markerPattern=String.raw`【[^】\n]*(?:未转换公式|未识别公式|无法识别公式|无法转换公式|公式[^】\n]*(?:未转换|未识别|转换失败|提取失败|识别失败)|superscript|subscript|请合并核对)[^】\n]*】|\uFFFD+`
export function extractionMarkers(text:string){return [...text.matchAll(new RegExp(markerPattern,'g'))]}
export function examWarnings(q:{question_text:string;notes:string;image_ids:string[]},assets?:{id:string;hash:string|null}[]):string[]{
 const text=q.question_text;const warnings:string[]=[]
 if(!text.trim())warnings.push('题目正文为空，请对照原文补全。')
 const matches=extractionMarkers(text)
 if(matches.some(m=>/公式/.test(m[0])))warnings.push('含未转换或未识别的公式，请对照原件替换。')
 if(matches.some(m=>/superscript|subscript|请合并核对/.test(m[0])))warnings.push('含尚未合并的上下标，请核对公式结构。')
 if(text.includes('\uFFFD'))warnings.push('含无法解码的替代字符，请对照原文核对。')
 for(const [start,end] of [['\\(','\\)'],['\\[','\\]']]){
  if(text.split(start).length!==text.split(end).length){warnings.push('公式起止标记不配对，请检查公式是否提取完整。');break}
 }
 const note=q.notes?.trim()||''
 if(note.startsWith('提取待核对：')){if(!text.trim())warnings.push(note)}
 else {
  // Notes preserve the initial extraction observation. Formula placeholders are
  // live text diagnostics above, so the old observation must not resurrect a
  // warning after a teacher repairs the question (including after save/reload).
  // Split mixed notes: fixing a formula must not hide an independent boundary,
  // option or image issue recorded in the same sentence.
  const unresolved=note.split(/[；;\n。，,]|并且|而且|同时|且/).map(s=>s.trim()).filter(Boolean).filter(clause=>{
   const formulaNote=/(?:未转换|未识别|无法识别|无法转换|转换失败|提取失败|识别失败).*公式|公式.*(?:未转换|未识别|无法识别|无法转换|转换失败|提取失败|识别失败|占位)/.test(clause)
   const otherProblem=/定位|边界|续页|(?:题干|题目|小问|选项|配图|题图|图形|条件|表格).*(?:缺失|丢失|不完整|不明确|不确定|未找到|模糊|错位|截断)/.test(clause)
   if(formulaNote&&!otherProblem)return false
   return /定位|边界|缺失|丢失|不完整|异常|不明确|不确定|重叠|未找到|无法|疑似|待核对|未识别|未转换|识别失败|提取失败|模糊|错位|截断/.test(clause)
  })
  if(unresolved.length)warnings.push('提取提示：'+unresolved.join('；'))
 }
 if(assets&&q.image_ids.some(id=>!assets.some(a=>a.id===id&&a.hash)))warnings.push('所选题图丢失或不可读取，请重新选择配图。')
 return warnings
}
