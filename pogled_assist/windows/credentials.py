"""ElevenLabs credentials belong to the current Windows user, outside app data."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

TARGET = "PogledAssist/ElevenLabs"
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


class CredentialError(Exception):
    pass


class Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialStore:
    def read(self) -> str:
        if sys.platform != "win32":
            return ""
        api = _credential_api()
        pointer = ctypes.POINTER(Credential)()
        if not api.CredReadW(TARGET, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == ERROR_NOT_FOUND:
                return ""
            raise CredentialError("Could not read the saved key")
        try:
            value = pointer.contents
            if value.CredentialBlobSize > 2560:
                raise CredentialError("Invalid saved key")
            return ctypes.string_at(value.CredentialBlob, value.CredentialBlobSize).decode(
                "utf-16-le"
            )
        finally:
            api.CredFree(pointer)

    def write(self, key: str) -> None:
        key = key.strip()
        if not key or not key.isascii() or any(char.isspace() for char in key):
            raise CredentialError("Invalid key")
        data = key.encode("utf-16-le")
        if len(data) > 2560:
            raise CredentialError("Invalid key")
        blob = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        credential = Credential(
            Type=CRED_TYPE_GENERIC,
            TargetName=TARGET,
            CredentialBlobSize=len(data),
            CredentialBlob=blob,
            Persist=CRED_PERSIST_LOCAL_MACHINE,
            UserName="Pogled Assist",
        )
        try:
            if not _credential_api().CredWriteW(ctypes.byref(credential), 0):
                raise CredentialError("Could not save the key")
        finally:
            ctypes.memset(blob, 0, len(data))

    def delete(self) -> None:
        if not _credential_api().CredDeleteW(TARGET, CRED_TYPE_GENERIC, 0):
            if ctypes.get_last_error() != ERROR_NOT_FOUND:
                raise CredentialError("Could not remove the key")


def _credential_api():
    if sys.platform != "win32":
        raise CredentialError("Windows Credential Manager is unavailable")
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.CredReadW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(Credential)),
    ]
    api.CredReadW.restype = wintypes.BOOL
    api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None
    return api
