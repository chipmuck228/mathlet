import json
import pytest
from mathlet.model_json import parse_model_json,ModelJSONError

@pytest.mark.parametrize('formula',[
 r'\frac{k}{x}',r'\theta+\beta',r'\rightarrow',r'\underbrace{x+x}_{2}',
 r'\mathbb{R}',r'\sqrt{x}',r'\tan A',r'\neq 0',
 r'\begin{cases}x&x>0\\0&x<0\end{cases}',
])
def test_correct_json_math_is_unchanged(formula):
    raw=json.dumps({'formula':formula,'note':'第一行\n第二行\t一列\r下一行','unicode':'α','id':'stable-id'},ensure_ascii=True)
    value,notes=parse_model_json(raw)
    assert value==json.loads(raw) and notes==[]

@pytest.mark.parametrize('raw,expected',[
 (r'{"formula":"\frac{k}{x}"}',r'\frac{k}{x}'),
 (r'{"formula":"\theta+\beta"}',r'\theta+\beta'),
 (r'{"formula":"\underbrace{x+x}_{2}"}',r'\underbrace{x+x}_{2}'),
 (r'{"formula":"\tan A\rightarrow 0"}',r'\tan A\rightarrow 0'),
 (r'{"formula":"\mathbb{R}"}',r'\mathbb{R}'),
 (r'{"formula":"\left\{x\right\}"}',r'\left\{x\right\}'),
])
def test_unambiguous_bare_commands_do_not_become_control_characters(raw,expected):
    value,notes=parse_model_json(raw)
    assert value['formula']==expected and notes


def test_marked_math_repairs_escapes_and_preserves_legitimate_prose_newlines():
    raw=r'{"reason":"第一行\n第二行，讨论\(\theta\ne 0\)与$\frac{k}{x}$。","id":"k1"}'
    value,notes=parse_model_json(raw)
    assert value['reason']=='第一行\n第二行，讨论'+r'\(\theta\ne 0\)与$\frac{k}{x}$。'
    assert value['id']=='k1' and notes


def test_fences_mixed_correct_and_incorrect_escapes_and_matrix_rows_are_preserved():
    raw='```json\n'+r'{"formula":"\begin{cases}x&x>0\\\\0&x<0\end{cases}","note":"\\(\\frac{1}{x}\\)"}'+'\n```'
    value,notes=parse_model_json(raw)
    assert value['formula']==r'\begin{cases}x&x>0\\0&x<0\end{cases}'
    assert value['note']==r'\(\frac{1}{x}\)' and len(notes)==2

@pytest.mark.parametrize('raw',[
 r'{"reason":"bare \theta"}',r'{"reason":"bare \right"}',
 r'{"formula":"\unknown{x}"}',r'{"x":"\u12G4"}',
 r'{"x":"\b"}',r'{"x":"\f"}',
 '{"x":1,"x":2}', '{"items":[', '{"x":"missing}', '{"x":"ok",}',
 '{"x":"one" "y":"two"}', '{"x":"unescaped\nnewline"}',
])
def test_ambiguous_or_damaged_outputs_are_not_guessed(raw):
    with pytest.raises(ModelJSONError):parse_model_json(raw)
