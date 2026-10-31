import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pathlib import Path

import pytest

from app.api.v1.routes.misc import _load_address_dict_from_json, _resolve_address_dict_path


EXPECTED_PATH = Path(__file__).resolve().parents[1] / "app" / "data" / "china_address_dict.json"


def test_resolve_address_dict_path_from_source_layout():
    assert _resolve_address_dict_path() == EXPECTED_PATH


@pytest.mark.parametrize("bundle_name", ["_internal", "_MEI12345"])
def test_dictionary_loads_from_frozen_resources_outside_working_directory(tmp_path, monkeypatch, bundle_name):
    import app.api.v1.routes.misc as misc
    bundle = tmp_path / "中文目录" / bundle_name / "app"
    module = bundle / "api" / "v1" / "routes" / "misc.py"
    resource = bundle / "resources" / "china_address_dict.json"
    resource.parent.mkdir(parents=True)
    resource.write_bytes(EXPECTED_PATH.read_bytes())
    monkeypatch.delenv("ADDRESS_DICT_PATH", raising=False)
    monkeypatch.setattr(misc, "__file__", str(module))
    monkeypatch.chdir(tmp_path)
    assert _resolve_address_dict_path() == resource.resolve()
    assert len(_load_address_dict_from_json()["provinces"]) == 34


def test_load_address_dict_from_json_has_non_empty_tree():
    tree = _load_address_dict_from_json()
    assert isinstance(tree, dict)
    assert tree["provinces"]


def test_missing_address_dict_is_distinguishable(monkeypatch):
    missing_path = Path("missing-china-address-dict.json")
    monkeypatch.setattr(
        "app.api.v1.routes.misc._resolve_address_dict_path",
        lambda: missing_path,
    )
    with pytest.raises(FileNotFoundError):
        _load_address_dict_from_json()
