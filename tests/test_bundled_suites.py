from pathlib import Path

from sla_app.core.yaml_loader import load_suite


def test_bundled_suites_are_valid() -> None:
    suite_paths = sorted(Path("suites").glob("*.yaml"))

    assert suite_paths
    for suite_path in suite_paths:
        suite = load_suite(suite_path)
        assert suite.name
        assert suite.scenarios
