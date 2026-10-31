"""Mount the original Web application and original business APIs in the desktop host."""
import hmac
import asyncio
import inspect
import re
import secrets
import time

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.core.response import ResultObject


class ConsoleServices:
    """Own the original message/AI workers under the desktop database lifecycle."""
    def __init__(self,gate):
        self.gate=gate
        self.startup=None
        self.stoppers=[]

    @property
    def clients(self):
        from app.services.ws_client import ws_manager
        return ws_manager._clients

    async def desktop_status(self):
        connected=sum(client.is_connected for client in self.clients.values())
        return {'state':'paused' if self.gate.blocked else 'running' if connected else 'offline',
                'pauseReasons':list(self.gate.reasons),'accountCount':len(self.clients),'connectedCount':connected}

    async def resume(self,reason,*,expected_revision=None):
        # Restoring the host gate never clears other independent pause reasons.
        return self.gate.clear(reason,expected_revision=expected_revision)

    async def start(self):
        from app.core.background_tasks import start_background_task_runtime
        from app.services.ws_startup import auto_start_all
        start_background_task_runtime()
        self.startup=asyncio.create_task(auto_start_all(),name='desktop-original-services')
        from app.services.cookie_token_refresher import start_dispatcher, stop_dispatcher
        from app.services.auto_rate_scheduler import start_auto_rate_scheduler, stop_auto_rate_scheduler
        from app.services.relist_scheduler import start_relist_scheduler, stop_relist_scheduler
        for start,stop in ((start_dispatcher,stop_dispatcher),(start_auto_rate_scheduler,stop_auto_rate_scheduler),(start_relist_scheduler,stop_relist_scheduler)):
            await start()
            self.stoppers.append(stop)

    async def stop(self):
        from app.services.ws_startup import stop_all
        from app.core.background_tasks import begin_background_task_shutdown, shutdown_background_tasks
        begin_background_task_shutdown()
        if self.startup is not None:
            self.startup.cancel()
            await asyncio.gather(self.startup,return_exceptions=True)
        for stop in reversed(self.stoppers):await stop()
        await stop_all()
        await shutdown_background_tasks()


def register_console(app, config, runtime, web_dir):
    # Import the same router used by server_app, without importing its MySQL
    # migrations, Redis requirements or server startup lifecycle.
    from app.api.v1.api import api_router
    from app.api.v1.deps import get_current_user, get_current_user_optional
    from app.core.database import get_db

    app.state.desktop_bootstrap=secrets.token_urlsafe(32)
    app.state.desktop_token=secrets.token_urlsafe(48)

    async def desktop_user(request: Request):
        value=request.headers.get('authorization','')
        if not hmac.compare_digest(value,'Bearer '+app.state.desktop_token):
            raise HTTPException(status_code=401,detail='本地会话已失效，请重新打开客户端')
        return {'user_id':0,'username':'本机管理员','role':'admin','jti':'desktop','exp':int(time.time())+86400}

    async def desktop_db():
        async with runtime.session() as session:
            try:
                yield session
            except BaseException:
                await session.rollback()
                raise

    app.dependency_overrides[get_db]=desktop_db
    app.dependency_overrides[get_current_user]=desktop_user
    app.dependency_overrides[get_current_user_optional]=desktop_user

    @app.post('/api/desktop/session')
    async def session(request: Request):
        if not hmac.compare_digest(request.headers.get('x-desktop-bootstrap',''),app.state.desktop_bootstrap):
            raise HTTPException(status_code=403,detail='本地工作区校验失败')
        return ResultObject.success({'token':app.state.desktop_token,'username':'本机管理员'})

    @app.post('/api/auth/logout')
    async def logout(request: Request):
        await desktop_user(request)
        app.state.desktop_token=secrets.token_urlsafe(48)
        return ResultObject.success(None,'已退出本地会话；重新打开客户端可恢复')

    # The existing SQLite warehouse adapters remain authoritative for routes
    # they already implement. All other original modules retain their handlers.
    def key(method,path):
        return method,re.sub(r'\{[^}]+\}','{}',path)
    def routes(items,prefix='',dependencies=()):
        for route in items:
            original=getattr(route,'original_router',None)
            context=getattr(route,'include_context',None)
            if original is not None and context is not None:
                yield from routes(original.routes,prefix+context.prefix,
                                  (*dependencies,*(context.dependencies or ())))
            else:
                yield route,prefix+getattr(route,'path',''),dependencies

    route_options=tuple(name for name in inspect.signature(app.add_api_route).parameters if name not in ('path','endpoint'))

    def mount(route,path,dependencies):
        if isinstance(route,APIRoute):
            options={name:getattr(route,name) for name in route_options if hasattr(route,name)}
            options['dependencies']=[*dependencies,*route.dependencies]
            app.add_api_route(path,route.endpoint,**options)
        else:
            app.router.routes.append(route)

    flat=list(routes(app.routes))
    app.router.routes.clear()
    for route,path,dependencies in flat:
        mount(route,path,dependencies)
    existing={key(method,path) for route,path,_ in flat for method in getattr(route,'methods',())}
    for route,path,dependencies in routes(api_router.routes,'/api'):
        keys={key(method,path) for method in getattr(route,'methods',())}
        if not keys.intersection(existing):
            mount(route,path,dependencies)
            existing.update(keys)

    @app.get('/')
    async def index():
        path=web_dir/'index.html'
        if not path.is_file():
            raise HTTPException(status_code=503,detail='原项目 Web 控制台尚未构建')
        html=path.read_text(encoding='utf-8')
        bootstrap=f'<meta name="xianyu-desktop-bootstrap" content="{app.state.desktop_bootstrap}">'
        return HTMLResponse(html.replace('</head>',bootstrap+'</head>'),headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'})

    # Do not serve stale files from the removed experimental frontends after
    # upgrading an existing source installation with an old dist directory.
    @app.get('/desktop/safety')
    @app.get('/desktop-safety.html')
    async def retired_frontend():
        raise HTTPException(status_code=404,detail='测试界面已移除，请使用主控制台')

    # Static API routes must precede parameter routes, such as /orders/stats
    # before /orders/{id}. This keeps the original module routes reachable.
    app.router.routes.sort(key=lambda route:(not isinstance(route,APIRoute), '{' in getattr(route,'path','')))
    from app.core.route_registry import assert_unique_routes
    assert_unique_routes(app.routes,context='desktop original console')

    app.mount('/uploads',StaticFiles(directory=config.uploads_path,check_dir=False),name='local-uploads')

    @app.api_route('/api/{path:path}',methods=['GET','POST','PUT','PATCH','DELETE'])
    async def missing_api(path: str):
        raise HTTPException(status_code=404,detail='接口不存在')

    if web_dir.is_dir():
        app.mount('/',StaticFiles(directory=web_dir,html=True),name='original-web-console')
