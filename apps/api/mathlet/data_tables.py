"""Bounded, rectangular question tables. Cell math uses existing LaTeX rendering."""
import html
import re
from pathlib import Path
from zipfile import ZipFile,BadZipFile
from lxml import etree as ET
from pydantic import BaseModel,ConfigDict,Field,model_validator
from .formulas import structured_docx

class DataTable(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=False)
    key:str=Field(min_length=1,max_length=80)
    caption:str=Field(default='',max_length=300)
    header_rows:int=Field(default=1,ge=0,le=60)
    rows:list[list[str]]=Field(min_length=1,max_length=60)
    source_block_ids:list[str]=Field(default_factory=list,max_length=30)
    source_note:str=Field(default='',max_length=2000)
    @model_validator(mode='after')
    def grid(self):
        width=len(self.rows[0])
        if not 1<=width<=20 or any(len(r)!=width for r in self.rows):raise ValueError('表格须有1—20列，每行列数一致')
        if self.header_rows>len(self.rows):raise ValueError('表头行数不能超过表格行数')
        if any(len(cell)>2000 for r in self.rows for cell in r) or sum(len(cell) for r in self.rows for cell in r)>60000:raise ValueError('表格单元格超过2000字或整表超过60000字')
        return self


def checked_tables(tables):
    if len(tables)>10:raise ValueError('每题最多10张数据表')
    values=[DataTable.model_validate(t).model_dump() for t in tables]
    if len({t['key'] for t in values})!=len(values):raise ValueError('同一题的表格编号不能重复')
    return values


def table_text(tables):
    return '\n\n'.join(('表格：'+t.get('caption','')+'\n'+'\n'.join('\t'.join(r) for r in t['rows'])).strip() for t in tables)


def table_html(tables):
    from .reader_text import render_reader_text
    parts=[]
    for t in checked_tables(tables):
        head=t['header_rows'];rows=[]
        for index,r in enumerate(t['rows']):
            tag='th' if index<head else 'td'
            rows.append('<tr>'+''.join('<'+tag+(' scope="col"' if tag=='th' else '')+'>'+render_reader_text(c)+'</'+tag+'>' for c in r)+'</tr>')
        caption='<caption>'+html.escape(t['caption'])+'</caption>' if t['caption'] else ''
        parts.append('<div class="question-table-wrap"><table class="question-data-table">'+caption+('<thead>'+''.join(rows[:head])+'</thead>' if head else '')+'<tbody>'+''.join(rows[head:])+'</tbody></table></div>')
    return ''.join(parts)

TABLE_CSS='''.question-table-wrap{max-width:100%;overflow-x:auto;margin:16px 0}.question-data-table{width:100%;border-collapse:collapse;font-size:15px}.question-data-table caption{text-align:left;font-weight:600;margin-bottom:8px}.question-data-table th,.question-data-table td{border:1px solid #aebbb3;padding:8px 12px;text-align:center;white-space:pre-wrap;overflow-wrap:anywhere}.question-data-table th{background:#edf3ed;font-weight:600}.question-data-table math{overflow:visible;max-width:none}@media print{.question-table-wrap{overflow:visible}.question-data-table{font-size:12px}.question-data-table thead{display:table-header-group}.question-data-table tr{break-inside:avoid}}'''


def docx_tables(path):
    """Read native top-level tables. Layout/nested/oversized tables remain source text."""
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'};w='{'+ns['w']+'}'
    result={}
    try:
        with ZipFile(path) as z:
            info=z.getinfo('word/document.xml')
            if info.file_size>50*1024*1024:return result
            root=ET.fromstring(z.read(info),ET.XMLParser(resolve_entities=False,no_network=True))
        for ordinal,node in enumerate(root.find('w:body',ns)):
            if node.tag!=w+'tbl' or node.findall('.//w:tbl',ns):continue
            rows=[];merged=False;previous=[]
            for tr in node.findall('w:tr',ns):
                before=tr.find('w:trPr/w:gridBefore',ns);cells=['']*(int(before.get(w+'val','0')) if before is not None else 0)
                for tc in tr.findall('w:tc',ns):
                    span=tc.find('w:tcPr/w:gridSpan',ns);count=int(span.get(w+'val','1')) if span is not None else 1
                    if not 1<=count<=20:raise ValueError('复杂表格')
                    value=structured_docx(tc)[0].strip();vertical=tc.find('w:tcPr/w:vMerge',ns)
                    if vertical is not None and vertical.get(w+'val')!='restart':value=previous[len(cells)] if len(previous)>len(cells) else value
                    merged=merged or count>1 or vertical is not None
                    cells.extend([value]*count)
                rows.append(cells);previous=cells
            width=max((len(r) for r in rows),default=0)
            if len(rows)<2 or width<2 or width>20 or len(rows)>60 or any(len(c)>300 for r in rows for c in r):continue
            rows=[r+['']*(width-len(r)) for r in rows]
            # A native table is a source hint, not a teacher-reviewed transcription.
            note='DOCX原生表格；需核对表头、数据与空白。'
            if merged:note+='合并单元格已按网格展开并重复对应文字，请核对表头归属。'
            result[ordinal]=DataTable(key='native-'+str(ordinal),rows=rows,source_note=note).model_dump()
    except (OSError,KeyError,ValueError,BadZipFile,ET.XMLSyntaxError,TypeError):
        # Existing original text is never discarded when native recovery fails.
        return result
    return result


def tabular_text(text):
    """Only unambiguous tab-separated rectangular runs; never infer spaced PDF columns."""
    lines=text.splitlines(keepends=True);tables=[];out=[];at=0
    while at<len(lines):
        if '\t' not in lines[at].rstrip('\r\n'):out.append(lines[at]);at+=1;continue
        end=at
        while end<len(lines) and '\t' in lines[end].rstrip('\r\n'):end+=1
        run=lines[at:end];rows=[line.rstrip('\r\n').split('\t') for line in run]
        if len(rows)>=2 and len({len(r) for r in rows})==1 and 2<=len(rows[0])<=20 and len(rows)<=60:
            try:table=DataTable(key='text-'+str(len(tables)+1),rows=rows,source_note='由连续制表符行列整理，请核对数据对应。').model_dump()
            except ValueError:out.extend(run)
            else:tables.append(table)
        else:out.extend(run)
        at=end
    remaining=''.join(out).strip()
    return (remaining,tables) if remaining and len(tables)<=10 else (text,[])
