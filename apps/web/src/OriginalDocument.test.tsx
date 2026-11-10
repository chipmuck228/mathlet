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
