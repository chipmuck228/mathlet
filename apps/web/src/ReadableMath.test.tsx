import { afterEach, expect, it, vi } from "vitest"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import ReadableMath from "./ReadableMath"
import { api } from "@/lib/api"
vi.mock("@/lib/api",()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)})}))
afterEach(()=>{cleanup();vi.mocked(api).mockReset()})
it("uses saved MathML while leaving prose and HTML-like text literal",()=>{
 const {container}=render(<ReadableMath text={String.raw`条件 <script>bad</script>，\(x^2\)`} content={[{type:"math",latex:"x^2",mathml:'<math><msup><mi>x</mi><mn>2</mn></msup></math>'}]}/> )
 expect(container.querySelector('msup')).toBeTruthy()
 expect(container.querySelector('script')).toBeNull()
 expect(container.textContent).toContain('<script>bad</script>')
 expect(api).not.toHaveBeenCalled()
})
it("renders explicit alternate delimiters and updates unsaved core formulas",async()=>{
 vi.mocked(api).mockImplementation(async(_path,init)=>({mathml:`<math><mi>${JSON.parse(init!.body as string).latex==='x^2'?'x':'y'}</mi></math>`}))
 const {container,rerender}=render(<ReadableMath text={String.raw`例：$x^2$ 与 \[y\]`}/>)
 await waitFor(()=>expect(container.querySelectorAll('math').length).toBe(2))
 rerender(<ReadableMath text="y" formula/>)
 await waitFor(()=>expect(container.querySelector('math')?.textContent).toBe('y'))
})
it("preserves source with an explicit warning on unsupported syntax",async()=>{
 vi.mocked(api).mockRejectedValue(new Error('unsupported'))
 render(<ReadableMath text={String.raw`\unknown{x}`} formula/>)
 await waitFor(()=>expect(screen.getByText(/公式暂无法显示/)).toBeTruthy())
 expect(screen.getByText(String.raw`\unknown{x}`)).toBeTruthy()
})
