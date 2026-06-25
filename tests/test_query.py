from portfolio.query import query

DATA = '{"untriaged_count":0,"projects":[' \
       '{"name":"a","tier":"active","status":"active","stale":false,"open_backlog":2,"purpose":"react app"},' \
       '{"name":"b","tier":"parking","status":"idea","stale":true,"open_backlog":0,"purpose":"shell script"}]}'

def test_query_filters_by_tier():
    assert [r["name"] for r in query({"tier": "active"}, json_text=DATA)] == ["a"]

def test_query_filters_by_stale_and_status():
    assert [r["name"] for r in query({"stale": True}, json_text=DATA)] == ["b"]
    assert [r["name"] for r in query({"status": "active"}, json_text=DATA)] == ["a"]
