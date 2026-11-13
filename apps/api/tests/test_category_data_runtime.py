import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.services.category_data import (
    CategoryDataError,
    _resolve_categories_path,
    load_categories,
)


EXPECTED_PATH = Path(__file__).resolve().parents[1] / "app" / "data" / "categories.json"


def test_resolve_categories_path_from_source_layout():
    assert _resolve_categories_path() == EXPECTED_PATH


@pytest.mark.parametrize("bundle_name", ["_internal", "_MEI12345"])
def test_categories_loads_from_frozen_resources_outside_working_directory(tmp_path, monkeypatch, bundle_name):
    import app.services.category_data as cat_module

    bundle = tmp_path / "中文目录" / bundle_name / "app"
    module = bundle / "services" / "category_data.py"
    resource = bundle / "resources" / "categories.json"
    resource.parent.mkdir(parents=True)
    resource.write_bytes(EXPECTED_PATH.read_bytes())

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(cat_module, "__file__", str(module))
    monkeypatch.chdir(tmp_path)

    assert _resolve_categories_path() == resource.resolve()
    data = load_categories()
    tree = data.get("cation", data.get("categories"))
    assert isinstance(tree, list)
    assert len(tree) > 0


def test_load_categories_snapshot_is_immutable():
    first = load_categories()
    first["mutated_custom_key"] = "forbidden"
    second = load_categories()
    assert "mutated_custom_key" not in second


def test_missing_categories_raises_category_data_error(tmp_path, monkeypatch):
    import app.services.category_data as cat_module

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    fake_module = empty_dir / "app" / "services" / "category_data.py"
    fake_module.parent.mkdir(parents=True)

    monkeypatch.setattr(cat_module, "__file__", str(fake_module))
    monkeypatch.setattr(cat_module, "_cache_value", None)
    monkeypatch.setattr(cat_module, "_cache_signature", None)

    with pytest.raises(CategoryDataError, match="分类树版本文件不存在或不可读取"):
        load_categories()
