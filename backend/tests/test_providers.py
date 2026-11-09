"""Tests for the provider registry.

The registry must report real availability from the environment, must never
return a credential value, and must select by declared capability rather than
by any performance claim.
"""

from __future__ import annotations

import os

import pytest

from level5.llm.providers import ProviderRegistry, ProviderSpec, get_registry


def _spec(**kw) -> ProviderSpec:
    base = dict(
        name="testprov",
        kind="openai",
        label="Test",
        base_url="https://example.invalid/v1",
        api_key_env="TESTPROV_KEY",
        default_model="m",
        capabilities=frozenset({"tools", "streaming"}),
    )
    base.update(kw)
    return ProviderSpec(**base)  # type: ignore[arg-type]


class TestAvailability:
    def test_provider_without_key_is_unavailable_with_reason(self, monkeypatch):
        monkeypatch.delenv("TESTPROV_KEY", raising=False)
        reg = ProviderRegistry((_spec(),))
        entry = reg.describe()[0]
        assert entry["available"] is False
        assert "TESTPROV_KEY" in str(entry["unavailable_reason"])
        assert reg.available() == []

    def test_provider_with_key_is_available(self, monkeypatch):
        monkeypatch.setenv("TESTPROV_KEY", "secret-value-xyz")
        reg = ProviderRegistry((_spec(),))
        assert reg.describe()[0]["available"] is True
        assert len(reg.available()) == 1

    def test_provider_without_base_url_is_unavailable(self, monkeypatch):
        monkeypatch.setenv("TESTPROV_KEY", "k")
        reg = ProviderRegistry((_spec(base_url=""),))
        entry = reg.describe()[0]
        assert entry["available"] is False
        assert "base URL" in str(entry["unavailable_reason"])


class TestNoSecretLeakage:
    def test_describe_never_returns_a_key_value(self, monkeypatch):
        monkeypatch.setenv("TESTPROV_KEY", "super-secret-key-123")
        reg = ProviderRegistry((_spec(),))
        blob = repr(reg.describe()) + repr(reg.report())
        assert "super-secret-key-123" not in blob
        assert "TESTPROV_KEY" in blob  # the name is fine, the value is not

    def test_as_dict_exposes_only_the_env_var_name(self):
        d = _spec().as_dict()
        assert d["api_key_env"] == "TESTPROV_KEY"
        assert "secret" not in repr(d).lower()

    def test_model_env_override_does_not_leak_key(self, monkeypatch):
        monkeypatch.setenv("TESTPROV_KEY", "another-secret")
        monkeypatch.setenv("TESTPROV_MODEL", "custom-model")
        reg = ProviderRegistry((_spec(model_env="TESTPROV_MODEL"),))
        blob = repr(reg.describe())
        assert "another-secret" not in blob
        assert "custom-model" in blob


class TestSelection:
    def test_select_requires_declared_capabilities(self, monkeypatch):
        monkeypatch.setenv("TESTPROV_KEY", "k")
        reg = ProviderRegistry((_spec(),))
        assert reg.select({"tools"}).name == "testprov"
        with pytest.raises(LookupError):
            reg.select({"vision"})

    def test_select_honours_preference_order(self, monkeypatch):
        monkeypatch.setenv("A_KEY", "k")
        monkeypatch.setenv("B_KEY", "k")
        a = _spec(name="a", api_key_env="A_KEY")
        b = _spec(name="b", api_key_env="B_KEY")
        reg = ProviderRegistry((a, b))
        assert reg.select({"tools"}, prefer=["b", "a"]).name == "b"
        assert reg.select({"tools"}, prefer=["a"]).name == "a"

    def test_select_prefers_larger_context_then_managed(self, monkeypatch):
        monkeypatch.setenv("A_KEY", "k")
        monkeypatch.setenv("B_KEY", "k")
        small = _spec(name="small", api_key_env="A_KEY", context_limit=8_000)
        big = _spec(name="big", api_key_env="B_KEY", context_limit=200_000)
        reg = ProviderRegistry((small, big))
        assert reg.select({"tools"}).name == "big"

    def test_select_raises_when_nothing_is_available(self, monkeypatch):
        monkeypatch.delenv("TESTPROV_KEY", raising=False)
        reg = ProviderRegistry((_spec(),))
        with pytest.raises(LookupError):
            reg.select({"tools"})

    def test_unknown_provider_raises(self):
        with pytest.raises(KeyError):
            ProviderRegistry((_spec(),)).get("nope")


class TestBuiltinRegistry:
    def test_report_shape(self):
        report = get_registry().report()
        assert report["total_count"] >= 5
        assert "providers" in report
        assert "note" in report

    def test_managed_openhands_gateway_is_listed(self):
        names = {p["name"] for p in get_registry().describe()}
        assert {"openhands", "openai", "anthropic", "google", "local"} <= names

    def test_no_api_key_value_appears_in_report(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-secret-999")
        blob = repr(get_registry().report())
        assert "sk-openai-secret-999" not in blob
        assert "OPENAI_API_KEY" in blob

    def test_capability_metadata_is_not_a_ranking(self):
        report = get_registry().report()
        assert "no provider is ranked" in str(report["note"]).lower()
        for entry in report["providers"]:  # type: ignore[union-attr]
            assert "score" not in entry
            assert "quality" not in entry
