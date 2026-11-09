import { afterEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import MathBlockEditor from "./MathBlockEditor"
import type { Block } from "@/lib/api"
vi.mock("./FormulaEditor", () => ({ default: ({ initial, onApply }: { initial: string; onApply: (s: string, markup: string) => void }) => <div><p data-testid="formula-seed">{initial}</p><button onClick={() => onApply("x^{2}", "<math><mi>x</mi></math>")}>测试应用</button></div> }))
afterEach(cleanup)
const block: Block = { id: "b", document_id: "d", locator: "文档块 1", text: "", preview: "", assets: [], warnings: [], verified: false, revision: 1 }
function setup(text: string) {
 const onChange = vi.fn()
 render(<MathBlockEditor block={block} text={text} disabled={false} onChange={onChange} onFocus={vi.fn()} />)
 fireEvent.click(screen.getByRole("button", { name: "插入公式" }))
 return { onChange, input: screen.getByRole("textbox", { name: "完整正文" }) as HTMLTextAreaElement }
}
it("loads all existing text and formulas, not an empty formula field", () => {
 const text = String.raw`A. x2+y=2 B. \(\frac{1}{x}=2\)`
 const { input, onChange } = setup(text)
 expect(input.value).toBe(text)
 fireEvent.click(screen.getByRole("button", { name: "取消修改" }))
 expect(onChange).not.toHaveBeenCalled()
})
it("replaces a selected fragment within full text and applies only on confirmation", async () => {
 const { input, onChange } = setup("A. x2+y=2 B. x+1=2")
 input.setSelectionRange(3,5)
 fireEvent.click(screen.getByRole("button", { name: "编辑选区公式／在光标处新增" }))
 await waitFor(() => expect(screen.getByTestId("formula-seed").textContent).toBe("x2"))
 fireEvent.click(screen.getByRole("button", { name: "测试应用" }))
 expect(input.value).toBe(String.raw`A. \(x^{2}\)+y=2 B. x+1=2`)
 expect(onChange).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole("button", { name: "应用完整内容" }))
 expect(onChange).toHaveBeenCalledWith(input.value)
})
it("edits existing formulas in context without fragmenting the main reading view", async () => {
 const text = String.raw`前文 \(x^3\) 后文 \(1/x\)`
 const { input } = setup(text)
 fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "编辑公式 x^3" }))
 await waitFor(() => expect(screen.getByTestId("formula-seed").textContent).toBe("x^3"))
 fireEvent.click(screen.getByRole("button", { name: "测试应用" }))
 expect(input.value).toBe(String.raw`前文 \(x^{2}\) 后文 \(1/x\)`)
})
it("allows direct full-text revisions while retaining formula boundaries", () => {
 const { input, onChange } = setup("原文")
 const next = String.raw`修订 \(x^2+1=2\) 完整条件`
 fireEvent.change(input, { target: { value: next } })
 fireEvent.click(screen.getByRole("button", { name: "应用完整内容" }))
 expect(onChange).toHaveBeenCalledWith(next)
})
