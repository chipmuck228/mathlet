"""Coloured, print-safe student reader. Presentation copy never replaces source mathematics."""
import html
from .formulas import render_text,render_latex
from .review_units import ROLES
from .reader_theme import CSS,icon
from .student_presentation import current_presentation

PHASES={'basic':'先把基础想起来','thinking':'试着找一条路','solve':'这次自己来','transfer':'换个样子再试试'}
def render_reader(snapshot):
    b=snapshot['body'];know=snapshot['knowledge'];studies={s['id']:s for s in snapshot['studies']};confirmed=snapshot['teacher_review']['confirmed']
    p=current_presentation(b,know);copies={x['knowledge_ref']:x for x in p['knowledge']} if p else {};card_copy={x['card_index']:x for x in p['cards']} if p else {};training_copy={x['training_index']:x for x in p['training']} if p else {}
    names={k['ref']:k['title'] for k in know['items']};anchors={k['ref']:'k-'+str(i) for i,k in enumerate(know['items'])}
    def text(value):return '<div class="text">'+render_text(value)+'</div>'
    def links(refs):return '、'.join('<a href="#'+anchors[r]+'">'+html.escape(names[r])+'</a>' for r in dict.fromkeys(refs))
    def listing(values):return '<ul class="cues">'+''.join('<li>'+render_text(v)+'</li>' for v in values)+'</ul>' if values else ''
    def details(label,body,cls=''):return '<details class="'+cls+'"><summary>'+html.escape(label)+'</summary>'+body+'</details>'
    def band(title,content,tone='blue',symbol='idea'):return '<div class="band tone-'+tone+'"><h4>'+icon(symbol)+html.escape(title)+'</h4>'+content+'</div>'
    def chapter(number,title,anchor):return '<div class="chapter" id="'+anchor+'"><span class="chapter-number">0'+str(number)+'</span><h2>'+html.escape(title)+'</h2></div>'
    def images(q):return ''.join('<img alt="原题配图" src="'+html.escape(a['data_url'],quote=True)+'">' for a in q['assets'] if a.get('data_url','').startswith('data:image/png;base64,'))
    parts=['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(b['title'])+'</title><style>'+CSS+'</style></head><body><header class="cover"><p class="eyebrow">MATHLET / 数学复习小册子 · '+('教师审定复习单元' if confirmed else '未审定草案，仅供核查')+'</p><h1>'+html.escape(b['title'])+'</h1>'+text(p['introduction'] if p else b['introduction'])+'<div class="goals"><h4>'+icon('check')+' 读完以后，试试这些事</h4>'+listing(p['goals'] if p else b['goals'])+'</div><p class="muted text">先自己想一想，卡住了再打开提示。做完后再翻到后面，对照答案和思考过程。</p><nav class="reading-route"><a href="#basics">先懂知识</a><a href="#cards">找到连接</a><a href="#practice">动笔试试</a><a href="#solutions">对照思路</a></nav></header>'+chapter(1,'先把知识弄明白','basics')]
    for index,k in enumerate(know['items']):
        v=k['body'];copy=copies.get(k['ref']);parts.append('<article class="knowledge" id="'+anchors[k['ref']]+'"><div class="entry-head"><span class="entry-number">K'+str(index+1).zfill(2)+'</span><h3>'+html.escape(k['title'])+'</h3></div>')
        if copy:parts.append(band('先这样理解',text(copy['plain_explanation']),'blue','book'))
        parts.append('<div class="source-definition"><strong>记准这句话 · 准确表述</strong>'+text(v['statement'])+'</div>'+band('条件别漏 · 成立条件',text(v['conditions']),'amber','alert'))
        if v.get('formula'):parts.append('<div class="formula"><strong>把公式和条件一起记</strong>'+render_latex(v['formula'])+'</div>')
        parts.append('<div class="comparison"><section class="example tone-green"><h4>'+icon('check')+' 正例 · 看看为什么对</h4>'+text(v['positive_example'])+'</section><section class="example tone-red"><h4>'+icon('cross')+' 反例与易错点 · 留心哪里不对</h4>'+text(v['misconception'])+'</section></div><p class="comparison-caption">把两边放在一起看：区别在哪里？哪一个条件决定了结果？</p>')
        if v.get('method_steps'):parts.append(band('动手时，可以按这个顺序',text(v['method_steps']),'plain','pen'))
        if copy:parts.append(band('记住这一点',text(copy['memory_hint']),'purple','idea')+band('合上讲解，你能回答吗？',text(copy['self_check']),'green','eye')+details('再对照一下原要求',text(v['mastery'])))
        else:parts.append(band('试着做给自己看',text(v['mastery']),'green','eye'))
        parts.append('</article>')
    if know.get('relations'):
        for relation in know['relations']:
            edge=relation['body'];source=know['version_id']+':'+edge['source_id'];target=know['version_id']+':'+edge['target_id']
            if source in names and target in names:parts.append(band('把这两点连起来','<p>'+links([source])+' → '+links([target])+'</p>'+text(edge['reason'])+text(edge['conditions'])+text(edge.get('example','')),'blue','link'))
    parts.append(chapter(2,'看到线索，找到思路','cards')+text(b['summary']))
    for edge in b.get('knowledge_connections',[]):parts.append(band('这两个知识，怎么一起用？','<p>'+links([edge['source_ref']])+' → '+links([edge['target_ref']])+'</p>'+text(edge['explanation'])+'<strong>先看条件</strong>'+text(edge['conditions'])+'<strong>放进例子里看</strong>'+text(edge['example']),'blue','link'))
    for index,card in enumerate(b['cards']):
        parts.append('<article class="thought"><h3>'+icon('idea')+' '+html.escape(card['title'])+'</h3>')
        if index in card_copy:parts.append(text(card_copy[index]['student_lead']))
        parts.append(band('看到这些，先停一下想想',listing(card['cues']),'purple','eye')+text(card['structure'])+'<h4>可以这样往下想</h4><ol class="steps">'+''.join('<li>'+text(s)+'</li>' for s in card['steps'])+'</ol>'+band('什么时候能这样做？',listing(card['conditions']),'amber','alert'))
        if card['alternatives']:parts.append(details('还可以走别的路吗？',listing(card['alternatives'])))
        if card['mistakes']:parts.append(band('这里容易绕弯',listing(card['mistakes']),'red','alert'))
        parts.append('<p>想不起来时，回看：'+links(card['knowledge_refs'])+'</p>'+details('比较哪些题目得出这一思路',''.join('<p><a href="#q-'+html.escape(e['analysis_id'])+'">'+html.escape(studies[e['analysis_id']]['question']['title'])+'</a> · 第'+str(e['step_index']+1)+'步</p>'+text(e['quote']) for e in card['evidence']))+'</article>')
    parts.append(chapter(3,'动笔试试，慢慢放开提示','practice'));shown_questions=set()
    for n,t in enumerate(b['training']):
        parts.append('<article class="exercise"><span class="badge">'+PHASES[t['phase']]+'</span><h3>'+str(n+1)+' · '+html.escape(t['title'])+'</h3><small>'+('围绕已审定原题的训练' if t['kind']=='original' else '自编迁移练习，非原真题')+'</small>')
        if n in training_copy:parts.append('<div class="student-lead">'+text(training_copy[n]['student_lead'])+'</div>')
        if t['kind']=='original':
            for key in t['source_analysis_ids']:
                if key in shown_questions:parts.append('<p><a href="#practice-q-'+html.escape(key)+'">回看原题：'+html.escape(studies[key]['question']['title'])+'</a></p>');continue
                shown_questions.add(key);q=studies[key]['question'];parts.append('<blockquote id="practice-q-'+html.escape(key)+'"><strong>'+html.escape(q['title'])+'</strong>'+text(q['statement'])+text(q['diagram_description'])+images(q)+'</blockquote>')
        parts.append(band('这次请你来',text(t['prompt']),'purple','pen')+'<p>需要时回顾：'+links(t['knowledge_refs'])+'</p><div class="writing-space" aria-hidden="true"></div>')
        for i,hint in enumerate(t['hints']):parts.append(details('卡住了？打开提示 '+str(i+1),text(hint),'hint'))
        parts.append('</article>')
    parts.append(chapter(4,'做完再看：答案与思考过程','solutions'))
    for s in studies.values():
        q=s['question'];a=s['analysis'];parts.append('<article class="solution" id="q-'+html.escape(s['id'])+'"><h3>'+html.escape(q['title'])+'</h3>'+text(q['statement'])+text(q['diagram_description'])+images(q))
        categories={'exam':'中考真题','mock':'模拟题','term':'学期试卷','unknown':'来源类别待确认'}
        parts.append('<small>来源：'+html.escape('；'.join(src['document_name']+' · '+categories.get(src['category'],src['category']) for src in q['sources'] if src['id'] in q['question_block_ids']))+'</small>')
        for path in a['approaches']:
            content=band('为什么会想到这条路？',text(path['trigger']),'blue','idea')+'<ol class="steps">'
            for step in path['steps']:content+='<li>'+text(step['action'])+'<div class="reason"><strong>为什么这一步成立？</strong>'+text(step['reason'])+'</div></li>'
            content+='</ol>'+band('得到什么结果？',text(path['conclusion']),'green','check')+band('别急，再检查一下',text(path['checks']),'blue','eye')
            if path['limitations']:content+=band('这个方法也有边界',text(path['limitations']),'amber','alert')
            parts.append(details(path['title']+' · 已审定研究解析',content))
        for m in [m for m in b['mappings'] if m['analysis_id']==s['id']]:
            content='<p>'+ROLES[m['relevance']]+'</p>'+text(m['reason'])
            for l in m['links']:content+='<p>'+links([l['knowledge_ref']])+'</p>'+text(l['quote'])+text(l['explanation'])+text(l['conditions'])
            parts.append(details('这道题，怎样用到本节知识？',content))
        parts.append('</article>')
    for n,t in enumerate(b['training']):parts.append(details('训练 '+str(n+1)+' 参考答案与思考过程',band('先对答案',text(t['answer']),'green','check')+band('再看为什么',text(t['reasoning']),'blue','idea')+band('自己检查这几处',listing(t['checkpoints']),'amber','eye')))
    parts.append('<footer><p>方法可以不止一种。多问自己一句：“为什么能这样做？”没有在例题中出现的知识，也值得回头看看。</p><small>'+('教师审定版本' if confirmed else '未审定草案')+' · '+html.escape(snapshot.get('created_at',''))+' · 可离线保存；打印为PDF时，提示与答案会一并展开。图标和边框也可帮助黑白阅读。</small></footer></body></html>')
    return ''.join(parts)
