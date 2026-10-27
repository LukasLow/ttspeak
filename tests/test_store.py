import io
import json

import pytest

from ttspeak import store
from ttspeak.errors import ModelNotInstalled, UsageError


def quiet_progress() -> store.PullProgress:
    return store.PullProgress(stream=io.StringIO())


def test_pull_static_model(env):
    installed = store.pull_model("fake:custom", progress=quiet_progress())
    assert installed.spec.id == "fake:custom"
    assert installed.path.is_dir()
    assert (installed.path / "model.safetensors").read_bytes().startswith(b"fake-weights")
    manifest = json.loads((installed.path / ".ttspeak-manifest.json").read_text())
    assert manifest["id"] == "fake:custom"
    assert manifest["revision"] == "static"
    assert manifest["total_size"] == sum(int(item["size"]) for item in env.files)
    assert store.is_installed("fake:custom")
    assert [item.spec.id for item in store.list_installed()] == ["fake:custom"]


def test_pull_is_idempotent(env):
    first = store.pull_model("fake:custom", progress=quiet_progress())
    second = store.pull_model("fake:custom", progress=quiet_progress())
    assert first.path == second.path
    assert second.size_bytes == first.size_bytes


def test_checksum_mismatch_leaves_no_model(env):
    with pytest.raises(ModelNotInstalled, match="Checksum mismatch"):
        store.pull_model("fake:broken", progress=quiet_progress())
    assert not store.is_installed("fake:broken")
    assert not store.model_path("fake:broken").exists()


def test_path_traversal_is_rejected(env):
    with pytest.raises(UsageError, match="Unsafe file path"):
        store.pull_model("fake:escape", progress=quiet_progress())
    assert not (env.tmp / "escaped.txt").exists()
    assert not store.is_installed("fake:escape")


def test_remove_requires_confirmation(env):
    store.pull_model("fake:custom", progress=quiet_progress())
    with pytest.raises(UsageError):
        store.remove_model("fake:custom")
    path = store.remove_model("fake:custom", assume_yes=True)
    assert not path.exists()
    assert not store.is_installed("fake:custom")


def test_prune_keeps_listed_models(env):
    store.pull_model("fake:custom", progress=quiet_progress())
    store.pull_model("fake:base", progress=quiet_progress())
    removed = store.prune_models(["fake:custom"], assume_yes=True)
    assert removed == ["fake:base"]
    assert [item.spec.id for item in store.list_installed()] == ["fake:custom"]


def test_resolve_installed_model_without_registry_entry(env):
    store.pull_model("fake:custom", progress=quiet_progress())
    assert store.resolve_installed_or_registry("fake-custom").id == "fake:custom"
