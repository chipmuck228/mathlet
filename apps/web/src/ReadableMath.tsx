import { useEffect, useState } from "react"
import { api, json, type FormulaPart } from "@/lib/api"

// Only explicit delimiters are interpreted; ordinary prose is never guessed as math.
const expression = /\\\(([\s\S]*?)\\\)|\\\[([\s\S]*?)\\\]|\$\$([\s\S]*?)\$\$|(?<![\\$])\$(?!\$)([^\n$]+?)(?<!\\)\$(?!\$)/g
function Formula({ latex, markup }: { latex: string; markup?: string }) {
  const [result,setResult]=useState<{latex:string;markup?:string;error?:string}>({latex,markup})
  useEffect(()=>{
    if(markup){setResult({latex,markup});return}
    let alive=true
    setResult({latex})
    void api<{mathml:string}>("/formulas/preview",json("POST",{latex})).then(value=>{if(alive)setResult({latex,markup:value.mathml})}).catch(()=>{if(alive)setResult({latex,error:"公式暂无法显示，请编辑核查"})})
    return()=>{alive=false}
  },[latex,markup])
  const current=result.latex===latex?result:{latex}
  return <span className="reading-formula">{current.markup?<span dangerouslySetInnerHTML={{__html:current.markup}}/>:<span>{current.error||"公式加载中…"}<code>{latex}</code></span>}</span>
}
export default function ReadableMath({ text, formula=false, content }: { text:string; formula?:boolean; content?:FormulaPart[] }) {
  if(formula)return text.trim()?<Formula latex={text} markup={content?.find(p=>p.type==="math"&&p.latex===text)?.mathml}/>:<span className="muted">未填写</span>
  const parts=[];let at=0
  for(const match of text.matchAll(expression)){
    const index=match.index!;const latex=match[1]??match[2]??match[3]??match[4]
    parts.push(<span key={`t${index}`}>{text.slice(at,index)}</span>)
    parts.push(<Formula key={`m${index}`} latex={latex} markup={content?.find(p=>p.type==="math"&&p.latex===latex)?.mathml}/>)
    at=index+match[0].length
  }
  parts.push(<span key="tail">{text.slice(at)}</span>)
  return <span className="readable-math">{parts}</span>
}
