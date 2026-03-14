from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from tree_sitter import Node, Parser
from tree_sitter_languages import get_parser

from ..ignore_rules import IgnoreRules
from ..models.evidence import EvidenceRef
from ..models.nodes import ClassDef, ModuleNode

from .sql_lineage import extract_tables_from_sql_string


# Python data-flow: (dataset_name or None if dynamic, "read"|"write", evidence)
PythonDataFlowItem = tuple[str | None, Literal["read", "write"], EvidenceRef]


Language = Literal["python", "sql", "yaml", "javascript", "typescript", "notebook", "unknown"]


def _ext_language(path: Path) -> Language:
    ext = path.suffix.lower()
    if ext == ".py":
        return "python"
    if ext in {".sql"}:
        return "sql"
    if ext in {".yml", ".yaml"}:
        return "yaml"
    if ext in {".js", ".jsx"}:
        return "javascript"
    if ext in {".ts", ".tsx"}:
        return "typescript"
    if ext in {".ipynb"}:
        return "notebook"
    return "unknown"


@dataclass(frozen=True)
class LanguageRouter:
    python: Parser
    sql: Parser
    yaml: Parser
    javascript: Parser
    typescript: Parser

    @classmethod
    def create(cls) -> "LanguageRouter":
        # tree-sitter-languages ships prebuilt grammars + parsers.
        return cls(
            python=get_parser("python"),
            sql=get_parser("sql"),
            yaml=get_parser("yaml"),
            javascript=get_parser("javascript"),
            typescript=get_parser("typescript"),
        )

    def parser_for(self, lang: Language) -> Parser | None:
        return {
            "python": self.python,
            "sql": self.sql,
            "yaml": self.yaml,
            "javascript": self.javascript,
            "typescript": self.typescript,
        }.get(lang)


def iter_source_files(repo_root: str) -> Iterable[Path]:
    root = Path(repo_root).resolve()
    ignore_rules = IgnoreRules.default()
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if ignore_rules.should_skip(rel):
            continue
        lang = _ext_language(p)
        if lang in {"python", "sql", "yaml", "javascript", "typescript", "notebook"}:
            yield p


def _node_evidence(path: str, node: Node) -> EvidenceRef:
    # tree-sitter is 0-based (row, column). Convert to 1-based line numbers.
    line_start = node.start_point[0] + 1
    line_end = node.end_point[0] + 1
    return EvidenceRef(path=path, line_start=line_start, line_end=line_end)


def _text(source: bytes, node: Node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def analyze_module(path: str, router: LanguageRouter) -> ModuleNode:
    p = Path(path)
    lang = _ext_language(p)

    module = ModuleNode(
        id=str(p),
        path=str(p),
        language=lang,
    )

    parser = router.parser_for(lang)
    if parser is None:
        # notebook/unknown: no parser
        if p.exists():
            try:
                module.loc = p.read_bytes().count(b"\n") + 1
            except Exception:
                pass
        return module

    source = p.read_bytes()
    tree = parser.parse(source)
    root = tree.root_node

    imports: list[str] = []
    public_functions: list[str] = []
    public_function_signatures: dict[str, str] = {}
    classes: list[ClassDef] = []

    # Complexity + comment ratio (best-effort for code-like languages)
    comment_nodes = 0
    decision_nodes = 1  # baseline of 1

    stack = [root]
    while stack:
        node = stack.pop()

        if node.type == "comment":
            comment_nodes += 1

        if node.type == "import_statement":
            imports.append(_text(source, node).strip())

        elif node.type == "import_from_statement":
            imports.append(_text(source, node).strip())

        elif node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            params_node = node.child_by_field_name("parameters")
            if name_node is not None:
                fn_name = _text(source, name_node)
                if not fn_name.startswith("_"):
                    public_functions.append(fn_name)
                    if params_node is not None:
                        public_function_signatures[fn_name] = f"{fn_name}{_text(source, params_node)}"

        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            bases_node = node.child_by_field_name("superclasses")
            if name_node is not None:
                cls_name = _text(source, name_node)
                bases: list[str] = []
                if bases_node is not None:
                    for child in bases_node.named_children:
                        bases.append(_text(source, child).strip())
                classes.append(
                    ClassDef(
                        name=cls_name,
                        bases=bases,
                        evidence=_node_evidence(str(p), node),
                    )
                )

        # JS/TS imports (ESM import statement)
        elif lang in {"javascript", "typescript"} and node.type == "import_statement":
            imports.append(_text(source, node).strip())

        # Basic cyclomatic complexity approximation (Python-focused)
        if lang == "python":
            if node.type in {
                "if_statement",
                "elif_clause",
                "for_statement",
                "while_statement",
                "except_clause",
                "conditional_expression",
                "with_statement",
                "assert_statement",
            }:
                decision_nodes += 1

        # DFS
        stack.extend(reversed(node.children))

    module.imports = imports
    module.public_functions = sorted(set(public_functions))
    module.public_function_signatures = public_function_signatures
    module.classes = classes
    module.loc = source.count(b"\n") + 1
    module.cyclomatic_complexity = decision_nodes if lang == "python" else None
    # comment ratio as fraction of comment nodes per LOC (node-based, best-effort)
    if module.loc and module.loc > 0:
        module.comment_ratio = min(1.0, comment_nodes / module.loc)
    return module


def analyze_modules_parallel(paths: list[str], max_workers: int = 8) -> list[ModuleNode]:
    """
    Parse modules in parallel with a bounded worker pool.

    Each worker creates its own LanguageRouter to avoid parser sharing across threads.
    """
    if not paths:
        return []
    bounded_workers = max(1, min(max_workers, 16))
    out: list[ModuleNode] = []

    def _task(path: str) -> ModuleNode:
        return analyze_module(path, LanguageRouter.create())

    with ThreadPoolExecutor(max_workers=bounded_workers) as ex:
        futures = {ex.submit(_task, p): p for p in paths}
        for fut in as_completed(futures):
            try:
                out.append(fut.result())
            except Exception:
                # Best-effort: skip unparseable files here; agent-level trace records coverage.
                continue
    return out


def _first_string_arg(source: bytes, call_node: Node) -> str | None:
    """Extract first string literal argument from a call (for path/table name). Returns None if dynamic."""
    # call has "arguments" field with ( expression (string), ... ) or ( identifier, ... )
    if call_node.type != "call":
        return None
    args_node = call_node.child_by_field_name("arguments")
    if not args_node or args_node.type != "argument_list":
        return None
    # First argument
    for child in args_node.named_children:
        if child.type == "string":
            raw = source[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
            if len(raw) >= 2 and raw[0] in '"\'' and raw[-1] == raw[0]:
                return raw[1:-1].strip()
            return raw.strip()
        if child.type == "concatenated_string":
            # f"foo" or "a" + "b" -> cannot resolve statically in general
            return None
        # name, call, etc. -> dynamic
        return None
    return None


def _extract_sql_from_execute_arg(source: bytes, call_node: Node) -> str | None:
    """
    Extract SQL string from execute() first argument.
    Handles: execute("SELECT ..."), execute(text("SELECT ...")).
    Returns None for dynamic refs (variables, f-strings, select() constructs).
    """
    if call_node.type != "call":
        return None
    args_node = call_node.child_by_field_name("arguments")
    if not args_node or args_node.type != "argument_list":
        return None
    children = list(args_node.named_children)
    if not children:
        return None
    first_arg = children[0]
    if first_arg.type == "string":
        raw = source[first_arg.start_byte : first_arg.end_byte].decode("utf-8", errors="replace")
        if len(raw) >= 2 and raw[0] in '"\'' and raw[-1] == raw[0]:
            return raw[1:-1].strip()
        return raw.strip()
    if first_arg.type == "concatenated_string":
        return None
    if first_arg.type == "call":
        # text("SELECT ...") or similar - get first arg of nested call
        func_node = first_arg.child_by_field_name("function")
        if func_node and _text(source, func_node) in ("text", "Text"):
            return _first_string_arg(source, first_arg)
        # select(...), etc. - cannot extract SQL statically
        return None
    return None


def extract_python_data_flow(path: str, source: bytes, router: LanguageRouter) -> list[PythonDataFlowItem]:
    """
    Find pandas/SQLAlchemy/PySpark read/write calls and extract dataset names where possible.

    Returns list of (dataset_name_or_None, "read"|"write", evidence). None = dynamic reference.
    """
    parser = router.parser_for("python")
    if not parser:
        return []
    tree = parser.parse(source)
    root = tree.root_node
    result: list[PythonDataFlowItem] = []

    DATA_READ_METHODS = ("read_csv", "read_parquet", "read_sql", "read_sql_table", "read_table", "parquet", "csv", "table", "format")
    DATA_WRITE_METHODS = ("to_csv", "to_parquet", "to_sql", "write_table", "save", "saveAsTable")
    SQLALCHEMY_EXECUTE_METHODS = ("execute", "execute_raw", "run_sync")

    def method_name_of_call(call_node: Node) -> str:
        func_node = call_node.child_by_field_name("function")
        if not func_node:
            return ""
        if func_node.type == "attribute":
            attr = func_node.child_by_field_name("attribute")
            return _text(source, attr) if attr else ""
        if func_node.type == "identifier":
            return _text(source, func_node)
        return ""

    def visit(node: Node) -> None:
        if node.type == "call":
            method_name = method_name_of_call(node)
            call_text = _text(source, node).strip()
            first_arg_str = _first_string_arg(source, node)
            evidence = _node_evidence(path, node)
            if method_name in DATA_READ_METHODS:
                result.append((first_arg_str, "read", evidence))
            elif ".read." in call_text and method_name in ("parquet", "csv", "table", "format"):
                result.append((first_arg_str, "read", evidence))
            elif method_name in DATA_WRITE_METHODS:
                result.append((first_arg_str, "write", evidence))
            elif ".write." in call_text and ("save" in call_text or "parquet" in call_text or "format" in call_text):
                result.append((first_arg_str, "write", evidence))
            elif method_name in SQLALCHEMY_EXECUTE_METHODS:
                sql_str = _extract_sql_from_execute_arg(source, node)
                if sql_str:
                    source_tables, target_table = extract_tables_from_sql_string(sql_str)
                    for tbl in source_tables:
                        result.append((tbl, "read", evidence))
                    if target_table:
                        result.append((target_table, "write", evidence))
                else:
                    result.append((None, "read", evidence))
        for child in node.children:
            visit(child)

    visit(root)
    return result
