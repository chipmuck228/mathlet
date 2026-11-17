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


def test_editorial_summary_never_becomes_student_intro_and_internal_ids_get_readable_names(client,monkeypatch):
    r,_,_,_=complete(client,monkeypatch)
    ids=r['body']['selected_analysis_ids'];report=f'从三道代表题归纳出共用线索，{ids[0][:4]} 与 {ids[1][:5]} 的知识映射均为 core，另一题为 optional 背景联系，未单独成卡。完整推理需教师核对解答。'
    b=json.loads(json.dumps(r['body']));b['introduction']=report;b['summary']=report;b['presentation']=None
    response=save(client,r,b);assert response.status_code==200,response.text;r=response.json()
    html=client.get('/api/review-units/runs/'+r['id']+'/preview').text
    assert '知识映射均为' not in html and '未单独成卡' not in html and '需教师核对' not in html
    from lxml.html import fromstring
    page=fromstring(html)
    for node in page.xpath('//style'):node.drop_tree()
    visible=page.text_content()
    assert 'core' not in visible and 'optional' not in visible and ids[0][:4] not in visible and ids[1][:5] not in visible
    assert '例题 1' in html and '例题 2' in html and '把下面的知识和例题' in html
    assert r['body']['summary']==report  # Teacher report remains intact for audit and editing.
    old=finish(client,r);assert old.status_code==201,old.text
    url='/api/review-units/versions/'+old.json()['id']+'/download';original=client.get(url).content
    fork=client.post('/api/review-units/versions/'+old.json()['id']+'/revise').json()
    task=client.post('/api/review-units/runs/'+fork['id']+'/presentation',json={'revision':fork['revision'],'run_revision':fork['run_revision'],'request_key':'clean-editorial-student-copy'});assert task.status_code==201,task.text
    sent=[]
    def capture(config,system,payload,tokens):
        sent.append(payload);encoded=json.dumps(payload)
        assert all(key not in encoded for key in ids)
        assert 'optional' not in encoded and '"scope"' not in encoded and '知识映射均为' not in encoded
        return model(config,system,payload,tokens)
    monkeypatch.setattr(worker,'generate',capture);worker.run_one_knowledge();next_draft=get(client,fork)
    assert next_draft['presentation_task']['status']=='completed',next_draft['presentation_task']['error']
    assert next_draft['body']['presentation']['summary'] and next_draft['body']['summary']==report
    final=finish(client,next_draft);assert final.status_code==201,final.text
    html=client.get('/api/review-units/versions/'+final.json()['id']+'/download').text
    assert '先看题目给了什么相等关系' in html and report not in html and 'optional' not in html and 'core' not in html
    assert client.get(url).content==original


def test_agent_rewrites_a_contaminated_opening_once_and_keeps_teacher_notes_separate(client,monkeypatch):
    v,_,_=prepare(client,monkeypatch);r=start(client,v);attempts=0
    def contaminated(config,system,payload,tokens):
        nonlocal attempts
        raw,usage=model(config,system,payload,tokens)
        if '学生阅读表达Agent' in system and 'cards' in payload:
            attempts+=1;value=json.loads(raw)
            if attempts==1:value['summary']='b202 的知识映射为 core，需教师核对。'
            else:value['review_notes']=['教师可以核对本段是否足够清楚。']
            return json.dumps(value),usage
        return raw,usage
    monkeypatch.setattr(worker,'generate',contaminated);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed' and r['body']['presentation'] and attempts==2
    assert any(x['step'].endswith(':clean') and x['status']=='succeeded' for x in r['calls'])
    assert any('教师可以核对' in a['message'] for a in r['advice'])
    html=client.get('/api/review-units/runs/'+r['id']+'/preview').text
    assert '教师可以核对' not in html and 'b202' not in html and 'core' not in html


def test_public_example_aliases_preserve_formula_symbols_and_avoid_ambiguous_prefixes():
    from mathlet.student_language import aliases,public_text
    body={'selected_analysis_ids':['b2020000','b2021111','a7a66000']}
    names=aliases(body,{'items':[]})
    assert 'b202' not in names and names['a7a66']=='例题 3'
    assert public_text('`a7a66`',names)=='例题 3'
    assert public_text(r'a7a66 与 b2020000；数学符号\(b2020000+1\)',names)==r'例题 3 与 例题 1；数学符号\(b2020000+1\)'


def test_published_library_lists_only_immutable_final_deliveries(client,monkeypatch):
    assert client.get('/api/review-units/published').json()==[]
    r,_,_,_=complete(client,monkeypatch)
    assert client.get('/api/review-units/published').json()==[]
    f=finish(client,r).json()
    listed=client.get('/api/review-units/published').json()
    assert len(listed)==1 and listed[0]['id']==f['id']
    assert listed[0]['title']==r['body']['title']
    assert listed[0]['knowledge_count']==len(r['knowledge']['items'])
    original=client.get('/api/review-units/versions/'+f['id']+'/download').content
    client.post('/api/review-units/versions/'+f['id']+'/revise')
    assert client.get('/api/review-units/published').json()==listed
    assert client.get('/api/review-units/versions/'+f['id']+'/download').content==original
