import { afterEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import OriginalDocument from "./OriginalDocument"
import { api } from "@/lib/api"
vi.mock("@/lib/api", () => ({ api: vi.fn() }))
afterEach(() => { cleanup(); vi.mocked(api).mockReset() })
it("shows the actual PDF URL and supports page navigation, not extracted HTML", async () => {
  vi.mocked(api).mockResolvedValue({ status: "ready", pages: 3, converted: true })
  render(<OriginalDocument documentId="doc" kind="docx" />)
  await waitFor(() => expect(screen.getByTitle("原始文档页面预览")).toBeTruthy())
  expect(screen.getByTitle("原始文档页面预览").getAttribute("src")).toBe("/api/documents/doc/original-view.pdf#page=1")
  fireEvent.change(screen.getByRole("spinbutton"), { target: { value: 2 } })
  expect(screen.getByTitle("原始文档页面预览").getAttribute("src")).toContain("#page=2")
})
it("shows conversion failures with a retry, without fabricating original-page evidence", async () => {
  vi.mocked(api).mockResolvedValue({ status: "failed", pages: 0, message: "未找到 LibreOffice" })
  render(<OriginalDocument documentId="doc" kind="docx" />)
  await waitFor(() => expect(screen.getByText("未找到 LibreOffice")).toBeTruthy())
  expect(screen.queryByTitle("原始文档页面预览")).toBeNull()
  vi.mocked(api).mockResolvedValueOnce({ status: "queued", pages: 0, message: "等待 Worker" })
  fireEvent.click(screen.getByRole("button", { name: "重试生成原文预览" }))
  await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledWith("/documents/doc/original-view", { method: "POST" }))
})

it("regenerates an existing preview while retaining the old PDF and showing progress", async () => {
  vi.mocked(api).mockResolvedValue({ status: "ready", available: true, pages: 2, version: "old" })
  render(<OriginalDocument documentId="doc" kind="docx" />)
  await waitFor(() => expect(screen.getByRole("button", { name: "重新生成原文预览" })).toBeTruthy())
  vi.mocked(api).mockResolvedValueOnce({ status: "queued", available: true, pages: 2, version: "old", message: "等待 Worker" })
  fireEvent.click(screen.getByRole("button", { name: "重新生成原文预览" }))
  await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledWith("/documents/doc/original-view?regenerate=true", { method: "POST" }))
  expect(screen.getByTitle("原始文档页面预览").getAttribute("src")).toContain("?v=old#page=1")
  expect((screen.getByRole("button", { name: "正在重新生成…" }) as HTMLButtonElement).disabled).toBe(true)
})
it("keeps a failed regeneration's old PDF readable and offers another attempt", async () => {
  vi.mocked(api).mockResolvedValue({ status: "failed", available: true, pages: 2, version: "old", message: "转换失败" })
  render(<OriginalDocument documentId="doc" kind="docx" />)
  await waitFor(() => expect(screen.getByRole("button", { name: "重新生成原文预览" })).toBeTruthy())
  expect(screen.getByTitle("原始文档页面预览")).toBeTruthy()
  expect(screen.getByText(/重新生成失败，保留上次预览/)).toBeTruthy()
})
