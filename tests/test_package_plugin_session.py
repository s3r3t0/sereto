import asyncio
import json
import sys
from pathlib import Path
from typing import cast

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosedOK, InvalidStatus
from websockets.typing import Subprotocol

import sereto.package_plugins.session as session_module
from sereto.exceptions import SeretoValueError
from sereto.package_plugins.protocol_v1 import (
    HelloMessage,
    Manifest,
    OperationRequest,
    OperationResultPayload,
    PluginProtocolError,
    ProgressMessage,
    ProgressPayload,
    RequestMessage,
    Resource,
    ResultMessage,
)
from sereto.package_plugins.session import (
    PluginLaunch,
    PluginOperationError,
    PluginProcessError,
    PluginSession,
    PluginSessionTimeout,
    SessionLimits,
)


class FakeProcess:
    def __init__(self, task: asyncio.Task[None], *, ignore_terminate: bool = False) -> None:
        self._task = task
        self._ignore_terminate = ignore_terminate
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        task.add_done_callback(self._set_returncode)

    def _set_returncode(self, task: asyncio.Task[None]) -> None:
        self.returncode = 0 if not task.cancelled() and task.exception() is None else 1

    async def wait(self) -> int:
        try:
            await asyncio.shield(self._task)
        except asyncio.CancelledError:
            if not self._task.cancelled():
                raise
        return self.returncode or 0

    def terminate(self) -> None:
        self.terminate_calls += 1
        if not self._ignore_terminate:
            self._task.cancel()

    def kill(self) -> None:
        self.kill_calls += 1
        self._task.cancel()


class FakeConnection:
    subprotocol = Subprotocol("sereto.plugin.v1")
    remote_address = ("127.0.0.1", 43123)

    def __init__(self, incoming: str = "") -> None:
        self.incoming = incoming
        self.sent: list[str] = []

    async def recv(self) -> str:
        return self.incoming

    async def send(self, message: str) -> None:
        self.sent.append(message)


class ClosedSendConnection(FakeConnection):
    async def send(self, message: str) -> None:
        raise ConnectionClosedOK(None, None)


def _launch() -> PluginLaunch:
    return PluginLaunch(
        python=Path(sys.executable),
        distribution_name="acme-testssl",
        distribution_version="2.4.1",
        entry_point="acme-testssl",
        expected_plugin_id="acme-testssl",
        sdk_api_major=1,
    )


@pytest.mark.parametrize(
    "limits",
    [
        pytest.param(SessionLimits(max_message_bytes=1023), id="message-limit-too-small"),
        pytest.param(SessionLimits(max_message_bytes=4 * 1024 * 1024 + 1), id="message-limit-too-large"),
        pytest.param(SessionLimits(handshake_timeout_seconds=0), id="handshake-timeout"),
        pytest.param(SessionLimits(invocation_timeout_seconds=0), id="invocation-timeout"),
        pytest.param(SessionLimits(cancel_grace_seconds=-1), id="cancel-grace"),
    ],
)
def test_session_limits_reject_invalid_values(limits: SessionLimits) -> None:
    with pytest.raises(SeretoValueError, match="invalid plugin session limits"):
        PluginSession(launch=_launch(), sereto_version="0.8.3", limits=limits)


def test_plugin_session_rejects_request_resource_kind_not_advertised_by_host() -> None:
    session = PluginSession(
        launch=_launch(),
        sereto_version="0.8.3",
        resource_kinds=(),
    )
    request = OperationRequest(
        operation_id="testssl.analyze",
        resources=(Resource(kind="sereto.target.v1", id="target_1", attributes={}),),
    )

    with pytest.raises(SeretoValueError, match="request uses a resource kind not supported by this host session"):
        asyncio.run(session.run(request))


def test_plugin_session_rejects_concurrent_reuse(monkeypatch: pytest.MonkeyPatch) -> None:
    process_started = asyncio.Event()

    async def never_connect() -> None:
        await asyncio.Event().wait()

    async def create_fake_process(*command: object, **kwargs: object) -> FakeProcess:
        process_started.set()
        return FakeProcess(asyncio.create_task(never_connect()))

    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", create_fake_process)

    async def exercise() -> None:
        session = PluginSession(
            launch=_launch(),
            sereto_version="0.8.3",
            limits=SessionLimits(handshake_timeout_seconds=1, cancel_grace_seconds=0.01),
        )
        first_invocation = asyncio.create_task(session.run(OperationRequest(operation_id="testssl.analyze")))
        await process_started.wait()
        with pytest.raises(SeretoValueError, match="plugin session is already active"):
            await session.run(OperationRequest(operation_id="testssl.analyze"))
        first_invocation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first_invocation

    asyncio.run(exercise())


def test_plugin_session_rejects_oversized_inbound_message() -> None:
    session = PluginSession(
        launch=_launch(),
        sereto_version="0.8.3",
        limits=SessionLimits(max_message_bytes=1024),
    )
    connection = cast(ServerConnection, FakeConnection("x" * 1025))

    with pytest.raises(PluginProtocolError, match="plugin protocol message exceeds 1024 bytes"):
        asyncio.run(session._receive(connection))


def test_plugin_session_rejects_oversized_outbound_message() -> None:
    session = PluginSession(
        launch=_launch(),
        sereto_version="0.8.3",
        limits=SessionLimits(max_message_bytes=1024),
    )
    connection = FakeConnection()
    message = RequestMessage(
        request_id="request-1",
        payload=OperationRequest(
            operation_id="testssl.analyze",
            arguments={"content": "x" * 1024},
        ),
    )

    with pytest.raises(PluginProtocolError, match="host protocol message exceeds 1024 bytes"):
        asyncio.run(session._send(cast(ServerConnection, connection), message))
    assert connection.sent == []


def test_plugin_session_normalizes_connection_closed_while_sending() -> None:
    session = PluginSession(launch=_launch(), sereto_version="0.8.3")
    message = RequestMessage(
        request_id="request-1",
        payload=OperationRequest(operation_id="testssl.analyze"),
    )

    with pytest.raises(PluginProcessError, match="plugin connection closed while sending request"):
        asyncio.run(session._send(cast(ServerConnection, ClosedSendConnection()), message))


def _read_bootstrap(path: Path) -> dict[str, object]:
    bootstrap = json.loads(path.read_text(encoding="utf-8"))
    path.unlink()
    return bootstrap


async def _send_hello(
    websocket: object,
    bootstrap: dict[str, object],
    *,
    plugin_id: str = "acme-testssl",
    distribution_identity: object | None = None,
) -> None:
    await websocket.send(  # type: ignore[attr-defined]
        json.dumps(
            {
                "protocol_version": 1,
                "type": "hello",
                "request_id": bootstrap["invocation_id"],
                "payload": {
                    "plugin_id": plugin_id,
                    "distribution": bootstrap["distribution"]
                    if distribution_identity is None
                    else distribution_identity,
                    "sdk": {"api_major": 1, "package_version": "0.1.0"},
                    "protocol_versions": [1],
                },
            }
        )
    )


def _manifest_result(bootstrap: dict[str, object], *, plugin_id: str = "acme-testssl") -> str:
    return json.dumps(
        {
            "protocol_version": 1,
            "type": "result",
            "request_id": bootstrap["invocation_id"],
            "payload": {
                "kind": "manifest",
                "manifest": {
                    "manifest_version": 1,
                    "plugin_id": plugin_id,
                    "sdk_api_major": 1,
                    "protocol_versions": [1],
                    "requires_sereto": ">=0.9,<1",
                    "capabilities": ["finding.propose"],
                    "resource_kinds": ["sereto.target.v1"],
                    "operations": [
                        {
                            "id": "testssl.analyze",
                            "capability": "finding.propose",
                            "resource_kinds": ["sereto.target.v1"],
                        }
                    ],
                    "commands": [
                        {
                            "path": ["findings", "testssl"],
                            "operation_id": "testssl.analyze",
                            "summary": "Analyze testssl output",
                        }
                    ],
                },
            },
        }
    )


def test_plugin_session_runs_authenticated_operation_over_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    progress: list[ProgressPayload] = []
    launched_command: tuple[object, ...] | None = None
    monkeypatch.setenv("UV_INDEX_PRIVATE_USERNAME", "plugin-must-not-see-this")
    monkeypatch.setenv("UV_INDEX_PRIVATE_PASSWORD", "plugin-must-not-see-this")

    async def fake_runner(bootstrap_path: Path) -> None:
        bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
        bootstrap_path.unlink()
        async with connect(
            bootstrap["endpoint"],
            additional_headers={"Authorization": f"Bearer {bootstrap['token']}"},
            subprotocols=[Subprotocol("sereto.plugin.v1")],
            compression=None,
            proxy=None,
        ) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "protocol_version": 1,
                        "type": "hello",
                        "request_id": bootstrap["invocation_id"],
                        "payload": {
                            "plugin_id": "acme-testssl",
                            "distribution": bootstrap["distribution"],
                            "sdk": {"api_major": 1, "package_version": "0.1.0"},
                            "protocol_versions": [1],
                        },
                    }
                )
            )
            ready = json.loads(await websocket.recv())
            assert ready["type"] == "ready"
            request = json.loads(await websocket.recv())
            assert request["payload"]["operation_id"] == "testssl.analyze"
            await websocket.send(
                json.dumps(
                    {
                        "protocol_version": 1,
                        "type": "progress",
                        "request_id": bootstrap["invocation_id"],
                        "payload": {"sequence": 1, "fraction": 0.5, "message": "Halfway"},
                    }
                )
            )
            await websocket.send(
                json.dumps(
                    {
                        "protocol_version": 1,
                        "type": "result",
                        "request_id": bootstrap["invocation_id"],
                        "payload": {
                            "kind": "operation",
                            "output": {"analyzed": 10},
                            "finding_proposals": [],
                        },
                    }
                )
            )

    async def create_fake_process(*command: object, **kwargs: object) -> FakeProcess:
        nonlocal launched_command
        launched_command = command
        assert set(kwargs) == {"env"}
        environment = cast(dict[str, str], kwargs["env"])
        assert "UV_INDEX_PRIVATE_USERNAME" not in environment
        assert "UV_INDEX_PRIVATE_PASSWORD" not in environment
        return FakeProcess(asyncio.create_task(fake_runner(Path(str(command[-1])))))

    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", create_fake_process)

    async def exercise() -> OperationResultPayload:
        session = PluginSession(
            launch=_launch(),
            sereto_version="0.8.3",
        )
        return await session.run(
            OperationRequest(operation_id="testssl.analyze"),
            on_progress=progress.append,
        )

    result = asyncio.run(exercise())

    assert result.output == {"analyzed": 10}
    assert [update.sequence for update in progress] == [1]
    assert launched_command is not None
    assert launched_command[:3] == (
        Path(sys.executable),
        "-m",
        "sereto_sdk.v1.runner",
    )


def test_plugin_session_discovers_manifest_before_plugin_id_is_known(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_runner(bootstrap_path: Path) -> None:
        bootstrap = _read_bootstrap(bootstrap_path)
        assert bootstrap["expected_plugin_id"] is None
        async with connect(
            str(bootstrap["endpoint"]),
            additional_headers={"Authorization": f"Bearer {bootstrap['token']}"},
            subprotocols=[Subprotocol("sereto.plugin.v1")],
            compression=None,
            proxy=None,
        ) as websocket:
            await _send_hello(websocket, bootstrap)
            await websocket.recv()
            request = json.loads(await websocket.recv())
            assert request["payload"]["operation_id"] == "sereto.manifest.get"
            await websocket.send(_manifest_result(bootstrap))

    async def create_fake_process(*command: object, **kwargs: object) -> FakeProcess:
        return FakeProcess(asyncio.create_task(fake_runner(Path(str(command[-1])))))

    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", create_fake_process)

    manifest = asyncio.run(
        PluginSession(
            launch=PluginLaunch(
                python=Path(sys.executable),
                distribution_name="acme-testssl",
                distribution_version="2.4.1",
                entry_point="acme-testssl",
                expected_plugin_id=None,
                sdk_api_major=1,
            ),
            sereto_version="0.8.3",
        ).discover_manifest()
    )

    assert isinstance(manifest, Manifest)
    assert manifest.plugin_id == "acme-testssl"
    assert manifest.operations[0].id == "testssl.analyze"


def test_plugin_session_rejects_manifest_identity_different_from_hello(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_runner(bootstrap_path: Path) -> None:
        bootstrap = _read_bootstrap(bootstrap_path)
        async with connect(
            str(bootstrap["endpoint"]),
            additional_headers={"Authorization": f"Bearer {bootstrap['token']}"},
            subprotocols=[Subprotocol("sereto.plugin.v1")],
            compression=None,
            proxy=None,
        ) as websocket:
            await _send_hello(websocket, bootstrap)
            await websocket.recv()
            await websocket.recv()
            await websocket.send(_manifest_result(bootstrap, plugin_id="other-plugin"))
            await websocket.wait_closed()

    async def create_fake_process(*command: object, **kwargs: object) -> FakeProcess:
        return FakeProcess(asyncio.create_task(fake_runner(Path(str(command[-1])))))

    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", create_fake_process)

    with pytest.raises(PluginProtocolError, match="manifest plugin ID does not match plugin hello"):
        asyncio.run(
            PluginSession(
                launch=PluginLaunch(
                    python=Path(sys.executable),
                    distribution_name="acme-testssl",
                    distribution_version="2.4.1",
                    entry_point="acme-testssl",
                    expected_plugin_id=None,
                    sdk_api_major=1,
                ),
                sereto_version="0.8.3",
            ).discover_manifest()
        )


def test_plugin_session_times_out_when_runner_never_connects(monkeypatch: pytest.MonkeyPatch) -> None:
    process: FakeProcess | None = None

    async def never_connect() -> None:
        await asyncio.Event().wait()

    async def create_fake_process(*command: object, **kwargs: object) -> FakeProcess:
        nonlocal process
        process = FakeProcess(asyncio.create_task(never_connect()))
        return process

    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", create_fake_process)

    async def exercise() -> None:
        session = PluginSession(
            launch=_launch(),
            sereto_version="0.8.3",
            limits=SessionLimits(handshake_timeout_seconds=0.01, cancel_grace_seconds=0.01),
        )
        with pytest.raises(PluginProcessError, match="timed out waiting for plugin runner connection"):
            await asyncio.wait_for(
                session.run(OperationRequest(operation_id="testssl.analyze")),
                timeout=0.2,
            )

    asyncio.run(exercise())

    assert process is not None
    assert process.returncode == 1


def test_plugin_session_times_out_when_runner_never_sends_hello(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_runner(bootstrap_path: Path) -> None:
        bootstrap = _read_bootstrap(bootstrap_path)
        async with connect(
            str(bootstrap["endpoint"]),
            additional_headers={"Authorization": f"Bearer {bootstrap['token']}"},
            subprotocols=[Subprotocol("sereto.plugin.v1")],
            compression=None,
            proxy=None,
        ) as websocket:
            await websocket.wait_closed()

    async def create_fake_process(*command: object, **kwargs: object) -> FakeProcess:
        return FakeProcess(asyncio.create_task(fake_runner(Path(str(command[-1])))))

    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", create_fake_process)

    with pytest.raises(PluginSessionTimeout, match="timed out waiting for plugin hello"):
        asyncio.run(
            PluginSession(
                launch=_launch(),
                sereto_version="0.8.3",
                limits=SessionLimits(handshake_timeout_seconds=0.02, cancel_grace_seconds=0.01),
            ).run(OperationRequest(operation_id="testssl.analyze"))
        )


def test_plugin_session_removes_bootstrap_after_launch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    bootstrap_path: Path | None = None

    async def fail_to_launch(*command: object, **kwargs: object) -> FakeProcess:
        nonlocal bootstrap_path
        assert set(kwargs) == {"env"}
        bootstrap_path = Path(str(command[-1]))
        assert bootstrap_path.is_file()
        if sys.platform != "win32":
            assert bootstrap_path.stat().st_mode & 0o777 == 0o600
        raise OSError("injected launch failure")

    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", fail_to_launch)

    with pytest.raises(PluginProcessError, match="failed to launch plugin runner: injected launch failure"):
        asyncio.run(
            PluginSession(launch=_launch(), sereto_version="0.8.3").run(
                OperationRequest(operation_id="testssl.analyze")
            )
        )

    assert bootstrap_path is not None
    assert not bootstrap_path.exists()


def test_plugin_session_rejects_unauthorized_connection_without_consuming_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay_status: int | None = None

    async def fake_runner(bootstrap_path: Path) -> None:
        nonlocal replay_status
        bootstrap = _read_bootstrap(bootstrap_path)
        endpoint = str(bootstrap["endpoint"])
        token = str(bootstrap["token"])
        with pytest.raises(InvalidStatus) as unauthorized:
            async with connect(
                endpoint,
                additional_headers={"Authorization": "Bearer invalid"},
                subprotocols=[Subprotocol("sereto.plugin.v1")],
                compression=None,
                proxy=None,
            ):
                pass
        assert unauthorized.value.response.status_code == 401

        with pytest.raises(InvalidStatus) as duplicate_authorization:
            async with connect(
                endpoint,
                additional_headers=[
                    ("Authorization", f"Bearer {token}"),
                    ("Authorization", f"Bearer {token}"),
                ],
                subprotocols=[Subprotocol("sereto.plugin.v1")],
                compression=None,
                proxy=None,
            ):
                pass
        assert duplicate_authorization.value.response.status_code == 401

        with pytest.raises(InvalidStatus) as browser_origin:
            async with connect(
                endpoint,
                origin="https://example.test",
                additional_headers={"Authorization": f"Bearer {token}"},
                subprotocols=[Subprotocol("sereto.plugin.v1")],
                compression=None,
                proxy=None,
            ):
                pass
        assert browser_origin.value.response.status_code == 403

        with pytest.raises(InvalidStatus) as missing_subprotocol:
            async with connect(
                endpoint,
                additional_headers={"Authorization": f"Bearer {token}"},
                compression=None,
                proxy=None,
            ):
                pass
        assert missing_subprotocol.value.response.status_code == 400

        async with connect(
            endpoint,
            additional_headers={"Authorization": f"Bearer {token}"},
            subprotocols=[Subprotocol("sereto.plugin.v1")],
            compression=None,
            proxy=None,
        ) as websocket:
            with pytest.raises(InvalidStatus) as replay:
                async with connect(
                    endpoint,
                    additional_headers={"Authorization": f"Bearer {token}"},
                    subprotocols=[Subprotocol("sereto.plugin.v1")],
                    compression=None,
                    proxy=None,
                ):
                    pass
            replay_status = replay.value.response.status_code
            await _send_hello(websocket, bootstrap)
            await websocket.recv()
            await websocket.recv()
            await websocket.send(
                json.dumps(
                    {
                        "protocol_version": 1,
                        "type": "result",
                        "request_id": bootstrap["invocation_id"],
                        "payload": {"kind": "operation", "output": {}, "finding_proposals": []},
                    }
                )
            )

    async def create_fake_process(*command: object, **kwargs: object) -> FakeProcess:
        return FakeProcess(asyncio.create_task(fake_runner(Path(str(command[-1])))))

    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", create_fake_process)

    result = asyncio.run(
        PluginSession(launch=_launch(), sereto_version="0.8.3").run(OperationRequest(operation_id="testssl.analyze"))
    )

    assert isinstance(result, OperationResultPayload)
    assert replay_status == 409


def test_plugin_session_rejects_mismatched_plugin_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_runner(bootstrap_path: Path) -> None:
        bootstrap = _read_bootstrap(bootstrap_path)
        async with connect(
            str(bootstrap["endpoint"]),
            additional_headers={"Authorization": f"Bearer {bootstrap['token']}"},
            subprotocols=[Subprotocol("sereto.plugin.v1")],
            compression=None,
            proxy=None,
        ) as websocket:
            await _send_hello(websocket, bootstrap, plugin_id="other-plugin")
            await websocket.wait_closed()

    async def create_fake_process(*command: object, **kwargs: object) -> FakeProcess:
        return FakeProcess(asyncio.create_task(fake_runner(Path(str(command[-1])))))

    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", create_fake_process)

    with pytest.raises(PluginProtocolError, match="plugin ID does not match the expected identity"):
        asyncio.run(
            PluginSession(launch=_launch(), sereto_version="0.8.3").run(
                OperationRequest(operation_id="testssl.analyze")
            )
        )


def test_plugin_session_rejects_mismatched_distribution_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_runner(bootstrap_path: Path) -> None:
        bootstrap = _read_bootstrap(bootstrap_path)
        async with connect(
            str(bootstrap["endpoint"]),
            additional_headers={"Authorization": f"Bearer {bootstrap['token']}"},
            subprotocols=[Subprotocol("sereto.plugin.v1")],
            compression=None,
            proxy=None,
        ) as websocket:
            await _send_hello(
                websocket,
                bootstrap,
                distribution_identity={"name": "other-distribution", "version": "2.4.1"},
            )
            await websocket.wait_closed()

    async def create_fake_process(*command: object, **kwargs: object) -> FakeProcess:
        return FakeProcess(asyncio.create_task(fake_runner(Path(str(command[-1])))))

    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", create_fake_process)

    with pytest.raises(PluginProtocolError, match="distribution identity does not match the launch metadata"):
        asyncio.run(
            PluginSession(launch=_launch(), sereto_version="0.8.3").run(
                OperationRequest(operation_id="testssl.analyze")
            )
        )


@pytest.mark.parametrize(
    ("subprotocol", "remote_address", "message"),
    [
        pytest.param(None, ("127.0.0.1", 43123), "required subprotocol", id="subprotocol"),
        pytest.param(
            Subprotocol("sereto.plugin.v1"),
            ("192.0.2.1", 43123),
            "IPv4 loopback",
            id="remote-address",
        ),
    ],
)
def test_plugin_session_verifies_connection_transport(
    subprotocol: Subprotocol | None,
    remote_address: tuple[str, int],
    message: str,
) -> None:
    class ConnectionMetadata:
        def __init__(self) -> None:
            self.subprotocol = subprotocol
            self.remote_address = remote_address

    session = PluginSession(launch=_launch(), sereto_version="0.8.3")

    with pytest.raises(PluginProtocolError, match=message):
        session._verify_connection(cast(ServerConnection, ConnectionMetadata()))


def test_plugin_session_rejects_noncontiguous_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_runner(bootstrap_path: Path) -> None:
        bootstrap = _read_bootstrap(bootstrap_path)
        async with connect(
            str(bootstrap["endpoint"]),
            additional_headers={"Authorization": f"Bearer {bootstrap['token']}"},
            subprotocols=[Subprotocol("sereto.plugin.v1")],
            compression=None,
            proxy=None,
        ) as websocket:
            await _send_hello(websocket, bootstrap)
            await websocket.recv()
            await websocket.recv()
            await websocket.send(
                json.dumps(
                    {
                        "protocol_version": 1,
                        "type": "progress",
                        "request_id": bootstrap["invocation_id"],
                        "payload": {"sequence": 2, "message": "Skipped sequence one"},
                    }
                )
            )
            await websocket.wait_closed()

    async def create_fake_process(*command: object, **kwargs: object) -> FakeProcess:
        return FakeProcess(asyncio.create_task(fake_runner(Path(str(command[-1])))))

    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", create_fake_process)

    with pytest.raises(PluginProtocolError, match="plugin progress sequence is not contiguous"):
        asyncio.run(
            PluginSession(launch=_launch(), sereto_version="0.8.3").run(
                OperationRequest(operation_id="testssl.analyze")
            )
        )


def test_plugin_session_preserves_structured_operation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_message_types: list[str] = []

    class RecordingSession(PluginSession):
        async def _send(self, connection: ServerConnection, message: object) -> None:
            sent_message_types.append(str(message.type))  # type: ignore[attr-defined]
            await super()._send(connection, message)  # type: ignore[arg-type]

    async def fake_runner(bootstrap_path: Path) -> None:
        bootstrap = _read_bootstrap(bootstrap_path)
        async with connect(
            str(bootstrap["endpoint"]),
            additional_headers={"Authorization": f"Bearer {bootstrap['token']}"},
            subprotocols=[Subprotocol("sereto.plugin.v1")],
            compression=None,
            proxy=None,
        ) as websocket:
            await _send_hello(websocket, bootstrap)
            await websocket.recv()
            await websocket.recv()
            await websocket.send(
                json.dumps(
                    {
                        "protocol_version": 1,
                        "type": "error",
                        "request_id": bootstrap["invocation_id"],
                        "payload": {
                            "code": "plugin.invalid-input",
                            "message": "scan.json is not supported",
                            "retryable": False,
                            "details": {"argument": "scan.json"},
                        },
                    }
                )
            )

    async def create_fake_process(*command: object, **kwargs: object) -> FakeProcess:
        return FakeProcess(asyncio.create_task(fake_runner(Path(str(command[-1])))))

    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", create_fake_process)

    with pytest.raises(PluginOperationError) as operation_error:
        asyncio.run(
            RecordingSession(launch=_launch(), sereto_version="0.8.3").run(
                OperationRequest(operation_id="testssl.analyze")
            )
        )

    assert operation_error.value.payload.code == "plugin.invalid-input"
    assert operation_error.value.payload.details == {"argument": "scan.json"}
    assert sent_message_types == ["ready", "request"]


def test_plugin_session_caller_cancellation_is_forwarded_without_terminating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_received = asyncio.Event()
    cancellation_received = asyncio.Event()
    process: FakeProcess | None = None

    async def fake_runner(bootstrap_path: Path) -> None:
        bootstrap = _read_bootstrap(bootstrap_path)
        async with connect(
            str(bootstrap["endpoint"]),
            additional_headers={"Authorization": f"Bearer {bootstrap['token']}"},
            subprotocols=[Subprotocol("sereto.plugin.v1")],
            compression=None,
            proxy=None,
        ) as websocket:
            await _send_hello(websocket, bootstrap)
            await websocket.recv()
            await websocket.recv()
            request_received.set()
            cancel = json.loads(await websocket.recv())
            assert cancel["type"] == "cancel"
            assert cancel["payload"]["reason"] == "host invocation cancelled"
            cancellation_received.set()

    async def create_fake_process(*command: object, **kwargs: object) -> FakeProcess:
        nonlocal process
        process = FakeProcess(asyncio.create_task(fake_runner(Path(str(command[-1])))))
        return process

    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", create_fake_process)

    async def exercise() -> None:
        invocation = asyncio.create_task(
            PluginSession(
                launch=_launch(),
                sereto_version="0.8.3",
                limits=SessionLimits(cancel_grace_seconds=0.1),
            ).run(OperationRequest(operation_id="testssl.analyze"))
        )
        await request_received.wait()
        invocation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await invocation

    asyncio.run(exercise())

    assert cancellation_received.is_set()
    assert process is not None
    assert process.terminate_calls == 0
    assert process.kill_calls == 0


def test_plugin_session_timeout_escalates_from_cancel_to_terminate_and_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancellation_received = asyncio.Event()
    process: FakeProcess | None = None

    async def fake_runner(bootstrap_path: Path) -> None:
        bootstrap = _read_bootstrap(bootstrap_path)
        async with connect(
            str(bootstrap["endpoint"]),
            additional_headers={"Authorization": f"Bearer {bootstrap['token']}"},
            subprotocols=[Subprotocol("sereto.plugin.v1")],
            compression=None,
            proxy=None,
        ) as websocket:
            await _send_hello(websocket, bootstrap)
            await websocket.recv()
            await websocket.recv()
            cancel = json.loads(await websocket.recv())
            assert cancel["type"] == "cancel"
            assert cancel["payload"]["reason"] == "plugin invocation timed out"
            cancellation_received.set()
            await asyncio.Event().wait()

    async def create_fake_process(*command: object, **kwargs: object) -> FakeProcess:
        nonlocal process
        process = FakeProcess(
            asyncio.create_task(fake_runner(Path(str(command[-1])))),
            ignore_terminate=True,
        )
        return process

    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", create_fake_process)

    with pytest.raises(PluginSessionTimeout, match="plugin invocation timed out"):
        asyncio.run(
            PluginSession(
                launch=_launch(),
                sereto_version="0.8.3",
                limits=SessionLimits(invocation_timeout_seconds=0.01, cancel_grace_seconds=0.01),
            ).run(OperationRequest(operation_id="testssl.analyze"))
        )

    assert cancellation_received.is_set()
    assert process is not None
    assert process.terminate_calls == 1
    assert process.kill_calls == 1


def test_plugin_session_accepts_buffered_result_after_runner_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    class DelayedResultSession(PluginSession):
        async def _receive(self, connection: object) -> HelloMessage | ProgressMessage | ResultMessage:
            message = await super()._receive(connection)  # type: ignore[arg-type]
            if isinstance(message, ResultMessage):
                await asyncio.sleep(0.02)
            return message

    async def fake_runner(bootstrap_path: Path) -> None:
        bootstrap = _read_bootstrap(bootstrap_path)
        async with connect(
            str(bootstrap["endpoint"]),
            additional_headers={"Authorization": f"Bearer {bootstrap['token']}"},
            subprotocols=[Subprotocol("sereto.plugin.v1")],
            compression=None,
            proxy=None,
        ) as websocket:
            await _send_hello(websocket, bootstrap)
            await websocket.recv()
            await websocket.recv()
            await websocket.send(
                json.dumps(
                    {
                        "protocol_version": 1,
                        "type": "result",
                        "request_id": bootstrap["invocation_id"],
                        "payload": {
                            "kind": "operation",
                            "output": {"buffered": True},
                            "finding_proposals": [],
                        },
                    }
                )
            )

    async def create_fake_process(*command: object, **kwargs: object) -> FakeProcess:
        return FakeProcess(asyncio.create_task(fake_runner(Path(str(command[-1])))))

    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", create_fake_process)

    result = asyncio.run(
        DelayedResultSession(
            launch=_launch(),
            sereto_version="0.8.3",
            limits=SessionLimits(cancel_grace_seconds=0.1),
        ).run(OperationRequest(operation_id="testssl.analyze"))
    )

    assert isinstance(result, OperationResultPayload)
    assert result.output == {"buffered": True}


def test_plugin_session_waits_for_slow_progress_callback_after_runner_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    progress: list[ProgressPayload] = []

    async def fake_runner(bootstrap_path: Path) -> None:
        bootstrap = _read_bootstrap(bootstrap_path)
        async with connect(
            str(bootstrap["endpoint"]),
            additional_headers={"Authorization": f"Bearer {bootstrap['token']}"},
            subprotocols=[Subprotocol("sereto.plugin.v1")],
            compression=None,
            proxy=None,
        ) as websocket:
            await _send_hello(websocket, bootstrap)
            await websocket.recv()
            await websocket.recv()
            await websocket.send(
                json.dumps(
                    {
                        "protocol_version": 1,
                        "type": "progress",
                        "request_id": bootstrap["invocation_id"],
                        "payload": {"sequence": 1, "fraction": 0.5, "message": "Halfway"},
                    }
                )
            )
            await websocket.send(
                json.dumps(
                    {
                        "protocol_version": 1,
                        "type": "result",
                        "request_id": bootstrap["invocation_id"],
                        "payload": {
                            "kind": "operation",
                            "output": {"buffered": True},
                            "finding_proposals": [],
                        },
                    }
                )
            )

    async def create_fake_process(*command: object, **kwargs: object) -> FakeProcess:
        return FakeProcess(asyncio.create_task(fake_runner(Path(str(command[-1])))))

    async def record_progress(update: ProgressPayload) -> None:
        await asyncio.sleep(0.02)
        progress.append(update)

    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", create_fake_process)

    result = asyncio.run(
        PluginSession(
            launch=_launch(),
            sereto_version="0.8.3",
            limits=SessionLimits(invocation_timeout_seconds=1, cancel_grace_seconds=0.001),
        ).run(
            OperationRequest(operation_id="testssl.analyze"),
            on_progress=record_progress,
        )
    )

    assert isinstance(result, OperationResultPayload)
    assert result.output == {"buffered": True}
    assert [update.sequence for update in progress] == [1]


def test_plugin_session_normalizes_connection_closed_before_terminal_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_runner(bootstrap_path: Path) -> None:
        bootstrap = _read_bootstrap(bootstrap_path)
        async with connect(
            str(bootstrap["endpoint"]),
            additional_headers={"Authorization": f"Bearer {bootstrap['token']}"},
            subprotocols=[Subprotocol("sereto.plugin.v1")],
            compression=None,
            proxy=None,
        ) as websocket:
            await _send_hello(websocket, bootstrap)
            await websocket.recv()
            await websocket.recv()

    async def create_fake_process(*command: object, **kwargs: object) -> FakeProcess:
        return FakeProcess(asyncio.create_task(fake_runner(Path(str(command[-1])))))

    monkeypatch.setattr(session_module.asyncio, "create_subprocess_exec", create_fake_process)

    with pytest.raises(PluginProcessError, match="plugin connection closed before a terminal result"):
        asyncio.run(
            PluginSession(launch=_launch(), sereto_version="0.8.3").run(
                OperationRequest(operation_id="testssl.analyze")
            )
        )
