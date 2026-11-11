"""Single-worker proposal execution with the shared paid-call checkpoints."""
import json
from .db import connect, now, uid
from .knowledge import packed, current, row
from .knowledge_actions import KnowledgeResult, CoverageResult, RelationsResult, validate_references


def run_action(run,config,snapshot):
    from .knowledge_worker import call, BODY_SHAPE, Critic
    meta=snapshot['action_task'];action=meta['action']
    source=next((x for x in meta['sources'] if x['id']==meta['candidate_id']),None)
    knowledge=action in {'revise','supplement','split'}
    def validate(value):
        if knowledge:
            result=KnowledgeResult.model_validate(value)
            if len(result.items)>meta['limit'] or action=='revise' and len(result.items)!=1 or action=='split' and len(result.items)<2: raise ValueError('候选数量不符合定向任务要求')
            names=[x.body.name.strip().casefold() for x in result.items]
            if any(not x for x in names) or len(names)!=len(set(names)): raise ValueError('候选知识名称为空或重复')
            return result
        if action=='coverage':
            result=CoverageResult.model_validate(value)
            if len(result.suggestions)>meta['limit']: raise ValueError('完整性建议超过单批上限')
            for item in result.suggestions: validate_references(meta,'coverage',item.model_dump())
            return result
        result=RelationsResult.model_validate(value)
        if len(result.relations)>meta['limit']: raise ValueError('关系建议超过单批上限')
        seen=set()
        for edge in result.relations:
            validate_references(meta,'relation',edge.model_dump())
            key=(edge.source_id,edge.target_id,edge.relation_type)
            if key in seen: raise ValueError('关系候选重复')
            seen.add(key)
        return result
    task={
        'supplement':'起草新增知识，不重复已有条目；根据教师要求和选中意见提出独立条目。',
        'revise':'只修订指定知识，返回一个完整条目，针对选中意见纠错或补充条件。',
        'split':'拆分指定知识为至少两个独立条目，明确概念、性质、方法的主导类型，避免重复。',
        'coverage':'检查当前单元候选的遗漏、重复、过大条目及缺失连接。区分清单已列出但尚未展开（unexpanded）与清单本身遗漏（missing），不要把尚未展开当成知识遗漏。只提出可选补充建议，不能宣称完整覆盖课程标准。上限是每批建议数，不是知识总量。',
        'relations':'提出当前已有知识之间的有向关系。只用提供的knowledge_id作为端点；缺少知识不要编造端点。prerequisite为源是目标的前置；derives为源可在条件下推出目标；uses为源方法使用目标知识；contrast为从源对照目标；representation为源到目标的表示转化。相关不等于推导。'
    }[action]
    if knowledge:
        shape={'items':[{'body':BODY_SHAPE,'reason':'新增、修订或拆分理由'}]}
    elif action=='coverage':
        shape={'summary':'本轮检查范围与局限，不能断言完整','suggestions':[{'name':'建议知识名称','kind':'concept/property/theorem/method','category':'missing/unexpanded/overlap/oversized/connection','action':'supplement/revise/split','related_ids':['已有knowledge_id'],'reason':'遗漏或调整依据'}]}
    else:
        shape={'relations':[{'source_id':'已有knowledge_id','target_id':'已有knowledge_id','relation_type':'prerequisite/derives/uses/contrast/representation','reason':'关系依据','conditions':'成立与使用条件','example':'具体使用例子'}]}
    task+='返回严格JSON：'+packed(shape)+'。不把随机ID、未核验课标标志当成数学疑问。正文公式使用\\(和\\)，formula字段仅LaTeX。范围、教学、组织问题与数学错误分别说明。'
    payload={'unit':{k:v for k,v in snapshot.items() if k!='action_task'},'action':action,'sources':meta['sources'],'catalog':meta.get('catalog',[]),
        'target':source,'selected_issues':meta['issues'],'suggestions':meta['suggestions'],'teacher_instruction':meta['instruction'],'max_items':meta['limit']}
    result=call(run,config,'action:'+action,task,payload,7000 if knowledge else 4000,validate)
    values=[x.model_dump() for x in result.items] if knowledge else [x.model_dump() for x in (result.suggestions if action=='coverage' else result.relations)]
    checks=[]
    if knowledge:
        def validate_checks(value):
            parsed=Critic.model_validate(value)
            if any(x.knowledge_id not in {str(i) for i in range(len(values))} for x in parsed.issues): raise ValueError('定向复核引用不存在的候选编号')
            return parsed
        critic=call(run,config,'action:critic','作为单独一轮数学检查，返回 {"issues":[{"knowledge_id":"候选编号","category":"correctness/scope/organization/teaching/system/unclassified","message":"具体问题"}]}。区分数学错误与范围、教学和组织建议，不评价随机ID或未核验课标标志。',
            {'unit':payload['unit'],'candidates':[{'knowledge_id':str(i),'body':x['body']} for i,x in enumerate(values)]},2200,validate_checks)
        checks=[x.model_dump() for x in critic.issues]
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if not current(c,row(c,'knowledge_runs',run['id'])): raise ValueError('原知识已修订；结果不写入，请针对当前版本重建任务')
        # Whole output set is committed once. Cached calls make retries repeatable.
        if c.execute('SELECT count(*) FROM knowledge_outputs WHERE run_id=?',(run['id'],)).fetchone()[0]: raise ValueError('任务已有结果，拒绝重复写入')
        keys=[]
        for value in values:
            key=uid();keys.append(key)
            c.execute('INSERT INTO knowledge_outputs(id,run_id,type,body,original_body) VALUES(?,?,?,?,?)',
                (key,run['id'],'knowledge' if knowledge else 'coverage' if action=='coverage' else 'relation',packed(value),packed(value)))
        for check in checks: check['output_id']=keys[int(check['knowledge_id'])]
        if action=='coverage': checks=[{'knowledge_id':'','category':'system','message':result.summary}]
        c.execute("UPDATE knowledge_runs SET status='completed',stage='completed',checks=?,revision=revision+1,updated_at=? WHERE id=?",(packed(checks),now(),run['id']))
