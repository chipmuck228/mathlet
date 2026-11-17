"""Bind model proposals to stored source text without trusting retyped quotations.

Only generation uses these repairs. Teacher saves still use strict reference validation.
Original model responses remain in knowledge_calls for traceability.
"""
from .review_unit_models import MappingBatch,CardSet
from .review_units import validate_mappings,validate_cards
from .corpus import fingerprint


def bind(e,studies):
    source=studies.get(e['analysis_id'])
    if not source:return None,'引用的研究不在本次范围中，未采用此证据。'
    paths=source['analysis']['approaches']
    path=next((a for a in paths if a['id']==e['approach_id']),None)
    if path and e['step_index']<len(path['steps']):
        step=path['steps'][e['step_index']]
        if any(e['quote'] in step[k] for k in ['action','reason']):return e,''
        result=e|{'quote':step['action']}
        return result,f"引文定位核对：{source['question']['title']}，解法 {path['id']} 第{e['step_index']+1}步。AI原引文为“{e['quote']}”；已按其解法与步骤索引直接读取原文替换，仅修复引用，不代表知识关联已验证。请对照原文、关联解释与成立条件，修改关联或由教师判断认可。"
    matches=[(a,i,s) for a in paths for i,s in enumerate(a['steps']) if any(e['quote'] in s[k] for k in ['action','reason'])]
    if len(matches)==1:
        a,i,_=matches[0]
        return e|{'approach_id':a['id'],'step_index':i},f"引文定位核对：{source['question']['title']}的解法／步骤编号不符，已通过唯一逐字引文定位到 {a['id']} 第{i+1}步。请核对该步骤是否支持所述关联。"
    return None,f"证据待定位：{source['question']['title']}，AI引用“{e['quote']}”，所指解法或步骤不存在，也无法唯一定位原文。未采用此关联；请在原题步骤中重新选择依据，或保留待判断。"


def mappings(value,know,studies):
    parsed=MappingBatch.model_validate(value).model_dump()
    for m in parsed['mappings']:
        kept=[];messages=[]
        for link in m['links']:
            # Do not move a link to another question to make its evidence appear valid.
            if link['analysis_id']!=m['analysis_id']:
                messages.append('证据待定位：关联引用了另一道题，已移除该关联，请对照本题研究补充。');continue
            repaired,note=bind(link,studies)
            if repaired:kept.append(repaired)
            if note:messages.append(note)
        m['links']=kept
        if m['relevance'] in {'core','support','optional'} and not kept:
            m['relevance']='uncertain'
            messages.append('全部关联尚无可定位证据，本题保留为依据待判断，不自动纳入代表题；其他题目继续编制。')
        if messages:
            # Keep all diagnostics, while respecting the existing list cardinality.
            m['gaps']=(m['gaps'][:14]+['\n'.join(m['gaps'][14:]+messages)]) if len(m['gaps'])>=15 else m['gaps']+['\n'.join(messages)]
    return validate_mappings(parsed,know,studies)


def cards(value,know,studies):
    parsed=CardSet.model_validate(value).model_dump();kept=[];omitted=[]
    for card in parsed['cards']:
        repaired=[];messages=[]
        for e in card['evidence']:
            resolved,note=bind(e,studies)
            if resolved:repaired.append(resolved)
            if note:messages.append(note)
        unique={fingerprint(studies[e['analysis_id']]['question']) for e in repaired}
        if len(unique)<2:
            omitted.append('未纳入思路卡“'+card['title']+'”：可定位证据不足两道不同题。请对照原研究补充两道不同题的步骤证据后再归纳；原AI候选保留在调用响应中。');continue
        card['evidence']=repaired
        if messages:card['doubts']=card['doubts'][:9]+['\n'.join(card['doubts'][9:]+messages)]
        kept.append(card)
    parsed['cards']=kept
    if omitted:
        note='\n'.join(omitted)
        combined=parsed['summary']+'\n'+note
        parsed['summary']=combined if len(combined)<=4000 else note+'\n原AI概述较长，完整概述保留在本次调用响应中；此处优先显示证据核查结果。'
    return validate_cards(parsed,know,studies)
