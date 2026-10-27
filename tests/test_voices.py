import io

import pytest

from ttspeak import store, voices
from ttspeak.errors import ModelNotInstalled, UsageError, VoiceError


def quiet_progress() -> store.PullProgress:
    return store.PullProgress(stream=io.StringIO())


def test_add_list_show_remove(env, reference_wav):
    store.pull_model("fake:base", progress=quiet_progress())
    profile = voices.add_profile("Lukas", reference_wav, "Hallo, ich bin Lukas.", model="fake:base")
    assert profile.audio.is_file()
    assert profile.sha256
    assert profile.model == "fake:base"
    assert (profile.path / "profile.json").is_file()

    listed = voices.list_profiles()
    assert [item.name for item in listed] == ["Lukas"]
    assert voices.get_profile("lukas") == listed[0]
    assert voices.get_profile("@Lukas") == listed[0]

    removed = voices.remove_profile("Lukas", assume_yes=True)
    assert removed.name == "Lukas"
    assert voices.list_profiles() == []


def test_add_requires_base_model(env, reference_wav):
    store.pull_model("fake:custom", progress=quiet_progress())
    with pytest.raises(VoiceError, match="cannot clone"):
        voices.add_profile("Lukas", reference_wav, "Hallo.", model="fake:custom")


def test_add_requires_installed_model(env, reference_wav):
    with pytest.raises(ModelNotInstalled):
        voices.add_profile("Lukas", reference_wav, "Hallo.", model="fake:base")


def test_add_validates_input(env, reference_wav):
    store.pull_model("fake:base", progress=quiet_progress())
    with pytest.raises(VoiceError, match="transcript"):
        voices.add_profile("Lukas", reference_wav, "   ", model="fake:base")
    with pytest.raises(VoiceError, match="not found"):
        voices.add_profile("Lukas", env.tmp / "missing.wav", "Hallo.", model="fake:base")
    with pytest.raises(VoiceError, match="path separators"):
        voices.add_profile("a/b", reference_wav, "Hallo.", model="fake:base")


def test_duplicate_profile_requires_force(env, reference_wav):
    store.pull_model("fake:base", progress=quiet_progress())
    voices.add_profile("Lukas", reference_wav, "Hallo.", model="fake:base")
    with pytest.raises(VoiceError, match="already exists"):
        voices.add_profile("Lukas", reference_wav, "Hallo.", model="fake:base")
    replaced = voices.add_profile(
        "Lukas", reference_wav, "Neuer Text.", model="fake:base", force=True
    )
    assert replaced.ref_text == "Neuer Text."


def test_remove_requires_confirmation(env, reference_wav):
    store.pull_model("fake:base", progress=quiet_progress())
    voices.add_profile("Lukas", reference_wav, "Hallo.", model="fake:base")
    with pytest.raises(UsageError):
        voices.remove_profile("Lukas")
    voices.remove_profile("Lukas", assume_yes=True)
    with pytest.raises(VoiceError):
        voices.remove_profile("Lukas", assume_yes=True)


def test_profiles_for_model_and_prune(env, reference_wav):
    store.pull_model("fake:base", progress=quiet_progress())
    voices.add_profile("Lukas", reference_wav, "Hallo.", model="fake:base")
    voices.add_profile("Anna", reference_wav, "Hallo.", model="fake:base")
    assert [item.name for item in voices.profiles_for_model("fake:base")] == ["Anna", "Lukas"]
    removed = voices.prune_profiles(["Lukas"], assume_yes=True)
    assert removed == ["Anna"]
    assert [item.name for item in voices.list_profiles()] == ["Lukas"]
