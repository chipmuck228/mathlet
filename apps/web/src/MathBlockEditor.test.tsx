import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { useState } from "react"
import MathBlockEditor from "./MathBlockEditor"
import { mathParts } from "@/lib/math-content"
import type { Block } from "@/lib/api"

vi.mock("./FormulaEditor", () => ({ default: ({ initial, onApply }: { initial: string; onApply: (s: string, markup: string) => void }) => <div role="dialog"><p data-testid="formula-seed">{initial}</p><button onClick={() => onApply("x^{3}", "<math><msup><mi>x</mi><mn>3</mn></msup></math>")}>测试应用</button></div> }))
beforeEach(() => { vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} }) })
afterEach(cleanup)
const block: Block = { id: "b", document_id: "d", locator: "文档块 1", text: "", preview: "", assets: [], warnings: [], verified: false, revision: 1 }

it("edits only the selected formula while retaining other choices and fractions", async () => {
  const text = String.raw`A. \(x^2\) B. \(\frac{1}{x}=2\)`
  const onChange = vi.fn()
  render(<MathBlockEditor block={block} text={text} disabled={false} onChange={onChange} onFocus={vi.fn()} />)
  fireEvent.click(screen.getByRole("button", { name: "编辑公式 x^2" }))
  await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy())
  expect(screen.getByTestId("formula-seed").textContent).toBe("x^2")
  fireEvent.click(screen.getByRole("button", { name: "测试应用" }))
  expect(onChange).toHaveBeenCalledWith(String.raw`A. \(x^{3}\) B. \(\frac{1}{x}=2\)`)
})

it("replaces selected flat tokens with an explicit formula instead of appending or guessing", async () => {
  const onChange = vi.fn()
  render(<MathBlockEditor block={block} text="B. x2+y=2" disabled={false} onChange={onChange} onFocus={vi.fn()} />)
  const input = screen.getByRole("textbox") as HTMLTextAreaElement
  input.setSelectionRange(3, 5); fireEvent.select(input)
  fireEvent.click(screen.getByRole("button", { name: "插入公式并替换选中文字" }))
  await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy())
  expect(screen.getByTestId("formula-seed").textContent).toBe("x2")
  fireEvent.click(screen.getByRole("button", { name: "测试应用" }))
  expect(onChange).toHaveBeenCalledWith(String.raw`B. \(x^{3}\)+y=2`)
})

it("inserts at a collapsed cursor without replacing the surrounding text", async () => {
  const onChange = vi.fn()
  render(<MathBlockEditor block={block} text="前文，后文。" disabled={false} onChange={onChange} onFocus={vi.fn()} />)
  const input = screen.getByRole("textbox") as HTMLTextAreaElement
  input.setSelectionRange(3, 3); fireEvent.select(input)
  const button = screen.getByRole("button", { name: "插入公式" })
  fireEvent.mouseDown(button); fireEvent.click(button)
  await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy())
  expect(screen.getByTestId("formula-seed").textContent).toBe("")
  fireEvent.click(screen.getByRole("button", { name: "测试应用" }))
  expect(onChange).toHaveBeenCalledWith(String.raw`前文，\(x^{3}\)后文。`)
})

it("retains the insertion point immediately after typing instead of falling back to the block end", async () => {
  function Controlled() {
    const [text, setText] = useState("leftRIGHT")
    return <MathBlockEditor block={block} text={text} disabled={false} onChange={setText} onFocus={vi.fn()} />
  }
  render(<Controlled />)
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "left!RIGHT", selectionStart: 5, selectionEnd: 5 } })
  fireEvent.click(screen.getByRole("button", { name: "插入公式" }))
  await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy())
  fireEvent.click(screen.getByRole("button", { name: "测试应用" }))
  expect(screen.getByRole("textbox", { name: "待核对内容 文档块 1" }).getAttribute("aria-label")).toBeTruthy()
  const values = screen.getAllByRole("textbox").map(e => (e as HTMLTextAreaElement).value)
  expect(values).toEqual(["left!", "RIGHT"])
})

it("drops obsolete cursor offsets when the whole block is replaced by an external candidate", async () => {
  const onChange = vi.fn()
  const props = { block, disabled: false, onChange, onFocus: vi.fn() }
  const { rerender } = render(<MathBlockEditor {...props} text="original text" />)
  const input = screen.getByRole("textbox") as HTMLTextAreaElement
  input.setSelectionRange(0, 8); fireEvent.select(input)
  rerender(<MathBlockEditor {...props} text="新候选" />)
  fireEvent.click(screen.getByRole("button", { name: "插入公式" }))
  await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy())
  fireEvent.click(screen.getByRole("button", { name: "测试应用" }))
  expect(onChange).toHaveBeenCalledWith(String.raw`新候选\(x^{3}\)`)
})

it("keeps text fragments on both sides of formulas and never infers powers from x2", () => {
  const parts = mathParts(String.raw`\(x^2\)`)
  expect(parts.map(p => p.type)).toEqual(["text", "math", "text"])
  expect(mathParts("x2+1x=2")).toEqual([{ type: "text", text: "x2+1x=2", start: 0, end: 7 }])
})
