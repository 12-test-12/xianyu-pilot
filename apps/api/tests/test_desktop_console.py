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
    app=create_desktop_app(config,web_dir=web)
    with TestClient(app,base_url='http://127.0.0.1:15177') as client:
        html=client.get('/')
        marker=re.search(r'name="xianyu-desktop-bootstrap" content="([^"]+)"',html.text)[1]
        session=client.post('/api/desktop/session',json={},headers={'X-Desktop-Bootstrap':marker})
        client.headers['Authorization']='Bearer '+session.json()['data']['token']
        yield client,config,app


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


def test_original_business_modules_use_real_persistent_storage(console):
    client,config,app=console
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute("INSERT INTO xianyu_account(id,external_uid,nickname,deleted,status) VALUES(11,'fixture-seller','本机账号',0,1)")
        db.execute("INSERT INTO xianyu_goods(id,account_id,external_goods_id,title,deleted,status,auto_relist_enabled,has_snapshot) VALUES(21,11,'fixture-item','本机商品',0,1,0,0)")
        db.execute("INSERT INTO operation_log(operator,operation_type,operation_desc) VALUES('本机管理员','fixture','真实数据库记录')")
        db.execute("INSERT INTO xianyu_trade_order(id,account_id,external_order_id,total_amount,order_status,deleted,created_time) VALUES(31,11,'fixture-order','10.50',2,0,'2030-01-02 12:00:00')")
    for endpoint in ('/api/xianyu/accounts','/api/xianyu/accounts/summary','/api/goods','/api/orders',
                     '/api/cards','/api/auto-delivery/rules','/api/auto-delivery/stats','/api/conversations',
                     '/api/auto-delivery/sources','/api/orders/today-amount',
                     '/api/operation-logs','/api/system/open-source-config','/api/system/runtime-status',
                     '/api/business-settings/ai-customer-service','/api/dashboard/summary'):
        response=client.get(endpoint)
        assert response.status_code==200,(endpoint,response.text)
        assert response.json()['code']==200,(endpoint,response.text)
    assert client.get('/api/xianyu/accounts').json()['data']['records'][0]['nickname']=='本机账号'
    assert client.get('/api/goods').json()['data']['records'][0]['title']=='本机商品'
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
