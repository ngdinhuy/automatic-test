"""Phạm vi thống kê theo môi trường; không sửa lịch sử hoặc quyền chạy testcase."""
PROD_LOCATION_IDS=frozenset({'CHAT-031-PEER_CURRENT','CHAT-031-PEER_LIVE','CHAT-031-GROUP_CURRENT','CHAT-031-GROUP_LIVE'})


def split_location_prod(rows):
    staging=[row for row in rows if row['id'] not in PROD_LOCATION_IDS]
    prod=[{'id':row['id'],'name':row['name'],'status':'NOT_RUN','environment':'prod',
           'message':'Location chỉ nghiệm thu trên prod theo yêu cầu người dùng; chưa có lượt chạy prod.',
           'staging_history_status':row['status'],'staging_history_report':row.get('report')} for row in rows if row['id'] in PROD_LOCATION_IDS]
    return staging,prod
