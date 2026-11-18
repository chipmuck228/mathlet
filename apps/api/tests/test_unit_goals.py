"""Synthetic end-to-end goal paths. No user papers, credentials or paid calls."""
import copy
import json
import pytest
from test_knowledge import client
from test_review_units import prepare as prepare_research,model as unit_model,start,get,save,finish
from mathlet import knowledge_worker as worker
from mathlet.db import connect


def prepare(client,monkeypatch):
    original,finals,blocks=prepare_research(client,monkeypatch)
    draft=client.post('/api/editor/versions/'+original['id']+'/revise').json()
    # This test adds a synthetic scope to a NEW draft only; the immutable source
    # version is never changed. Exercise normal coverage-save and finalization APIs.
    spec={'objectives':[{'id':'g1','text':'能选择加减消元并求解','requirement_ids':[]},{'id':'g2','text':'能在实际情境中建立方程组','requirement_ids':[]},{'id':'g3','text':'一个尚缺基础说明的合成目标','requirement_ids':[]}],
          'required_content':['消元求解','实际建模'],'boundary_notes':'先研究初中基本解法','extension_candidates':[],'prerequisites':[],'connections':[],'difficulties':[],'presentation_hints':[],'evidence':[],'notes':'合成教研目标，不是课标原文'}
    with connect() as c:
        old=c.execute('SELECT input_json FROM knowledge_runs WHERE id=?',(draft['id'],)).fetchone()
        value=json.loads(old['input_json']);value['topic_spec']=spec
        c.execute('UPDATE knowledge_runs SET input_json=? WHERE id=?',(json.dumps(value),draft['id']))
    ctx=client.get('/api/knowledge-coverage/runs/'+draft['id']).json();rows=[]
    for t in ctx['targets']:
        kid='synthetic-5' if t['id'] in {'goal:g1','required:0'} else 'synthetic-7'
        missing=t['id']=='goal:g3'
        rows.append({'target_id':t['id'],'status':'missing' if missing else 'covered','links':[] if missing else [{'knowledge_id':kid,'fields':['statement','conditions'],'explanation':'合成基础内容已有说明'}],
                     'gap':'需要补基础内容' if missing else '', 'guidance':'回基础知识编制补充' if missing else ''})
    result=client.put('/api/knowledge-coverage/runs/'+draft['id'],json={'revision':draft['revision'],'source_hash':ctx['source_hash'],'result_id':ctx['result_id'],'report':{'rows':rows,'issues':[],'teacher_note':'合成测试教师判断'}})
    assert result.status_code==200,result.text
    final=client.post('/api/editor/runs/'+draft['id']+'/finalize',json={'revision':result.json()['revision'],'confirmed':True});assert final.status_code==201,final.text
    return final.json(),finals,blocks,original


def goal_model(config,system,payload,tokens):
    if '检查复习单元的目标对应' not in system:return unit_model(config,system,payload,tokens)
    rows=[];known=payload['knowledge'];aids=[s['analysis_id'] for s in payload['research_evidence']]
    for t in payload['targets']:
        first=t['id'] in {'goal:g1','required:0'};missing=t['id']=='goal:g3';ref=known[5 if first else 7]['ref']
        rows.append({'target_id':t['id'],'student_goal':'怎样根据系数选择消元方法？' if first else '',
            'knowledge_refs':[] if missing else [ref], 'analysis_ids':aids if first else [], 'card_indices':[0] if first and payload['cards'] and aids else [],
            'training_indices':list(range(len(payload['training']))) if first and aids else [],'expected_phases':['basic'] if missing else ['basic','thinking','solve'],
            'assessment':'arranged' if first and aids else 'partial','gap_types':[],
            'explanation':'有基础、具体消元研究和训练依据' if first else '尚缺对应研究题或基础内容',
            'guidance':'' if first and aids else '缺基础说明时回基础知识编制；缺研究题时补充合适题目，不强配现有题。'})
    return json.dumps({'rows':rows,'teacher_note':''}),None


def complete(client,monkeypatch):
    version,finals,blocks,original=prepare(client,monkeypatch);r=start(client,version)
    monkeypatch.setattr(worker,'generate',goal_model);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error']
    return r,version,finals,blocks,original


def test_goal_paths_distinguish_knowledge_and_research_gaps_and_student_links(client,monkeypatch):
    r,_,_,_,_=complete(client,monkeypatch)
    report=r['body']['goal_coverage'];assert report['report'] and r['goal_context']['state']=='current'
    statuses={v['target_id']:v for v in r['goal_context']['row_states']}
    assert statuses['goal:g1']['status']=='arranged'
    assert statuses['goal:g2']['status']=='partial' and 'research' in statuses['goal:g2']['gaps'] and 'knowledge' not in statuses['goal:g2']['gaps']
    assert statuses['goal:g3']['status']=='missing' and 'knowledge' in statuses['goal:g3']['gaps']
    assert len(r['calls'])==8 and not statuses['goal:g1']['gaps']
    assert 'transfer' not in statuses['goal:g1']['gaps']
    f=finish(client,r);assert f.status_code==201,f.text
    html=client.get('/api/review-units/versions/'+f.json()['id']+'/reader').text
    assert '想练哪一件事' in html and '怎样根据系数选择消元方法？' in html
    assert 'href="#training-1"' in html and 'id="training-1"' in html
    assert 'href="#thought-1"' in html and 'id="thought-1"' in html
    assert 'goal:g1' not in html and '待补充或' not in html
    assert report['report']['rows'][1]['guidance'] not in html


def test_teacher_can_edit_paths_without_ai_and_coverage_edits_do_not_stale_student_copy(client,monkeypatch):
    from mathlet.student_presentation import current_presentation
    r,_,_,_,_=complete(client,monkeypatch);assert current_presentation(r['body'],r['knowledge'])
    body=copy.deepcopy(r['body']);body['goal_coverage']['report']['teacher_note']='教师认可目前仅补充基本解法'
    changed=save(client,r,body);assert changed.status_code==200,changed.text
    changed=changed.json();assert changed['body']['goal_coverage']['origin']=='teacher'
    assert current_presentation(changed['body'],changed['knowledge'])
    assert save(client,r,body).status_code==409
    final=finish(client,changed);assert final.status_code==201,final.text
    url='/api/review-units/versions/'+final.json()['id']+'/download';old=client.get(url).content
    fork=client.post('/api/review-units/versions/'+final.json()['id']+'/revise').json()
    body=copy.deepcopy(fork['body']);body['training'][0]['prompt']='教师修改了训练任务'
    changed=save(client,fork,body);assert changed.status_code==200,changed.text
    changed=changed.json();assert changed['goal_context']['state']=='stale'
    assert finish(client,changed).status_code==201
    assert client.get(url).content==old


@pytest.mark.parametrize('kind',['target','knowledge','study','card','training','unrelated_study'])
def test_invalid_path_endpoints_cannot_be_approved_as_current(client,monkeypatch,kind):
    r,_,_,_,_=complete(client,monkeypatch);body=copy.deepcopy(r['body']);p=body['goal_coverage']['report']['rows'][0]
    if kind=='target':p['target_id']='foreign'
    if kind=='knowledge':p['knowledge_refs']=['foreign']
    if kind=='study':p['analysis_ids']=['foreign']
    if kind=='card':p['card_indices']=[99]
    if kind=='training':p['training_indices']=[99]
    if kind=='unrelated_study':p['knowledge_refs']=[r['knowledge']['items'][7]['ref']]
    response=save(client,r,body);assert response.status_code==422,response.text
    assert get(client,r)['revision']==r['revision']


def test_failed_goal_check_preserves_entire_draft_and_does_not_veto_final(client,monkeypatch):
    version,_,_,_=prepare(client,monkeypatch);r=start(client,version)
    def broken(config,system,payload,tokens):
        if '检查复习单元的目标对应' in system:return '{broken',None
        return unit_model(config,system,payload,tokens)
    monkeypatch.setattr(worker,'generate',broken);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed' and r['body']['training'] and r['body']['goal_coverage']['error']
    assert r['goal_context']['state']=='failed'
    assert finish(client,r).status_code==201


def check(client,r):return client.post('/api/review-units/runs/'+r['id']+'/goal-coverage',json={'revision':r['revision'],'run_revision':r['run_revision']})
def test_recheck_updates_only_correspondence_and_reuses_running_request(client,monkeypatch):
    r,_,_,_,_=complete(client,monkeypatch);oldbody=copy.deepcopy(r['body'])
    response=check(client,r);assert response.status_code==201,response.text
    assert check(client,r).json()['id']==response.json()['id']
    worker.run_one_knowledge();updated=get(client,r)
    assert updated['revision']==r['revision']+1 and updated['goal_coverage_task']['status']=='completed'
    assert {k:v for k,v in updated['body'].items() if k!='goal_coverage'}=={k:v for k,v in oldbody.items() if k!='goal_coverage'}
    assert updated['goal_context']['state']=='current'


def test_inflight_check_cannot_overwrite_teacher_edit_or_final(client,monkeypatch):
    r,_,_,_,_=complete(client,monkeypatch);assert check(client,r).status_code==201
    def editing(config,system,payload,tokens):
        b=copy.deepcopy(r['body']);b['title']='教师已经更新标题'
        response=save(client,r,b);assert response.status_code==200
        return goal_model(config,system,payload,tokens)
    monkeypatch.setattr(worker,'generate',editing);worker.run_one_knowledge();updated=get(client,r)
    assert updated['body']['title']=='教师已经更新标题' and updated['goal_coverage_task']['status']=='failed'
    assert check(client,updated).status_code==201
    frozen={}
    def finalizing(config,system,payload,tokens):
        response=finish(client,updated);assert response.status_code==201
        frozen['url']='/api/review-units/versions/'+response.json()['id']+'/download';frozen['bytes']=client.get(frozen['url']).content
        return goal_model(config,system,payload,tokens)
    monkeypatch.setattr(worker,'generate',finalizing);worker.run_one_knowledge()
    assert get(client,updated)['goal_coverage_task']['status']=='failed'
    assert client.get(frozen['url']).content==frozen['bytes']


def test_no_matching_paper_does_not_force_a_false_closed_loop(client,monkeypatch):
    version,_,_,_=prepare(client,monkeypatch);r=start(client,version)
    def unmatched(config,system,payload,tokens):
        if '逐一判断' in system:return json.dumps({'mappings':[{'analysis_id':s['id'],'relevance':'none','reason':'当前研究不支持本主题','links':[],'gaps':[]} for s in payload['reviewed_studies']]}),None
        return goal_model(config,system,payload,tokens)
    monkeypatch.setattr(worker,'generate',unmatched);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed' and r['body']['training']==[] and r['body']['cards']==[]
    assert 'research' in next(v['gaps'] for v in r['goal_context']['row_states'] if v['target_id']=='goal:g1')
    assert finish(client,r).status_code==201


def test_changed_source_stops_recheck_and_marks_the_live_path_stale(client,monkeypatch):
    r,_,_,blocks,_=complete(client,monkeypatch);assert check(client,r).status_code==201
    b=blocks[0];response=client.put('/api/blocks/'+b['id'],json={'revision':2,'text':b['text']+'条件修改','verified':True});assert response.status_code==200
    monkeypatch.setattr(worker,'generate',lambda *_:pytest.fail('stale source must not invoke model'))
    worker.run_one_knowledge();updated=get(client,r)
    assert updated['stale'] and updated['goal_context']['state']=='stale'
    assert not updated['goal_context']['row_states'] and updated['goal_coverage_task']['status']=='failed'


def test_student_routes_hide_editorial_copy_and_recheck_preserves_teacher_notes(client,monkeypatch):
    r,_,_,_,_=complete(client,monkeypatch)
    b=copy.deepcopy(r['body']);b['goal_coverage']['report']['teacher_note']='教师决定保留基础路径，应用题后续补充'
    b['goal_coverage']['report']['rows'][0]['student_goal']='core 需要教师审核 goal:g1'
    response=save(client,r,b);assert response.status_code==200,response.text
    r=response.json()
    assert 'core 需要教师审核 goal:g1' not in client.get('/api/review-units/runs/'+r['id']+'/preview').text
    assert check(client,r).status_code==201;worker.run_one_knowledge();updated=get(client,r)
    assert updated['body']['goal_coverage']['report']['teacher_note']=='教师决定保留基础路径，应用题后续补充'
    # An explicitly teacher-edited but polluted route is omitted from learner prose.
    preview=client.get('/api/review-units/runs/'+r['id']+'/preview').text
    assert 'core 需要教师审核 goal:g1' not in preview
