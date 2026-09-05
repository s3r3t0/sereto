import asyncio
import hmac
import inspect
import json
import math
import os
import re
import secrets
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import Literal, Protocol, cast

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed, InvalidHeader
from websockets.headers import parse_subprotocol
from websockets.http11 import Request, Response
from websockets.typing import Subprotocol

from sereto.exceptions import SeretoRuntimeError, SeretoValueError
from sereto.package_plugins.protocol_v1 import (
    MANIFEST_OPERATION_ID,
    PROTOCOL_VERSION,
    SUBPROTOCOL,
    CancelMessage,
    CancelPayload,
    DistributionIdentity,
    ErrorMessage,
    ErrorPayload,
    HelloMessage,
    Manifest,
    ManifestResultPayload,
    OperationRequest,
    OperationResultPayload,
    PluginProtocolError,
    ProgressMessage,
    ProgressPayload,
    ReadyLimits,
    ReadyMessage,
    ReadyPayload,
    RequestMessage,
    ResourceKind,
    ResultMessage,
    decode_plugin_message,
    encode_host_message,
)

DEFAULT_MAX_MESSAGE_BYTES = 4 * 1024 * 1024
DEFAULT_HANDSHAKE_TIMEOUT_SECONDS = 5.0
DEFAULT_INVOCATION_TIMEOUT_SECONDS = 15 * 60.0
DEFAULT_CANCEL_GRACE_SECONDS = 3.0
BOOTSTRAP_TTL_SECONDS = 30.0
_UV_INDEX_CREDENTIAL = re.compile(r"^UV_INDEX_[A-Z0-9_]+_(?:USERNAME|PASSWORD)$")

type SessionResult = ManifestResultPayload | OperationResultPayload
type ProgressCallback = Callable[[ProgressPayload], None | Awaitable[None]]


class Process(Protocol):
    returncode: int | None

    async def wait(self) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class PluginProcessError(SeretoRuntimeError):
    """The managed plugin runner failed before completing its protocol session."""


class PluginSessionTimeout(SeretoRuntimeError):
    """The managed plugin did not complete a session phase before its deadline."""


class PluginOperationError(SeretoRuntimeError):
    """The managed plugin returned a structured operation error."""

    def __init__(self, payload: ErrorPayload) -> None:
        super().__init__(f"{payload.code}: {payload.message}")
        self.payload = payload


@dataclass(frozen=True)
class PluginLaunch:
    python: Path
    distribution_name: str
    distribution_version: str
    entry_point: str
    expected_plugin_id: str | None
    sdk_api_major: Literal[1]


@dataclass(frozen=True)
class SessionLimits:
    max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES
    handshake_timeout_seconds: float = DEFAULT_HANDSHAKE_TIMEOUT_SECONDS
    invocation_timeout_seconds: float = DEFAULT_INVOCATION_TIMEOUT_SECONDS
    cancel_grace_seconds: float = DEFAULT_CANCEL_GRACE_SECONDS


class PluginSession:
    """Launch one managed SDK runner and exchange one request over loopback."""

    def __init__(
        self,
        launch: PluginLaunch,
        sereto_version: str,
        limits: SessionLimits | None = None,
        resource_kinds: tuple[ResourceKind, ...] = ("sereto.target.v1",),
    ) -> None:
        resolved_limits = limits or SessionLimits()
        numeric_limits = (
            resolved_limits.handshake_timeout_seconds,
            resolved_limits.invocation_timeout_seconds,
            resolved_limits.cancel_grace_seconds,
        )
        if (
            type(resolved_limits.max_message_bytes) is not int
            or not 1024 <= resolved_limits.max_message_bytes <= DEFAULT_MAX_MESSAGE_BYTES
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in numeric_limits)
            or resolved_limits.handshake_timeout_seconds <= 0
            or resolved_limits.invocation_timeout_seconds <= 0
            or resolved_limits.cancel_grace_seconds < 0
        ):
            raise SeretoValueError("invalid plugin session limits")
        if type(launch.sdk_api_major) is not int or launch.sdk_api_major != 1:
            raise SeretoValueError("unsupported plugin SDK API major")
        self.launch = launch
        self.sereto_version = sereto_version
        self.limits = resolved_limits
        self.resource_kinds = resource_kinds
        self._connection: ServerConnection | None = None
        self._request_sent = False
        self._cancel_sent = False
        self._terminal_received = False
        self._active = False

    async def discover_manifest(self) -> Manifest:
        """Discover and validate the plugin manifest through the selected SDK runner."""
        result = await self.run(OperationRequest(operation_id=MANIFEST_OPERATION_ID))
        if not isinstance(result, ManifestResultPayload):
            raise PluginProtocolError("manifest discovery did not return a manifest")
        return result.manifest

    async def run(
        self,
        request: OperationRequest,
        on_progress: ProgressCallback | None = None,
    ) -> SessionResult:
        if self._active:
            raise SeretoValueError("plugin session is already active")
        unsupported_resource_kinds = {resource.kind for resource in request.resources} - set(self.resource_kinds)
        if unsupported_resource_kinds:
            raise SeretoValueError("request uses a resource kind not supported by this host session")

        self._active = True
        try:
            return await self._run(request=request, on_progress=on_progress)
        finally:
            self._active = False

    async def _run(
        self,
        request: OperationRequest,
        on_progress: ProgressCallback | None,
    ) -> SessionResult:
        invocation_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        result_future: asyncio.Future[SessionResult] = asyncio.get_running_loop().create_future()
        connection_started = asyncio.Event()
        accepted_connection = False
        handshake_deadline: float | None = None

        def reject(connection: ServerConnection, status: HTTPStatus, message: str) -> Response:
            return connection.respond(status, f"{message}\n")

        async def authenticate(connection: ServerConnection, raw_request: Request) -> Response | None:
            nonlocal accepted_connection
            authorization_headers = raw_request.headers.get_all("Authorization")
            supplied = authorization_headers[0] if len(authorization_headers) == 1 else ""
            expected = f"Bearer {token}"
            if not hmac.compare_digest(supplied, expected):
                return reject(connection, HTTPStatus.UNAUTHORIZED, "Unauthorized")
            if raw_request.headers.get_all("Origin"):
                return reject(connection, HTTPStatus.FORBIDDEN, "Origin is not allowed")
            try:
                offered_subprotocols = {
                    subprotocol
                    for header in raw_request.headers.get_all("Sec-WebSocket-Protocol")
                    for subprotocol in parse_subprotocol(header)
                }
            except InvalidHeader:
                return reject(connection, HTTPStatus.BAD_REQUEST, "Invalid WebSocket subprotocol")
            if SUBPROTOCOL not in offered_subprotocols:
                return reject(connection, HTTPStatus.BAD_REQUEST, "Required WebSocket subprotocol was not offered")
            if accepted_connection:
                return reject(connection, HTTPStatus.CONFLICT, "Invocation already connected")
            accepted_connection = True
            return None

        async def handle(connection: ServerConnection) -> None:
            connection_started.set()
            try:
                result = await self._exchange(
                    connection=connection,
                    invocation_id=invocation_id,
                    request=request,
                    on_progress=on_progress,
                    handshake_deadline=handshake_deadline,
                )
            except BaseException as error:
                if not result_future.done():
                    result_future.set_exception(error)
            else:
                if not result_future.done():
                    result_future.set_result(result)

        subprotocol = Subprotocol(SUBPROTOCOL)
        async with serve(
            handle,
            "127.0.0.1",
            0,
            subprotocols=[subprotocol],
            process_request=authenticate,
            origins=[None],
            compression=None,
            server_header=None,
            open_timeout=self.limits.handshake_timeout_seconds,
            close_timeout=self.limits.cancel_grace_seconds,
            max_size=self.limits.max_message_bytes,
        ) as server:
            listener_socket = next(iter(server.sockets), None)
            if listener_socket is None:
                raise PluginProcessError("plugin listener did not expose a socket")
            port = int(listener_socket.getsockname()[1])
            handshake_deadline = asyncio.get_running_loop().time() + self.limits.handshake_timeout_seconds
            bootstrap_path = self._write_bootstrap(
                endpoint=f"ws://127.0.0.1:{port}",
                token=token,
                invocation_id=invocation_id,
            )
            process: Process | None = None
            process_wait: asyncio.Task[SessionResult] | None = None
            connection_wait: asyncio.Task[bool] | None = None
            try:
                try:
                    process = cast(
                        Process,
                        await asyncio.wait_for(
                            asyncio.create_subprocess_exec(
                                self.launch.python,
                                "-m",
                                f"sereto_sdk.v{self.launch.sdk_api_major}.runner",
                                bootstrap_path,
                                env=self._runner_environment(),
                            ),
                            timeout=self._remaining(handshake_deadline),
                        ),
                    )
                except TimeoutError:
                    raise PluginProcessError("timed out launching plugin runner") from None
                except OSError as error:
                    raise PluginProcessError(f"failed to launch plugin runner: {error}") from error

                async def fail_on_process_exit() -> SessionResult:
                    exit_code = await process.wait()
                    if result_future.done():
                        return result_future.result()
                    if connection_started.is_set():
                        return await asyncio.shield(result_future)
                    raise PluginProcessError(
                        f"plugin runner exited before completing the session with code {exit_code}"
                    )

                process_wait = asyncio.create_task(fail_on_process_exit())
                connection_wait = asyncio.create_task(connection_started.wait())
                gate_completed, _ = await asyncio.wait(
                    {
                        cast(asyncio.Future[object], connection_wait),
                        cast(asyncio.Future[object], process_wait),
                    },
                    timeout=self._remaining(handshake_deadline),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if process_wait in gate_completed:
                    return process_wait.result()
                if connection_wait not in gate_completed:
                    raise PluginProcessError("timed out waiting for plugin runner connection")

                completed, _ = await asyncio.wait(
                    {
                        cast(asyncio.Future[object], result_future),
                        cast(asyncio.Future[object], process_wait),
                    },
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if result_future in completed:
                    result = result_future.result()
                    await self._stop_process(process, terminate=False)
                    return result
                return process_wait.result()
            except asyncio.CancelledError:
                if process is not None:
                    await asyncio.shield(self._cancel_and_stop(process, invocation_id, "host invocation cancelled"))
                raise
            except BaseException:
                if process is not None:
                    await self._cancel_and_stop(process, invocation_id, "host session failed")
                raise
            finally:
                bootstrap_path.unlink(missing_ok=True)
                if not result_future.done():
                    result_future.cancel()
                else:
                    with suppress(BaseException):
                        result_future.result()
                for task in (connection_wait, process_wait):
                    if task is not None and not task.done():
                        task.cancel()
                for task in (connection_wait, process_wait):
                    if task is not None:
                        with suppress(BaseException):
                            await task
                self._connection = None
                self._request_sent = False
                self._cancel_sent = False
                self._terminal_received = False

    async def _exchange(
        self,
        connection: ServerConnection,
        invocation_id: str,
        request: OperationRequest,
        on_progress: ProgressCallback | None,
        handshake_deadline: float | None,
    ) -> SessionResult:
        self._verify_connection(connection)
        self._connection = connection
        try:
            hello_message = await asyncio.wait_for(
                self._receive(connection),
                timeout=self._remaining(handshake_deadline),
            )
        except TimeoutError:
            raise PluginSessionTimeout("timed out waiting for plugin hello") from None
        if not isinstance(hello_message, HelloMessage):
            raise PluginProtocolError("expected hello as the first plugin message")
        self._verify_hello(hello_message, invocation_id)
        plugin_id = hello_message.payload.plugin_id

        deadline = datetime.now(UTC) + timedelta(seconds=self.limits.invocation_timeout_seconds)
        await self._send(
            connection,
            ReadyMessage(
                request_id=invocation_id,
                payload=ReadyPayload(
                    sereto_version=self.sereto_version,
                    deadline=deadline,
                    limits=ReadyLimits(max_message_bytes=self.limits.max_message_bytes),
                    resource_kinds=self.resource_kinds,
                ),
            ),
        )
        await self._send(connection, RequestMessage(request_id=invocation_id, payload=request))
        self._request_sent = True

        expected_sequence = 1
        try:
            async with asyncio.timeout(self.limits.invocation_timeout_seconds):
                while True:
                    message = await self._receive(connection)
                    if message.request_id != invocation_id:
                        raise PluginProtocolError("plugin message request_id does not match the invocation")
                    if isinstance(message, ProgressMessage):
                        if message.payload.sequence != expected_sequence:
                            raise PluginProtocolError("plugin progress sequence is not contiguous")
                        expected_sequence += 1
                        if on_progress is not None:
                            callback_result = on_progress(message.payload)
                            if inspect.isawaitable(callback_result):
                                await callback_result
                        continue
                    if isinstance(message, ResultMessage):
                        if request.operation_id == MANIFEST_OPERATION_ID and not isinstance(
                            message.payload, ManifestResultPayload
                        ):
                            raise PluginProtocolError("manifest discovery returned an operation result")
                        if (
                            isinstance(message.payload, ManifestResultPayload)
                            and message.payload.manifest.plugin_id != plugin_id
                        ):
                            raise PluginProtocolError("manifest plugin ID does not match plugin hello")
                        if request.operation_id != MANIFEST_OPERATION_ID and not isinstance(
                            message.payload, OperationResultPayload
                        ):
                            raise PluginProtocolError("plugin operation returned a manifest result")
                        self._terminal_received = True
                        return message.payload
                    if isinstance(message, ErrorMessage):
                        self._terminal_received = True
                        raise PluginOperationError(message.payload)
                    raise PluginProtocolError("unexpected plugin message after request")
        except TimeoutError:
            with suppress(Exception):
                await self._send(
                    connection,
                    CancelMessage(
                        request_id=invocation_id,
                        payload=CancelPayload(reason="plugin invocation timed out"),
                    ),
                )
                self._cancel_sent = True
            raise PluginSessionTimeout("plugin invocation timed out") from None

    def _verify_connection(self, connection: ServerConnection) -> None:
        if connection.subprotocol != SUBPROTOCOL:
            raise PluginProtocolError(f"plugin did not negotiate required subprotocol {SUBPROTOCOL!r}")
        remote_address = connection.remote_address
        if not isinstance(remote_address, tuple) or not remote_address or remote_address[0] != "127.0.0.1":
            raise PluginProtocolError("plugin connection did not originate from IPv4 loopback")

    def _verify_hello(self, message: HelloMessage, invocation_id: str) -> None:
        if message.request_id != invocation_id:
            raise PluginProtocolError("plugin hello request_id does not match the invocation")
        if message.payload.distribution != DistributionIdentity(
            name=self.launch.distribution_name,
            version=self.launch.distribution_version,
        ):
            raise PluginProtocolError("plugin distribution identity does not match the launch metadata")
        if message.payload.sdk.api_major != self.launch.sdk_api_major:
            raise PluginProtocolError("plugin SDK API major does not match the selected runner")
        if PROTOCOL_VERSION not in message.payload.protocol_versions:
            raise PluginProtocolError("plugin does not support host protocol version 1")
        if self.launch.expected_plugin_id is not None and message.payload.plugin_id != self.launch.expected_plugin_id:
            raise PluginProtocolError("plugin ID does not match the expected identity")

    @staticmethod
    def _runner_environment() -> dict[str, str]:
        return {key: value for key, value in os.environ.items() if not _UV_INDEX_CREDENTIAL.fullmatch(key)}

    async def _receive(
        self,
        connection: ServerConnection,
    ) -> HelloMessage | ProgressMessage | ResultMessage | ErrorMessage:
        try:
            raw_message = await connection.recv()
        except ConnectionClosed as error:
            expected = "a terminal result" if self._request_sent else "plugin hello"
            raise PluginProcessError(f"plugin connection closed before {expected}") from error
        size = len(raw_message) if isinstance(raw_message, bytes) else len(raw_message.encode("utf-8"))
        if size > self.limits.max_message_bytes:
            raise PluginProtocolError(f"plugin protocol message exceeds {self.limits.max_message_bytes} bytes")
        return decode_plugin_message(raw_message)

    async def _send(
        self,
        connection: ServerConnection,
        message: ReadyMessage | RequestMessage | CancelMessage,
    ) -> None:
        encoded = encode_host_message(message)
        if len(encoded.encode("utf-8")) > self.limits.max_message_bytes:
            raise PluginProtocolError(f"host protocol message exceeds {self.limits.max_message_bytes} bytes")
        try:
            await connection.send(encoded)
        except ConnectionClosed as error:
            raise PluginProcessError(f"plugin connection closed while sending {message.type}") from error

    def _write_bootstrap(self, endpoint: str, token: str, invocation_id: str) -> Path:
        descriptor, raw_path = tempfile.mkstemp(prefix="sereto-plugin-", suffix=".json")
        path = Path(raw_path)
        try:
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            content = json.dumps(
                {
                    "endpoint": endpoint,
                    "token": token,
                    "invocation_id": invocation_id,
                    "entry_point": self.launch.entry_point,
                    "distribution": {
                        "name": self.launch.distribution_name,
                        "version": self.launch.distribution_version,
                    },
                    "expected_plugin_id": self.launch.expected_plugin_id,
                    "expires_at": (datetime.now(UTC) + timedelta(seconds=BOOTSTRAP_TTL_SECONDS)).isoformat(),
                    "max_message_bytes": self.limits.max_message_bytes,
                },
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            with os.fdopen(descriptor, "wb") as bootstrap_file:
                descriptor = -1
                bootstrap_file.write(content)
                bootstrap_file.flush()
                os.fsync(bootstrap_file.fileno())
            return path
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            path.unlink(missing_ok=True)
            raise

    async def _cancel_and_stop(self, process: Process, invocation_id: str, reason: str) -> None:
        if self._terminal_received:
            await self._stop_process(process, terminate=False)
            return
        cancellation_sent = self._cancel_sent
        if not cancellation_sent and self._connection is not None and self._request_sent:
            with suppress(Exception):
                await self._send(
                    self._connection,
                    CancelMessage(request_id=invocation_id, payload=CancelPayload(reason=reason)),
                )
                cancellation_sent = True
        await self._stop_process(process, terminate=not cancellation_sent)

    async def _stop_process(self, process: Process, terminate: bool) -> None:
        if process.returncode is not None:
            return
        if not terminate:
            try:
                await asyncio.wait_for(process.wait(), timeout=self.limits.cancel_grace_seconds)
                return
            except TimeoutError:
                terminate = True
        if terminate:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=self.limits.cancel_grace_seconds)
                return
            except TimeoutError:
                process.kill()
                await process.wait()

    @staticmethod
    def _remaining(deadline: float | None) -> float:
        if deadline is None:
            return 0.0
        return max(0.0, deadline - asyncio.get_running_loop().time())
