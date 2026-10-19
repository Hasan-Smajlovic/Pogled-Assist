"""Bounded HTTP work whose sockets can be interrupted by the caller."""

from __future__ import annotations

import http.client
import json
import socket
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from threading import Event, Lock, Thread

from .voice_state import SpeechCancelled, VoiceError

API_HOST = "api.elevenlabs.io"
MAX_AUDIO_BYTES = 16 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Budget:
    cancel: Event
    deadline: float

    def remaining(self) -> float:
        if self.cancel.is_set():
            raise SpeechCancelled
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise VoiceError("timeout")
        return remaining


@dataclass(frozen=True)
class Request:
    key: str = field(repr=False)
    method: str
    path: str
    payload: dict | None = field(default=None, repr=False)
    audio: bool = False


class _CallStop:
    def __init__(self, caller: Event) -> None:
        self.caller = caller
        self.abandoned = Event()
        self._lock = Lock()
        self._connections: set = set()
        self._sockets: set = set()

    def is_set(self) -> bool:
        return self.caller.is_set() or self.abandoned.is_set()

    def attach(self, connection) -> None:
        with self._lock:
            self._connections.add(connection)
            if self.is_set():
                _close_connection(connection)

    def detach(self, connection) -> None:
        with self._lock:
            self._connections.discard(connection)

    def attach_socket(self, active_socket) -> None:
        if active_socket is None:
            return
        with self._lock:
            self._sockets.add(active_socket)
            if self.is_set():
                _shutdown(active_socket)

    def abort(self) -> None:
        with self._lock:
            self.abandoned.set()
            for active_socket in self._sockets:
                _shutdown(active_socket)
            for connection in self._connections:
                _close_connection(connection)


def _close_connection(connection) -> None:
    # close() alone may leave getresponse/read blocked on another thread.
    if connection.sock is not None:
        _shutdown(connection.sock)
    with suppress(OSError):
        connection.close()


def _shutdown(active_socket) -> None:
    with suppress(OSError, AttributeError):
        active_socket.shutdown(socket.SHUT_RDWR)


class BoundedCall:
    """Keep at most one worker per boundary, even if DNS cannot be interrupted."""

    def __init__(self) -> None:
        self._slot = Lock()

    def run(self, operation: Callable, cancel: Event, timeout: float):
        budget = Budget(cancel, time.monotonic() + timeout)
        if not self._slot.acquire(timeout=min(1.0, budget.remaining())):
            budget.remaining()
            raise VoiceError("busy")
        stop = _CallStop(cancel)
        try:
            budget.remaining()
        except (SpeechCancelled, VoiceError):
            self._slot.release()
            raise
        finished, result = self._start_worker(operation, stop, budget.deadline)
        try:
            return self._wait_for_result(finished, result, budget)
        finally:
            stop.abort()

    def _start_worker(self, operation, stop, deadline):
        finished, result = Event(), []

        def work() -> None:
            try:
                result.append((True, operation(stop, deadline)))
            except SpeechCancelled:
                result.append((False, "busy"))
            except VoiceError as error:
                result.append((False, error.reason))
            except Exception:
                result.append((False, "offline"))
            finally:
                self._slot.release()
                finished.set()

        try:
            Thread(target=work, daemon=True, name="speech-network").start()
        except RuntimeError:
            self._slot.release()
            raise VoiceError("offline") from None
        return finished, result

    @staticmethod
    def _wait_for_result(finished, result, budget):
        while not finished.is_set():
            budget.cancel.wait(min(0.02, budget.remaining()))
        budget.remaining()
        success, value = result[0]
        if not success:
            raise VoiceError(value)
        return value


def request_data(request: Request, budget: Budget):
    connection = http.client.HTTPSConnection(API_HOST, timeout=budget.remaining())
    attach = getattr(budget.cancel, "attach", lambda _connection: None)
    detach = getattr(budget.cancel, "detach", lambda _connection: None)
    attach(connection)
    try:
        return _receive(connection, request, budget)
    except TimeoutError:
        raise VoiceError("timeout") from None
    except (VoiceError, SpeechCancelled):
        raise
    except Exception:
        budget.remaining()
        raise VoiceError("offline") from None
    finally:
        detach(connection)
        connection.close()


def _receive(connection, request, budget):
    response = _send(connection, request, budget)
    successful = 200 <= response.status < 300
    audio = request.audio and successful
    data = _read_body(connection, response, MAX_AUDIO_BYTES if audio else MAX_JSON_BYTES, budget)
    if not successful:
        raise VoiceError(error_reason(response.status, data))
    return _validate_response(response, data, request.audio)


def _socket_budget(connection, budget) -> None:
    remaining = budget.remaining()
    if connection.sock is not None:
        connection.sock.settimeout(remaining)


def _send(connection, request, budget):
    headers = {
        "xi-api-key": request.key,
        "Accept": "audio/mpeg" if request.audio else "application/json",
    }
    body = None
    if request.payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(request.payload, ensure_ascii=False).encode("utf-8")
    connection.connect()
    attach_socket = getattr(budget.cancel, "attach_socket", lambda _socket: None)
    attach_socket(connection.sock)
    # DNS may complete after abandonment; never send a late authenticated POST.
    _socket_budget(connection, budget)
    connection.request(request.method, request.path, body=body, headers=headers)
    _socket_budget(connection, budget)
    return connection.getresponse()


def _read_body(connection, response, limit, budget):
    data = bytearray()
    while True:
        _socket_budget(connection, budget)
        chunk = response.read1(min(65536, limit + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > limit:
            raise VoiceError("audio" if limit == MAX_AUDIO_BYTES else "offline")
    budget.remaining()
    return bytes(data)


def _validate_response(response, data, audio):
    reason = "audio" if audio else "offline"
    declared = response.getheader("Content-Length", "")
    _validate_length(declared, len(data), reason)
    if audio:
        if not data or "audio/" not in response.getheader("Content-Type", ""):
            raise VoiceError("audio")
        return data
    return json.loads(data)


def _validate_length(declared, actual, reason):
    if not declared:
        return
    if not declared.isdigit() or int(declared) != actual:
        raise VoiceError(reason)


CODE_REASONS = {
    **dict.fromkeys(("insufficient_credits", "quota_exceeded"), "quota"),
    **dict.fromkeys(
        (
            "insufficient_permissions",
            "missing_permissions",
            "forbidden",
            "voice_access_denied",
            "model_access_denied",
        ),
        "permission",
    ),
    **dict.fromkeys(("invalid_api_key", "missing_api_key", "unauthorized"), "invalid_key"),
    "text_too_long": "too_long",
}
STATUS_REASONS = {
    402: "quota",
    403: "permission",
    401: "invalid_key",
    429: "rate_limit",
    400: "configuration",
    404: "configuration",
    422: "configuration",
}


def error_reason(status: int, body: bytes) -> str:
    try:
        detail = json.loads(body).get("detail", {})
        code = detail.get("code", detail.get("status", "")) if isinstance(detail, dict) else ""
    except (ValueError, AttributeError):
        code = ""
    if not isinstance(code, str):
        code = ""
    priority = (
        "quota",
        "permission",
        "invalid_key",
        "rate_limit",
        "too_long",
        "configuration",
        "offline",
    )
    reasons = (CODE_REASONS.get(code, "offline"), STATUS_REASONS.get(status, "offline"))
    return min(reasons, key=priority.index)
