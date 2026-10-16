import asyncio

import pytest
from textual.app import App

from sereto.models.target import TargetDastModel, TargetMobileModel, TargetModel, TargetSastModel
from sereto.tui.app import ConfigRecordFormScreen, _TargetFormData


@pytest.mark.parametrize(
    "model",
    [
        TargetDastModel(
            id="edge",
            category="dast",
            name="Public API",
            locators=[{"type": "url", "value": "https://example.com"}],
            documents=[{"type": "api", "value": "openapi.json"}],
            dst_ips_dynamic=True,
            dst_ips_dynamic_details="Cloud-hosted",
            src_ips=["192.0.2.1", "198.51.100.0/24"],
            ip_filtering=True,
            ip_allowed=True,
            authentication=True,
            credentials_provided=False,
            exposure="external",
            environment="production",
            waf_present=True,
            waf_whitelisted=False,
            owner="security",
        ),
        TargetSastModel(
            category="sast",
            name="Backend",
            code_origin="archive",
            code_origin_name="source.tar.gz",
            code_integrity={"source.tar.gz": "sha256:abc"},
            source_code_analyzer_files=["results.sarif"],
        ),
        TargetMobileModel(
            category="mobile",
            name="Client apps",
            android={
                "package_name": "com.example.app",
                "version_name": "2.0",
                "version_code": "20",
                "file_integrity": {"app.apk": "sha256:def"},
            },
            ios={
                "bundle_id": "com.example.app",
                "short_version_string": "2.0",
                "version": "20",
                "file_integrity": {"app.ipa": "sha256:ghi"},
            },
        ),
        TargetModel(category="generic", name="Other", custom_flag=True),
    ],
)
def test_target_edit_form_round_trips_model(model: TargetModel) -> None:
    async def run_form() -> TargetModel:
        app = App()
        async with app.run_test() as pilot:
            screen = ConfigRecordFormScreen(
                "target",
                categories=[model.category.upper()],
                initial=_TargetFormData(model),
            )
            await app.push_screen(screen)
            await pilot.pause()
            return screen._build_target_model(model.category, model.name)

    result = asyncio.run(run_form())

    assert type(result) is type(model)
    assert result.model_dump(mode="json") == model.model_dump(mode="json")
