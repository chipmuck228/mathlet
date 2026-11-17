"""Self-contained student reader: escaped prose, MathML, images and printable answers."""
import html
from .formulas import render_text,render_latex
from .review_units import ROLES

PHASES={'basic':'基础唤起','thinking':'思路训练','solve':'独立解题','transfer':'迁移练习'}
def render_reader(snapshot):
    b=snapshot['body'];know=snapshot['knowledge'];studies={s['id']:s for s in snapshot['studies']};confirmed=snapshot['teacher_review']['confirmed']
    names={k['ref']:k['title'] for k in know['items']};anchors={k['ref']:'k-'+str(i) for i,k in enumerate(know['items'])}
    def text(value):return '<div class="text">'+render_text(value)+'</div>'
    def links(refs):return '、'.join('<a href="#'+anchors[r]+'">'+html.escape(names[r])+'</a>' for r in dict.fromkeys(refs))
    def listing(values):return ''.join(text(v) for v in values)
    def details(label,body):return '<details><summary>'+html.escape(label)+'</summary>'+body+'</details>'
    parts=['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(b['title'])+'</title><style>body{max-width:800px;margin:36px auto;padding:0 24px;color:#26372e;background:#fffdf8;font:17px/1.9 system-ui,sans-serif}.text{white-space:pre-wrap;margin:10px 0}h1{font-size:30px}h2{margin-top:44px;border-bottom:1px solid #c8d1c4}h3{margin-top:28px}a,summary{color:#345e42}details{border-top:1px solid #ddd;padding:12px 0;margin:12px 0}summary{cursor:pointer}img{max-width:100%;max-height:400px}small{color:#667468}blockquote{border-left:3px solid #a6b8a0;padding-left:16px;margin-left:0}math{max-width:100%;overflow:auto}nav{display:flex;gap:18px;flex-wrap:wrap}@media print{body{background:white;margin:0;max-width:none}h2{break-before:page}details> :not(summary){display:block!important}details::details-content{content-visibility:visible!important;height:auto!important}img{max-height:280px}a{color:inherit}}</style></head><body><header><small>Mathlet · '+('教师审定复习单元' if confirmed else '未审定草案，仅供核查')+'</small><h1>'+html.escape(b['title'])+'</h1>'+text(b['introduction'])+listing(b['goals'])+'<p>先独立尝试，再按需要展开提示。完整解析与训练参考答案在后部。可以下载本读物留存，或使用浏览器打印为PDF；打印前请展开需要的解析和答案。</p><nav><a href="#basics">基础知识</a><a href="#cards">连接与思路</a><a href="#practice">分层训练</a><a href="#solutions">解析与答案</a></nav></header><h2 id="basics">一、基础知识</h2>']
    for k in know['items']:
        v=k['body'];parts.append('<article id="'+anchors[k['ref']]+'"><h3>'+html.escape(k['title'])+'</h3>'+text(v['statement'])+'<strong>成立条件</strong>'+text(v['conditions']))
        if v.get('formula'):parts.append(render_latex(v['formula']))
        parts.append('<strong>正例</strong>'+text(v['positive_example'])+'<strong>反例与易错点</strong>'+text(v['misconception'])+text(v.get('method_steps',''))+'<strong>掌握表现</strong>'+text(v['mastery'])+'</article>')
    if know.get('relations'):
        parts.append('<h3>知识之间怎样连接</h3>')
        for relation in know['relations']:
            edge=relation['body'];source=know['version_id']+':'+edge['source_id'];target=know['version_id']+':'+edge['target_id']
            if source in names and target in names:parts.append('<p>'+links([source])+' → '+links([target])+'</p>'+text(edge['reason'])+text(edge['conditions'])+text(edge.get('example','')))
    parts.append('<h2 id="cards">二、连接与思路</h2>'+text(b['summary']))
    if b.get('knowledge_connections'):
        parts.append('<h3>知识之间怎样连接</h3>')
        for edge in b['knowledge_connections']:
            parts.append('<p>'+links([edge['source_ref']])+' → '+links([edge['target_ref']])+'</p>'+text(edge['explanation'])+'<strong>成立条件</strong>'+text(edge['conditions'])+'<strong>例子</strong>'+text(edge['example']))
    for card in b['cards']:
        parts.append('<article><h3>'+html.escape(card['title'])+'</h3><strong>看到什么线索</strong>'+listing(card['cues'])+text(card['structure'])+'<strong>可以怎样思考</strong>'+listing(card['steps'])+'<strong>使用边界</strong>'+listing(card['conditions'])+'<strong>其他可行路径</strong>'+listing(card['alternatives'])+'<strong>易错点</strong>'+listing(card['mistakes'])+'<p>回顾知识：'+links(card['knowledge_refs'])+'</p>')
        parts.append(details('比较哪些题目得出这一思路',''.join('<p><a href="#q-'+html.escape(e['analysis_id'])+'">'+html.escape(studies[e['analysis_id']]['question']['title'])+'</a> · 第'+str(e['step_index']+1)+'步</p>'+text(e['quote']) for e in card['evidence']))+'</article>')
    parts.append('<h2 id="practice">三、分层训练</h2>')
    shown_questions=set()
    for n,t in enumerate(b['training']):
        parts.append('<article><h3>'+str(n+1)+' · '+PHASES[t['phase']]+' · '+html.escape(t['title'])+'</h3><small>'+('围绕已审定原题的训练' if t['kind']=='original' else '自编迁移练习，非原真题')+'</small>')
        if t['kind']=='original':
            for key in t['source_analysis_ids']:
                if key in shown_questions:
                    parts.append('<p><a href="#practice-q-'+html.escape(key)+'">回看原题：'+html.escape(studies[key]['question']['title'])+'</a></p>')
                    continue
                shown_questions.add(key)
                parts.append('<blockquote id="practice-q-'+html.escape(key)+'"><strong>'+html.escape(studies[key]['question']['title'])+'</strong>'+text(studies[key]['question']['statement'])+text(studies[key]['question']['diagram_description'])+''.join('<img alt="原题配图" src="'+html.escape(a['data_url'],quote=True)+'">' for a in studies[key]['question']['assets'] if a.get('data_url','').startswith('data:image/png;base64,'))+'</blockquote>')
        parts.append(text(t['prompt'])+'<p>可回顾：'+links(t['knowledge_refs'])+'</p>')
        for i,hint in enumerate(t['hints']):parts.append(details('提示 '+str(i+1),text(hint)))
        parts.append('</article>')
    parts.append('<h2 id="solutions">四、真题解析与训练参考答案</h2>')
    for s in studies.values():
        q=s['question'];a=s['analysis'];parts.append('<article id="q-'+html.escape(s['id'])+'"><h3>'+html.escape(q['title'])+'</h3>'+text(q['statement'])+text(q['diagram_description']))
        for asset in q['assets']:
            if asset.get('data_url','').startswith('data:image/png;base64,'):parts.append('<img alt="原题配图" src="'+html.escape(asset['data_url'],quote=True)+'">')
        categories={'exam':'中考真题','mock':'模拟题','term':'学期试卷','unknown':'来源类别待确认'}
        parts.append('<small>来源：'+html.escape('；'.join(src['document_name']+' · '+categories.get(src['category'],src['category']) for src in q['sources'] if src['id'] in q['question_block_ids']))+'</small>')
        for path in a['approaches']:
            content=text(path['trigger'])
            for i,step in enumerate(path['steps']):content+='<strong>第'+str(i+1)+'步</strong>'+text(step['action'])+text('依据：'+step['reason'])
            content+='<strong>结论</strong>'+text(path['conclusion'])+'<strong>检验</strong>'+text(path['checks'])+'<strong>使用边界</strong>'+text(path['limitations'])
            parts.append(details(path['title']+' · 已审定研究解析',content))
        mappings=[m for m in b['mappings'] if m['analysis_id']==s['id']]
        for m in mappings:
            content='<p>'+ROLES[m['relevance']]+'</p>'+text(m['reason'])
            for l in m['links']:content+='<p>'+links([l['knowledge_ref']])+'</p>'+text(l['quote'])+text(l['explanation'])+text(l['conditions'])
            parts.append(details('如何连接本节知识',content))
        parts.append('</article>')
    for n,t in enumerate(b['training']):parts.append(details('训练 '+str(n+1)+' 参考答案与思考过程',text(t['answer'])+text(t['reasoning'])+listing(t['checkpoints'])))
    parts.append('<footer><p>本单元只归纳当前证据支持的思路，不声称覆盖全部题型或唯一解法。未在代表题中使用的知识仍需复习。</p><small>'+('教师审定版本' if confirmed else '未审定草案')+' · '+html.escape(snapshot.get('created_at',''))+'</small></footer></body></html>')
    return ''.join(parts)
