"""
Integration tests for policy loading from YAML files.

Tests the full path: loader.py → YAML parsing → policy instantiation.
"""
import logging
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from aiwarden.policies.loader import load_policies, _build, _find_config, _read_config


class TestYAMLLoading:
    """Test loading policies from YAML files."""

    def test_valid_yaml_all_types(self, tmp_path):
        """Valid YAML with all policy types loads correctly."""
        config = {"policies": [
            {"name": "pii", "type": "pii", "enabled": True},
            {"name": "budget", "type": "budget", "enabled": True, "limit": 100.0},
            {"name": "tools", "type": "tools", "enabled": True,
             "builtin": {"filesystem-safety": True}},
            {"name": "control", "type": "agent_control", "enabled": True, "max_turns": 25},
            {"name": "custom", "type": "custom", "enabled": True, "rules": [
                {"name": "r1", "hook": "pre", "action": "warn",
                 "match": {"model": {"contains": "test"}}}
            ]},
        ]}
        yaml_file = tmp_path / "policies.yaml"
        yaml_file.write_text(yaml.dump(config))

        with patch.dict("os.environ", {"AIWARDEN_POLICY_FILE": str(yaml_file)}):
            policies = load_policies()

        assert len(policies) == 5
        names = [p.name for p in policies]
        assert "pii-protection" in names
        assert "budget-control" in names
        assert "tool-safety" in names
        assert "agent-control" in names
        assert "custom" in names

    def test_missing_yaml_returns_defaults(self):
        """Missing YAML file returns default policies (no crash)."""
        with patch.dict("os.environ", {"AIWARDEN_POLICY_FILE": "/nonexistent/path.yaml"}):
            policies = load_policies()
        assert len(policies) >= 1  # defaults: PII + tool-safety

    def test_malformed_yaml_graceful_fallback(self, tmp_path):
        """Malformed YAML logs warning, falls back to defaults."""
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("{{{{not valid yaml:::::")

        with patch.dict("os.environ", {"AIWARDEN_POLICY_FILE": str(yaml_file)}):
            policies = load_policies()
        assert len(policies) >= 1  # falls back to defaults

    def test_invalid_policy_type_skipped(self, tmp_path):
        """Invalid policy type is skipped with warning."""
        config = {"policies": [
            {"name": "good", "type": "pii", "enabled": True},
            {"name": "bad", "type": "nonexistent_type", "enabled": True},
        ]}
        yaml_file = tmp_path / "policies.yaml"
        yaml_file.write_text(yaml.dump(config))

        with patch.dict("os.environ", {"AIWARDEN_POLICY_FILE": str(yaml_file)}):
            policies = load_policies()
        assert len(policies) == 1
        assert policies[0].name == "pii-protection"

    def test_invalid_regex_in_pii_skipped(self, tmp_path):
        """Invalid regex in PII patterns is skipped with warning."""
        config = {"policies": [
            {"name": "pii", "type": "pii", "enabled": True,
             "patterns": {"bad": "[invalid", "good": r"\d+"}},
        ]}
        yaml_file = tmp_path / "policies.yaml"
        yaml_file.write_text(yaml.dump(config))

        with patch.dict("os.environ", {"AIWARDEN_POLICY_FILE": str(yaml_file)}):
            policies = load_policies()
        assert len(policies) == 1
        # Bad pattern skipped, good pattern + builtins still work
        pii = policies[0]
        assert "good" in pii._patterns
        assert "bad" not in pii._patterns

    def test_priority_ordering_after_engine_load(self, tmp_path):
        """PolicyEngine sorts policies by priority after loading."""
        from aiwarden.policies.engine import PolicyEngine

        config = {"policies": [
            {"name": "high-pri", "type": "pii", "enabled": True, "priority": 99},
            {"name": "low-pri", "type": "budget", "enabled": True, "priority": 5, "limit": 100},
        ]}
        yaml_file = tmp_path / "policies.yaml"
        yaml_file.write_text(yaml.dump(config))

        with patch.dict("os.environ", {"AIWARDEN_POLICY_FILE": str(yaml_file)}):
            engine = PolicyEngine()
            engine._policies = None
            policies = engine._get_policies()
        priorities = [p.priority for p in policies]
        assert priorities == sorted(priorities)

    def test_enabled_false_excluded(self, tmp_path):
        """Policy with enabled: false is excluded."""
        config = {"policies": [
            {"name": "active", "type": "pii", "enabled": True},
            {"name": "disabled", "type": "budget", "enabled": False, "limit": 100},
        ]}
        yaml_file = tmp_path / "policies.yaml"
        yaml_file.write_text(yaml.dump(config))

        with patch.dict("os.environ", {"AIWARDEN_POLICY_FILE": str(yaml_file)}):
            policies = load_policies()
        assert len(policies) == 1
        assert policies[0].name == "pii-protection"


class TestConfigDiscovery:
    """Test YAML config file discovery."""

    def test_env_var_takes_precedence(self, tmp_path):
        """AIWARDEN_POLICY_FILE env var takes precedence."""
        yaml_file = tmp_path / "custom.yaml"
        yaml_file.write_text(yaml.dump({"policies": []}))

        with patch.dict("os.environ", {"AIWARDEN_POLICY_FILE": str(yaml_file)}):
            path = _find_config()
        assert path == yaml_file

    def test_project_level_found(self, tmp_path, monkeypatch):
        """Project-level .aiwarden/policies.yaml found."""
        monkeypatch.chdir(tmp_path)
        project_dir = tmp_path / ".aiwarden"
        project_dir.mkdir()
        yaml_file = project_dir / "policies.yaml"
        yaml_file.write_text(yaml.dump({"policies": []}))

        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("AIWARDEN_POLICY_FILE", None)
            path = _find_config()
        assert path is not None
        assert path.resolve() == yaml_file.resolve()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
