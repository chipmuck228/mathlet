import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import FormulaEditor from "./FormulaEditor"
import { api } from "@/lib/api"

vi.mock("mathlive", () => {
  class TestField extends HTMLElement {
    static fontsDirectory: string | null = null
    static soundsDirectory: string | null = null
    static computeEngine = null
    value = ""
    mathVirtualKeyboardPolicy = "auto"
    insert(text: string) { this.value += text }
  }
  customElements.define("test-formula-field", TestField)
  return { MathfieldElement: TestField }
})
vi.mock("@/lib/api", () => ({ api: vi.fn(), json: (method: string, body: unknown) => ({ method, body: JSON.stringify(body) }) }))
beforeEach(() => { vi.mocked(api).mockReset() })
afterEach(cleanup)

it("prefills the original formula and inserts a template only at the LaTeX selection", async () => {
  const onApply = vi.fn()
  vi.mocked(api).mockImplementation(async (_path, init) => ({ latex: JSON.parse(init!.body as string).latex, mathml: "<math/>" }))
  render(<FormulaEditor initial="x+1=2" onApply={onApply} onClose={vi.fn()} />)
  const input = screen.getByLabelText("LaTeX 输入（与可视化编辑同步）") as HTMLTextAreaElement
  expect(input.value).toBe("x+1=2")
  await waitFor(() => expect((screen.getByRole("button", { name: "插入分式" }) as HTMLButtonElement).disabled).toBe(false))
  input.focus(); fireEvent.focus(input); input.setSelectionRange(2, 3)
  const button = screen.getByRole("button", { name: "插入分式" })
  fireEvent.mouseDown(button); fireEvent.click(button)
  expect(input.value).toBe(String.raw`x+\frac{1}{x}=2`)
  fireEvent.click(screen.getByRole("button", { name: "应用公式" }))
  await waitFor(() => expect(onApply).toHaveBeenCalledWith(String.raw`x+\frac{1}{x}=2`, "<math/>"))
})

it("starts a new insertion empty and cancellation does not modify the original formula", () => {
  const onApply = vi.fn(), onClose = vi.fn()
  render(<FormulaEditor initial="" onApply={onApply} onClose={onClose} />)
  expect((screen.getByLabelText("LaTeX 输入（与可视化编辑同步）") as HTMLTextAreaElement).value).toBe("")
  expect((screen.getByRole("button", { name: "应用公式" }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole("button", { name: "取消" }))
  expect(onClose).toHaveBeenCalledOnce()
  expect(onApply).not.toHaveBeenCalled()
})
