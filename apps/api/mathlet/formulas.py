"""Structured Office Math extraction and a deliberately bounded LaTeX renderer."""
import html
import re
from lxml import etree as ET
from latex2mathml.converter import convert

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
UNSUPPORTED = "【未转换公式，请对照原件并替换】"
COMMANDS = set("frac dfrac tfrac sqrt left right cdot times div pm mp le ge ne leq geq neq lt gt approx equiv sim simeq cong parallel perp in notin subset supset cup cap emptyset infty pi alpha beta gamma theta lambda mu sigma omega Delta angle triangle circ degree sin cos tan log ln text mathrm mathbf mathbb odot overline underline vec hat bar begin end quad qquad space limits sum prod int displaystyle textstyle ldots cdots dots lvert rvert vert lbrace rbrace lbrack rbrack langle rangle percent".split())


def render_latex(latex: str) -> str:
    if not latex.strip() or len(latex) > 6000:
        raise ValueError("公式不能为空或超过6000字符")
    if latex.lstrip().startswith(("^", "_")) or re.search(r"[\^_]\s*(?:$|[+=<>])", latex):
        raise ValueError("上下标缺少底数或内容")
    if re.search(r"\\(?![A-Za-z]|[\\ ,;:!{}|_%#])", latex):
        raise ValueError("包含不支持的转义，请检查公式")
    unknown = set(re.findall(r"\\([A-Za-z]+)", latex)) - COMMANDS
    if unknown:
        raise ValueError("暂不支持的公式命令：" + ", ".join(sorted(unknown)))
    depth = 0
    for char in re.sub(r"\\[{}]", "", latex):
        if char == "{": depth += 1
        if char == "}": depth -= 1
        if depth < 0 or depth > 40: raise ValueError("公式括号不匹配或嵌套过深")
    if depth or re.search(r"\{\s*\}", latex):
        raise ValueError("公式存在不匹配或未填写的花括号")
    environments = re.findall(r"\\(?:begin|end)\{([^}]+)\}", latex)
    if any(e not in {"cases", "matrix", "pmatrix", "bmatrix", "aligned"} for e in environments):
        raise ValueError("暂不支持该公式环境")
    try:
        result = convert(latex)
        root = ET.fromstring(result.encode(), ET.XMLParser(resolve_entities=False, no_network=True))
        # Strictly remove links, events and non-MathML output, even if a converter changes.
        for element in root.iter():
            if ET.QName(element).namespace != "http://www.w3.org/1998/Math/MathML":
                raise ValueError("公式渲染包含非法节点")
            for key in list(element.attrib):
                if key not in {"display", "mathvariant", "stretchy", "fence", "form", "separator", "accent", "accentunder", "columnalign", "rowalign", "columnspacing", "rowspacing", "linethickness", "notation", "width", "height", "depth", "lspace", "rspace", "symmetric", "movablelimits"}:
                    del element.attrib[key]
        return ET.tostring(root, encoding="unicode")
    except Exception as exc:
        raise ValueError("公式不能完整渲染，请检查分式、括号和上下标") from exc


def parts_from_text(text: str, strict=False):
    """Text is an explicit serialization, never flattened mathematical tokens."""
    parts = []
    at = 0
    while at < len(text):
        start = text.find(r"\(", at)
        if start == -1:
            tail = text[at:]
            if strict and r"\)" in tail: raise ValueError("公式结束标记没有对应开始标记")
            parts.append({"type": "text", "text": tail}); break
        if start > at: parts.append({"type": "text", "text": text[at:start]})
        end = text.find(r"\)", start + 2)
        if end == -1:
            if strict: raise ValueError("公式缺少结束标记")
            parts.append({"type": "text", "text": text[start:]}); break
        latex = text[start + 2:end]
        try:
            markup = render_latex(latex)
            parts.append({"type": "math", "latex": latex, "mathml": markup, "error": None})
        except ValueError as exc:
            if strict: raise
            parts.append({"type": "math", "latex": latex, "mathml": "", "error": str(exc)})
        at = end + 2
    return parts or [{"type": "text", "text": ""}]


def render_text(text):
    result = []
    for part in parts_from_text(text):
        if part["type"] == "text": result.append(html.escape(part["text"]))
        elif not part["error"]: result.append(part["mathml"])
        else: result.append('<span class="formula-error">' + html.escape(r"\(" + part["latex"] + r"\)") + " [公式待修正]</span>")
    return "".join(result)


def omml_to_latex(node):
    tag = ET.QName(node).localname
    def child(name):
        return next((c for c in node if ET.QName(c).localname == name), None)
    def arg(name):
        c = child(name)
        if c is None: raise ValueError("公式缺少参数")
        return omml_to_latex(c)
    if tag.endswith("Pr"): return ""
    if tag == "t":
        text = node.text or ""
        if any(c in text for c in "\\^_"):
            raise ValueError("文字运行中的转义或上下标符号需人工核对")
        replacements = {"{": r"\{", "}": r"\}", "%": r"\%", "#": r"\#", "−": "-", "×": r"\times ", "÷": r"\div ", "≤": r"\leq ", "≥": r"\geq ", "≠": r"\neq ", "π": r"\pi ", "±": r"\pm ", "∞": r"\infty ", "θ": r"\theta ", "α": r"\alpha ", "β": r"\beta ", "∠": r"\angle ", "⊥": r"\perp ", "∥": r"\parallel "}
        return "".join(replacements.get(c, c) for c in text)
    if tag in {"oMath", "oMathPara", "r", "e", "num", "den", "sub", "sup", "deg", "lim", "fName"}:
        return "".join(omml_to_latex(c) for c in node)
    if tag == "f": return r"\frac{" + arg("num") + "}{" + arg("den") + "}"
    if tag == "sSup": return "{" + arg("e") + "}^{" + arg("sup") + "}"
    if tag == "sSub": return "{" + arg("e") + "}_{" + arg("sub") + "}"
    if tag == "sSubSup": return "{" + arg("e") + "}_{" + arg("sub") + "}^{" + arg("sup") + "}"
    if tag == "rad":
        degree = arg("deg") if child("deg") is not None else ""
        return r"\sqrt" + ("[" + degree + "]" if degree else "") + "{" + arg("e") + "}"
    if tag == "d":
        prop = child("dPr")
        def delim(name, default):
            element = prop.find(f"{{{M}}}{name}") if prop is not None else None
            value = element.get(f"{{{M}}}val", default) if element is not None else default
            if value not in {"", "(", ")", "[", "]", "{", "}", "|"}: raise ValueError("不支持的分隔符")
            return {"": ".", "{": r"\{", "}": r"\}"}.get(value, value)
        values = [omml_to_latex(c) for c in node if ET.QName(c).localname == "e"]
        if len(values) != 1: raise ValueError("多参数分隔结构需要人工处理")
        return r"\left" + delim("begChr", "(") + values[0] + r"\right" + delim("endChr", ")")
    if tag == "func":
        name = arg("fName")
        return ("\\" + name + " " if name in {"sin", "cos", "tan", "log", "ln"} else name) + arg("e")
    if tag == "eqArr":
        values = [omml_to_latex(c) for c in node if ET.QName(c).localname == "e"]
        return r"\begin{aligned}" + r"\\".join(values) + r"\end{aligned}"
    if tag == "bar": return r"\overline{" + arg("e") + "}"
    raise ValueError(f"暂不支持的 Office Math 结构 {tag}")


def structured_docx(node):
    """Preserve paragraphs, table boundaries, superscript runs and math order."""
    parts = []
    def add_text(text):
        if parts and parts[-1]["type"] == "text": parts[-1]["text"] += text
        else: parts.append({"type": "text", "text": text})
    def walk(n):
        tag = ET.QName(n).localname
        if tag == "oMath":
            try:
                latex = omml_to_latex(n)
                render_latex(latex)
                parts.append({"type": "math", "latex": latex, "supported": True})
            except ValueError:
                parts.append({"type": "unsupported", "text": UNSUPPORTED,
                              "original_xml": ET.tostring(n, encoding="unicode"), "supported": False})
            return
        if tag == "r" and ET.QName(n).namespace == W:
            vert = n.find(f"{{{W}}}rPr/{{{W}}}vertAlign")
            text = "".join(n.xpath(".//w:t/text()", namespaces={"w": W}))
            if vert is not None and vert.get(f"{{{W}}}val") in {"superscript", "subscript"}:
                # Baseline lives in the preceding run, so never guess its scope.
                add_text(f"【{vert.get(f'{{{W}}}val')}：{text}，请合并核对】")
                return
        if tag == "t": add_text(n.text or ""); return
        if tag in {"tab"}: add_text("\t"); return
        if tag in {"br", "cr"}: add_text("\n"); return
        if tag.endswith("Pr"): return
        for c in n: walk(c)
        if tag == "p": add_text("\n")
        if tag == "tc": add_text("\t")
    walk(node)
    text = "".join(r"\(" + p["latex"] + r"\)" if p["type"] == "math" else p["text"] for p in parts).strip()
    return text, parts
