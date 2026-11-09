"""Tests for the shared sandboxed Python runner.

The runner is the single execution path behind both the problem-solving and
innovation pipelines, so it is tested directly: real subprocesses, real exit
codes, real timeouts and real artifact capture.
"""

from __future__ import annotations

import json

from level5.execution import parse_json_block, run_python_script


class TestParseJsonBlock:
    def test_extracts_embedded_object(self):
        assert parse_json_block('noise {"a": 1} trailing') == {"a": 1}

    def test_returns_none_without_object(self):
        assert parse_json_block("no json here") is None

    def test_returns_none_for_malformed_json(self):
        assert parse_json_block("{not valid}") is None

    def test_returns_none_for_json_array(self):
        assert parse_json_block("[1, 2, 3]") is None


class TestRunPythonScript:
    async def test_runs_real_script_and_parses_output(self, tmp_path):
        script = "import json\nprint(json.dumps({'value': 6 * 7}))\n"
        result = await run_python_script(script, tmp_path, timeout=30)
        assert result.succeeded
        assert result.parsed == {"value": 42}
        assert result.exit_code == 0
        assert (tmp_path / "models" / "model.py").exists()

    async def test_captures_real_stderr_on_failure(self, tmp_path):
        result = await run_python_script("raise RuntimeError('kaboom')\n", tmp_path, timeout=30)
        assert result.succeeded is False
        assert result.exit_code != 0
        assert "kaboom" in result.stderr

    async def test_timeout_is_enforced(self, tmp_path):
        result = await run_python_script(
            "import time\ntime.sleep(30)\n", tmp_path, timeout=1.5
        )
        assert result.timed_out is True
        assert result.succeeded is False

    async def test_reports_files_created_by_the_run(self, tmp_path):
        script = (
            "from pathlib import Path\n"
            "Path('output.txt').write_text('hi')\n"
            "print('{}')\n"
        )
        result = await run_python_script(script, tmp_path, timeout=30)
        assert "output.txt" in result.files

    async def test_custom_subdir_and_filename(self, tmp_path):
        result = await run_python_script(
            "print('{}')\n", tmp_path, timeout=30, subdir="prototype", filename="prototype.py"
        )
        assert (tmp_path / "prototype" / "prototype.py").exists()
        assert result.succeeded

    async def test_environment_is_minimal(self, tmp_path):
        script = (
            "import json, os\n"
            "print(json.dumps({'has_secret': 'SECRET' in os.environ}))\n"
        )
        result = await run_python_script(script, tmp_path, timeout=30)
        assert result.parsed == {"has_secret": False}

    async def test_duration_is_recorded(self, tmp_path):
        result = await run_python_script("print('{}')\n", tmp_path, timeout=30)
        assert result.duration_s >= 0.0
