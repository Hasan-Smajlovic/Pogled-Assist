from __future__ import annotations

import ctypes
from types import SimpleNamespace

import pytest

from pogled_assist.windows import credentials


@pytest.fixture
def api(monkeypatch):
    calls = []
    blob = (ctypes.c_ubyte * 26).from_buffer_copy("synthetic-key".encode("utf-16-le"))
    record = credentials.Credential(CredentialBlobSize=26, CredentialBlob=blob)

    def read(target, kind, flags, output):
        calls.append(("read", target, kind, flags))
        ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(credentials.Credential)))[0] = (
            ctypes.pointer(record)
        )
        return True

    def write(pointer, flags):
        value = ctypes.cast(pointer, ctypes.POINTER(credentials.Credential)).contents
        calls.append(
            (
                "write",
                value.TargetName,
                value.Type,
                value.Persist,
                ctypes.string_at(value.CredentialBlob, value.CredentialBlobSize),
            )
        )
        return True

    native = SimpleNamespace(
        CredReadW=read,
        CredWriteW=write,
        CredFree=lambda pointer: calls.append(("free", bool(pointer))),
        CredDeleteW=lambda *args: calls.append(("delete", *args)) or True,
    )
    monkeypatch.setattr(credentials, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(credentials, "_credential_api", lambda: native)
    return native, calls


def test_read_releases_windows_buffer_and_write_uses_per_user_persistence(api):
    _native, calls = api
    store = credentials.WindowsCredentialStore()
    assert store.read() == "synthetic-key"
    assert calls[-1] == ("free", True)
    store.write("new-synthetic-key")
    assert calls[-1] == (
        "write",
        "PogledAssist/ElevenLabs",
        1,
        2,
        "new-synthetic-key".encode("utf-16-le"),
    )
    store.delete()
    assert calls[-1] == ("delete", "PogledAssist/ElevenLabs", 1, 0)


def test_missing_key_is_distinct_from_credential_access_failure(api, monkeypatch):
    native, _calls = api
    native.CredReadW = lambda *_: False
    monkeypatch.setattr(credentials.ctypes, "get_last_error", lambda: 1168, raising=False)
    assert credentials.WindowsCredentialStore().read() == ""
    monkeypatch.setattr(credentials.ctypes, "get_last_error", lambda: 5, raising=False)
    with pytest.raises(credentials.CredentialError):
        credentials.WindowsCredentialStore().read()


@pytest.mark.parametrize("value", ["", "has whitespace", "has\nnewline", "ž", "x" * 1281])
def test_invalid_key_never_reaches_native_store(api, value):
    _native, calls = api
    with pytest.raises(credentials.CredentialError):
        credentials.WindowsCredentialStore().write(value)
    assert calls == []


def test_store_does_not_fall_back_to_plaintext_when_windows_is_unavailable(monkeypatch):
    monkeypatch.setattr(credentials, "sys", SimpleNamespace(platform="darwin"))
    store = credentials.WindowsCredentialStore()
    assert store.read() == ""
    with pytest.raises(credentials.CredentialError):
        store.write("synthetic-key")
