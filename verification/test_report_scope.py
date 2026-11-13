"""Log staging không biến thành kết quả nghiệm thu location prod."""
from tammi_runner.report_scope import split_location_prod,PROD_LOCATION_IDS


def test_location_results_remain_history_without_counting_as_prod_results():
    rows=[{'id':case_id,'name':'location','status':status,'report':'old-run/report.html'} for case_id,status in zip(sorted(PROD_LOCATION_IDS),['FAIL','ERROR','BLOCKED','BLOCKED'])]
    rows.append({'id':'CHAT-004-VOICE','name':'voice','status':'BLOCKED'})
    staging,prod=split_location_prod(rows)
    assert [row['id'] for row in staging]==['CHAT-004-VOICE']
    assert len(prod)==4 and all(row['status']=='NOT_RUN' and row['environment']=='prod' for row in prod)
    assert {row['staging_history_status'] for row in prod}=={'FAIL','ERROR','BLOCKED'}
    assert rows[0]['status']=='FAIL'
