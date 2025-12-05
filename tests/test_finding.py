from collections.abc import Sequence
from ipaddress import ip_address
from pathlib import Path
from typing import cast

from pydantic import AnyUrl

from sereto.enums import Risk
from sereto.finding import FindingGroup, SubFinding
from sereto.models.locator import IpLocatorModel, LocatorModel, UrlLocatorModel


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


def test_group_subfinding_locators_hide_duplicates():
    group = FindingGroup(
        name="web",
        explicit_risk=None,
        sub_findings=[_sf("a", [UrlLocatorModel(value=_url("https://shared"))])],
        _target_locators=_loc_list(),
        _finding_group_locators=_loc_list(UrlLocatorModel(value=_url("https://shared"))),
        _show_locator_types=["url"],
    )

    assert group.subfinding_locators(group.sub_findings[0]) == []


def test_group_subfinding_locators_return_unique_values():
    group = FindingGroup(
        name="api",
        explicit_risk=None,
        sub_findings=[
            _sf(
                "a",
                [
                    UrlLocatorModel(value=_url("https://group")),
                    IpLocatorModel(value=ip_address("10.0.0.20")),
                ],
            )
        ],
        _target_locators=_loc_list(),
        _finding_group_locators=_loc_list(UrlLocatorModel(value=_url("https://group"))),
        _show_locator_types=["url", "ip"],
    )

    assert _serialize(group.subfinding_locators(group.sub_findings[0])) == [
        ("url", "https://group/"),
        ("ip", "10.0.0.20"),
    ]


def test_group_subfinding_locators_ignore_hidden_types():
    group = FindingGroup(
        name="hidden",
        explicit_risk=None,
        sub_findings=[_sf("a", [IpLocatorModel(value=ip_address("10.1.1.1"))])],
        _target_locators=_loc_list(),
        _finding_group_locators=_loc_list(),
        _show_locator_types=["url"],
    )

    assert group.subfinding_locators(group.sub_findings[0]) == []


def test_subfinding_locators_detects_equality_ignoring_order():
    sub = _sf(
        "ordered",
        [
            UrlLocatorModel(value=_url("https://same")),
            IpLocatorModel(value=ip_address("10.0.0.8")),
        ],
    )
    group = FindingGroup(
        name="order",
        explicit_risk=None,
        sub_findings=[sub],
        _target_locators=_loc_list(),
        _finding_group_locators=_loc_list(
            IpLocatorModel(value=ip_address("10.0.0.8")),
            UrlLocatorModel(value=_url("https://same")),
        ),
        _show_locator_types=["url", "ip"],
    )

    assert group.subfinding_locators(sub) == []


def test_subfinding_locators_return_unique_values_when_group_has_additional_context():
    sub_a = _sf(
        "a",
        [
            UrlLocatorModel(value=_url("https://service-a")),
            UrlLocatorModel(value=_url("https://service-a")),
        ],
    )
    sub_b = _sf("b", [IpLocatorModel(value=ip_address("10.0.0.2"))])
    group = FindingGroup(
        name="with-extra",
        explicit_risk=None,
        sub_findings=[sub_a, sub_b],
        _target_locators=_loc_list(),
        _finding_group_locators=_loc_list(),
        _show_locator_types=["url", "ip"],
    )

    assert _serialize(group.subfinding_locators(sub_a)) == [("url", "https://service-a/")]


def test_subfinding_locators_fallbacks_to_target_when_sub_is_empty():
    empty = _sf("empty", [])
    other = _sf("other", [UrlLocatorModel(value=_url("https://other"))])
    group = FindingGroup(
        name="fallback",
        explicit_risk=None,
        sub_findings=[empty, other],
        _target_locators=_loc_list(
            IpLocatorModel(value=ip_address("172.16.0.1")),
            UrlLocatorModel(value=_url("https://fallback")),
        ),
        _finding_group_locators=_loc_list(),
        _show_locator_types=["ip"],
    )

    assert _serialize(group.subfinding_locators(empty)) == [("ip", "172.16.0.1")]


def test_subfinding_locators_filters_disallowed_types_in_subresults():
    sub_a = _sf(
        "filtered",
        [
            IpLocatorModel(value=ip_address("10.0.0.1")),
            UrlLocatorModel(value=_url("https://hidden")),
        ],
    )
    sub_b = _sf("peer", [IpLocatorModel(value=ip_address("10.0.0.2"))])
    group = FindingGroup(
        name="filter-types",
        explicit_risk=None,
        sub_findings=[sub_a, sub_b],
        _target_locators=_loc_list(),
        _finding_group_locators=_loc_list(),
        _show_locator_types=["ip"],
    )

    assert _serialize(group.subfinding_locators(sub_a)) == [("ip", "10.0.0.1")]


def test_subfinding_locators_returns_empty_when_only_explicit_group_locators_exist():
    sub = _sf("empty", [])
    group = FindingGroup(
        name="explicit",
        explicit_risk=None,
        sub_findings=[sub],
        _target_locators=_loc_list(IpLocatorModel(value=ip_address("192.0.2.5"))),
        _finding_group_locators=_loc_list(UrlLocatorModel(value=_url("https://explicit"))),
        _show_locator_types=["url", "ip"],
    )

    assert group.subfinding_locators(sub) == []
