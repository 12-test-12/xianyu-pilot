import json
import socket

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import upload_security
from app.models.entities import NotificationTestAttempt, NotificationTestTargetMutex
from app.services import notify_dispatcher
from app.services.notification_test_attempt import NotificationTestCommand, NotificationTestCoordinator, SqlNotificationTestAttemptStore


def dns(address):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))]


@pytest.mark.asyncio
async def test_feishu_proxy_dns_retains_sni_and_pinned_address(monkeypatch):
    monkeypatch.setattr(upload_security.settings, 'runtime_mode', 'desktop')
    monkeypatch.setattr(upload_security.socket, 'getaddrinfo', lambda *a, **kw: dns('198.18.0.143'))
    real_client = httpx.AsyncClient
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.host == '198.18.0.143'
        assert request.headers['host'] == 'open.feishu.cn'
        assert request.extensions['sni_hostname'] == 'open.feishu.cn'
        return httpx.Response(200, json={'code': 0})

    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        assert kwargs.get('verify', True) is True
        return real_client(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(upload_security.httpx, 'AsyncClient', client)
    result = await notify_dispatcher._send_feishu({'webhookUrl': 'https://open.feishu.cn/open-apis/bot/v2/hook/fixture'}, '测试', 10)
    assert result['success'] is True and len(requests) == 1


@pytest.mark.parametrize('host,address,desktop,opt_in', [
    ('open.feishu.cn','127.0.0.1',True,True),
    ('open.feishu.cn','10.0.0.1',True,True),
    ('open.feishu.cn','169.254.169.254',True,True),
    ('open.feishu.cn','198.18.0.143',False,True),
    ('open.feishu.cn','198.18.0.143',True,False),
    ('service.example','198.18.0.143',True,True),
    ('open.feishu.cn.attacker.example','198.18.0.143',True,True),
])
def test_proxy_exception_cannot_enable_private_or_arbitrary_destinations(monkeypatch,host,address,desktop,opt_in):
    monkeypatch.setattr(upload_security.settings,'runtime_mode','desktop' if desktop else 'server')
    monkeypatch.setattr(upload_security.socket,'getaddrinfo',lambda *a,**kw:dns(address))
    with pytest.raises(upload_security.UnsafeRemoteURLError):
        upload_security._resolve_public_image_targets(f'https://{host}/hook',require_https=True,allow_desktop_proxy_dns=opt_in)


@pytest.mark.asyncio
@pytest.mark.parametrize('reply,success', [({'code':0},True),({'StatusCode':0},True),({'code':19021,'StatusCode':0},False)])
async def test_feishu_signing_and_modern_or_legacy_receipts(monkeypatch,reply,success):
    captured = []
    async def post(url,**kwargs):
        captured.append((url,json.loads(kwargs['content'])))
        return upload_security.PublicHTTPResponse(200,httpx.Headers(),json.dumps(reply).encode())
    monkeypatch.setattr(notify_dispatcher,'request_public_https',post)
    monkeypatch.setattr(notify_dispatcher.time,'time',lambda:1700000000)
    result = await notify_dispatcher._send_feishu({'webhookUrl':'https://open.feishu.cn/open-apis/bot/v2/hook/fixture','secret':'fixture-secret'},'测试内容',10)
    assert result['success'] is success and result['outcome_known'] is True
    url,payload=captured[0]
    assert '?' not in url
    assert payload['timestamp']=='1700000000'
    assert payload['sign']==notify_dispatcher._gen_feishu_sign(1700000000,'fixture-secret')
    assert payload['content']=={'text':'测试内容'}
    assert 'fixture-secret' not in json.dumps(result,ensure_ascii=False)
    if not success: assert result['error_code']=='provider_rejected_19021'


@pytest_asyncio.fixture
async def session(tmp_path):
    engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "notification.sqlite3"}')
    async with engine.begin() as conn:
        await conn.run_sync(NotificationTestAttempt.__table__.create)
        await conn.run_sync(NotificationTestTargetMutex.__table__.create)
    try:
        async with async_sessionmaker(engine,expire_on_commit=False)() as db:
            yield db
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_proven_pre_send_failure_can_retry_same_intent_once(session,monkeypatch):
    attempts=[]
    async def remote(command):
        attempts.append(command.idempotency_key)
        if len(attempts)==1:
            return {'success':False,'outcomeKnown':True,'providerCalled':False}
        return {'success':True,'statusCode':200,'outcomeKnown':True,'providerCalled':True}
    coordinator=NotificationTestCoordinator(SqlNotificationTestAttemptStore(session),remote)
    command=NotificationTestCommand(1,'feishu','notify-test:fixture-original-key','测试','测试内容')
    first=await coordinator.execute(command)
    assert first.status=='failed' and first.retry_safe is True
    assert '尚未发送' in first.message
    assert (await coordinator.execute(command)).status=='confirmed'
    assert (await coordinator.execute(command)).status=='confirmed'
    assert len(attempts)==2


@pytest.mark.asyncio
@pytest.mark.parametrize('transport_error,expected',[(upload_security.PublicRequestNotSent('blocked'),'failed'),(httpx.ReadTimeout('fixture'),'unknown')])
async def test_actual_transport_failure_classification_and_unknown_never_replays(session,monkeypatch,transport_error,expected):
    calls=[]
    async def post(*args,**kwargs):
        calls.append(1)
        raise transport_error
    monkeypatch.setattr(notify_dispatcher,'request_public_https',post)
    async def remote(command):
        result=await notify_dispatcher._send_feishu({'webhookUrl':'https://open.feishu.cn/open-apis/bot/v2/hook/fixture'},'测试',10)
        return {'success':result['success'],'outcomeKnown':result['outcome_known'],'providerCalled':result['provider_called'],'errorCode':result['error_code']}
    coordinator=NotificationTestCoordinator(SqlNotificationTestAttemptStore(session),remote)
    command=NotificationTestCommand(1,'feishu','notify-test:fixture-original-key','测试','测试内容')
    result=await coordinator.execute(command)
    assert result.status==expected
    if expected=='unknown':
        assert '回执超时' in result.message and result.retry_safe is False
        assert (await coordinator.execute(command)).status=='unknown'
        assert len(calls)==1


@pytest.mark.asyncio
async def test_status_endpoint_is_read_only_and_recognizes_closed_record(session):
    from app.api.v1.routes.frontend_compat import inspect_notification_test_attempt
    calls=[]
    async def unknown(command):
        calls.append(1)
        return {'success':False,'outcomeKnown':False}
    store=SqlNotificationTestAttemptStore(session)
    command=NotificationTestCommand(1,'feishu','notify-test:fixture-original-key','测试','内容')
    first=await NotificationTestCoordinator(store,unknown).execute(command)
    payload={'channelKey':'feishu','idempotencyKey':command.idempotency_key}
    response=await inspect_notification_test_attempt(first.attempt_id,payload,session,{'user_id':1})
    assert response.data['attemptStatus']=='unknown' and response.data['providerCalled'] is False
    await store.resolve_unknown(user_id=1,channel_key='feishu',attempt_id=first.attempt_id,idempotency_key=command.idempotency_key)
    response=await inspect_notification_test_attempt(first.attempt_id,payload,session,{'user_id':1})
    assert response.data['attemptStatus']=='resolved'
    denied=await inspect_notification_test_attempt(first.attempt_id,payload,session,{'user_id':2})
    assert denied.status_code==404
    assert len(calls)==1
