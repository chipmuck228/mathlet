"""AI findings are review advice; teacher confirmation is the approval decision."""
from .db import now

def advisories(body,checks):
    result=[]
    for i,message in enumerate(body.get('missing_information',[])):
        result.append({'kind':'missing_information','path':'missing_information','title':f'条件／信息疑问 {i+1}','message':message,
          'guidance':'先对照原题、已知条件和当前解法检查这一条：若确实缺条件，请补充并确认题目后研究；若已具备或不影响当前解法，可由教师说明依据后认可；若是AI误判，可在中央正文“条件／信息核查意见”中修正或删除并保存。'})
    hints={'correctness':'核对所指步骤的计算、推理与结论；可直接编辑解法，或说明为什么该意见不适用。','condition':'核对原题条件是否已经明确，区分真实缺条件与AI误判。','scope':'结合学生学习范围和本节定位判断，不必将范围疑问当作数学错误。','teaching':'这是教学组织建议，由教师决定是否采用，不必作为定稿前置条件。','source':'对照原题及已确认的文字条件，核查是否使用了未经说明的图形关系。'}
    for i,check in enumerate(checks):
        result.append({'kind':'critic','path':'approaches','title':f'AI复核意见 {i+1}'+(' · 路径 '+check['approach_id'] if check.get('approach_id') else ''),'message':check['message'],'guidance':hints.get(check.get('category'),'核对具体意见，修改正文或记录教师判断依据。')})
    return result

def teacher_review(body,checks,note,revision,reviewer):
    return {'decision':'approved','reviewer':reviewer,'output_revision':revision,'acknowledged_advisories':True,'note':note.strip() or '教师已核查并认可当前研究稿；保留的AI意见不作为自动否决。','advisories':advisories(body,checks),'created_at':now()}
