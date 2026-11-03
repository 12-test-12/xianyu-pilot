"""Contract tests for the embedded Chromium phone-scan login window.

The window only opens a real network session in ``start()``; these tests never
call it, so the Qt/Chromium lifecycle stays offline and display-free.
"""
import os
import sys
from types import SimpleNamespace

import pytest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

pytest.importorskip('PySide6',reason='Qt is installed by the GitHub Windows packaging job only')
pytestmark=pytest.mark.skipif(sys.platform!='win32',reason='Windows host')

from app.portable.login_window import (
    ALLOWED_HOSTS,LOGIN_URL,LoginWindow,cookie_header,has_login,is_allowed,
    parse_login_target,
)


@pytest.fixture(scope='session')
def qapp():
    # One QApplication per pytest process; offscreen keeps the host display-free.
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def offscreen_platform(monkeypatch,qapp):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    yield


@pytest.fixture
def window(qapp):
    from PySide6.QtWebEngineCore import QWebEngineProfile
    from shiboken6 import delete,isValid
    # An explicit off-the-record profile keeps the window's Chromium teardown
    # independent from the default profile of the host process.
    profile=QWebEngineProfile()
    w=LoginWindow(profile)
    try:
        yield w
    finally:
        w.stop()
        # Page -> view -> window before the profile, mirroring qt_host.dispose().
        if isValid(w):
            delete(w)
        if isValid(profile):
            delete(profile)


@pytest.mark.parametrize('url',[
    'https://passport.goofish.com/mini_login.htm',
    'https://www.goofish.com/',
    'https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.pc.login.token/1.0/',
    'https://login.taobao.com/member/login.jhtml',
    'https://g.alicdn.com/x.js',
    'about:blank',
])
def test_allowed_login_hosts(url):
    assert is_allowed(url) is True


@pytest.mark.parametrize('url',[
    'https://evil.com/',
    'https://goofish.com.evil.com/',
    'http://127.0.0.1:15177/',
    'javascript:alert(1)',
])
def test_blocked_non_login_urls(url):
    assert is_allowed(url) is False


def test_login_url_is_allowlisted():
    assert is_allowed(LOGIN_URL) is True
    assert ALLOWED_HOSTS


def test_cookie_header_from_dict_items():
    cookies=[{'name':'a','value':'1'},{'name':'b','value':'2'}]
    assert cookie_header(cookies)=='a=1; b=2'


def test_cookie_header_from_name_value_objects():
    cookies=[SimpleNamespace(name='a',value='1'),SimpleNamespace(name='b',value='2')]
    assert cookie_header(cookies)=='a=1; b=2'


def test_cookie_header_drops_empty_values():
    cookies=[{'name':'a','value':'1'},{'name':'b','value':''},{'name':'c','value':'3'}]
    assert cookie_header(cookies)=='a=1; c=3'


def test_cookie_header_last_value_wins_but_keeps_first_position():
    cookies=[{'name':'a','value':'1'},{'name':'b','value':'2'},{'name':'a','value':'3'}]
    assert cookie_header(cookies)=='a=3; b=2'


def test_cookie_header_empty_list():
    assert cookie_header([])==''
    assert cookie_header([{'name':'a','value':''}])==''


@pytest.mark.parametrize('cookie,expected',[
    ('unb=123; a=b',True),
    ('a=b; unb=',False),
    ('xunb=1',False),
    ('',False),
])
def test_has_login_requires_exact_unb_key(cookie,expected):
    assert has_login(cookie) is expected


@pytest.mark.parametrize('url,expected',[
    ('xianyu-desktop://login',(True,None)),
    ('xianyu-desktop://login?accountId=42',(True,42)),
    ('xianyu-desktop://login?accountId=abc',(True,None)),
    ('https://www.goofish.com/',(False,None)),
])
def test_parse_login_target(url,expected):
    assert parse_login_target(url)==expected


def test_window_title_mentions_xianyu(window):
    assert '闲鱼' in window.windowTitle()


def test_handle_cookies_emits_header_for_login_cookie(window):
    received=[]
    window.cookies_ready.connect(received.append)
    ok=window.handle_cookies([
        {'name':'unb','value':'1'},
        {'name':'_m_h5_tk','value':'tk'},
    ])
    assert ok is True
    assert received==['unb=1; _m_h5_tk=tk']


def test_handle_cookies_without_unb_returns_false_and_stays_silent(window):
    received=[]
    window.cookies_ready.connect(received.append)
    assert window.handle_cookies([{'name':'_m_h5_tk','value':'tk'}]) is False
    assert window.handle_cookies([]) is False
    assert received==[]


def test_stop_is_idempotent(window):
    window.stop()
    window.stop()
