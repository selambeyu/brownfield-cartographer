"""
Airflow DAG parser: extract pipeline topology from Airflow DAG Python files.

Parses Python files for DAG(...), *Operator(...) task definitions, and task
dependencies (>>, set_downstream, set_upstream). Extracts DAG IDs, task IDs,
and the execution dependency graph.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from ..models.evidence import EvidenceRef


# Operator classes that define tasks (task_id is first or second arg typically)
AIRFLOW_OPERATORS = (
    "PythonOperator",
    "BashOperator",
    "SqlOperator",
    "BigQueryOperator",
    "SnowflakeOperator",
    "PostgresOperator",
    "MySqlOperator",
    "MssqlOperator",
    "OracleOperator",
    "DbtRunOperator",
    "DbtTestOperator",
    "KubernetesPodOperator",
    "DockerOperator",
    "SimpleHttpOperator",
    "EmailOperator",
    "S3ToRedshiftOperator",
    "S3ToGcsOperator",
    "GenericOperator",
    "EmptyOperator",
    "ShortCircuitOperator",
    "BranchPythonOperator",
    "BranchOperator",
    "ExternalTaskSensor",
    "HttpSensor",
    "SqlSensor",
    "Operator",
)


@dataclass
class AirflowDAGResult:
    """Result of parsing one Airflow DAG file."""

    path: str
    evidence: EvidenceRef
    dag_id: str | None = None
    tasks: list[dict] = field(default_factory=list)  # [{task_id, operator, line}, ...]
    dependencies: list[tuple[str, str]] = field(default_factory=list)  # (upstream, downstream)
    parse_error: str | None = None


def _get_constant_str(node: ast.expr) -> str | None:
    """Extract string from ast.Constant or ast.Str (Python 3.7 compat)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if hasattr(ast, "Str") and isinstance(node, ast.Str):
        return node.s
    return None


def _get_keyword_arg(call: ast.Call, name: str) -> str | None:
    """Get string value of a keyword argument."""
    for kw in call.keywords:
        if kw.arg == name:
            return _get_constant_str(kw.value)
    return None


def _get_positional_arg(call: ast.Call, index: int) -> str | None:
    """Get string value of positional argument at index."""
    if index < len(call.args):
        return _get_constant_str(call.args[index])
    return None


def _collect_names(node: ast.expr) -> list[str]:
    """Collect all variable/attribute names from an expression."""
    names: list[str] = []

    def visit(n: ast.AST) -> None:
        if isinstance(n, ast.Name):
            names.append(n.id)
        elif isinstance(n, ast.Attribute):
            visit(n.value)
            names.append(n.attr)
        elif isinstance(n, ast.Tuple) or isinstance(n, ast.List):
            for elt in n.elts:
                visit(elt)
        elif isinstance(n, ast.BinOp) and isinstance(n.op, ast.RShift):
            visit(n.left)
            visit(n.right)

    visit(node)
    return names


def _rightmost_names(node: ast.expr) -> list[str]:
    """For a>>b>>c, the left of outer >> is (a>>b) which 'returns' b. Get rightmost."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, (ast.Tuple, ast.List)):
        out: list[str] = []
        for elt in node.elts:
            out.extend(_rightmost_names(elt))
        return out
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.RShift):
        return _rightmost_names(node.right)
    return []


def _resolve_to_task_ids(
    names: list[str],
    var_to_task: dict[str, str],
) -> list[str]:
    """Map variable names to task_ids. Unresolved names use the name as fallback."""
    out: list[str] = []
    for n in names:
        out.append(var_to_task.get(n, n))
    return out


def extract_airflow_dag(path: str | Path, source: str) -> AirflowDAGResult:
    """
    Extract DAG topology from an Airflow DAG Python file.

    Finds: DAG(dag_id=...), *Operator(task_id=...), task_a >> task_b,
    set_downstream, set_upstream.

    Args:
        path: File path for evidence.
        source: Python source code.

    Returns:
        AirflowDAGResult with dag_id, tasks, dependencies.
    """
    p = Path(path)
    evidence = EvidenceRef(path=str(path), line_start=1, line_end=source.count("\n") + 1)

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return AirflowDAGResult(path=str(path), evidence=evidence, parse_error=str(e))

    dag_id: str | None = None
    var_to_task: dict[str, str] = {}
    tasks: list[dict] = []
    deps: list[tuple[str, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for item in node.items:
                if isinstance(item.context_expr, ast.Call):
                    call = item.context_expr
                    func_name = ""
                    if isinstance(call.func, ast.Name):
                        func_name = call.func.id
                    elif isinstance(call.func, ast.Attribute):
                        func_name = call.func.attr
                    if func_name == "DAG":
                        tid = _get_keyword_arg(call, "dag_id") or _get_positional_arg(call, 0)
                        if tid:
                            dag_id = tid
                        break
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    var_name = target.id
                    if isinstance(node.value, ast.Call):
                        call = node.value
                        func_name = ""
                        if isinstance(call.func, ast.Name):
                            func_name = call.func.id
                        elif isinstance(call.func, ast.Attribute):
                            func_name = call.func.attr

                        if func_name == "DAG":
                            tid = _get_keyword_arg(call, "dag_id") or _get_positional_arg(call, 0)
                            if tid:
                                dag_id = tid
                        elif func_name in AIRFLOW_OPERATORS or (
                            "Operator" in func_name and not func_name.startswith("_")
                        ):
                            tid = _get_keyword_arg(call, "task_id") or _get_positional_arg(call, 0)
                            if tid:
                                var_to_task[var_name] = tid
                                tasks.append({
                                    "task_id": tid,
                                    "operator": func_name,
                                    "line": node.lineno,
                                    "var_name": var_name,
                                })

        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.RShift):
            # task_a >> task_b or task_a >> [task_b, task_c]; chain: a >> b >> c
            left = node.left
            right = node.right
            left_names = _rightmost_names(left)
            right_names = _collect_names(right)
            if left_names and right_names:
                left_ids = _resolve_to_task_ids(left_names, var_to_task)
                right_ids = _resolve_to_task_ids(right_names, var_to_task)
                for u in left_ids:
                    for d in right_ids:
                        deps.append((u, d))

        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Attribute):
                method = call.func.attr
                if method == "set_downstream" and call.args:
                    # task.set_downstream(other) or task.set_downstream([a, b])
                    obj_names = _collect_names(call.func.value)
                    arg_names = _collect_names(call.args[0])
                    if obj_names and arg_names:
                        upstream = _resolve_to_task_ids(obj_names, var_to_task)
                        downstream = _resolve_to_task_ids(arg_names, var_to_task)
                        for u in upstream:
                            for d in downstream:
                                deps.append((u, d))
                elif method == "set_upstream" and call.args:
                    # task.set_upstream(other)
                    obj_names = _collect_names(call.func.value)
                    arg_names = _collect_names(call.args[0])
                    if obj_names and arg_names:
                        downstream = _resolve_to_task_ids(obj_names, var_to_task)
                        upstream = _resolve_to_task_ids(arg_names, var_to_task)
                        for u in upstream:
                            for d in downstream:
                                deps.append((u, d))

    if not dag_id and tasks:
        dag_id = p.stem

    return AirflowDAGResult(
        path=str(path),
        evidence=evidence,
        dag_id=dag_id,
        tasks=tasks,
        dependencies=deps,
    )


def extract_airflow_dag_from_file(file_path: str | Path) -> AirflowDAGResult:
    """Read file from disk and extract Airflow DAG topology."""
    path = Path(file_path)
    if not path.exists():
        return AirflowDAGResult(
            path=str(path),
            evidence=EvidenceRef(path=str(path)),
            parse_error="File not found",
        )
    source = path.read_text(encoding="utf-8", errors="replace")
    return extract_airflow_dag(path, source)


def is_likely_airflow_dag(path: Path) -> bool:
    """Heuristic: file in dags/ or contains 'airflow' and 'DAG'."""
    path_str = str(path).lower()
    if "dags" in path_str or path.name == "dag.py":
        return True
    return False
