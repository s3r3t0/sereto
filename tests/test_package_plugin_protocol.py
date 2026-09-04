import json

import pytest

from sereto.package_plugins.protocol_v1 import (
    CancelMessage,
    OperationResultPayload,
    PluginProtocolError,
    ResultMessage,
    decode_plugin_message,
    encode_host_message,
)


def test_plugin_result_decodes_from_representative_text_json() -> None:
    message = decode_plugin_message(
        json.dumps(
            {
                "protocol_version": 1,
                "type": "result",
                "request_id": "018f2d8e-27d1-7a8d-9b34-913fd9f558ad",
                "payload": {
                    "kind": "operation",
                    "output": {"endpoints_analyzed": 10},
                    "finding_proposals": [],
                },
            }
        )
    )

    assert isinstance(message, ResultMessage)
    assert isinstance(message.payload, OperationResultPayload)
    assert message.payload.output == {"endpoints_analyzed": 10}


@pytest.mark.parametrize(
    ("message", "error"),
    [
        pytest.param(b"{}", "binary plugin protocol messages", id="binary"),
        pytest.param(
            '{"protocol_version":1,"protocol_version":1}',
            "duplicate JSON key 'protocol_version'",
            id="duplicate-key",
        ),
        pytest.param(
            '{"protocol_version":1,"type":"progress","request_id":"request-1",'
            '"payload":{"sequence":1,"fraction":NaN}}',
            "non-finite JSON number 'NaN'",
            id="non-finite-number",
        ),
        pytest.param(
            '{"protocol_version":true,"type":"progress","request_id":"request-1","payload":{"sequence":1}}',
            "invalid plugin protocol message",
            id="boolean-version",
        ),
        pytest.param(
            '{"protocol_version":1,"type":"hello","request_id":"request-1",'
            '"payload":{"plugin_id":"acme-testssl","distribution":{"name":"acme-testssl",'
            '"version":"2.4.1"},"sdk":{"api_major":2,"package_version":"0.1.0"},'
            '"protocol_versions":[1]}}',
            "invalid plugin protocol message",
            id="wrong-sdk-major",
        ),
        pytest.param(
            '{"protocol_version":1,"type":"hello","request_id":"request-1",'
            '"payload":{"plugin_id":"acme-testssl","distribution":{"name":"acme-testssl",'
            '"version":"2.4.1"},"sdk":{"api_major":1,"package_version":"0.1.0"},'
            '"protocol_versions":[2]}}',
            "invalid plugin protocol message",
            id="unsupported-protocol-version",
        ),
    ],
)
def test_protocol_rejects_non_text_or_ambiguous_json(message: str | bytes, error: str) -> None:
    with pytest.raises(PluginProtocolError, match=error):
        decode_plugin_message(message)


def test_protocol_rejects_manifest_operation_with_undeclared_resource_kind() -> None:
    message = json.dumps(
        {
            "protocol_version": 1,
            "type": "result",
            "request_id": "request-1",
            "payload": {
                "kind": "manifest",
                "manifest": {
                    "manifest_version": 1,
                    "plugin_id": "acme-testssl",
                    "sdk_api_major": 1,
                    "protocol_versions": [1],
                    "requires_sereto": ">=0.9,<1",
                    "capabilities": ["finding.propose"],
                    "resource_kinds": [],
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

    with pytest.raises(PluginProtocolError, match="operation 'testssl.analyze' uses an undeclared resource kind"):
        decode_plugin_message(message)


def test_host_message_encoding_is_compact_json() -> None:
    encoded = encode_host_message(CancelMessage(request_id="request-1"))

    assert " " not in encoded
