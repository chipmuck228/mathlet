import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import ContinuousReview from "./ContinuousReview"
import { api, type Block } from "@/lib/api"

vi.mock("@/lib/api", () => ({ api: vi.fn(), json: (method: string, body: unknown) => ({ method, body: JSON.stringify(body) }) }))

const blocks: Block[] = [1, 2, 3].map(i => ({ id: `b${i}`, document_id: "d", locator: `文档块 ${i}`, text: `题目${i}`, preview: `<p>原文${i}</p>`, assets: [], warnings: [], verified: false, revision: 1 }))
beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} })
  Element.prototype.scrollIntoView = vi.fn()
  vi.mocked(api).mockReset()
})
afterEach(cleanup)

describe("continuous source review", () => {
  it("shows every editable block and keeps the full document when searching", () => {
    render(<ContinuousReview blocks={blocks} documentId="d" kind="docx" focusId="" onSaved={vi.fn()} onDirtyChange={vi.fn()} />)
    for (const b of blocks) expect(screen.getByRole("textbox", { name: `待核对内容 ${b.locator}` })).toBeTruthy()
    fireEvent.change(screen.getByRole("textbox", { name: "查找连续内容" }), { target: { value: "题目2" } })
    fireEvent.click(screen.getByRole("button", { name: "定位下一处" }))
    for (const b of blocks) expect(screen.getByRole("textbox", { name: `待核对内容 ${b.locator}` })).toBeTruthy()
    expect(screen.getByText(/并非 Word 原页渲染/)).toBeTruthy()
    expect(vi.mocked(api)).not.toHaveBeenCalled()
  })

  it("saves only edits without approval and confirms only the selected scope", async () => {
    vi.mocked(api).mockResolvedValueOnce([{ ...blocks[0], text: "修正题一", revision: 2 }])
    const onDirty = vi.fn()
    render(<ContinuousReview blocks={blocks} documentId="d" kind="docx" focusId="" onSaved={vi.fn()} onDirtyChange={onDirty} />)
    fireEvent.change(screen.getByRole("textbox", { name: "待核对内容 文档块 1" }), { target: { value: "修正题一" } })
    fireEvent.click(screen.getByRole("button", { name: "保存修改（1）" }))
    await waitFor(() => expect(screen.getByText(/已保存 1 处修改/)).toBeTruthy())
    const save = JSON.parse(vi.mocked(api).mock.calls[0][1]!.body as string)
    expect(save.changes).toEqual([{ id: "b1", revision: 1, text: "修正题一", verified: false }])
    vi.mocked(api).mockResolvedValueOnce([{ ...blocks[1], revision: 2, verified: true }])
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 文档块 2" }))
    fireEvent.click(screen.getByRole("button", { name: "保存并确认选中内容" }))
    await waitFor(() => expect(screen.getByText(/已保存并确认选中的 1 个/)).toBeTruthy())
    const confirmation = JSON.parse(vi.mocked(api).mock.calls[1][1]!.body as string)
    expect(confirmation.changes).toEqual([{ id: "b2", revision: 1, text: "题目2", verified: true }])
    expect(onDirty).toHaveBeenCalledWith(false)
  })

  it("keeps edits after a conflict instead of replacing them with stale server text", async () => {
    vi.mocked(api).mockRejectedValue(new Error("内容已变化"))
    render(<ContinuousReview blocks={blocks} documentId="d" kind="pdf" focusId="" onSaved={vi.fn()} onDirtyChange={vi.fn()} />)
    const input = screen.getByRole("textbox", { name: "待核对内容 文档块 1" }) as HTMLTextAreaElement
    fireEvent.change(input, { target: { value: "不能丢失的修改" } })
    fireEvent.click(screen.getByRole("button", { name: "保存修改（1）" }))
    await waitFor(() => expect(screen.getByText(/本地修改已保留/)).toBeTruthy())
    expect(input.value).toBe("不能丢失的修改")
    expect(screen.getByText("原始 PDF 页面")).toBeTruthy()
  })
})
