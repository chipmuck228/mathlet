"""Display-only normalization; never rewrites approved mathematical source data."""
import html
import re
from .formulas import parts_from_text, render_latex


def render_reader_text(value):
    # Some providers serialize an entire LaTeX fragment twice. Only collapse a
    # doubled command/delimiter, keeping matrix row separators intact.
    value = html.unescape(value)
    value = re.sub(r'\\\\(?=[A-Za-z]|[()])', r'\\', value)
    result = []
    for part in parts_from_text(value):
        if part['type'] == 'math':
            if not part['error']:
                result.append(part['mathml'])
            else:
                result.append('<span class="formula-error">'+html.escape(r'\('+part['latex']+r'\)')+' [公式待修正]</span>')
            continue
        # Legacy research steps may contain undelimited ASCII expressions. Only
        # recognize spans containing an explicit LaTeX command, never prose or HTML.
        chunks = re.split(r'([A-Za-z0-9\\{}_^=+*/().<>|,\-]+)', part['text'])
        for chunk in chunks:
            if re.search(r'\\[A-Za-z]+', chunk):
                try:
                    result.append(render_latex(chunk)); continue
                except ValueError:
                    pass
            # Minimal inline emphasis, escaped before adding our fixed tags.
            escaped = html.escape(chunk)
            result.append(re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', escaped))
    return ''.join(result)


def goal_text(value):
    return re.sub(r'^\s*读完(?:以后)?(?:，|,)?\s*试试\s*[:：]\s*', '', value)
