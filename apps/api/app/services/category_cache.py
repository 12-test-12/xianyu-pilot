"""Disposable category recommendations stored beside the desktop application."""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from ..core.config import settings
from ..core.paths import contained_data_path, data_directory
from .publish_category import category_option

logger = logging.getLogger(__name__)


def category_scope(account_id=None, cookie_str="") -> str | None:
    if account_id:
        identity = f"account:{account_id}"
    else:
        cookies = dict(part.strip().split("=", 1) for part in cookie_str.split(";") if "=" in part)
        identity = f"unb:{cookies['unb']}" if cookies.get("unb") else ""
    return hashlib.sha256(identity.encode()).hexdigest() if identity else None


def category_query_key(*values) -> str:
    # Neither credentials nor product text are stored in a cache key.
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def cache_payload(value: dict) -> dict:
    """Allow only category metadata, never raw API responses or CDN URLs."""
    candidates = [option for item in value.get("candidates", [])[:100] if (option := category_option(item))]
    selected = category_option(value.get("selectedCategory") or value)
    if not candidates and not selected:
        return {}
    result = {"candidates": candidates}
    if "recommended" in value:
        result.update(selected or {})
        result.update(recommended=bool(value.get("recommended") and selected), cardList=[])
    else:
        result.update(success=bool(value.get("success") and selected), source="xianyu_auto",
                      autoSelected=bool(selected), selectedCategory=selected or None,
                      fallbackRequired=not bool(selected), fallbackReason=value.get("fallbackReason"),
                      cdnImageUrl=None, raw=None)
    return result


class CategoryCache:
    def __init__(self, path: Path, *, ttl_seconds=1800, max_entries=256, now=time.time):
        self.path, self.ttl, self.limit, self.now = path, ttl_seconds, max_entries, now

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=2)
        try:
            with connection:
                connection.execute("CREATE TABLE IF NOT EXISTS category_cache (scope TEXT, query_key TEXT, payload TEXT NOT NULL, fetched_at REAL NOT NULL, PRIMARY KEY(scope,query_key))")
                connection.execute("CREATE TABLE IF NOT EXISTS category_cache_generation (scope TEXT PRIMARY KEY, generation INTEGER NOT NULL)")
                yield connection
        finally:
            connection.close()

    def get(self, scope, key):
        if not scope:
            return None
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT payload,fetched_at FROM category_cache WHERE scope=? AND query_key=?", (scope, key)).fetchone()
                if not row or not 0 <= self.now() - row[1] < self.ttl:
                    return None
                return {**json.loads(row[0]), "cacheHit": True, "checkedAt": row[1]}
        except (OSError, sqlite3.Error, ValueError, TypeError):
            logger.warning("Category cache unavailable; using a live category request")
            return None

    def generation(self, scope):
        if not scope:
            return None
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT generation FROM category_cache_generation WHERE scope=?", (scope,)).fetchone()
                return row[0] if row else 0
        except (OSError, sqlite3.Error):
            return None

    def put(self, scope, key, value, *, generation=None):
        payload = cache_payload(value)
        if not scope or not payload:
            return
        try:
            with self._connect() as connection:
                if generation is not None:
                    connection.execute("INSERT OR IGNORE INTO category_cache_generation VALUES(?,0)", (scope,))
                    current = connection.execute("SELECT generation FROM category_cache_generation WHERE scope=?", (scope,)).fetchone()[0]
                    if generation != current:
                        return
                connection.execute("INSERT OR REPLACE INTO category_cache VALUES(?,?,?,?)", (scope, key, json.dumps(payload, ensure_ascii=False), self.now()))
                connection.execute("DELETE FROM category_cache WHERE fetched_at < ?", (self.now() - self.ttl,))
                connection.execute("DELETE FROM category_cache WHERE rowid NOT IN (SELECT rowid FROM category_cache ORDER BY fetched_at DESC,rowid DESC LIMIT ?)", (self.limit,))
        except (OSError, sqlite3.Error):
            logger.warning("Category cache could not be saved")

    def invalidate(self, scope):
        if not scope:
            return
        try:
            with self._connect() as connection:
                connection.execute("INSERT INTO category_cache_generation VALUES(?,1) ON CONFLICT(scope) DO UPDATE SET generation=generation+1", (scope,))
                connection.execute("DELETE FROM category_cache WHERE scope=?", (scope,))
        except (OSError, sqlite3.Error):
            logger.warning("Category cache could not be invalidated")


def desktop_category_cache() -> CategoryCache | None:
    if settings.runtime_mode != "desktop":
        return None
    try:
        return CategoryCache(contained_data_path(data_directory(), "cache/categories.sqlite3"))
    except (OSError, ValueError):
        logger.warning("Category cache path unavailable; using live requests")
        return None
