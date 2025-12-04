from collections.abc import Sequence
from ipaddress import ip_address
from pathlib import Path
from typing import cast

from sereto.enums import Risk
from sereto.finding import FindingGroup, SubFinding
from sereto.models.locator import IpLocatorModel, LocatorModel, UrlLocatorModel
from pydantic import AnyUrl


def _sf(name: str, locators: Sequence[LocatorModel]) -> SubFinding:
    return SubFinding(name=name, risk=Risk.low, vars={}, path=Path(__file__), locators=list(locators))


def _serialize(locs: Sequence[LocatorModel]) -> list[tuple[str, str]]:
    return [(loc.type, str(loc.value)) for loc in locs]


def _url(value: str) -> AnyUrl:
    return cast(AnyUrl, value)


def _loc_list(*locs: LocatorModel) -> list[LocatorModel]:
    return list(locs)


def test_locators_use_explicit_group_list():
    group = FindingGroup(
        name="web",
        explicit_risk=None,
        sub_findings=[_sf("a", []), _sf("b", [])],
        _target_locators=_loc_list(
            UrlLocatorModel(value=_url("https://target")),
            IpLocatorModel(value=ip_address("10.0.0.1")),
        ),
        _finding_group_locators=_loc_list(
            UrlLocatorModel(value=_url("https://group")),
            IpLocatorModel(value=ip_address("10.0.0.10")),
        ),
        _show_locator_types=["url", "ip"],
    )

    assert _serialize(group.locators) == [
        ("url", "https://group/"),
        ("ip", "10.0.0.10"),
    ]


def test_locators_union_when_all_subfindings_have_entries():
    group = FindingGroup(
        name="api",
        explicit_risk=None,
        sub_findings=[
            _sf(
                "a",
                [
                    UrlLocatorModel(value=_url("https://a")),
                    IpLocatorModel(value=ip_address("192.168.0.1")),
                ],
            ),
            _sf(
                "b",
                [
                    UrlLocatorModel(value=_url("https://b")),
                    UrlLocatorModel(value=_url("https://a")),
                ],
            ),
        ],
        _target_locators=_loc_list(IpLocatorModel(value=ip_address("10.0.0.1"))),
        _finding_group_locators=_loc_list(),
        _show_locator_types=["url", "ip"],
    )

    assert _serialize(group.locators) == [
        ("url", "https://a/"),
        ("ip", "192.168.0.1"),
        ("url", "https://b/"),
    ]


def test_locators_partial_subfindings_include_target_fallback():
    group = FindingGroup(
        name="mixed",
        explicit_risk=None,
        sub_findings=[
            _sf("a", [UrlLocatorModel(value=_url("https://app"))]),
            _sf("b", []),
        ],
        _target_locators=_loc_list(
            IpLocatorModel(value=ip_address("10.10.10.10")),
            UrlLocatorModel(value=_url("https://target")),
        ),
        _finding_group_locators=_loc_list(),
        _show_locator_types=["url", "ip"],
    )

    assert _serialize(group.locators) == [
        ("url", "https://app/"),
        ("ip", "10.10.10.10"),
        ("url", "https://target/"),
    ]
