"""One math dialect shared by rendering, capability discovery and model guidance.

Passive symbols come from the pinned converter's own registry, rather than a
handwritten list that repeatedly misses arrows, relations and Greek letters.
Structural commands remain explicit; this is not a full TeX interpreter.
"""
import re
from latex2mathml.symbols_parser import SYMBOLS
from latex2mathml import commands

STRUCTURAL = set('''frac dfrac tfrac cfrac binom dbinom tbinom sqrt left middle right
text textbf textit textrm textnormal mathrm mathbf mathbb mathcal mathfrak mathit
mathscr mathsf mathtt mathnormal boldsymbol bm Bbb operatorname
begin end quad qquad space enspace thinspace thickspace
limits nolimits sum prod int displaystyle textstyle scriptstyle scriptscriptstyle
log ln sin cos tan cot sec csc arcsin arccos arctan sinh cosh tanh
lim min max sup inf gcd det mod bmod pmod
overset underset stackrel boxed cancel bcancel xcancel
big Big bigg Bigg bigl bigr Bigl Bigr biggl biggr Biggl Biggr
xrightarrow xleftarrow xleftrightarrow xRightarrow xLeftarrow xLeftrightarrow
'''.split())
STRUCTURAL.update(x[1:] for x in commands.DIACRITICS if re.fullmatch(r'\\[A-Za-z]+',x))
SYMBOL_COMMANDS = {x[1:] for x in SYMBOLS if re.fullmatch(r'\\[A-Za-z]+',x)}
# Never accept external resources, links, HTML or user-defined TeX programs.
FORBIDDEN = set('href url includegraphics input include def gdef edef xdef let newcommand renewcommand providecommand require usepackage documentclass htmlClass htmlId htmlStyle htmlData htmlId style class cssId color colorbox fcolorbox'.split())
COMMANDS = (SYMBOL_COMMANDS | STRUCTURAL) - FORBIDDEN
ENVIRONMENTS = {'cases','matrix','pmatrix','bmatrix','Bmatrix','vmatrix','Vmatrix','smallmatrix','aligned'}
DIALECT_VERSION = 'mathlet-math-v2'
MODEL_GUIDANCE = r'''公式使用常规数学LaTeX：支持分式、根式、上下标、希腊字母、数学符号、箭头（如\rightarrow、\iff）、标注（如\underbrace、\overset）、数集字体（如\mathbb）和矩阵／分段式。正文使用\(…\)，独立formula字段不加定界符。不要生成自定义宏、HTML、链接、外部资源或文档排版命令。公式需通过工作台统一渲染检查，能渲染不等于数学内容正确。'''
