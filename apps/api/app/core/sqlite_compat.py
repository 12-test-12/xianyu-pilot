"""SQLite equivalents for SQL used by the original, shared business routes.

Only the SQLite engine installs these adapters. Server/MySQL SQL is untouched.
Values and quoted strings are masked while translating SQL syntax.
"""
import datetime as dt
import asyncio
import re
import sqlite3
import weakref
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.elements import Cast
from sqlalchemy.types import Date

_locks=weakref.WeakKeyDictionary()


@compiles(Cast,'sqlite')
def sqlite_cast(element,compiler,**kwargs):
    # SQLite CAST(timestamp AS DATE) returns a year integer, not an ISO date.
    if isinstance(element.type,Date):
        return 'date('+compiler.process(element.clause,**kwargs)+')'
    return compiler.visit_cast(element,**kwargs)


class SQLiteBusinessSession(AsyncSession):
    """Preserve write reservations and named mutexes used by shared routes."""
    async def execute(self,statement,params=None,**kwargs):
        sql=str(statement)
        named=re.match(r'\s*SELECT\s+(GET_LOCK|RELEASE_LOCK)\(',sql,re.I)
        if named:
            values=params or {}
            name=str(values.get('lock_name',''))
            pool=_locks.setdefault(asyncio.get_running_loop(),{})
            key=(str(self.bind.url),name)
            held=self.info.setdefault('sqlite_named_locks',{})
            if named[1].upper()=='GET_LOCK':
                lock=pool.setdefault(key,asyncio.Lock())
                if key in held:
                    result=1
                else:
                    timeout=float(values.get('timeout_seconds',3))
                    try:
                        if timeout<=0 and lock.locked():
                            result=0
                        else:
                            await asyncio.wait_for(lock.acquire(),timeout=max(timeout,0.01))
                            held[key]=lock
                            result=1
                    except asyncio.TimeoutError:
                        result=0
            else:
                lock=held.pop(key,None)
                if lock is not None:lock.release()
                result=1 if lock else None
            return await super().execute(text('SELECT :result'),{'result':result})
        if re.search(r'\bFOR\s+UPDATE\b',sql,re.I) or getattr(statement,'_for_update_arg',None) is not None:
            connection=await self.connection()
            active=await connection.run_sync(lambda conn:conn.connection.driver_connection.in_transaction)
            if not active:
                await connection.exec_driver_sql('BEGIN IMMEDIATE')
        return await super().execute(statement,params,**kwargs)

    async def close(self):
        try:
            await super().close()
        finally:
            for lock in self.info.pop('sqlite_named_locks',{}).values():lock.release()


def translate_sql(statement):
    literals=[]
    def mask(match):
        literals.append(match[0])
        return f'__SQL_LITERAL_{len(literals)-1}__'
    sql=re.sub(r"'(?:''|\\.|[^'\\])*'",mask,statement)
    sql=re.sub(r'\bINSERT\s+IGNORE\b','INSERT OR IGNORE',sql,flags=re.I)
    # SQLite serializes writers. A write transaction must acquire its reservation
    # before a read/modify/write sequence; it cannot use MySQL row-lock syntax.
    sql=re.sub(r'\s+FOR\s+UPDATE(?:\s+SKIP\s+LOCKED)?\b','',sql,flags=re.I)
    marker=re.search(r'\bON\s+DUPLICATE\s+KEY\s+UPDATE\b',sql,re.I)
    if marker:
        updates=sql[marker.end():]
        updates=re.sub(r'\bVALUES\s*\(\s*(`?\w+`?)\s*\)',r'excluded.\1',updates,flags=re.I)
        sql=sql[:marker.start()]+' ON CONFLICT DO UPDATE SET '+updates
    sql=re.sub(r'\bCOLLATE\s+utf8mb4_\w+', 'COLLATE NOCASE',sql,flags=re.I)
    sql=re.sub(r'\bAS\s+UNSIGNED\b','AS INTEGER',sql,flags=re.I)
    # SQLite text equality already uses binary collation by default. These
    # original record/recovery joins use MySQL's unary BINARY cast on strings.
    sql=re.sub(r'\bBINARY\s+(?=(?:COALESCE|CAST)\s*\()','',sql,flags=re.I)
    offset=0
    while match:=re.search(r'\bGROUP_CONCAT\s*\(',sql[offset:],re.I):
        start=offset+match.start()
        opening=offset+match.end()
        end=opening;depth=1
        while end<len(sql) and depth:
            if sql[end]=='(':depth+=1
            elif sql[end]==')':depth-=1
            end+=1
        body=sql[opening:end-1]
        ordered=re.fullmatch(r'(.*?)\s+ORDER BY\s+(.*?)\s+SEPARATOR\s+(__SQL_LITERAL_\d+__)',body,re.I|re.S)
        if ordered:
            replacement=f'GROUP_CONCAT({ordered[1]}, {ordered[3]} ORDER BY {ordered[2]})'
            sql=sql[:start]+replacement+sql[end:]
            offset=start+len(replacement)
        else:offset=end
    # These forms occur in the original recovery/history queries; units cannot
    # be bound parameters, while interval values remain bound normally.
    sql=re.sub(r'\bDATE_(SUB|ADD)\(\s*((?:NOW|CURDATE)\(\)|[\w.]+)\s*,\s*INTERVAL\s+(\?|:\w+|\d+)\s+(SECOND|MINUTE|HOUR|DAY)\s*\)',
               lambda m:f"datetime({m[2]}, '{'-' if m[1].upper()=='SUB' else '+'}' || {m[3]} || ' {m[4].lower()}')",sql,flags=re.I)
    return re.sub(r'__SQL_LITERAL_(\d+)__',lambda match:literals[int(match[1])],sql)


def configure_functions(connection):
    now=lambda:dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    connection.create_function('NOW',0,now)
    connection.create_function('CURDATE',0,lambda:dt.date.today().isoformat())
    connection.create_function('VERSION',0,lambda:'SQLite '+sqlite3.sqlite_version)
    connection.create_function('CONCAT',-1,lambda *values:None if None in values else ''.join(map(str,values)))
    connection.create_function('IF',3,lambda condition,yes,no:yes if condition else no)
    # SQLite JSON_EXTRACT already decodes JSON strings. The original source
    # binding query compares both numeric and string IDs as unquoted text.
    connection.create_function('JSON_UNQUOTE',1,lambda value:None if value is None else str(value))
    connection.create_function('GREATEST',-1,lambda *values:None if None in values else max(values))
    connection.create_function('LEAST',-1,lambda *values:None if None in values else min(values))
    connection.create_function('DATE_FORMAT',2,lambda value,format:dt.datetime.fromisoformat(str(value)).strftime(format.replace('%i','%M').replace('%s','%S')) if value else None)
    connection.create_function('SUBSTRING_INDEX',3,lambda value,delimiter,count:delimiter.join(str(value).split(delimiter)[:int(count)] if int(count)>0 else str(value).split(delimiter)[int(count):]) if value is not None else None)
