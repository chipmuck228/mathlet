import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import MathBlockEditor from "./MathBlockEditor"
import { mathParts } from "@/lib/math-content"
import type { Block } from "@/lib/api"

vi.mock("./FormulaEditor", () => ({ default: ({ initial, onApply }: { initial: string; onApply: (s: string, markup: string) => void }) => <div role="dialog"><p>{initial}</p><button onClick={() => onApply("x^{3}", "<math><msup><mi>x</mi><mn>3</mn></msup></math>")}>测试应用</button></div> }))
beforeEach(() => { vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} }) })
afterEach(cleanup)
const block: Block = { id: "b", document_id: "d", locator: "文档块 1", text: "", preview: "", assets: [], warnings: [], verified: false, revision: 1 }

it("edits only the selected formula while retaining other choices and fractions", async () => {
  const text = String.raw`A. \(x^2\) B. \(\frac{1}{x}=2\)`
  const onChange = vi.fn()
  render(<MathBlockEditor block={block} text={text} disabled={false} onChange={onChange} onFocus={vi.fn()} />)
  fireEvent.click(screen.getByRole("button", { name: "编辑公式 x^2" }))
  await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy())
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
  fireEvent.click(screen.getByRole("button", { name: "测试应用" }))
  expect(onChange).toHaveBeenCalledWith(String.raw`B. \(x^{3}\)+y=2`)
})

it("keeps text fragments on both sides of formulas and never infers powers from x2", () => {
  const parts = mathParts(String.raw`\(x^2\)`)
  expect(parts.map(p => p.type)).toEqual(["text", "math", "text"])
  expect(mathParts("x2+1x=2")).toEqual([{ type: "text", text: "x2+1x=2", start: 0, end: 7 }])
})
