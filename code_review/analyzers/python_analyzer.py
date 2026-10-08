import ast
import re
from .http_analyzer import analyze_http_timeouts


class PythonAnalyzer(ast.NodeVisitor):

    def __init__(self):
        self.findings = []

    def add_finding(
        self,
        category,
        severity,
        title,
        line,
        description,
        impact,
        suggested_fix,
    ):
        self.findings.append({
            "category": category,
            "severity": severity,
            "title": title,
            "line": line,
            "description": description,
            "impact": impact,
            "suggested_fix": suggested_fix,
        })

    # --------------------------------------------------
    # ERROR HANDLING
    # --------------------------------------------------

    def visit_ExceptHandler(self, node):

        # except:
        if node.type is None:
            self.add_finding(
                category="Error Handling",
                severity="MEDIUM",
                title="Bare except detected",
                line=node.lineno,
                description=(
                    "The exception handler catches every exception "
                    "without specifying an exception type."
                ),
                impact=(
                    "Unexpected errors may be hidden and production "
                    "failures can become difficult to diagnose."
                ),
                suggested_fix=(
                    "Catch specific exceptions such as ValueError, "
                    "requests.RequestException or database exceptions."
                ),
            )

        # except:
        #     pass
        if (
            len(node.body) == 1
            and isinstance(node.body[0], ast.Pass)
        ):
            self.add_finding(
                category="Error Handling",
                severity="HIGH",
                title="Exception silently ignored",
                line=node.lineno,
                description=(
                    "An exception is caught and ignored using pass."
                ),
                impact=(
                    "The application may fail silently without "
                    "producing useful logs for investigation."
                ),
                suggested_fix=(
                    "Log or explicitly handle the exception instead "
                    "of silently ignoring it."
                ),
            )

        self.generic_visit(node)

    # --------------------------------------------------
    # FUNCTION CALL ANALYSIS
    # --------------------------------------------------

    def visit_Call(self, node):

        # requests.get(), requests.post(), etc.
        # HTTP calls are checked in a separate pass with import tracking.

        # eval() / exec()
        self.detect_dangerous_execution(node)

        # subprocess(..., shell=True)
        self.detect_unsafe_subprocess(node)

        self.generic_visit(node)

    # --------------------------------------------------
    # EVAL / EXEC
    # --------------------------------------------------

    def detect_dangerous_execution(self, node):

        if not isinstance(node.func, ast.Name):
            return

        if node.func.id not in {"eval", "exec"}:
            return

        self.add_finding(
            category="Security",
            severity="CRITICAL",
            title=f"Dangerous {node.func.id}() usage",
            line=node.lineno,
            description=(
                f"{node.func.id}() dynamically executes Python "
                "code at runtime."
            ),
            impact=(
                "If attacker-controlled input reaches this function, "
                "arbitrary code may execute on the server."
            ),
            suggested_fix=(
                f"Avoid {node.func.id}(). Parse and validate the "
                "expected input explicitly instead."
            ),
        )

    # --------------------------------------------------
    # SUBPROCESS
    # --------------------------------------------------

    def detect_unsafe_subprocess(self, node):

        if not isinstance(node.func, ast.Attribute):
            return

        if not isinstance(node.func.value, ast.Name):
            return

        if node.func.value.id != "subprocess":
            return

        methods = {
            "run",
            "Popen",
            "call",
            "check_call",
            "check_output",
        }

        if node.func.attr not in methods:
            return

        for keyword in node.keywords:

            if (
                keyword.arg == "shell"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
            ):
                self.add_finding(
                    category="Security",
                    severity="HIGH",
                    title="Subprocess executed with shell=True",
                    line=node.lineno,
                    description=(
                        "A subprocess command is executed through "
                        "the system shell."
                    ),
                    impact=(
                        "If untrusted data becomes part of the command, "
                        "this can introduce command injection."
                    ),
                    suggested_fix=(
                        "Avoid shell=True and pass command arguments "
                        "as a list whenever possible."
                    ),
                )

    # --------------------------------------------------
    # ASSIGNMENTS
    # --------------------------------------------------

    def visit_Assign(self, node):

        for target in node.targets:
            self.detect_secret_target(target, node.value)

        self.generic_visit(node)

    # --------------------------------------------------
    # HARDCODED SECRETS
    # --------------------------------------------------

    def visit_AnnAssign(self, node):
        self.detect_secret_target(node.target, node.value)
        self.generic_visit(node)

    def visit_Dict(self, node):
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                self.detect_hardcoded_secret(key.value, value)
        self.generic_visit(node)

    def visit_keyword(self, node):
        if node.arg is not None:
            self.detect_hardcoded_secret(node.arg, node.value)
        self.generic_visit(node)

    def detect_secret_target(self, target, value):
        if isinstance(target, ast.Name):
            self.detect_hardcoded_secret(target.id, value)
        elif isinstance(target, ast.Attribute):
            self.detect_hardcoded_secret(target.attr, value)
        elif (isinstance(target, ast.Subscript)
              and isinstance(target.slice, ast.Constant)
              and isinstance(target.slice.value, str)):
            self.detect_hardcoded_secret(target.slice.value, value)

    def detect_hardcoded_secret(self, name, value):
        """Inspect literal values only; never include a credential in a finding."""
        if not (isinstance(value, ast.Constant)
                and isinstance(value.value, str) and value.value.strip()):
            return
        # Split camelCase/acronyms, then match complete suffixes rather than
        # substrings: DB_PASSWORD qualifies, password_hint does not.
        normalized = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
        normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", normalized)
        normalized = normalized.lower().strip("_")
        sensitive_names = {
            "password", "passwd", "pwd", "secret", "secret_key",
            "api_key", "apikey", "access_token", "auth_token",
            "client_secret", "private_key", "refresh_token",
        }
        if any(normalized == suffix or normalized.endswith("_" + suffix)
               for suffix in sensitive_names):
            self.add_finding(
                category="Security",
                severity="CRITICAL",
                title="Potential hard-coded secret",
                line=value.lineno,
                description=(
                    "A credential-like name is assigned a nonempty literal "
                    "string. This may be a hard-coded secret; verify whether "
                    "it is an actual credential or example data."
                ),
                impact=(
                    "Secrets committed to source control may be "
                    "exposed to unauthorized users or leaked "
                    "through repository history."
                ),
                suggested_fix=(
                    "Store secrets in environment variables or a "
                    "dedicated secrets-management service."
                ),
            )

class DatabaseConnectionVisitor(ast.NodeVisitor):
    """Match simple assignments and later closes within one lexical scope.

    This is syntactic evidence, not control-flow or ownership analysis. Aliases,
    returned connections, context managers and conditional cleanup are not
    resolved here. Each acquisition is retained even if its name is overwritten.
    """

    def __init__(self, analyzer):
        self.analyzer = analyzer
        self.active = {}
        self.connections = []

    def visit_scope(self, node):
        previous = self.active
        self.active = {}
        for statement in node.body:
            self.visit(statement)
        self.active = previous

    visit_FunctionDef = visit_scope
    visit_AsyncFunctionDef = visit_scope
    visit_ClassDef = visit_scope

    def visit_Lambda(self, node):
        # A deferred lambda body is not evidence of cleanup in its parent.
        pass

    def track_assignment(self, targets, value):
        if value is not None:
            self.visit(value)
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            self.active.pop(target.id, None)
            if (isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and value.func.attr == "connect"):
                connection = {"variable": target.id, "line": value.lineno, "closed": False}
                self.connections.append(connection)
                self.active[target.id] = connection

    def visit_Assign(self, node):
        self.track_assignment(node.targets, node.value)

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self.track_assignment([node.target], node.value)

    def visit_Call(self, node):
        self.generic_visit(node)
        if (isinstance(node.func, ast.Attribute)
                and node.func.attr == "close"
                and isinstance(node.func.value, ast.Name)
                and not node.args and not node.keywords):
            connection = self.active.get(node.func.value.id)
            if connection is not None:
                connection["closed"] = True


def detect_unclosed_db_connections(tree, analyzer):
    visitor = DatabaseConnectionVisitor(analyzer)
    visitor.visit(tree)
    for connection in visitor.connections:
        if not connection["closed"]:
            variable = connection["variable"]
            analyzer.add_finding(
                category="Database",
                severity="HIGH",
                title="Database connection may not be closed",
                line=connection["line"],
                description=(
                    f"The database connection '{variable}' is "
                    "created but no later close() call for that binding "
                    "was detected in the same scope. This is a possible "
                    "leak; aliases and ownership transfers are not resolved."
                ),
                impact=(
                    "Repeated requests may leave connections open, "
                    "eventually exhausting the database connection "
                    "pool."
                ),
                suggested_fix=(
                    "Use a context manager where supported, or close "
                    "the connection reliably in a finally block."
                ),
            )


# --------------------------------------------------
# SQL INJECTION
# --------------------------------------------------

def sql_string_parts(node):
    """Return literal SQL fragments and whether an expression interpolates data.

    Never evaluate submitted code. This rule inspects expressions only; it does
    not trace variables or prove that a query reaches a database.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, False
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else "?"
            for part in node.values
        ), any(isinstance(part, ast.FormattedValue) for part in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, left_dynamic = sql_string_parts(node.left)
        right, right_dynamic = sql_string_parts(node.right)
        return left + right, left_dynamic or right_dynamic
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        literal, _ = sql_string_parts(node.left)
        return literal, True
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "format"):
        literal, dynamic = sql_string_parts(node.func.value)
        return literal, dynamic or bool(node.args or node.keywords)
    return "?", True


class SQLInjectionVisitor(ast.NodeVisitor):
    # Match SQL structure, not words such as "updated" in ordinary messages.
    sql_pattern = re.compile(
        r"\b(?:SELECT\b[\s\S]*?\bFROM|INSERT\s+INTO|"
        r"UPDATE\b[\s\S]*?\bSET|DELETE\s+FROM)\b",
        re.IGNORECASE,
    )

    def __init__(self):
        self.findings = []

    def visit(self, node):
        candidate = (
            isinstance(node, ast.JoinedStr)
            or (isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)))
            or (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "format")
        )
        if candidate:
            literal, dynamic = sql_string_parts(node)
            if dynamic and self.sql_pattern.search(literal):
                self.findings.append({
                    "category": "Security",
                    "severity": "CRITICAL",
                    "title": "Potential SQL injection",
                    "line": node.lineno,
                    "description": (
                        "SQL appears to be constructed using string interpolation "
                        "or concatenation. This rule does not establish whether "
                        "the values are untrusted or the query is executed."
                    ),
                    "impact": (
                        "If untrusted input reaches this query, it may alter the "
                        "intended SQL and expose or modify database data."
                    ),
                    "suggested_fix": (
                        "Use your database driver's parameter placeholders and "
                        "pass values separately to execute(query, parameters). "
                        "Do not format or concatenate values into SQL."
                    ),
                })
                # Report the complete expression once, not each nested fragment.
                return
        super().visit(node)


def detect_sql_injection(tree):
    analyzer = SQLInjectionVisitor()
    analyzer.visit(tree)
    return analyzer.findings


# --------------------------------------------------
# MAIN ANALYZER
# --------------------------------------------------

def analyze_python_code(code):

    try:
        tree = ast.parse(code)

    except SyntaxError as error:

        return {
            "success": False,
            "summary": (
                "The supplied Python code contains a syntax error."
            ),
            "findings": [],
            "syntax_error": {
                "line": error.lineno,
                "message": error.msg,
            },
        }

    analyzer = PythonAnalyzer()

    analyzer.visit(tree)
    analyze_http_timeouts(tree, analyzer)

    detect_unclosed_db_connections(
        tree,
        analyzer,
    )

    analyzer.findings.extend(
        detect_sql_injection(tree)
    )

    severity_order = {
        "CRITICAL": 0,
        "HIGH": 1,
        "MEDIUM": 2,
        "LOW": 3,
    }

    analyzer.findings.sort(
        key=lambda finding: (
            severity_order.get(
                finding["severity"],
                99,
            ),
            finding["line"],
        )
    )

    counts = {
        "CRITICAL": 0,
        "HIGH": 0,
        "MEDIUM": 0,
        "LOW": 0,
    }

    for finding in analyzer.findings:

        severity = finding["severity"]

        if severity in counts:
            counts[severity] += 1

    return {
        "success": True,
        "summary": (
            f"TraceAI analyzed the code and detected "
            f"{len(analyzer.findings)} potential issue(s)."
        ),
        "findings": analyzer.findings,
        "counts": counts,
    }
