"""Regression tests for VHAS execution and deployment safety locks.

These tests inspect source structure without invoking execution methods.
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_method(filename, method_name):
    """Parse a production method without importing or executing it."""
    path = ROOT / filename

    tree = ast.parse(
        path.read_text(encoding="utf-8"),
        filename=str(path),
    )

    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == method_name
    ]

    assert len(matches) == 1, (
        f"Expected exactly one method named {method_name}"
    )

    return matches[0]


def is_false_return(node):
    return (
        isinstance(node, ast.Return)
        and isinstance(node.value, ast.Constant)
        and node.value.value is False
    )


def test_pipeline_validation_has_unconditional_deny_lock():
    """Validation must stop before reaching disabled execution code."""
    method = load_method(
        "vhas_self_correction.py",
        "run_pipeline_validation",
    )

    top_level_returns = [
        index
        for index, node in enumerate(method.body)
        if is_false_return(node)
    ]

    assert len(top_level_returns) == 1, (
        "Expected exactly one top-level deny return"
    )

    lock_index = top_level_returns[0]

    assert lock_index < len(method.body) - 1, (
        "Expected disabled execution code after the deny lock"
    )

    # The statements before the lock must not contain executable
    # subprocess calls, which could bypass the intended boundary.
    before_lock = method.body[:lock_index]

    for statement in before_lock:
        for node in ast.walk(statement):
            if not isinstance(node, ast.Call):
                continue

            if isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {
                    "run",
                    "Popen",
                    "call",
                    "check_call",
                    "check_output",
                }, "Potential subprocess call before validation lock"


def test_deployment_governor_remains_deny_only():
    """The deployment method must not perform Git actions."""
    method = load_method(
        "vhas_git_governor.py",
        "safe_deploy_patch",
    )

    statements = [
        node
        for node in method.body
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
    ]

    assert len(statements) == 2, (
        "Deployment method contains unexpected statements"
    )

    assert isinstance(statements[0], ast.Assign), (
        "Expected deployment denial report assignment"
    )

    assert isinstance(statements[1], ast.Return), (
        "Expected immediate deployment denial"
    )

    assert is_false_return(statements[1]), (
        "Deployment must unconditionally return False"
    )

    for statement in statements:
        assert not any(
            isinstance(node, ast.Call)
            for node in ast.walk(statement)
        ), "Deployment method must not call external operations"


def test_validation_lock_precedes_cargo_execution():
    """The disabled Cargo execution block must remain unreachable."""
    method = load_method(
        "vhas_self_correction.py",
        "run_pipeline_validation",
    )

    lock_index = next(
        index
        for index, node in enumerate(method.body)
        if is_false_return(node)
    )

    later_statements = method.body[lock_index + 1:]

    assert later_statements, (
        "Expected disabled validation implementation after lock"
    )

    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
        for statement in later_statements
        for node in ast.walk(statement)
    ), "Expected disabled subprocess execution after lock"
