export type MathPart = { type: "text"; text: string; start: number; end: number } | { type: "math"; latex: string; start: number; end: number }
export function mathParts(text: string): MathPart[] {
  const result: MathPart[] = []
  const expression = /\\\(([\s\S]*?)\\\)/g
  let at = 0
  for (const match of text.matchAll(expression)) {
    const start = match.index!
    result.push({ type: "text", text: text.slice(at, start), start: at, end: start })
    result.push({ type: "math", latex: match[1], start, end: start + match[0].length })
    at = start + match[0].length
  }
  result.push({ type: "text", text: text.slice(at), start: at, end: text.length })
  return result
}
export function putFormula(text: string, start: number, end: number, latex: string) {
  return text.slice(0, start) + "\\(" + latex + "\\)" + text.slice(end)
}
