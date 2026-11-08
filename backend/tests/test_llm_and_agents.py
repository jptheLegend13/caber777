"""Unit tests for the LLM client helpers and the agent registry."""

from __future__ import annotations

from level5.agents.registry import (
    all_roles,
    get_role,
    register_dynamic,
    roles_by_discipline,
    select_roles_for_domain,
)
from level5.llm.client import parse_json_loose


class TestParseJsonLoose:
    def test_plain_object(self):
        assert parse_json_loose('{"a": 1}') == {"a": 1}

    def test_fenced_object(self):
        assert parse_json_loose('```json\n{"a": 2}\n```') == {"a": 2}

    def test_object_with_prose(self):
        text = 'Here is the result:\n{"a": 3, "b": [1,2]}\nHope that helps!'
        assert parse_json_loose(text) == {"a": 3, "b": [1, 2]}

    def test_nested_object(self):
        text = '{"outer": {"inner": {"deep": true}}}'
        assert parse_json_loose(text)["outer"]["inner"]["deep"] is True

    def test_invalid_returns_none(self):
        assert parse_json_loose("not json at all") is None

    def test_empty_returns_none(self):
        assert parse_json_loose("") is None


class TestAgentRegistry:
    def test_registry_has_all_required_disciplines(self):
        grouped = roles_by_discipline()
        for discipline in ("leadership", "research", "software", "ai", "graphics", "quality"):
            assert discipline in grouped, f"missing discipline {discipline}"

    def test_registry_covers_required_roles(self):
        names = {r.name for r in all_roles()}
        required = {
            "chief_research_director",
            "chief_engineering_architect",
            "product_architect",
            "ui_ux_engineer",
            "frontend_engineer",
            "backend_engineer",
            "database_engineer",
            "api_engineer",
            "fullstack_engineer",
            "mobile_engineer",
            "desktop_engineer",
            "cloud_engineer",
            "devops_engineer",
            "ai_research_engineer",
            "agent_systems_engineer",
            "machine_learning_engineer",
            "data_engineer",
            "three_d_systems_engineer",
            "procedural_geometry_engineer",
            "rendering_engineer",
            "simulation_engineer",
            "building_intelligence_engineer",
            "testing_engineer",
            "security_engineer",
            "performance_engineer",
            "debugging_engineer",
            "code_reviewer",
        }
        assert required <= names, f"missing roles: {required - names}"

    def test_unknown_role_falls_back(self):
        role = get_role("does_not_exist")
        assert role.name == "fullstack_engineer"

    def test_dynamic_registration(self):
        role = register_dynamic(
            name="test_dynamic_role",
            title="Test Role",
            discipline="research",
            objective="Test dynamic creation",
        )
        assert role.dynamic is True
        assert get_role("test_dynamic_role").title == "Test Role"

    def test_domain_role_selection(self):
        assert "building_intelligence_engineer" in select_roles_for_domain("architecture_3d")
        assert "mobile_engineer" in select_roles_for_domain("mobile_app")
        assert select_roles_for_domain("unknown_domain")
