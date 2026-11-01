from app.services.category_cache import CategoryCache, category_scope, category_query_key
from app.services import auto_category as auto_service

CATEGORY = dict(catId="91000001", catName="测试叶子分类", channelCatId="92000001", tbCatId="93000001")


def test_cache_survives_restart_expires_and_isolates_accounts(tmp_path):
    now = [1000.0]
    path = tmp_path / "categories.sqlite3"
    cache = CategoryCache(path, ttl_seconds=30, now=lambda: now[0])
    first, second = category_scope(1), category_scope(2)
    value = {**CATEGORY, "recommended": True, "candidates": [CATEGORY]}
    cache.put(first, "query", value)
    assert CategoryCache(path, ttl_seconds=30, now=lambda: now[0]).get(first, "query")["cacheHit"] is True
    assert cache.get(second, "query") is None
    cache.put(second, "query", value)
    cache.invalidate(first)
    assert cache.get(first, "query") is None
    assert cache.get(second, "query") is not None
    now[0] += 31
    assert cache.get(second, "query") is None


def test_cache_stores_only_bounded_category_metadata_and_drops_invalidated_inflight_results(tmp_path):
    cache = CategoryCache(tmp_path / "categories.sqlite3", max_entries=2)
    scope = category_scope(1, "unb=fixture; token=fixture-secret")
    key = category_query_key("private-product-title", "private-description")
    result = {**CATEGORY, "recommended": True, "candidates": [{**CATEGORY, "cookie": "fixture-secret"}], "raw": "fixture-secret", "cdnImageUrl": "fixture-url-token"}
    cache.put(scope, key, result)
    payload = cache.path.read_bytes()
    for private in [b"fixture-secret", b"fixture-url-token", b"private-product-title", b"private-description"]:
        assert private not in payload
    generation = cache.generation(scope)
    cache.invalidate(scope)
    cache.put(scope, key, result, generation=generation)
    assert cache.get(scope, key) is None
    for index in range(3):
        cache.put(scope, str(index), result)
    assert cache.get(scope, "0") is None
    assert cache.get(scope, "2") is not None


def test_auto_category_reuses_existing_interface_only_on_cache_miss_or_force(tmp_path, monkeypatch):
    cache = CategoryCache(tmp_path / "categories.sqlite3")
    calls = []

    def live(*args):
        calls.append(args)
        return {"success": True, "source": "xianyu_auto", "selectedCategory": CATEGORY, "candidates": [CATEGORY]}

    monkeypatch.setattr(auto_service, "desktop_category_cache", lambda: cache)
    monkeypatch.setattr(auto_service, "_auto_category_live", live)
    assert auto_service.auto_category("fixture", b"image", "title", account_id=1)["cacheHit"] is False
    assert auto_service.auto_category("fixture", b"image", "title", account_id=1)["cacheHit"] is True
    assert len(calls) == 1
    auto_service.auto_category("fixture", b"image", "title", account_id=2)
    auto_service.auto_category("fixture", b"image", "title", account_id=1, force_refresh=True)
    auto_service.auto_category("fixture", b"new-image", "title", account_id=1)
    assert len(calls) == 4


def test_failed_refresh_does_not_fall_back_to_old_candidates(tmp_path, monkeypatch):
    cache = CategoryCache(tmp_path / "categories.sqlite3")
    monkeypatch.setattr(auto_service, "desktop_category_cache", lambda: cache)
    monkeypatch.setattr(auto_service, "_auto_category_live", lambda *args: {"success": True, "selectedCategory": CATEGORY, "candidates": [CATEGORY]})
    auto_service.auto_category("fixture", b"image", "title", account_id=1)
    monkeypatch.setattr(auto_service, "_auto_category_live", lambda *args: {"success": False, "candidates": []})
    assert auto_service.auto_category("fixture", b"image", "title", account_id=1, force_refresh=True)["success"] is False
    assert auto_service.auto_category("fixture", b"image", "title", account_id=1)["success"] is False


def test_unreadable_cache_is_optional_and_cannot_prevent_live_recognition(tmp_path, monkeypatch):
    path = tmp_path / "categories.sqlite3"
    path.write_bytes(b"fixture-corrupt-cache")
    cache = CategoryCache(path)
    monkeypatch.setattr(auto_service, "desktop_category_cache", lambda: cache)
    monkeypatch.setattr(auto_service, "_auto_category_live", lambda *args: {"success": True, "selectedCategory": CATEGORY, "candidates": [CATEGORY]})
    assert auto_service.auto_category("fixture", b"image", "title", account_id=1)["success"] is True
