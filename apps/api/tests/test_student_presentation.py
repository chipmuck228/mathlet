"""Reading overlay generation, source preservation and immutable book redesign."""
import json
from test_knowledge import client
from test_review_units import complete,get,save,finish,model,prepare,start
from mathlet import knowledge_worker as worker
from mathlet.db import connect
from mathlet.student_presentation import current_presentation


def test_student_agent_generates_short_copy_with_coloured_comparison_and_source_math_preserved(client,monkeypatch):
    r,_,_,_=complete(client,monkeypatch);p=r['body']['presentation']
    assert p['agent']['model']=='test-model' and p['agent']['run_id']==r['id']
    assert p and len(p['knowledge'])==len(r['knowledge']['items']) and current_presentation(r['body'],r['knowledge'])
    html=client.get('/api/review-units/runs/'+r['id']+'/preview').text
    assert 'comparison' in html and 'tone-green' in html and 'tone-red' in html and '<svg' in html
    assert '正例 · 看看为什么对' in html and '反例与易错点' in html and '读完以后，试试这些事' in html
    assert '先别急着算' in html and '你能说清' in html and '@media print' in html
    from mathlet.formulas import render_text
    for k in r['knowledge']['items']:
        for key in ['statement','conditions','positive_example','misconception']:assert render_text(k['body'][key]) in html
    assert '<script' not in html and 'src="http' not in html and 'href="http' not in html


def test_existing_final_is_revised_then_student_agent_updates_only_overlay_and_new_version(client,monkeypatch):
    r,_,_,_=complete(client,monkeypatch);f=finish(client,r).json();url='/api/review-units/versions/'+f['id']+'/download';old=client.get(url).content
    fork=client.post('/api/review-units/versions/'+f['id']+'/revise').json();original={k:v for k,v in fork['body'].items() if k!='presentation'}
    req={'revision':fork['revision'],'run_revision':fork['run_revision'],'request_key':'student-presentation-existing-final'}
    task=client.post('/api/review-units/runs/'+fork['id']+'/presentation',json=req);assert task.status_code==201,task.text
    assert client.post('/api/review-units/runs/'+fork['id']+'/presentation',json=req).json()['id']==task.json()['id']
    monkeypatch.setattr(worker,'generate',model);worker.run_one_knowledge();updated=get(client,fork)
    assert updated['revision']==fork['revision']+1 and updated['presentation_task']['status']=='completed'
    assert {k:v for k,v in updated['body'].items() if k!='presentation'}==original
    assert current_presentation(updated['body'],updated['knowledge'])
    assert not updated['read_only'] and not updated['teacher_review']
    assert client.get(url).content==old
    f2=finish(client,updated);assert f2.status_code==201,f2.text
    assert client.get(url).content==old


def test_source_edits_mark_copy_stale_and_teacher_can_edit_copy_or_keep_source_text(client,monkeypatch):
    r,_,_,_=complete(client,monkeypatch);b=json.loads(json.dumps(r['body']));b['training'][0]['prompt']='教师修改后的当前任务'
    changed=save(client,r,b);assert changed.status_code==200,changed.text;r=changed.json()
    assert not current_presentation(r['body'],r['knowledge'])
    assert any('回退到当前正文' in a['message'] for a in r['advice'])
    html=client.get('/api/review-units/runs/'+r['id']+'/preview').text
    assert '教师修改后的当前任务' in html and '先别急着算。看看题目' not in html
    b=r['body'];b['presentation']['introduction']='教师审定的学生口吻导读';b['presentation']['agent']['model']='forged-model'
    changed=save(client,r,b);assert changed.status_code==200,changed.text;r=changed.json();assert current_presentation(r['body'],r['knowledge'])
    assert r['body']['presentation']['agent']['model']=='test-model'
    assert '教师审定的学生口吻导读' in client.get('/api/review-units/runs/'+r['id']+'/preview').text
    b=r['body'];b['presentation']=None
    changed=save(client,r,b);assert changed.status_code==200 and finish(client,changed.json()).status_code==201


def test_concurrent_teacher_save_prevents_agent_from_overwriting_work_and_keeps_old_final(client,monkeypatch):
    r,_,_,_=complete(client,monkeypatch)
    task=client.post('/api/review-units/runs/'+r['id']+'/presentation',json={'revision':r['revision'],'run_revision':r['run_revision'],'request_key':'student-agent-concurrent-change'});assert task.status_code==201,task.text
    changed=r['body'];changed['introduction']='生成期间教师保存的新内容';changed=save(client,r,changed);assert changed.status_code==200
    monkeypatch.setattr(worker,'generate',model);worker.run_one_knowledge();latest=get(client,r)
    assert latest['presentation_task']['status']=='failed' and latest['body']['introduction']=='生成期间教师保存的新内容'
    assert latest['revision']==changed.json()['revision']


def test_reading_agent_failure_does_not_block_math_manuscript_and_retry_reuses_successful_copy(client,monkeypatch):
    v,_,_=prepare(client,monkeypatch);r=start(client,v)
    def fail_reading(config,system,payload,tokens):
        if '学生阅读表达Agent' in system:raise ValueError('模拟表达服务失败')
        return model(config,system,payload,tokens)
    monkeypatch.setattr(worker,'generate',fail_reading);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed' and r['body']['presentation'] is None
    assert any('学生表达Agent未完成' in a['message'] for a in r['advice'])
    task=client.post('/api/review-units/runs/'+r['id']+'/presentation',json={'revision':r['revision'],'run_revision':r['run_revision'],'request_key':'student-agent-retry-checkpoints'}).json()
    failed=True;calls=[]
    def fail_opening(config,system,payload,tokens):
        nonlocal failed
        calls.append('opening' if 'cards' in payload else tuple(x['ref'] for x in payload.get('knowledge',[])))
        if 'cards' in payload and '学生阅读表达Agent' in system and failed:failed=False;raise ValueError('模拟导读步骤中断')
        return model(config,system,payload,tokens)
    monkeypatch.setattr(worker,'generate',fail_opening);worker.run_one_knowledge();r=get(client,r)
    assert r['presentation_task']['status']=='failed'
    response=client.post('/api/review-units/presentation-tasks/'+task['id']+'/retry',json={'revision':r['presentation_task']['revision']});assert response.status_code==200,response.text
    worker.run_one_knowledge();r=get(client,r);assert r['presentation_task']['status']=='completed'
    assert not any('学生表达Agent未完成' in a['message'] for a in r['advice'])
    assert len([x for x in calls if x!='opening'])==2 and calls.count('opening')==2


def test_teacher_edit_during_an_actual_presentation_call_wins_over_agent_response(client,monkeypatch):
    r,_,_,_=complete(client,monkeypatch)
    response=client.post('/api/review-units/runs/'+r['id']+'/presentation',json={'revision':r['revision'],'run_revision':r['run_revision'],'request_key':'student-agent-mid-call-change'});assert response.status_code==201
    changed=False
    def concurrent(config,system,payload,tokens):
        nonlocal changed
        value=model(config,system,payload,tokens)
        if not changed:
            changed=True;b=json.loads(json.dumps(r['body']));b['introduction']='教师在模型回复期间保存的导读';result=save(client,r,b);assert result.status_code==200,result.text
        return value
    monkeypatch.setattr(worker,'generate',concurrent);worker.run_one_knowledge();latest=get(client,r)
    assert changed and latest['presentation_task']['status']=='failed'
    assert latest['body']['introduction']=='教师在模型回复期间保存的导读'
    assert latest['presentation_task']['calls'][0]['status']=='succeeded'
