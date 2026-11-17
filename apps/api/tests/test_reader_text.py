from mathlet.reader_text import render_reader_text,goal_text
from mathlet.reader_theme import CSS


def test_doubled_and_bare_latex_are_mathml_not_entities():
    for text in [r'由 \\(0<m<3\\)，得 \\(\\frac{1}{m}>\\frac{1}{3}\\)',
                 r'由 0<m<3，得 \\frac{1}{m}>\\frac{1}{3}，故 n=\\frac{12}{m}>4。']:
        output=render_reader_text(text)
        assert '<mfrac>' in output and '\\frac' not in output
        assert '&#x7531;' not in output and '公式待修正' not in output


def test_entities_remain_safe_and_source_math_is_not_changed():
    source=r'&#x7531; \(\frac{1}{m}\) &lt;script&gt;alert(1)&lt;/script&gt;'
    out=render_reader_text(source)
    assert out.startswith('由 ') and '<mfrac>' in out
    assert '<script>' not in out and '&lt;script&gt;' in out
    assert source.startswith('&#x7531;')


def test_goals_and_fraction_layout():
    assert goal_text('读完试试：你能判断吗？')=='你能判断吗？'
    assert goal_text('你能判断吗？')=='你能判断吗？'
    assert 'math{max-width:none;overflow:visible' in CSS
