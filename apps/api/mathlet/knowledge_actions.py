"""Bounded editorial proposals; adopting a proposal is not mathematical approval."""
import json
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .db import connect, now, uid
from .knowledge import row, revision, current, packed, run_json, normalized_checks
from .knowledge_models import KnowledgeBody, Kind
from .model_provider import load_provider, public_provider

router=APIRouter(prefix='/api/knowledge',tags=['knowledge actions'])
Action=Literal['supplement','revise','split','coverage','relations']
Category=Literal['unclassified','correctness','scope','organization','teaching','system']

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
class StartAction(Strict):
    revision:int
    action:Action
    candidate_id:str|None=None
    issue_ids:list[str]=Field(default_factory=list,max_length=60)
    instruction:str=Field(default='',max_length=4000)
    limit:int=Field(default=3,ge=1,le=4)
    consent:bool=False
    suggestion_run_id:str|None=None
    suggestion_ids:list[str]=Field(default_factory=list,max_length=4)
class KnowledgeProposal(Strict):
    body:KnowledgeBody
    reason:str=Field(min_length=1,max_length=2000)
class KnowledgeResult(Strict):
    items:list[KnowledgeProposal]=Field(min_length=1,max_length=4)
class Gap(Strict):
    name:str=Field(min_length=1,max_length=160)
    kind:Kind
    category:Literal['missing','unexpanded','overlap','oversized','connection']
    action:Literal['supplement','revise','split']
    related_ids:list[str]=Field(default_factory=list,max_length=30)
    reason:str=Field(min_length=1,max_length=2500)
class CoverageResult(Strict):
    summary:str=Field(min_length=1,max_length=2000)
    suggestions:list[Gap]=Field(max_length=12)
class Relation(Strict):
    source_id:str
    target_id:str
    relation_type:Literal['prerequisite','derives','uses','contrast','representation']
    reason:str=Field(min_length=1,max_length=2500)
    conditions:str=Field(min_length=1,max_length=2500)
    example:str=Field(min_length=1,max_length=2500)
class RelationsResult(Strict):
    relations:list[Relation]=Field(max_length=12)


def outputs(c,run_id):
    return [dict(r)|{'body':json.loads(r['body']),'original_body':json.loads(r['original_body'])} for r in c.execute('SELECT * FROM knowledge_outputs WHERE run_id=? ORDER BY rowid',(run_id,))]


def relations(c,run_id):
    result=[]
    for r in c.execute('SELECT * FROM knowledge_relations WHERE run_id=? ORDER BY rowid',(run_id,)):
        value=dict(r);value['body']=json.loads(value['body'])
        a=c.execute('SELECT revision,review_state,scope FROM knowledge_candidates WHERE run_id=? AND knowledge_id=?',(run_id,value['body']['source_id'])).fetchone()
        b=c.execute('SELECT revision,review_state,scope FROM knowledge_candidates WHERE run_id=? AND knowledge_id=?',(run_id,value['body']['target_id'])).fetchone()
        value['stale']=bool(value['retired']) or not current(c,row(c,'knowledge_runs',run_id)) or not a or not b or a['revision']!=value['source_revision'] or b['revision']!=value['target_revision']
        value['usable']=not value['stale'] and all(x['review_state']=='approved' and x['scope']!='excluded' for x in [a,b])
        result.append(value)
    return result


@router.post('/runs/{run_id}/actions',status_code=201)
def start_action(run_id:str,body:StartAction):
    provider=load_provider()
    if not body.consent: raise HTTPException(422,'请确认向已保存模型发送知识、意见和补充要求')
    if not provider.api_key or not provider.model: raise HTTPException(422,'请先保存模型配置')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');base=row(c,'knowledge_runs',run_id);revision(base,body.revision)
        if base['status']!='completed' or not current(c,base) or json.loads(base['input_json']).get('action_task'):
            raise HTTPException(409,'请在当前已完成的知识批次发起任务')
        candidates=[dict(x)|{'body':json.loads(x['body'])} for x in c.execute('SELECT * FROM knowledge_candidates WHERE run_id=? ORDER BY rowid',(run_id,))]
        if not candidates: raise HTTPException(422,'尚无知识正文，不能检查或补充')
        source=next((x for x in candidates if x['id']==body.candidate_id),None)
        if body.candidate_id and not source: raise HTTPException(422,'所选知识不属于此批次')
        if body.action in {'revise','split'} and not source: raise HTTPException(422,'修订或拆分需要指定知识条目')
        if body.action=='split' and body.limit<2: raise HTTPException(422,'拆分至少需要2项')
        checks=normalized_checks(c,base);by_id={x['id']:x for x in checks}
        if len(set(body.issue_ids))!=len(body.issue_ids) or any(x not in by_id for x in body.issue_ids): raise HTTPException(422,'核查意见不存在或已变化')
        if source and any(by_id[x]['knowledge_id']!=source['knowledge_id'] for x in body.issue_ids): raise HTTPException(422,'核查意见不属于所选知识')
        suggestions=[]
        if body.suggestion_ids:
            if not body.suggestion_run_id: raise HTTPException(422,'缺少建议来源')
            suggestion_run=row(c,'knowledge_runs',body.suggestion_run_id)
            meta=json.loads(suggestion_run['input_json']).get('action_task',{})
            if meta.get('base_run_id')!=run_id or meta.get('base_revision')!=base['revision'] or suggestion_run['status']!='completed' or not current(c,suggestion_run): raise HTTPException(409,'完整性建议已过期')
            found={x['id']:x for x in outputs(c,body.suggestion_run_id) if x['type']=='coverage'}
            if len(set(body.suggestion_ids))!=len(body.suggestion_ids) or any(x not in found for x in body.suggestion_ids): raise HTTPException(422,'补充建议选择无效')
            suggestions=[found[x]['body'] for x in body.suggestion_ids]
        if body.action in {'supplement','revise','split'} and not (body.instruction.strip() or body.issue_ids or suggestions): raise HTTPException(422,'请选择核查意见或填写简短要求')
        reserve=9200 if body.action in {'supplement','revise','split'} else 4000
        if provider.output_token_budget<reserve: raise HTTPException(422,'本任务输出预留预算不足')
        snapshot=json.loads(base['input_json']);snapshot['prompt_version']='knowledge-actions-v1'
        # Source snapshots contain exactly editorial inputs, never credentials or raw files.
        snapshot['action_task']={'action':body.action,'base_run_id':run_id,'base_revision':base['revision'],
            'catalog':json.loads(base['catalog']),'candidate_id':body.candidate_id,'instruction':body.instruction,'limit':body.limit,
            'issues':[by_id[x] for x in body.issue_ids],'suggestions':suggestions,
            'sources':[{'id':x['id'],'knowledge_id':x['knowledge_id'],'revision':x['revision'],'body':x['body'],'scope':x['scope']} for x in candidates]}
        key=uid()
        c.execute('INSERT INTO knowledge_runs(id,unit_id,input_revision,input_json,model_json,status,stage,base_run_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (key,base['unit_id'],base['input_revision'],packed(snapshot),packed(public_provider(provider)),'queued','action',run_id,now(),now()))
        return run_json(c,row(c,'knowledge_runs',key))

class Classify(Strict):
    revision:int
    issue_id:str
    category:Category
    note:str=Field(min_length=1,max_length=2000)
@router.post('/runs/{run_id}/classify')
def classify(run_id:str,body:Classify):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');run=row(c,'knowledge_runs',run_id);revision(run,body.revision)
        if run['status']!='completed' or not current(c,run): raise HTTPException(409,'批次未完成或已过期')
        checks=normalized_checks(c,run);issue=next((x for x in checks if x['id']==body.issue_id),None)
        if not issue: raise HTTPException(404,'核查意见不存在')
        if not body.note.strip(): raise HTTPException(422,'请填写分类或处理依据')
        issue.update(category=body.category,classification_note=body.note)
        old=c.execute('SELECT * FROM knowledge_candidates WHERE run_id=? AND knowledge_id=?',(run_id,issue['knowledge_id'])).fetchone()
        if old:
            c.execute('INSERT INTO knowledge_candidate_history VALUES(?,?,?,?,?)',(uid(),old['id'],old['revision'],packed(dict(old)),now()))
            c.execute("UPDATE knowledge_candidates SET review_state='pending',reviewer='',revision=revision+1 WHERE id=?",(old['id'],))
        c.execute('UPDATE knowledge_runs SET checks=?,revision=revision+1,updated_at=? WHERE id=?',(packed(checks),now(),run_id))
        return run_json(c,row(c,'knowledge_runs',run_id))

class OutputEdit(Strict):
    revision:int
    body:dict
@router.put('/outputs/{output_id}')
def edit_output(output_id:str,body:OutputEdit):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');value=row(c,'knowledge_outputs',output_id);revision(value,body.revision);run=row(c,'knowledge_runs',value['run_id'])
        if not current(c,run) or run['status']!='completed' or value['state']!='pending': raise HTTPException(409,'结果已处理或来源过期')
        schemas={'knowledge':KnowledgeProposal,'relation':Relation,'coverage':Gap}
        if value['type'] not in schemas: raise HTTPException(422,'此结果请在内容规划中编辑')
        schema=schemas[value['type']]
        try: valid=schema.model_validate(body.body).model_dump()
        except ValueError: raise HTTPException(422,'候选内容结构无效') from None
        validate_references(json.loads(run['input_json'])['action_task'],value['type'],valid)
        c.execute('INSERT INTO knowledge_output_history VALUES(?,?,?,?,?)',(uid(),output_id,value['revision'],packed(value),now()))
        c.execute('UPDATE knowledge_outputs SET body=?,revision=revision+1 WHERE id=?',(packed(valid),output_id))
        c.execute('UPDATE knowledge_runs SET revision=revision+1 WHERE id=?',(run['id'],))
        return outputs(c,run['id'])


def validate_references(meta,kind,value):
    allowed={x['knowledge_id'] for x in meta['sources']}
    if kind=='relation' and (value['source_id'] not in allowed or value['target_id'] not in allowed or value['source_id']==value['target_id']):
        raise HTTPException(422,'关系端点缺失、越界或指向自身')
    if kind=='coverage' and not set(value['related_ids'])<=(allowed|{x['id'] for x in meta.get('catalog',[])}): raise HTTPException(422,'完整性建议引用了不存在的知识')

class OutputSelection(Strict):
    id:str
    revision:int=Field(ge=1)

class Apply(Strict):
    revision:int
    parent_revision:int
    outputs:list[OutputSelection]=Field(min_length=1,max_length=12)
    reviewer:str=Field(min_length=1,max_length=80)
    note:str=Field(min_length=1,max_length=3000)
    confirmed:bool=False
    decision:Literal['apply','reject']='apply'
@router.post('/runs/{task_id}/apply')
def apply_outputs(task_id:str,body:Apply):
    if not body.confirmed or not body.reviewer.strip() or not body.note.strip(): raise HTTPException(422,'请填写处理人、说明并明确确认')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');task=row(c,'knowledge_runs',task_id);revision(task,body.revision)
        meta=json.loads(task['input_json']).get('action_task')
        if not meta: raise HTTPException(422,'不是定向任务')
        base=row(c,'knowledge_runs',meta['base_run_id']);revision(base,body.parent_revision)
        if task['status']!='completed' or not current(c,task): raise HTTPException(409,'任务未完成或来源已过期')
        selected=[]
        if len({x.id for x in body.outputs})!=len(body.outputs): raise HTTPException(422,'重复结果')
        for requested in body.outputs:
            value=row(c,'knowledge_outputs',requested.id);revision(value,requested.revision)
            if value['run_id']!=task_id or value['state']!='pending': raise HTTPException(409,'结果已处理或不属于本任务')
            value['decoded']=json.loads(value['body']);selected.append(value)
        if body.decision=='apply' and any(x['type']=='coverage' for x in selected): raise HTTPException(422,'完整性建议请先发起定向生成，不可直接当作知识纳入')
        knowledge=[x for x in selected if x['type']=='knowledge']
        if body.decision=='apply' and meta['action']=='split' and len(knowledge)!=len(outputs(c,task_id)): raise HTTPException(422,'拆分需整体采纳，或整体退回后重新生成')
        if body.decision=='apply' and knowledge:
            catalog=json.loads(base['catalog']);ids=json.loads(base['selected_ids']);checks=normalized_checks(c,base)
            old=next((x for x in meta['sources'] if x['id']==meta['candidate_id']),None)
            if meta['action']=='split':
                target=row(c,'knowledge_candidates',old['id'])
                c.execute('INSERT INTO knowledge_candidate_history VALUES(?,?,?,?,?)',(uid(),target['id'],target['revision'],packed(target),now()))
                c.execute("UPDATE knowledge_candidates SET scope='excluded',review_state='pending',reviewer='',review_note=?,revision=revision+1 WHERE id=?",('已采纳拆分建议；原稿保留。'+body.note,target['id']))
            for value in knowledge:
                proposed=value['decoded'];kb=KnowledgeBody.model_validate(proposed['body']).model_dump()
                if meta['action']=='revise':
                    if any(x['id']!=old['id'] and json.loads(x['body'])['name'].strip().casefold()==kb['name'].strip().casefold() for x in c.execute('SELECT id,body FROM knowledge_candidates WHERE run_id=?',(base['id'],))): raise HTTPException(422,'修订后与已有知识同名，请区分名称')
                    target=row(c,'knowledge_candidates',old['id']);kid=target['knowledge_id']
                    c.execute('INSERT INTO knowledge_candidate_history VALUES(?,?,?,?,?)',(uid(),target['id'],target['revision'],packed(target),now()))
                    c.execute("UPDATE knowledge_candidates SET body=?,review_state='pending',reviewer='',review_note=?,revision=revision+1 WHERE id=?",(packed(kb),body.note,target['id']))
                    for entry in catalog:
                        if entry['id']==kid: entry.update(name=kb['name'],kind=kb['kind'])
                else:
                    if len(ids)>=30: raise HTTPException(422,'本批最多30项，请减少补充或拆分范围')
                    if any(json.loads(x['body'])['name'].strip().casefold()==kb['name'].strip().casefold() for x in c.execute('SELECT body FROM knowledge_candidates WHERE run_id=?',(base['id'],))): raise HTTPException(422,'已有同名知识，请编辑建议以区分或使用修订')
                    existing=next((x for x in catalog if x['id'] not in ids and x['name'].strip().casefold()==kb['name'].strip().casefold()),None)
                    if existing and existing['kind']!=kb['kind']: raise HTTPException(422,'已有未展开清单使用不同类型，请先明确条目名称和类型')
                    kid=existing['id'] if existing else uid();ids.append(kid)
                    if not existing: catalog.append({'id':kid,'name':kb['name'],'kind':kb['kind'],'reason':proposed['reason']})
                    c.execute('INSERT INTO knowledge_candidates(id,run_id,knowledge_id,body,original_body,review_note) VALUES(?,?,?,?,?,?)',(uid(),base['id'],kid,packed(kb),packed(value['original_body'] and json.loads(value['original_body'])['body']),body.note))
                # Attach independent checks to the resulting knowledge, not the temporary output id.
                for issue in json.loads(task['checks']):
                    if issue.get('output_id')==value['id']:
                        checks.append({'id':uid(),'knowledge_id':kid,'message':issue['message'],'category':issue.get('category','unclassified')})
            c.execute('UPDATE knowledge_runs SET catalog=?,selected_ids=?,checks=? WHERE id=?',(packed(catalog),packed(ids),packed(checks),base['id']))
        if body.decision=='apply':
            existing_edges={(x['body']['source_id'],x['body']['target_id'],x['body']['relation_type']) for x in relations(c,base['id']) if not x['stale']}
            for value in selected:
                if value['type']=='relation':
                    edge=Relation.model_validate(value['decoded']).model_dump();validate_references(meta,'relation',edge)
                    edge_key=(edge['source_id'],edge['target_id'],edge['relation_type'])
                    if edge_key in existing_edges: raise HTTPException(422,'同类型同方向关系已存在，请避免重复采纳')
                    existing_edges.add(edge_key)
                    endpoints=[c.execute('SELECT revision FROM knowledge_candidates WHERE run_id=? AND knowledge_id=?',(base['id'],edge[k])).fetchone() for k in ['source_id','target_id']]
                    if not all(endpoints): raise HTTPException(409,'关系端点已不存在')
                    c.execute('INSERT INTO knowledge_relations(id,run_id,task_id,output_id,body,source_revision,target_revision,reviewer,review_note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(uid(),base['id'],task_id,value['id'],packed(edge),endpoints[0]['revision'],endpoints[1]['revision'],body.reviewer,body.note,now()))
        for value in selected:
            c.execute('UPDATE knowledge_outputs SET state=?,reviewer=?,note=?,revision=revision+1 WHERE id=?',('applied' if body.decision=='apply' else 'rejected',body.reviewer,body.note,value['id']))
        c.execute('UPDATE knowledge_runs SET revision=revision+1,updated_at=? WHERE id=?',(now(),task_id))
        # Adopting results changes the parent; rejection only annotates the proposal.
        if body.decision=='apply': c.execute('UPDATE knowledge_runs SET revision=revision+1,updated_at=? WHERE id=?',(now(),base['id']))
        return run_json(c,row(c,'knowledge_runs',base['id']))

@router.get('/outputs/{output_id}/history')
def output_history(output_id:str):
    with connect() as c:
        row(c,'knowledge_outputs',output_id)
        return [dict(x)|{'snapshot':json.loads(x['snapshot'])} for x in c.execute('SELECT * FROM knowledge_output_history WHERE output_id=? ORDER BY revision DESC',(output_id,))]

class Retire(Strict):
    revision:int
    reviewer:str=Field(min_length=1,max_length=80)
    note:str=Field(min_length=1,max_length=3000)
    confirmed:bool=False
@router.post('/runs/{run_id}/relations/{relation_id}/retire')
def retire_relation(run_id:str,relation_id:str,body:Retire):
    if not body.confirmed: raise HTTPException(422,'请明确确认撤回关系')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');run=row(c,'knowledge_runs',run_id);revision(run,body.revision)
        edge=row(c,'knowledge_relations',relation_id)
        if not current(c,run) or run['status']!='completed' or edge['run_id']!=run_id or edge['retired']: raise HTTPException(409,'关系不属于当前批次、已过期或已撤回')
        # Preserve original approval and body; append the withdrawal evidence.
        c.execute('UPDATE knowledge_relations SET retired=1,review_note=? WHERE id=?',(edge['review_note']+'\n撤回：'+body.reviewer+'；'+body.note,relation_id))
        c.execute('UPDATE knowledge_runs SET revision=revision+1,updated_at=? WHERE id=?',(now(),run_id))
        return run_json(c,row(c,'knowledge_runs',run_id))
