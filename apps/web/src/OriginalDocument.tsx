import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
type View = { status: string; pages: number; converted: boolean; message?: string; available?: boolean; version?: string | null }
export default function OriginalDocument({ documentId, kind }: { documentId: string; kind: string }) {
  const [view, setView] = useState<View | null>(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [page, setPage] = useState(1)
  useEffect(() => {
    let alive = true
    async function load() {
      try { const result = await api<View>(`/documents/${documentId}/original-view`); if (alive) { setView(result); setError("") } }
      catch (e) { if (alive) setError(String(e)) }
    }
    void load()
    const timer = window.setInterval(() => { void load() }, 3000)
    return () => { alive = false; window.clearInterval(timer) }
  }, [documentId])
  async function generate(regenerate = false) {
    setBusy(true); setError("")
    try { setView(await api<View>(`/documents/${documentId}/original-view${regenerate ? "?regenerate=true" : ""}`, { method: "POST" })) }
    catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  const available = view?.available ?? view?.status === "ready"
  const generating = busy || ["queued", "running"].includes(view?.status || "")
  const shownPage = Math.min(page, view?.pages || 1)
  const url = `/api/documents/${documentId}/original-view.pdf${view?.version ? `?v=${view.version}` : ""}`
  return <>
    <div className="review-column-title"><h2>原始文档 · 只读</h2>
      <p>{kind === "docx" ? "由原始 DOCX 经 LibreOffice 转换的页面，独立于提取正文。字体与分页可能和 Word 有差异，存疑时请打开原件。文档块与页码不自动对应，请按题号翻页。" : "直接查看上传的原始 PDF，独立于提取正文。"}</p>
      <div className="actions"><a href={`/api/documents/${documentId}/original`}>下载原始文件</a>{available && <a href={url} target="_blank" rel="noreferrer">单独打开页面预览</a>}{kind === "docx" && available && <Button disabled={generating} onClick={() => generate(true)}>{generating ? "正在重新生成…" : "重新生成原文预览"}</Button>}</div>
    </div>
    {kind === "docx" && view?.status === "ready" && view.message && <p className="small muted">{view.message}</p>}
    {error && <p role="alert">原页预览暂不可用：{error}</p>}
    {available && view?.status !== "ready" && <p role="status">{view?.message}{view?.status === "failed" ? "；重新生成失败，保留上次预览。" : "；仍显示上次预览。"}</p>}
    {available ? <>
      <div className="actions original-pages"><label>页码 <input aria-label="原文页码" type="number" min={1} max={view!.pages} value={shownPage} onChange={e => setPage(Math.min(view!.pages, Math.max(1, Number(e.target.value) || 1)))} /></label><span>共 {view!.pages} 页</span></div>
      <iframe key={`${url}-${shownPage}`} className="original-pdf" title="原始文档页面预览" src={`${url}#page=${shownPage}`} />
      <p className="small muted">浏览器不支持内嵌 PDF 时，可单独打开或下载原件核对。</p>
    </> : <div className="original-unavailable"><p>{view?.message || (error ? "请检查服务后重试。" : "正在读取原文预览状态…")}</p>{view && !["queued", "running"].includes(view.status) && <Button disabled={busy} onClick={() => generate()}>{view.status === "failed" ? "重试生成原文预览" : "生成原文预览"}</Button>}<p className="small muted">原页生成不修改提取结果，也不会清空人工修订。DOCX 需要本机安装 LibreOffice。</p></div>}
  </>
}
