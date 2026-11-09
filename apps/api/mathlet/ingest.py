"""Conservative extraction: unsupported equations stay reviewable, never guessed."""
import html
import io
import json
import posixpath
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from lxml import etree as ET
from PIL import Image
from pypdf import PdfReader
import pypdfium2 as pdfium

from .db import uid

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "m": "http://schemas.openxmlformats.org/officeDocument/2006/math"}
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MAX_UNPACKED = 150 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 25_000_000


def local(node):
    return ET.QName(node).localname


def mathml(node):
    """Return (safe MathML, complete). No raw XML/HTML is passed through."""
    tag = local(node)
    if tag.endswith("Pr"):
        return "", True
    if tag == "t":
        return "<mtext>" + html.escape(node.text or "") + "</mtext>", True
    values = [mathml(c) for c in node]
    inner = "".join(v[0] for v in values)
    complete = all(v[1] for v in values)
    if tag in {"oMath", "r", "e", "num", "den", "sub", "sup", "deg"}:
        return "<mrow>" + inner + "</mrow>", complete
    if tag in {"f", "sSup", "sSub", "sSubSup"}:
        names = {"f": ("num", "den"), "sSup": ("e", "sup"),
                 "sSub": ("e", "sub"), "sSubSup": ("e", "sub", "sup")}[tag]
        children = [next((c for c in node if local(c) == name), None) for name in names]
        if any(c is None for c in children):
            return inner, False
        items = [mathml(c) for c in children]
        out = {"f": "mfrac", "sSup": "msup", "sSub": "msub", "sSubSup": "msubsup"}[tag]
        return f"<{out}>" + "".join(v[0] for v in items) + f"</{out}>", complete
    if tag == "rad":
        e = next((c for c in node if local(c) == "e"), None)
        deg = next((c for c in node if local(c) == "deg"), None)
        value = mathml(e)[0] if e is not None else "<mrow/>"
        if deg is not None and "".join(deg.itertext()).strip():
            return "<mroot>" + value + mathml(deg)[0] + "</mroot>", complete
        return "<msqrt>" + value + "</msqrt>", complete
    # Delimiters, matrices, systems and accents need a richer converter.
    # Their token text remains available; no fake parentheses are invented.
    return inner, False


def extract_docx(path: Path, assets_dir: Path):
    parser = ET.XMLParser(resolve_entities=False, no_network=True)
    try:
        z = ZipFile(path)
    except BadZipFile as e:
        raise ValueError("不是有效的 DOCX 文件") from e
    with z:
        if sum(i.file_size for i in z.infolist()) > MAX_UNPACKED:
            raise ValueError("DOCX 解压后过大，请拆分文件")
        root = ET.fromstring(z.read("word/document.xml"), parser)
        rels = ET.fromstring(z.read("word/_rels/document.xml.rels"), parser) if "word/_rels/document.xml.rels" in z.namelist() else []
        relations = {r.get("Id"): posixpath.normpath("word/" + r.get("Target", ""))
                     for r in rels if r.get("TargetMode") != "External"}
        for ordinal, node in enumerate(root.find("w:body", NS)):
            if local(node) == "sectPr":
                continue
            warnings = {"需对照原件核对公式、条件及图题对应；此处不是原页渲染"}
            assets = []
            text = "".join(node.xpath(".//w:t/text() | .//m:t/text()", namespaces=NS))

            def render(n):
                tag = local(n)
                if tag == "oMath":
                    value, complete = mathml(n)
                    if not complete:
                        warnings.add("含暂不支持完整转换的公式结构；必须打开 Word 原件核对")
                    return '<math xmlns="http://www.w3.org/1998/Math/MathML">' + value + "</math>"
                if tag == "t":
                    return html.escape(n.text or "")
                if tag in {"blip", "imagedata"}:
                    rid = n.get("{" + REL + "}embed") or n.get("{" + REL + "}id")
                    target = relations.get(rid, "")
                    if not target.startswith("word/media/") or target not in z.namelist():
                        warnings.add("图形对象未能提取，请核对原件")
                        return ""
                    try:
                        with Image.open(io.BytesIO(z.read(target))) as image:
                            image.load()
                            filename = uid() + ".png"
                            image.convert("RGBA").save(assets_dir / filename)
                            assets.append(filename)
                    except Exception:
                        warnings.add("图片格式暂不支持，请对照原件")
                    return ""
                if tag.endswith("Pr"):
                    return ""
                inside = "".join(render(c) for c in n)
                if tag in {"tbl", "tr", "tc", "p"}:
                    out = {"tbl": "table", "tr": "tr", "tc": "td", "p": "p"}[tag]
                    return f"<{out}>" + inside + f"</{out}>"
                return inside

            preview = render(node)
            if text.strip() or assets:
                yield dict(id=uid(), ordinal=ordinal, locator=f"文档块 {ordinal + 1}", text=text,
                           preview=preview, assets=assets, warnings=sorted(warnings))


def extract_pdf(path: Path, assets_dir: Path):
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ValueError("暂不支持加密 PDF，请提供未加密副本")
    if len(reader.pages) > 120:
        raise ValueError("单份 PDF 最多120页，请拆分后导入")
    pdf = pdfium.PdfDocument(str(path))
    try:
        for index, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            p = pdf[index]
            try:
                width, height = p.get_size()
                scale = min(1.7, 2000 / max(width, height))
                bitmap = p.render(scale=scale)
                try:
                    filename = uid() + ".png"
                    bitmap.to_pil().save(assets_dir / filename)
                finally:
                    bitmap.close()
            finally:
                p.close()
            warnings = ["PDF 按页导入，尚未自动分题；公式与表格的文本顺序需对照页面核对"]
            if not text.strip():
                warnings.append("未提取到文字，可能是扫描页；本版无 OCR，请人工补录")
            yield dict(id=uid(), ordinal=index, locator=f"第 {index + 1} 页", text=text,
                       preview="<p>" + html.escape(text).replace("\n", "<br>") + "</p>",
                       assets=[filename], warnings=warnings)
    finally:
        pdf.close()


def extract(path: Path, kind: str, assets_dir: Path):
    assets_dir.mkdir(parents=True, exist_ok=True)
    return list(extract_docx(path, assets_dir) if kind == "docx" else extract_pdf(path, assets_dir))
