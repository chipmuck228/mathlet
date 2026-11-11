import io
from zipfile import ZipFile
import pytest
from fastapi.testclient import TestClient
from mathlet.main import app
from mathlet.db import connect, init_db
from mathlet.worker import run_one
from mathlet.formulas import render_latex, parts_from_text


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('MATHLET_DATA_DIR', str(tmp_path))
    with TestClient(app) as c: yield c


def upload(client):
    m='m:'
    power='<m:sSup><m:e><m:r><m:t>x</m:t></m:r></m:e><m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSup>'
    fraction='<m:f><m:num><m:r><m:t>1</m:t></m:r></m:num><m:den><m:r><m:t>x</m:t></m:r></m:den></m:f>'
    expressions=['<m:r><m:t>x+2=1</m:t></m:r>',power+'<m:r><m:t>+y=2</m:t></m:r>', '<m:r><m:t>2</m:t></m:r>'+power+'<m:r><m:t>+x=1</m:t></m:r>',power+'<m:r><m:t>+</m:t></m:r>'+fraction+'<m:r><m:t>=2</m:t></m:r>']
    xml='<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><w:body><w:p>'
    for label,e in zip('ABCD',expressions): xml+=f'<w:r><w:t>{label}. </w:t></w:r><m:oMath>{e}</m:oMath><w:r><w:tab/></w:r>'
    xml+='</w:p></w:body></w:document>'
    b=io.BytesIO()
    with ZipFile(b,'w') as z:z.writestr('word/document.xml',xml)
    r=client.post('/api/documents',files={'file':('math.docx',b.getvalue())});assert r.status_code==201
    assert run_one();doc=r.json()['id']
    return doc,client.get(f'/api/documents/{doc}/blocks').json()[0]


def test_import_visual_edit_save_and_offline_export_round_trip(client):
    doc,block=upload(client)
    assert r'\frac{1}{x}' in block['text'] and '^{2}' in block['text']
    math=[p for p in block['content'] if p['type']=='math']
    assert len(math)==4 and '<mfrac>' in math[3]['mathml'] and '<msup>' in math[1]['mathml']
    text=block['text'].replace('^{2}','^{3}')
    r=client.put(f"/api/documents/{doc}/blocks/review",json={'changes':[dict(id=block['id'],revision=1,text=text,verified=True)]})
    assert r.status_code==200,r.text
    saved=client.get(f'/api/documents/{doc}/blocks').json()[0]
    assert '^{3}' in saved['text'] and any('^{2}' in p.get('latex','') for p in block['original_content'])
    draft=client.post('/api/drafts',json={'title':'公式测试','source_ids':[block['id']]}).json()
    path='/api/drafts/'+draft['id']
    assert client.post(path+'/approve',json={'revision':1,'reviewer':'教师','confirmed':True}).status_code==200
    release=client.post(path+'/releases',json={'revision':1}).json()
    html=client.get('/api/releases/'+release['id']+'/download').text
    assert '<mfrac>' in html and '<msup>' in html and '<mn>3</mn>' in html
    assert '\\frac' not in html and '<script' not in html


def test_old_content_and_confirmation_are_not_overwritten_by_candidates(client):
    doc,block=upload(client)
    with connect() as c:
        c.execute("UPDATE blocks SET text='人工修订 x2 与 1x',verified=1,original_content='[]' WHERE id=?",(block['id'],))
    before=client.get(f'/api/documents/{doc}/blocks').json()[0]
    r=client.post(f'/api/documents/{doc}/formula-candidates')
    assert r.status_code==200 and len(r.json())==1
    candidate=r.json()[0]
    assert candidate['base_revision']==before['revision'] and '\\frac' in candidate['text']
    assert client.get(f'/api/documents/{doc}/blocks').json()[0]==before
    assert client.get(f'/api/documents/{doc}/formula-candidates').json()[0]['text']==candidate['text']
    init_db();assert client.get(f'/api/documents/{doc}/blocks').json()[0]==before


def test_bad_formula_cannot_be_confirmed_and_does_not_partially_save(client):
    doc,block=upload(client)
    for invalid in [r'\(\frac{}{x}\)',r'\(\href{javascript:alert(1)}{x}\)',r'\(x^{2}',r'\(x^\)', '【未转换公式，请对照原件并替换】']:
        r=client.put(f'/api/documents/{doc}/blocks/review',json={'changes':[dict(id=block['id'],revision=1,text=invalid,verified=True)]})
        assert r.status_code==422,r.text
    assert client.get(f'/api/documents/{doc}/blocks').json()[0]['revision']==1
    assert client.post('/api/formulas/preview',json={'latex':r'\frac{1}{x}'}).status_code==200
    assert client.post('/api/formulas/preview',json={'latex':r'\includegraphics{http://example.com/x}'}).status_code==422


def test_common_formulas_are_structural_and_html_is_not_executed():
    for latex,tag in [(r'x^2','msup'),(r'x_1','msub'),(r'\sqrt{x+1}','msqrt'),(r'\frac{1}{x}','mfrac')]:
        result=render_latex(latex);assert '<'+tag+'>' in result
    parts=parts_from_text('条件：'+r'\(x^2+\frac{1}{x}=2\)'+'，且x≠0。',strict=True)
    assert [p['type'] for p in parts]==['text','math','text']


def test_upgrade_keeps_legacy_text_without_guessing_and_snapshot_format_compatibility(client):
    doc,block=upload(client)
    with connect() as c:
        c.execute("UPDATE blocks SET text='人工修订 x2+1x',verified=1 WHERE id=?",(block['id'],))
        c.execute('DROP TABLE formula_candidates')
        c.execute('ALTER TABLE blocks DROP COLUMN original_content')
        c.execute('DELETE FROM schema_migrations WHERE version=2')
    init_db()
    saved=client.get(f'/api/documents/{doc}/blocks').json()[0]
    assert saved['text']=='人工修订 x2+1x' and saved['verified'] and saved['original_content']==[]
    from mathlet.main import render_book
    source={'document_name':'旧来源','locator':'块1','text':r'\(x^2\)','images':[]}
    snapshot={'draft':{'title':'旧快照','revision':1,'approved':False,'content':'正文'},'sources':[source]}
    assert '<msup>' not in render_book(snapshot)
    snapshot['format_version']=2
    assert '<msup>' in render_book(snapshot)


def test_deepseek_circle_and_number_set_commands_render_without_rewriting(client):
    from lxml import etree as ET
    for latex,expected in [(r'\odot O','⊙'),(r'x\in\mathbb{R}','ℝ')]:
        response=client.post('/api/formulas/preview',json={'latex':latex})
        assert response.status_code==200,response.text
        root=ET.fromstring(response.json()['mathml'].encode())
        assert expected in ''.join(root.itertext())
        assert parts_from_text(r'\('+latex+r'\)',strict=True)[0]['latex']==latex
    for latex in [r'\href{javascript:alert(1)}{x}',r'\htmlClass{bad}{x}',r'\newcommand{\x}{x}',r'\unknown{x}']:
        assert client.post('/api/formulas/preview',json={'latex':latex}).status_code==422


@pytest.mark.parametrize('latex,symbol,tag',[
    (r'a\iff b','⟺',None),
    (r'x\rightarrow 0','→',None),
    (r'a\Rightarrow b','⇒',None),
    (r'\underbrace{x+x}_{2\text{项}}','⏟','munder'),
    (r'\overbrace{x+x}^{2\text{项}}','⏞','mover'),
    (r'\overset{a}{=}','=', 'mover'),
    (r'\underset{x}{\min}','min','munder'),
    (r'\alpha+\beta\notin\mathbb{R}','ℝ',None),
    (r'\angle ABC\cong\angle DEF','∠',None),
    (r'\operatorname{max}(x,y)','max',None),
    (r'\begin{pmatrix}a&b\\c&d\end{pmatrix}','a','mtable'),
])
def test_standard_math_dialect_symbols_and_structures(client,latex,symbol,tag):
    from lxml import etree as ET
    response=client.post('/api/formulas/preview',json={'latex':latex})
    assert response.status_code==200,response.text
    root=ET.fromstring(response.json()['mathml'].encode())
    assert symbol in ''.join(root.itertext())
    if tag: assert root.findall('.//{http://www.w3.org/1998/Math/MathML}'+tag)
    assert not any('\\' in (node.text or '') and '\\'+latex.lstrip('\\').split('{')[0] in (node.text or '') for node in root.iter())


def test_formula_capabilities_and_residual_command_detection(client,monkeypatch):
    import mathlet.formulas as formulas
    capabilities=client.get('/api/formulas/capabilities').json()
    assert not capabilities['full_tex']
    assert {'iff','underbrace','rightarrow','mathbb'}<=set(capabilities['commands'])
    assert not {'href','includegraphics','newcommand','htmlClass'}&set(capabilities['commands'])
    # A converter upgrade must not silently echo a command and pass as rendered math.
    monkeypatch.setattr(formulas,'convert',lambda _: '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>\\rightarrow</mi></math>')
    assert client.post('/api/formulas/preview',json={'latex':r'x\rightarrow 0'}).status_code==422


@pytest.mark.parametrize('latex',[
    r'\href{https://example.com}{x}',r'\htmlStyle{color:red}{x}',
    r'\input{secret}',r'\newcommand{\x}{x}',r'\unknown{x}',
    r'\begin{matrix}x\end{cases}',r'\begin{matrix}x',r'\end{matrix}',
])
def test_math_dialect_rejects_programs_unknown_commands_and_unbalanced_environments(client,latex):
    assert client.post('/api/formulas/preview',json={'latex':latex}).status_code==422
