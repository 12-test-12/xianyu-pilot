"""Run the original console contracts against a real local SQLite database."""
import asyncio
import json
from pathlib import Path
import re
import sqlite3
import socket
import time
import httpx

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.core.database import DatabaseRuntime
from app.core.sqlite_compat import translate_sql
from app.desktop_app import create_desktop_app


def test_native_backend_shutdown_does_not_wait_forever_for_the_console_sse(tmp_path,monkeypatch):
    from app.core import paths
    from app.core.instance_lock import SingleInstance
    from app.portable.backend import DesktopBackend
    monkeypatch.setattr(paths,'SOURCE_ROOT',tmp_path)
    with socket.socket() as socket_probe:
        socket_probe.bind(('127.0.0.1',0))
        port=socket_probe.getsockname()[1]
    config=Settings(runtime_mode='desktop',desktop_port=port)
    config.desktop_data_path.mkdir(parents=True)
    with SingleInstance(config.desktop_data_path) as lock:
        backend=DesktopBackend(config,tmp_path/'web',lock)
        backend.start()
        try:
            deadline=time.monotonic()+10
            while not backend.ready and time.monotonic()<deadline:time.sleep(0.02)
            assert backend.ready,backend.error
            with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,timeout=5) as client:
                headers={'Authorization':'Bearer '+backend.app.state.desktop_token}
                ticket=client.post('/api/sse/ticket',headers=headers).json()['data']['ticket']
                with client.stream('GET','/api/sse/subscribe',params={'ticket':ticket}) as stream:
                    assert 'connected' in next(stream.iter_lines())
                    backend.stop()
                    backend.thread.join(timeout=5)
                    assert backend.stopped,'native shutdown is blocked by the browser SSE connection'
        finally:
            backend.stop()
            backend.thread.join(timeout=5)


@pytest.fixture
def console(tmp_path,monkeypatch):
    from app.core import paths
    monkeypatch.setattr(paths,'SOURCE_ROOT',tmp_path)
    web=tmp_path/'web'
    (web/'assets').mkdir(parents=True)
    original=Path(__file__).resolve().parents[2]/'web/index.html'
    (web/'index.html').write_bytes(original.read_bytes())
    (web/'assets/module.js').write_text('export {}',encoding='utf-8')
    (web/'xya/brand').mkdir(parents=True)
    (web/'xya/brand/icon.png').write_bytes(b'fixture image')
    config=Settings(runtime_mode='desktop')
    monkeypatch.setattr(config, 'scheduler_poll_interval_seconds', 1)
    app=create_desktop_app(config,web_dir=web)
    with TestClient(app,base_url='http://127.0.0.1:15177') as client:
        html=client.get('/')
        marker=re.search(r'name="xianyu-desktop-bootstrap" content="([^"]+)"',html.text)[1]
        session=client.post('/api/desktop/session',json={},headers={'X-Desktop-Bootstrap':marker})
        client.headers['Authorization']='Bearer '+session.json()['data']['token']
        yield client,config,app


def test_scheduled_task_enable_runs_automatically_and_disable_preserves_result(console, monkeypatch):
    from app.services.scheduled_task_runtime import ScheduledTaskExecutor, TaskExecutionOutcome

    async def execute(self, task):
        return TaskExecutionOutcome(status="success", result={"synced": 3})

    monkeypatch.setattr(ScheduledTaskExecutor, "execute", execute)
    client, config, _ = console
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute("INSERT INTO xianyu_account(id, status, deleted) VALUES(11, 1, 0)")

    route = "/api/scheduled-tasks"
    created = client.post(route, json={
        "taskName": "定时同步商品", "taskType": "sync_goods", "cronExpression": "0 8 * * *",
        "accountId": 11, "enabled": False,
    }).json()["data"]
    task_id = created["id"]
    toggle = f"{route}/{task_id}/enabled"
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute("UPDATE scheduled_task SET lease_until='2099-01-01' WHERE id=?", (task_id,))
    assert client.patch(toggle, json={"enabled": 1}).status_code == 409
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute("UPDATE scheduled_task SET lease_until=NULL WHERE id=?", (task_id,))
    assert client.patch(toggle, json={"enabled": 1}).json()["data"]["enabled"] == 1
    task = client.get(route).json()["data"]["records"][0]
    assert task["nextRunTime"]
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute("UPDATE scheduled_task SET next_run_time='2000-01-01' WHERE id=?", (task_id,))

    deadline = time.monotonic() + 5
    while task["lastStatus"] != "success" and time.monotonic() < deadline:
        time.sleep(0.05)
        task = client.get(route).json()["data"]["records"][0]
    assert task["lastStatus"] == "success"
    assert task["lastResult"]["result"] == {"synced": 3}
    assert client.patch(toggle, json={"enabled": 0}).json()["data"]["enabled"] == 0
    disabled = client.get(route).json()["data"]["records"][0]
    assert disabled["nextRunTime"] is None
    assert disabled["lastResult"] == task["lastResult"]


@pytest.mark.asyncio
async def test_console_services_stops_scheduler_gracefully():
    from app.desktop_console import ConsoleServices

    gate = type("Gate", (), {"blocked": False, "reasons": []})()
    delivery = type("Delivery", (), {"_stopping": False, "wake_probe": asyncio.Event(), "interval": 10})()
    config = type("Config", (), {"scheduler_batch_size": 10, "scheduler_poll_interval_seconds": 60})()
    services = ConsoleServices(gate, delivery, config)
    completed = False

    async def fake_run_due_once(*args, **kwargs):
        nonlocal completed
        await asyncio.sleep(0.05)
        completed = True
        return {"processed": 1}

    fake_runtime = type("Runtime", (), {"run_due_once": fake_run_due_once})()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.services.scheduled_task_runtime.get_scheduled_task_runtime", lambda: fake_runtime)
        services.scheduler_task = asyncio.create_task(services.poll_scheduled_tasks())
        await asyncio.sleep(0.01)
        await services.stop()

    assert completed is True
    assert services.scheduler_task.done()
    assert not services.scheduler_task.cancelled()


def test_original_index_assets_session_and_boundary(console):
    client,config,app=console
    page=client.get('/')
    assert page.status_code==200 and 'text/html' in page.headers['content-type']
    assert '/src/main.js' in page.text and '发货安全工作台' not in page.text
    assert page.headers['cache-control']=='no-store'
    assert client.get('/assets/module.js').text=='export {}'
    assert client.get('/xya/brand/icon.png').content==b'fixture image'
    assert client.get('/api/does-not-exist').status_code==404
    assert client.get('/api/xianyu/accounts',headers={'Authorization':''}).status_code==401
    assert client.post('/api/desktop/session',json={}).status_code==403
    assert client.post('/api/desktop/session',json={},headers={'Origin':'https://outside.example','X-Desktop-Bootstrap':app.state.desktop_bootstrap}).status_code==403


@pytest.mark.parametrize('upstream_status', [200, 401, 429])
def test_ai_customer_service_with_deepseek(console, monkeypatch, upstream_status):
    from app.core.upload_security import PublicHTTPResponse
    from app.services import ai_provider

    async def complete(url, **kwargs):
        assert url == 'https://api.deepseek.com/chat/completions'
        assert json.loads(kwargs['content'])['model'] == 'deepseek-flash'
        body = (b'{"choices":[{"message":{"content":"Hello"}}]}' if upstream_status == 200
                else b'{"error":{"message":"private upstream diagnostic"}}')
        return PublicHTTPResponse(upstream_status, httpx.Headers(), body)

    monkeypatch.setattr(ai_provider, 'request_public_https', complete)
    client, _, _ = console
    saved = client.put('/api/system/open-source-config', json={'generalModel': {
        'provider': 'deepseek', 'modelName': 'deepseek-flash',
        'baseUrl': 'https://api.deepseek.com/anthropic/', 'apiKey': 'fixture-deepseek-key',
    }})
    assert saved.json()['code'] == 200
    response = client.post('/api/business-settings/ai-customer-service/test', json={'message': 'Hello'})
    if upstream_status == 200:
        assert response.status_code == 200
        assert response.json()['data']['reply'] == 'Hello'
    else:
        assert response.status_code == 503
        expected = '模型服务拒绝了 API Key' if upstream_status == 401 else '模型服务请求过于频繁'
        assert expected in response.text
        assert 'private upstream diagnostic' not in response.text


def test_ai_customer_service_openai_endpoint_and_text_parts(console, monkeypatch):
    from app.core.upload_security import PublicHTTPResponse
    from app.services import ai_provider

    async def complete(url, **kwargs):
        assert url == 'https://models.example/v2/chat/completions'
        assert json.loads(kwargs['content'])['model'] == 'example-chat'
        return PublicHTTPResponse(200, httpx.Headers(),
            b'{"choices":[{"message":{"content":[{"type":"text","text":"Hello"}]}}]}')

    monkeypatch.setattr(ai_provider, 'request_public_https', complete)
    client, _, _ = console
    saved = client.put('/api/system/open-source-config', json={'generalModel': {
        'provider': 'openai', 'modelName': 'example-chat',
        'baseUrl': 'https://models.example/v2/chat/completions', 'apiKey': 'fixture-model-key',
    }})
    assert saved.json()['code'] == 200
    response = client.post('/api/business-settings/ai-customer-service/test', json={'message': 'Hello'})
    assert response.json()['data']['reply'] == 'Hello'


def test_ai_customer_service_latest_automatic_result_contains_only_diagnostics(console):
    client, config, _ = console
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute("""INSERT INTO message_automation_outbox
            (account_id,chat_message_id,source_message_digest,branch,state,retry_safe,attempt_count,last_error_code,updated_time)
            VALUES(1,1,'digest','ai','completed',0,1,'scope_disabled',CURRENT_TIMESTAMP)""")
    response = client.get('/api/auto-reply-scope/latest-run')
    assert response.status_code == 200
    data = response.json()['data']
    assert set(data) == {'state', 'reason', 'updatedAt'}
    assert data['reason'] == 'scope_disabled'


@pytest.mark.asyncio
async def test_automatic_reply_requires_opt_in_and_sends_after_platform_ack(tmp_path, monkeypatch):
    from app.core import paths, secret_store
    from app.core.database import use_database_runtime
    from app.desktop_storage import DesktopStore
    from app.services import automation_runtime, ws_startup
    from app.services.business_settings import save_raw_business_setting

    monkeypatch.setattr(paths, 'SOURCE_ROOT', tmp_path)
    config = Settings(runtime_mode='desktop')
    monkeypatch.setattr(secret_store, 'settings', config)
    DesktopStore(config.sqlite_path).initialize()
    runtime = DatabaseRuntime(config)
    sent = []

    class Client:
        is_connected = True
        _sid = 'registered'

        async def send_text_message(self, *, cid, to_id, text, persist):
            assert (cid, to_id, persist) == ('session@goofish', 'buyer@goofish', False)
            sent.append(text)
            return {'code': 200}

    async def load_model():
        return {'enabled': True, 'base_url': 'https://models.example', 'model': 'example-chat', 'api_key': 'fixture-model-key'}

    async def generate(**kwargs):
        assert kwargs['messages'][-1]['content'] == '现在有货吗？'
        return {'ok': True, 'content': '您好，有货。'}

    monkeypatch.setitem(automation_runtime.ws_manager._clients, 1, Client())
    monkeypatch.setattr(automation_runtime, '_resolve_ai_config', load_model)
    monkeypatch.setattr(automation_runtime, 'generate_text', generate)
    messages = [{'sId': 'session', 'pnmId': 'inbound', 'senderUserId': 'buyer', 'msgContent': '现在有货吗？'}]
    with use_database_runtime(runtime):
        async with runtime.session() as db:
            await save_raw_business_setting(db, 'ai-customer-service', {'enabled': True})
            await db.commit()
        await ws_startup._dispatch_ai_auto_reply_batch(1, messages, 'seller')
        assert not sent
        async with runtime.session() as db:
            await save_raw_business_setting(db, 'auto-reply-account-scopes', {'accounts': {'1': True}})
            await db.commit()
        await ws_startup._dispatch_ai_auto_reply_batch(1, messages, 'seller')
        await runtime.dispose()
    assert sent == ['您好，有货。']
    with sqlite3.connect(config.sqlite_path) as db:
        assert db.execute('SELECT state FROM ai_auto_reply_attempt').fetchone() == ('confirmed',)


def test_desktop_source_apply_creates_the_rules_used_by_paid_orders(console):
    from app.services.unified_delivery_rules import UnifiedDeliveryRules

    client, config, _ = console
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute("INSERT INTO xianyu_account(id,external_uid,nickname,deleted,status) VALUES(11,'fixture-seller','本机账号',0,1)")
        db.execute("INSERT INTO xianyu_goods(id,account_id,external_goods_id,title,deleted,status,auto_relist_enabled,has_snapshot) VALUES(21,11,'fixture-item','测试商品',0,1,0,0)")
        db.execute("INSERT INTO xianyu_goods_sku(goods_id,account_id,sku_id,property_key) VALUES(21,11,'sku-one','one'),(21,11,'sku-two','two')")
        db.execute("INSERT INTO delivery_text_source(id,title,content,deleted) VALUES(5,'测试货源','测试发货内容',0)")
    response = client.post('/api/auto-delivery/sources/5/apply', json={'goodsIds': [21], 'timing': 'payDelivery'})
    assert response.status_code == 200, response.text
    assert response.json()['data']['appliedCount'] == 1
    for sku in ('sku-one', 'sku-two'):
        _, rule = UnifiedDeliveryRules(config.sqlite_path).resolve(11, 'fixture-item', sku)
        assert rule.enabled and rule.trigger.mode == 'payment'
        assert rule.plan.parts[0].content == '测试发货内容'
        assert rule.plan.source_id == 5
    detail = client.get('/api/auto-delivery/sources/5/goods').json()['data']
    assert detail['source']['usageCount'] == 1
    assert [goods['id'] for goods in detail['configuredGoods']] == [21]
    assert client.get('/api/auto-delivery/sources').json()['data']['records'][0]['usageCount'] == 1
    # Disabling a rule keeps its source association; unbinding must disable execution too.
    rules = client.get('/api/auto-delivery/goods/21/config').json()['data']
    rules['variants'][0]['enabled'] = False
    saved = client.put('/api/auto-delivery/goods/21/config', json={
        'expectedVersion': rules['version'], 'variants': rules['variants']})
    assert saved.status_code == 200
    assert client.get('/api/auto-delivery/sources/5/goods').json()['data']['source']['usageCount'] == 1
    removed = client.delete('/api/auto-delivery/sources/5/goods/21', headers={'Content-Type': 'application/json'})
    assert removed.status_code == 200, removed.text
    assert removed.json()['data']['updated'] is True
    assert client.get('/api/auto-delivery/sources/5/goods').json()['data']['configuredGoods'] == []
    for variant in client.get('/api/auto-delivery/goods/21/config').json()['data']['variants']:
        assert not variant['enabled'] and variant['plan']['sourceId'] is None
    assert client.delete('/api/auto-delivery/sources/5/goods/21', headers={'Content-Type': 'application/json'}).json()['data']['updated'] is False
    saved = client.put('/api/auto-delivery/goods/21/config', json={
        'skuId': 'sku-one', 'enabled': True, 'sourceId': 5, 'content': '独立修改的内容'})
    assert saved.status_code == 200
    assert client.get('/api/auto-delivery/sources/5/goods').json()['data']['source']['usageCount'] == 1
    assert UnifiedDeliveryRules(config.sqlite_path).resolve(11, 'fixture-item', 'sku-one')[1].plan.parts[0].content == '独立修改的内容'
    invalid = client.put('/api/auto-delivery/goods/21/config', json={
        'skuId': 'sku-one', 'enabled': True, 'sourceId': 999, 'content': '无效货源'})
    assert invalid.status_code == 404


@pytest.mark.asyncio
async def test_conversation_uses_account_scoped_order_nickname(console):
    from app.services.ws_storage import _enrich_online_conversations_batch

    _, config, _ = console
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute("INSERT INTO xianyu_trade_order(account_id,external_order_id,buyer_id,buyer_name,deleted) VALUES(11,'fixture-order','123456','买家真实昵称',0)")
    runtime = DatabaseRuntime(config)
    try:
        async with runtime.session() as db:
            rows = await _enrich_online_conversations_batch(db, 11, [
                {"sid": "888", "peerUserId": "123456@goofish", "peerUserName": "123456"},
            ])
        assert rows[0]['peerUserName'] == '买家真实昵称'
    finally:
        await runtime.dispose()


@pytest.mark.asyncio
async def test_conversation_placeholder_does_not_override_a_known_buyer(console):
    from app.services.ws_storage import _backfill_online_conversation_records

    _, config, _ = console
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute("""INSERT INTO xianyu_conversation(account_id,s_id,peer_key,peer_external_uid,buyer_name)
            VALUES(11,'777@goofish','sid:777@goofish','123456','买家真实昵称'),
                  (11,'777','sid:777','123456','oofish'),
                  (12,'777','sid:777','123456','其他账号昵称')""")
    runtime = DatabaseRuntime(config)
    try:
        async with runtime.session() as db:
            rows = await _backfill_online_conversation_records(db, 11, [
                {"sid": "777", "peerUserId": "123456@goofish", "peerUserName": "oofish"},
            ])
        assert rows[0]['peerUserName'] == '买家真实昵称'
    finally:
        await runtime.dispose()


def test_desktop_conversation_profile_reads_local_auth(console, monkeypatch):
    from app.core.cookie_crypto import encrypt_cookie_for_storage
    from app.services import xianyu_api_service

    _, config, _ = console
    monkeypatch.setattr(xianyu_api_service, 'settings', config)
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute("INSERT INTO xianyu_account(id,external_uid,nickname,deleted,status) VALUES(11,'fixture-seller','本机账号',0,1)")
        db.execute("""INSERT INTO xianyu_account_auth(account_id,encrypted_cookie,cookie_status,last_login_status_code,updated_time,deleted)
            VALUES(11, ?, 1, 'OK', '2020-01-01 00:00:00', 0)""",
            (encrypt_cookie_for_storage('old_cookie; _m_h5_tk=old_tk'),)
        )
    assert xianyu_api_service._get_account_auth(11) is not None
    assert xianyu_api_service._get_account_auth(12) is None

    # Refresh cookie with matching previous_cookie updates credentials and updated_time
    xianyu_api_service._persist_account_auth_cookies(11, 'new_cookie; _m_h5_tk=new_tk', previous_cookie='old_cookie; _m_h5_tk=old_tk')
    with sqlite3.connect(config.sqlite_path) as db:
        row = db.execute("SELECT encrypted_cookie, encrypted_token, updated_time FROM xianyu_account_auth WHERE account_id=11").fetchone()
    assert xianyu_api_service._decrypt_value(row[0]) == 'new_cookie; _m_h5_tk=new_tk'
    assert xianyu_api_service._decrypt_value(row[1]) == 'new_tk'
    assert row[2] != '2020-01-01 00:00:00'

    # Stale previous_cookie does not update (CAS guard)
    xianyu_api_service._persist_account_auth_cookies(11, 'stale_write', previous_cookie='wrong_cookie')
    with sqlite3.connect(config.sqlite_path) as db:
        row2 = db.execute("SELECT encrypted_cookie FROM xianyu_account_auth WHERE account_id=11").fetchone()
    assert xianyu_api_service._decrypt_value(row2[0]) == 'new_cookie; _m_h5_tk=new_tk'


def test_original_business_modules_use_real_persistent_storage(console):
    client,config,app=console
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute("INSERT INTO xianyu_account(id,external_uid,nickname,deleted,status) VALUES(11,'fixture-seller','本机账号',0,1)")
        db.execute("INSERT INTO xianyu_goods(id,account_id,external_goods_id,title,deleted,status,auto_relist_enabled,has_snapshot) VALUES(21,11,'fixture-item','本机商品',0,1,0,0)")
        db.execute("INSERT INTO operation_log(operator,operation_type,operation_desc) VALUES('本机管理员','fixture','真实数据库记录')")
        db.execute("INSERT INTO xianyu_trade_order(id,account_id,external_order_id,buyer_name,total_amount,order_status,deleted,created_time) VALUES(31,11,'fixture-order','买家甲','10.50',2,0,'2030-01-02 12:00:00')")
    for endpoint in ('/api/xianyu/accounts','/api/xianyu/accounts/summary','/api/goods','/api/orders',
                     '/api/cards','/api/auto-delivery/rules','/api/auto-delivery/stats','/api/conversations',
                     '/api/auto-delivery/sources','/api/orders/today-amount','/api/auto-delivery/records',
                     '/api/operation-logs','/api/system/open-source-config','/api/system/runtime-status',
                     '/api/business-settings/ai-customer-service','/api/dashboard/summary'):
        response=client.get(endpoint)
        assert response.status_code==200,(endpoint,response.text)
        assert response.json()['code']==200,(endpoint,response.text)
    assert client.get('/api/xianyu/accounts').json()['data']['records'][0]['nickname']=='本机账号'
    assert client.get('/api/goods').json()['data']['records'][0]['title']=='本机商品'
    order=client.get('/api/orders').json()['data']['records'][0]
    assert order['buyerName']=='买家甲' and 'items' in order and 'manualDeliveryAttempt' in order
    assert client.get('/api/orders?status=3').json()['data']['total']==0
    assert client.get('/api/orders?keyword=买家甲').json()['data']['total']==1
    assert client.get('/api/orders/31').json()['data']['buyerName']=='买家甲'
    body={'ruleName':'本机自动回复','matchKeywords':'你好','replyContent':'欢迎咨询','status':1}
    response=client.post('/api/auto-reply/rules',json=body)
    assert response.status_code==200 and response.json()['code']==200,response.text
    assert client.get('/api/auto-reply/rules').json()['data']['records'][0]['replyContent']=='欢迎咨询'
    for content in ('第一次保存','更新后的配置'):
        response=client.post('/api/business-settings/message-settings',json={'greeting':content})
        assert response.status_code==200 and response.json()['code']==200,response.text
    assert client.get('/api/business-settings/message-settings').json()['data']['greeting']=='更新后的配置'
    with sqlite3.connect(config.sqlite_path) as db:
        assert db.execute('SELECT reply_content FROM auto_reply_rule').fetchone()[0]=='欢迎咨询'
    trend=client.get('/api/dashboard/sales-trend?date=2030-01-02&days=7').json()
    assert trend['code']==200 and trend['data']['orderCount'][-1]==1,trend


@pytest.mark.asyncio
async def test_original_online_conversation_query_keeps_latest_message(console):
    from app.services.ws_storage import get_online_conversations
    _,config,_=console
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute("INSERT INTO xianyu_account(id,external_uid,deleted) VALUES(11,'fixture-seller',0)")
        for index,content in ((1,'earlier'),(2,'latest')):
            db.execute("INSERT INTO xianyu_chat_message(account_id,s_id,msg_content,content_type,message_time,direction,sender_user_id,receiver_user_id,peer_external_uid,xy_goods_id,deleted) VALUES(11,'fixture-session',?,1,?,'IN','fixture-buyer','fixture-seller','fixture-buyer','fixture-goods',0)",(content,index))
    runtime=DatabaseRuntime(config)
    try:
        async with runtime.session() as db:
            conversations=await get_online_conversations(db,11,schedule_live_refresh=False)
            assert len(conversations)==1 and conversations[0]['lastMessage']=='latest'
    finally:await runtime.dispose()


def test_sse_ticket_is_real_single_use_and_session_is_revoked(console):
    from app.api.v1.routes.sse import _consume_ticket
    client,config,app=console
    response=client.post('/api/sse/ticket')
    assert response.status_code==200
    ticket=response.json()['data']['ticket']
    assert _consume_ticket(ticket) and not _consume_ticket(ticket)
    assert client.post('/api/auth/logout').json()['code']==200
    assert client.get('/api/xianyu/accounts').status_code==401


def test_source_goods_binding_uses_original_json_query(console):
    client,config,_=console
    response=client.post('/api/auto-delivery/sources',json={'title':'本机货源','content':'原项目发货内容'})
    assert response.json()['code']==200,response.text
    with sqlite3.connect(config.sqlite_path) as db:
        source_id=db.execute('SELECT id FROM delivery_text_source').fetchone()[0]
        db.execute("INSERT INTO xianyu_account(id,external_uid,deleted) VALUES(11,'fixture-seller',0)")
        db.execute("INSERT INTO xianyu_goods(id,account_id,external_goods_id,title,deleted,status,auto_relist_enabled,has_snapshot) VALUES(21,11,'fixture-item','已绑定商品',0,1,0,0)")
        db.execute('INSERT INTO delivery_goods_config(goods_id,config_json,deleted) VALUES(21,?,0)',
                   (json.dumps({'payDelivery':{'sourceId':source_id}}),))
    response=client.get(f'/api/auto-delivery/sources/{source_id}/goods')
    assert response.status_code==200 and response.json()['code']==200,response.text
    assert response.json()['data']['configuredGoodsPage']['total']==1,response.text


def test_sql_translation_never_rewrites_literal_values():
    sql="SELECT 'FOR UPDATE', 'NOW() ON DUPLICATE KEY UPDATE', '__SQL_LITERAL_1__' FOR UPDATE"
    assert translate_sql(sql)==sql.removesuffix(' FOR UPDATE')


@pytest.mark.asyncio
async def test_sqlite_upsert_and_locking_preserve_original_contract(console):
    _,config,_=console
    runtime=DatabaseRuntime(config)
    try:
        async with runtime.session() as db:
            for value in ('first','updated'):
                await db.execute(text("INSERT INTO xianyu_sys_setting(setting_key,setting_value) VALUES('test',:value) ON DUPLICATE KEY UPDATE setting_value=VALUES(setting_value)"),{'value':value})
            await db.commit()
            assert (await db.execute(text("SELECT setting_value FROM xianyu_sys_setting WHERE setting_key='test' FOR UPDATE"))).scalar()=='updated'
            assert (await db.execute(text('SELECT GET_LOCK(:lock_name,:timeout_seconds)'),{'lock_name':'fixture','timeout_seconds':1})).scalar()==1
            async with runtime.session() as other:
                assert (await other.execute(text('SELECT GET_LOCK(:lock_name,:timeout_seconds)'),{'lock_name':'fixture','timeout_seconds':0})).scalar()==0
            assert (await db.execute(text('SELECT RELEASE_LOCK(:lock_name)'),{'lock_name':'fixture'})).scalar()==1
    finally:
        await runtime.dispose()
