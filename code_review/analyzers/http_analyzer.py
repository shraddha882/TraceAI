"""Syntactic Requests timeout checks; submitted code is never executed.

Tracks direct imports and simple rebinding. Session objects, wrappers, dynamic
options and control-flow-dependent imports require deeper analysis.
"""
import ast


METHODS = {"get", "post", "put", "delete", "patch", "request", "head", "options"}


class HTTPTimeoutVisitor(ast.NodeVisitor):
    def __init__(self, analyzer):
        self.analyzer = analyzer
        # Retain support for existing snippets without an explicit import.
        self.bindings = {"requests": "requests"}

    def visit_Import(self, node):
        for alias in node.names:
            self.bindings[alias.asname or alias.name.split(".")[0]] = (
                "requests" if alias.name == "requests" else None
            )

    def visit_ImportFrom(self, node):
        for alias in node.names:
            self.bindings[alias.asname or alias.name] = (
                "requests." + alias.name
                if node.module == "requests" and node.level == 0 else None
            )

    def visit_FunctionDef(self, node):
        for expression in node.decorator_list + node.args.defaults + node.args.kw_defaults:
            if expression is not None:
                self.visit(expression)
        self.bindings[node.name] = None
        previous = self.bindings
        self.bindings = previous.copy()

        def collect_locals(current):
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.bindings[current.name] = None
                return
            if isinstance(current, ast.Lambda):
                return
            if isinstance(current, ast.Name) and isinstance(current.ctx, ast.Store):
                self.bindings[current.id] = None
            if isinstance(current, (ast.Import, ast.ImportFrom)):
                for alias in current.names:
                    self.bindings[alias.asname or alias.name.split(".")[0]] = None
            for child in ast.iter_child_nodes(current):
                collect_locals(child)

        for statement in node.body:
            collect_locals(statement)
        self.shadow_arguments(node.args)
        for statement in node.body:
            self.visit(statement)
        self.bindings = previous

    visit_AsyncFunctionDef = visit_FunctionDef

    def shadow_arguments(self, args):
        for argument in args.posonlyargs + args.args + args.kwonlyargs + [args.vararg, args.kwarg]:
            if argument is not None:
                self.bindings[argument.arg] = None

    def visit_Lambda(self, node):
        for expression in node.args.defaults + node.args.kw_defaults:
            if expression is not None:
                self.visit(expression)
        previous = self.bindings
        self.bindings = previous.copy()
        self.shadow_arguments(node.args)
        self.visit(node.body)
        self.bindings = previous

    def visit_ClassDef(self, node):
        self.bindings[node.name] = None
        previous = self.bindings
        self.bindings = previous.copy()
        self.generic_visit(node)
        self.bindings = previous

    def visit_Assign(self, node):
        self.visit(node.value)
        for target in node.targets:
            self.invalidate(target)

    def invalidate(self, target):
        for child in ast.walk(target):
            if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
                self.bindings[child.id] = None

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self.visit(node.value)
            self.invalidate(node.target)

    def visit_Call(self, node):
        resolved = None
        if isinstance(node.func, ast.Name):
            resolved = self.bindings.get(node.func.id)
        elif (isinstance(node.func, ast.Attribute)
              and isinstance(node.func.value, ast.Name)
              and self.bindings.get(node.func.value.id) == "requests"):
            resolved = "requests." + node.func.attr
        if resolved in {"requests." + method for method in METHODS}:
            timeout = next((kw.value for kw in node.keywords if kw.arg == "timeout"), None)
            disabled = isinstance(timeout, ast.Constant) and timeout.value is None
            unknown_options = any(kw.arg is None for kw in node.keywords)
            if disabled or (timeout is None and not unknown_options):
                self.analyzer.add_finding(
                    category="Reliability", severity="HIGH",
                    title="HTTP request has no timeout", line=node.lineno,
                    description=(
                        f"{resolved}() explicitly sets timeout=None, disabling the timeout."
                        if disabled else f"{resolved}() is called without an explicit timeout."
                    ),
                    impact="A slow external service can block application workers and reduce availability.",
                    suggested_fix=(
                        "Pass a finite timeout, such as timeout=5 or timeout=(3, 10) "
                        "for separate connect and read limits."
                    ),
                )
        self.generic_visit(node)


def analyze_http_timeouts(tree, analyzer):
    HTTPTimeoutVisitor(analyzer).visit(tree)
