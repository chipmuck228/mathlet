"""Offline HTML with MathML, internal knowledge links and native progressive disclosures."""
import html
from .formulas import render_text,render_latex
from .teaching import PHASE_NAMES

def render_reader(snapshot):
    body=snapshot['body'];know=snapshot['knowledge'];questions={q['version_id']:q for q in snapshot['questions']}
    anchors={x['ref']:'knowledge-'+str(i+1) for i,x in enumerate(know['items'])}
    names={x['ref']:x['title'] for x in know['items']}
    def text(s):return '<div class="text">'+render_text(s)+'</div>'
    def link(ref):return '<a href="#'+anchors[ref]+'">'+html.escape(names[ref])+'</a>'
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(body['title'])+'</title><style>body{max-width:800px;margin:40px auto;padding:0 22px;color:#26332c;background:#fffdf8;font:17px/1.9 system-ui,sans-serif}h1{font-size:28px}h2{margin-top:42px;border-bottom:1px solid #ccd2c7;padding-bottom:8px}h3{font-size:19px}a{color:#325c43}.text{white-space:pre-wrap;margin:10px 0}blockquote{border-left:3px solid #afc2a8;padding-left:18px;margin-left:0}details{margin:16px 0;border-top:1px solid #ddd;padding:10px 0}summary{cursor:pointer;color:#365c40}img{max-width:100%;max-height:400px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:8px;text-align:left}math{max-width:100%;overflow:auto}small{color:#667366}@media print{body{background:white;margin:0;max-width:none}h2{break-before:page}details> :not(summary){display:block!important}summary{display:block}a{color:inherit}details::details-content{content-visibility:visible!important;height:auto!important}img{max-height:260px}article{break-inside:auto}}</style><header><small>Mathlet · '+('经教师审定的小节读物' if snapshot['teacher_confirmed'] else '未审定草稿，仅供核查')+'</small><h1>'+html.escape(body['title'])+'</h1><p>先理解基础知识，再尝试思路训练，最后对照完整解析。提示按需要逐层打开。打印时展开的正文与答案一起保留。</p></header><h2>一、基本知识</h2>']
    for i,k in enumerate(know['items']):
        b=k['body'];parts.append('<article id="'+anchors[k['ref']]+'"><h3>B'+str(i+1)+' '+html.escape(k['title'])+'</h3>'+text(b['statement'])+'<strong>成立条件</strong>'+text(b['conditions']))
        if b.get('formula'):parts.append('<div>'+render_latex(b['formula'])+'</div>')
        parts.append('<strong>正例</strong>'+text(b['positive_example'])+'<strong>反例与易错点</strong>'+text(b['misconception']))
        if b.get('method_steps'):parts.append('<strong>方法步骤</strong>'+text(b['method_steps']))
        parts.append('<strong>掌握表现</strong>'+text(b['mastery'])+'</article>')
    if know.get('relations'):
        parts.append('<h3>知识之间怎样连接</h3>')
        for r in know['relations']:
            e=r['body'];source=know['version_id']+':'+e['source_id'];target=know['version_id']+':'+e['target_id']
            if source in names and target in names:parts.append('<p>'+link(source)+' → '+link(target)+'</p>'+text(e['reason'])+'<strong>条件</strong>'+text(e['conditions']))
    for index,c in enumerate(body['cases']):
        if c['relevance'] not in {'primary','combined','optional'}:continue
        q=questions[c['question_version_id']];parts.append('<h2>二、代表题 '+str(index+1)+' · '+html.escape(q['title'])+'</h2>'+text(q['statement']))
        for a in q['assets']:
            if a.get('data_url','').startswith('data:image/png;base64,'):parts.append('<img alt="原题配图" src="'+html.escape(a['data_url'],quote=True)+'">')
        if q['diagram_description']:parts.append('<p>图形条件：</p>'+text(q['diagram_description']))
        sources=[s for s in q['sources'] if s['id'] in q['question_block_ids']]
        category={'exam':'中考真题','mock':'模拟题','term':'学期试卷','unknown':'来源类别待确认'}
        parts.append('<small>来源：'+html.escape('；'.join(s['document_name']+' · '+category.get(s['category'],s['category'])+' · '+s['locator'] for s in sources))+'</small><h3>先尝试思考</h3>')
        bymap={m['id']:m for m in c['applications']}
        for t in c['training']:
            parts.append('<article><h3>'+PHASE_NAMES[t['phase']]+'</h3>'+text(t['prompt']))
            for n,h in enumerate(t['hints']):parts.append('<details><summary>提示 '+str(n+1)+'</summary>'+text(h)+'</details>')
            parts.append('<details><summary>对照思考与检查要点</summary>'+text(t['expected_reasoning'])+''.join(text(x) for x in t['checkpoints'])+'<p>可回顾：'+ '、'.join(link(ref) for ref in dict.fromkeys(bymap[m]['knowledge_ref'] for m in t['mapping_ids']))+'</p></details></article>')
        parts.append('<details><summary>为什么想到这些知识</summary>')
        for m in c['applications']:parts.append('<blockquote>'+text(m['quote'])+'</blockquote><p>'+link(m['knowledge_ref'])+'</p>'+text(m['why'])+'<strong>思考操作</strong>'+text(m['operation'])+'<strong>条件</strong>'+text(m['conditions'])+'<small>对应路径 '+html.escape(m['approach_id'])+'，第'+str(m['step_index']+1)+'步</small>')
        a=c['analysis'];parts.append('</details><details><summary>完整真题解析 · 可行路径</summary><h3>分类及依据</h3>'+text('、'.join(a['problem_types']))+text(a['classification_reason'])+'<h3>条件与目标</h3>'+''.join(text(x) for x in a['given_conditions']+a['goals']))
        for point in a['assessed_points']:parts.append('<strong>考察：'+html.escape(point['name'])+'</strong>'+text(point['evidence']))
        for path in a['approaches']:
            parts.append('<h3>'+html.escape(path['title'])+'</h3>'+text(path['trigger']))
            for n,s in enumerate(path['steps']):parts.append('<p><strong>第'+str(n+1)+'步</strong></p>'+text(s['action'])+text('依据：'+s['reason'])+'<p>使用知识：'+'、'.join(link(r) for r in s['knowledge_refs'])+'</p>')
            parts.append('<strong>结论</strong>'+text(path['conclusion'])+'<strong>检验</strong>'+text(path['checks'])+'<strong>使用边界</strong>'+text(path['limitations']))
        parts.append('<h3>易错点</h3>'+''.join(text(x) for x in a['common_mistakes'])+'</details>')
    parts.append('<h2>三、回顾与补充</h2><p>当前代表题没有使用的知识，仍需复习，不能据此判断不重要。</p>')
    for r in snapshot['coverage']:parts.append('<p>'+link(r['ref'])+'：'+html.escape(r['status'])+'</p>')
    parts.append('<footer><small>'+('教师审定版本' if snapshot['teacher_confirmed'] else '未审定草稿')+' · '+html.escape(snapshot['created_at'])+'。本读物不声称覆盖所有题型或唯一解法。</small></footer></html>')
    return ''.join(parts)
