from __future__ import annotations

import ast
import json
import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

ROUTE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("http", re.compile(r"\bRoute::(get|post|put|patch|delete|options|any)\s*\(\s*['\"]([^'\"]+)", re.I)),
    ("http", re.compile(r"\b(?:app|router)\.(get|post|put|patch|delete|options|head|all)\s*\(\s*['\"]([^'\"]+)", re.I)),
    ("http", re.compile(r"@\w+\.(get|post|put|patch|delete|options|head)\s*\(\s*['\"]([^'\"]+)", re.I)),
    ("http", re.compile(r"@(?:GetMapping|PostMapping|PutMapping|PatchMapping|DeleteMapping|RequestMapping)\s*\(\s*(?:value\s*=\s*)?['\"]([^'\"]+)", re.I)),
    ("http", re.compile(r"\bMap(Get|Post|Put|Patch|Delete|Methods)\s*\(\s*['\"]([^'\"]+)", re.I)),
]
ENV_PATTERNS = [
    re.compile(r"\bos\.getenv\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    re.compile(r"\bos\.environ(?:\.get)?\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    re.compile(r"\bos\.environ\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]"),
    re.compile(r"\bprocess\.env\.([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"\b(?:env|getenv)\(\s*['\"]([A-Za-z_][A-Za-z0-9_.-]*)['\"]"),
    re.compile(r"\$_ENV\[['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\]"),
    re.compile(r"Environment\.GetEnvironmentVariable\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
]
CONFIG_PATTERNS = [
    re.compile(r"\bconfig\(\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"\bsettings?\[['\"]([^'\"]+)['\"]\]", re.I),
]
SQL_RE = re.compile(r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+TABLE|ALTER\s+TABLE)\b", re.I)
CONCURRENCY_RE = re.compile(r"\b(async|await|thread|mutex|lock|semaphore|queue|channel|goroutine|tokio|Task\.Run|parallel|concurrent|atomic)\b", re.I)
SECURITY_RE = re.compile(r"\b(auth|authentication|authorization|permission|role|token|jwt|oauth|csrf|xss|encrypt|decrypt|password|secret|credential|sanitize|escape)\b", re.I)
TODO_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b[:\s-]*(.*)", re.I)
_SOURCE_SECRET_RE = re.compile('(?i)(?:api[-_]?key|secret[-_]?key|access[-_]?token|password|passwd|auth[-_]?token|bearer)\\s*[=:]\\s*["\\\']([A-Za-z0-9+/\\-_]{12,})["\\\']')
_SOURCE_HARDCODED_IP = re.compile('\\b(?:https?://)\\d{1,3}(?:\\.\\d{1,3}){3}(?::\\d+)?\\b')
_SOURCE_UNITY_LIFECYCLES = re.compile('\\b(Awake|Start|Update|FixedUpdate|LateUpdate|OnEnable|OnDisable|OnDestroy|OnTriggerEnter|OnCollisionEnter|OnTriggerExit|OnCollisionExit|OnApplicationPause|OnApplicationQuit)\\s*\\(', re.M)
_SOURCE_REACT_COMPONENT = re.compile('(?:export\\s+(?:default\\s+)?)?(?:function|const|class)\\s+([A-Z][A-Za-z0-9_]+)', re.M)
_SOURCE_REACT_HOOK = re.compile('\\bconst\\s+(use[A-Z][A-Za-z0-9_]*)\\s*=', re.M)
_SOURCE_REACT_ROUTE = re.compile('(?:path|to)\\s*[:=]\\s*[\\\'"`]([/][^\\\'"`]*)[\\\'"`]', re.M)
_SOURCE_TS_DECLARATION = re.compile('^\\s*(?:export\\s+)?(?:default\\s+)?(interface|type|enum|class)\\s+([A-Za-z_$][A-Za-z0-9_$]*)', re.M)
_SOURCE_NEXT_ROUTE_HANDLER = re.compile('^\\s*export\\s+(?:async\\s+)?function\\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\\s*\\(', re.M)
_SOURCE_NEST_DECORATOR = re.compile('^\\s*@(Controller|Injectable|Get|Post|Put|Patch|Delete)\\s*(?:\\(\\s*[\'\\"]?([^\'\\")\\s]*)[\'\\"]?\\s*\\))?', re.M)
_SOURCE_TEST_SUITE_BLOCK = re.compile('^\\s*(describe|it|test)\\s*\\(\\s*[\'\\"` ]([^\'\\"`]+)[\'\\"` ]', re.M)
_SOURCE_FORM_TAG = re.compile('<form\\b([^>]*)>', re.I)
_SOURCE_ACTION_ATTR = re.compile('\\baction=["\\\']([^"\\\']+)["\\\']', re.I)
_SOURCE_METHOD_ATTR = re.compile('\\bmethod=["\\\']([^"\\\']+)["\\\']', re.I)
_SOURCE_SCRIPT_SRC = re.compile('<script\\b[^>]*\\bsrc=["\\\']([^"\\\']+)["\\\']', re.I)
_SOURCE_LINK_CSS = re.compile('<link\\b[^>]*\\bhref=["\\\']([^"\\\']+)["\\\']', re.I)
_SOURCE_ELEM_ID = re.compile('\\bid=["\\\']([A-Za-z0-9_-]+)["\\\']', re.I)
_SOURCE_WEB_COMPONENT = re.compile('<([a-z0-9]+-[a-z0-9-]+)\\b', re.I)
_SOURCE_BLADE_DIRECTIVE = re.compile('@(extends|include|section|yield|livewire|component)\\s*\\(\\s*["\\\']([^"\\\']+)["\\\']', re.I)
_SOURCE_CSS_VAR = re.compile('--([A-Za-z0-9_-]+)\\s*:\\s*([^;]+);')
_SOURCE_KEYFRAMES = re.compile('@keyframes\\s+([A-Za-z0-9_-]+)')
_SOURCE_MEDIA_QUERY = re.compile('@media\\s+([^{]+)')
_SOURCE_CSS_CLASS = re.compile('^\\s*(\\.[A-Za-z0-9_-]+)\\s*\\{')
_SOURCE_PHP_DEF = re.compile('^\\s*(?:(?:final|abstract|readonly)\\s+)*(class|trait|interface|enum)\\s+([A-Za-z_][A-Za-z0-9_]*)', re.M)
_SOURCE_PHP_FUNC = re.compile('^\\s*(?:(?:public|protected|private|static|final|abstract)\\s+)*function\\s+([A-Za-z_][A-Za-z0-9_]*)\\s*\\(', re.M)
_SOURCE_PHP_NS = re.compile('^\\s*namespace\\s+([A-Za-z_][A-Za-z0-9_\\\\]*)', re.M)
_SOURCE_PHP_ROUTE_ATTR = re.compile('#\\[(?:Route|Get|Post|Put|Patch|Delete)\\s*(?:\\(\\s*[\'\\"]([^\'\\"]+)[\'\\"](?:[^)]*methods:\\s*\\[([^\\]]+)\\])?\\s*\\))?\\]', re.M)
_SOURCE_PHP_ATTR = re.compile('#\\[([A-Za-z_][A-Za-z0-9_\\\\]*(?:\\([^)]*\\))?)\\]', re.M)
_SOURCE_WP_HOOK = re.compile('\\b(add_action|add_filter|do_action|apply_filters)\\s*\\(\\s*[\'\\"]([^\'\\"]+)[\'\\"]', re.M)
_SOURCE_LARAVEL_RESOURCE = re.compile('\\bRoute::(?:apiResource|resource)\\s*\\(\\s*[\'\\"]([^\'\\"]+)[\'\\"]\\s*,\\s*([A-Za-z0-9_\\\\]+)', re.M)
_SOURCE_ELOQUENT_TABLE = re.compile('protected\\s+\\$table\\s*=\\s*[\\\'"]([^\\\'"]+)[\\\'"]')
_SOURCE_ELOQUENT_FILLABLE = re.compile('protected\\s+\\$fillable\\s*=\\s*\\[([^\\]]+)\\]')
_SOURCE_ELOQUENT_REL = re.compile('return\\s+\\$this->(belongsTo|hasMany|hasOne|belongsToMany|morphTo|morphMany)\\s*\\(\\s*([A-Za-z0-9_:\\\\]+)', re.I)
_SOURCE_SCHEMA_CREATE = re.compile('Schema::create\\s*\\(\\s*[\\\'"]([^\\\'"]+)[\\\'"]')
_SOURCE_MIGRATION_COL = re.compile('\\$table->(string|integer|bigInteger|unsignedBigInteger|id|foreignId|boolean|text|longText|json|timestamp|date)\\s*\\(\\s*(?:[\\\'"]([^\\\'"]+)[\\\'"])?')
_SOURCE_ARTISAN_CMD = re.compile('protected\\s+\\$signature\\s*=\\s*[\\\'"]([^\\\'"]+)[\\\'"]')
_SOURCE_FORM_REQ = re.compile('class\\s+([A-Za-z0-9_]+)\\s+extends\\s+FormRequest\\b')
_SOURCE_CAKE_ROUTE = re.compile('\\$(?:builder|routes)->connect\\s*\\(\\s*[\\\'"]([^\\\'"]+)[\\\'"]')
_SOURCE_CAKE_RESOURCES = re.compile('\\$(?:builder|routes)->resources\\s*\\(\\s*[\\\'"]([^\\\'"]+)[\\\'"]')
_SOURCE_CAKE_TABLE = re.compile('class\\s+([A-Za-z0-9_]+Table)\\s+extends\\s+Table\\b')
_SOURCE_CAKE_ENTITY = re.compile('class\\s+([A-Za-z0-9_]+)\\s+extends\\s+Entity\\b')
_SOURCE_CAKE_ASSOC = re.compile('\\$this->(hasMany|belongsTo|belongsToMany|hasOne)\\s*\\(\\s*[\\\'"]([^\\\'"]+)[\\\'"]')
_SOURCE_CAKE_MIGRATION = re.compile('\\$this->table\\s*\\(\\s*[\\\'"]([^\\\'"]+)[\\\'"]')
_SOURCE_DECORATOR_RE = re.compile('^@([\\w.]+)', re.M)
_SOURCE_ASYNC_DEF_RE = re.compile('\\basync\\s+def\\s+(\\w+)', re.M)
_SOURCE_DATACLASS_RE = re.compile('@dataclass', re.M)
_SOURCE_IMPORT_FROM = re.compile('^(?:from\\s+([\\w.]+)\\s+import\\s+([\\w, ]+)|import\\s+([\\w.]+))', re.M)
_SOURCE_TESTED_CLASS = re.compile('class\\s+Test(\\w+)', re.M)
_SOURCE_PHP_TESTED_CLASS = re.compile('class\\s+(\\w+)Test\\b', re.M)
_SOURCE_PHP_USE = re.compile('^\\s*use\\s+([A-Za-z_][A-Za-z0-9_\\\\]+);', re.M)
_SOURCE_JS_IMPORT = re.compile('import\\s+(?:\\{([^}]+)\\}|(\\w+))\\s+from\\s+[\'\\"]([^\'\\"]+)[\'\\"]', re.M)
_SOURCE_TABLE_INSERT_I = re.compile('\\b(?:CREATE\\s+TABLE|ALTER\\s+TABLE|INSERT\\s+INTO|UPDATE|DELETE\\s+FROM|FROM|JOIN)\\s+(?:IF\\s+(?:NOT\\s+)?EXISTS\\s+)?[`\\"\\[]?([A-Za-z_][A-Za-z0-9_.$:-]*)', re.I)


def extract_source_facts(
    path: str,
    text: str,
    *,
    language: Callable[..., Any],
    fact: Callable[..., Any],
    flatten_config: Callable[..., Any],
    extract_python_ast: Callable[..., Any],
    extract_infra_facts: Callable[..., Any],
    is_test: Callable[..., Any],
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    lang = language(path)
    if lang == "python":
        try:
            ast.parse(text)
        except SyntaxError as exc:
            facts.append(fact("syntax_error", "python", str(exc.msg), int(exc.lineno or 1)))
        facts.extend(extract_python_ast(text))
    elif lang in {"json", "toml", "xml"}:
        try:
            if lang == "json": data = json.loads(text)
            elif lang == "toml": data = tomllib.loads(text)
            else:
                root = ET.fromstring(text)
                data = {"xml_tags": list(dict.fromkeys(node.tag.split("}")[-1] for node in root.iter()))[:200]}
            for key in flatten_config(data)[:200]:
                facts.append(fact("config_key", key, key, 1))
            if lang == "json" and isinstance(data, dict) and ("openapi" in data or "swagger" in data) and isinstance(data.get("paths"), dict):
                for route, operations in list(data.get("paths", {}).items())[:500]:
                    if not isinstance(operations, dict):
                        continue
                    for method in operations:
                        if str(method).lower() in {"get", "post", "put", "patch", "delete", "options", "head", "trace"}:
                            facts.append(fact("route", str(route), str(method).upper(), 1, method=str(method).upper(), source="openapi-json"))
        except Exception as exc:
            facts.append(fact("syntax_error", lang, str(exc)[:300], 1))

    # ── Language-specific analyzers ──────────────────────────────────────────
    ext = Path(path).suffix.lower()

    # Unity / C# analyzer
    if ext == ".cs":
        UNITY_LIFECYCLES = _SOURCE_UNITY_LIFECYCLES
        for line_no, line in enumerate(text.splitlines(), 1):
            m = UNITY_LIFECYCLES.search(line)
            if m:
                facts.append(fact("unity_lifecycle", m.group(1), line.strip()[:200], line_no))
            if "[SerializeField]" in line or "[SerializeField(" in line:
                facts.append(fact("unity_serialize_field", "SerializeField", line.strip()[:200], line_no))
            if "MonoBehaviour" in line:
                facts.append(fact("unity_monobehaviour", "MonoBehaviour", line.strip()[:200], line_no))
            if "ScriptableObject" in line:
                facts.append(fact("unity_scriptable_object", "ScriptableObject", line.strip()[:200], line_no))
            if "[CustomEditor(" in line:
                facts.append(fact("unity_custom_editor", "CustomEditor", line.strip()[:200], line_no))

    # JavaScript / TypeScript / Vue / Svelte analyzer
    if ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte"):
        REACT_COMPONENT = _SOURCE_REACT_COMPONENT
        REACT_HOOK = _SOURCE_REACT_HOOK
        REACT_ROUTE = _SOURCE_REACT_ROUTE
        TS_DECLARATION = _SOURCE_TS_DECLARATION
        NEXT_ROUTE_HANDLER = _SOURCE_NEXT_ROUTE_HANDLER
        NEST_DECORATOR = _SOURCE_NEST_DECORATOR
        TEST_SUITE_BLOCK = _SOURCE_TEST_SUITE_BLOCK
        for line_no, line in enumerate(text.splitlines(), 1):
            cm = REACT_COMPONENT.search(line)
            if cm and ("React" in text or "jsx" in path or "tsx" in path or "useState" in text or "useEffect" in text):
                facts.append(fact("react_component", cm.group(1), line.strip()[:200], line_no))
            hm = REACT_HOOK.search(line)
            if hm:
                facts.append(fact("react_hook", hm.group(1), line.strip()[:200], line_no))
            rm = REACT_ROUTE.search(line)
            if rm:
                facts.append(fact("route", rm.group(1), "ANY", line_no))
            tm = TS_DECLARATION.search(line)
            if tm:
                kind = tm.group(1)
                symbol_name = tm.group(2)
                facts.append(fact(f"ts_{kind}", symbol_name, line.strip()[:200], line_no))
            nm = NEXT_ROUTE_HANDLER.search(line)
            if nm:
                method = nm.group(1).upper()
                route_path = "/" + Path(path.replace("\\", "/")).as_posix().lstrip("/")
                facts.append(fact("route", route_path, method, line_no, method=method, source="next-route-handler"))
            nest_m = NEST_DECORATOR.search(line)
            if nest_m:
                dec_type = nest_m.group(1)
                dec_val = nest_m.group(2) or ""
                if dec_type in {"Get", "Post", "Put", "Patch", "Delete"}:
                    facts.append(fact("route", dec_val or "/", dec_type.upper(), line_no, method=dec_type.upper(), source="nestjs"))
                else:
                    facts.append(fact("nest_decorator", dec_type, dec_val, line_no))
            tbm = TEST_SUITE_BLOCK.search(line)
            if tbm:
                block_type = tbm.group(1)
                test_title = tbm.group(2)
                facts.append(fact(f"test_{block_type}", test_title, line.strip()[:200], line_no))

    # HTML & template analyzer
    if ext in (".html", ".htm") or path.lower().endswith(".blade.php") or ext == ".ctp":
        FORM_TAG = _SOURCE_FORM_TAG
        ACTION_ATTR = _SOURCE_ACTION_ATTR
        METHOD_ATTR = _SOURCE_METHOD_ATTR
        SCRIPT_SRC = _SOURCE_SCRIPT_SRC
        LINK_CSS = _SOURCE_LINK_CSS
        ELEM_ID = _SOURCE_ELEM_ID
        WEB_COMPONENT = _SOURCE_WEB_COMPONENT
        BLADE_DIRECTIVE = _SOURCE_BLADE_DIRECTIVE

        for line_no, line in enumerate(text.splitlines(), 1):
            for fm in FORM_TAG.finditer(line):
                attrs = fm.group(1)
                am = ACTION_ATTR.search(attrs)
                mm = METHOD_ATTR.search(attrs)
                r_path = am.group(1) if am else "/"
                m_method = (mm.group(1) if mm else "GET").upper()
                facts.append(fact("html_form", r_path, m_method, line_no, method=m_method, action=r_path))
                facts.append(fact("route", r_path, m_method, line_no, method=m_method, source="html-form"))
            sm = SCRIPT_SRC.search(line)
            if sm:
                facts.append(fact("html_script", sm.group(1), sm.group(1), line_no))
            lm = LINK_CSS.search(line)
            if lm and ("stylesheet" in line.lower() or ".css" in lm.group(1).lower()):
                facts.append(fact("html_stylesheet", lm.group(1), lm.group(1), line_no))
            for id_m in ELEM_ID.finditer(line):
                facts.append(fact("html_id", id_m.group(1), id_m.group(1), line_no))
            for wc_m in WEB_COMPONENT.finditer(line):
                facts.append(fact("web_component", wc_m.group(1), wc_m.group(1), line_no))
            for bm in BLADE_DIRECTIVE.finditer(line):
                directive, arg = bm.group(1).lower(), bm.group(2)
                facts.append(fact(f"blade_{directive}", arg, arg, line_no))

    # CSS / SCSS / LESS analyzer
    if ext in (".css", ".scss", ".sass", ".less"):
        CSS_VAR = _SOURCE_CSS_VAR
        KEYFRAMES = _SOURCE_KEYFRAMES
        MEDIA_QUERY = _SOURCE_MEDIA_QUERY
        CSS_CLASS = _SOURCE_CSS_CLASS

        for line_no, line in enumerate(text.splitlines(), 1):
            vm = CSS_VAR.search(line)
            if vm:
                facts.append(fact("css_variable", f"--{vm.group(1)}", vm.group(2).strip(), line_no))
            km = KEYFRAMES.search(line)
            if km:
                facts.append(fact("css_keyframes", km.group(1), km.group(1), line_no))
            mm = MEDIA_QUERY.search(line)
            if mm:
                facts.append(fact("css_media_query", mm.group(1).strip()[:100], mm.group(1).strip()[:100], line_no))
            cm = CSS_CLASS.search(line)
            if cm:
                facts.append(fact("css_class", cm.group(1), cm.group(1), line_no))

    # PHP & CakePHP analyzer
    if ext in (".php", ".ctp"):
        PHP_DEF = _SOURCE_PHP_DEF
        PHP_FUNC = _SOURCE_PHP_FUNC
        PHP_NS = _SOURCE_PHP_NS
        PHP_ROUTE_ATTR = _SOURCE_PHP_ROUTE_ATTR
        PHP_ATTR = _SOURCE_PHP_ATTR
        WP_HOOK = _SOURCE_WP_HOOK
        LARAVEL_RESOURCE = _SOURCE_LARAVEL_RESOURCE
        # Laravel specifics
        ELOQUENT_TABLE = _SOURCE_ELOQUENT_TABLE
        ELOQUENT_FILLABLE = _SOURCE_ELOQUENT_FILLABLE
        ELOQUENT_REL = _SOURCE_ELOQUENT_REL
        SCHEMA_CREATE = _SOURCE_SCHEMA_CREATE
        MIGRATION_COL = _SOURCE_MIGRATION_COL
        ARTISAN_CMD = _SOURCE_ARTISAN_CMD
        FORM_REQ = _SOURCE_FORM_REQ

        # CakePHP specifics
        CAKE_ROUTE = _SOURCE_CAKE_ROUTE
        CAKE_RESOURCES = _SOURCE_CAKE_RESOURCES
        CAKE_TABLE = _SOURCE_CAKE_TABLE
        CAKE_ENTITY = _SOURCE_CAKE_ENTITY
        CAKE_ASSOC = _SOURCE_CAKE_ASSOC
        CAKE_MIGRATION = _SOURCE_CAKE_MIGRATION

        current_ns = ""
        for line_no, line in enumerate(text.splitlines(), 1):
            ns_m = PHP_NS.search(line)
            if ns_m:
                current_ns = ns_m.group(1).rstrip(";")
                facts.append(fact("php_namespace", current_ns, current_ns, line_no))
                continue

            def_m = PHP_DEF.search(line)
            if def_m:
                kind = def_m.group(1)
                name = def_m.group(2)
                fqn = f"{current_ns}\\{name}" if current_ns else name
                facts.append(fact(f"php_{kind}", name, fqn, line_no, namespace=current_ns, fqn=fqn))

            fn_m = PHP_FUNC.search(line)
            if fn_m:
                fn_name = fn_m.group(1)
                if fn_name.lower() not in {"__construct", "__destruct", "__get", "__set"}:
                    facts.append(fact("php_function", fn_name, line.strip()[:200], line_no))

            attr_m = PHP_ATTR.search(line)
            if attr_m:
                attr_val = attr_m.group(1)
                facts.append(fact("php_attribute", attr_val, attr_val, line_no))

            route_attr_m = PHP_ROUTE_ATTR.search(line)
            if route_attr_m:
                route_path = route_attr_m.group(1) or "/"
                methods_str = route_attr_m.group(2) or "ANY"
                for method in methods_str.replace("'", "").replace('"', "").split(","):
                    m_clean = method.strip().upper() or "ANY"
                    facts.append(fact("route", route_path, m_clean, line_no, method=m_clean, source="php-attribute"))

            lr_m = LARAVEL_RESOURCE.search(line)
            if lr_m:
                res_path = lr_m.group(1)
                controller = lr_m.group(2)
                facts.append(fact("route", f"/{res_path.lstrip('/')}", "RESOURCE", line_no, controller=controller, source="laravel-resource"))

            wp_m = WP_HOOK.search(line)
            if wp_m:
                hook_kind = wp_m.group(1)
                hook_name = wp_m.group(2)
                facts.append(fact("wordpress_hook", hook_name, hook_kind, line_no, hook=hook_name, hook_type=hook_kind))

            # Laravel facts
            tbl_m = ELOQUENT_TABLE.search(line)
            if tbl_m:
                facts.append(fact("eloquent_table", tbl_m.group(1), tbl_m.group(1), line_no))
            fill_m = ELOQUENT_FILLABLE.search(line)
            if fill_m:
                cols = [c.strip().strip("'\"") for c in fill_m.group(1).split(",") if c.strip().strip("'\"")]
                for col in cols:
                    facts.append(fact("eloquent_fillable", col, col, line_no))
            rel_m = ELOQUENT_REL.search(line)
            if rel_m:
                facts.append(fact("eloquent_relation", rel_m.group(2).split("::")[0], rel_m.group(1), line_no, relation_type=rel_m.group(1)))
            sc_m = SCHEMA_CREATE.search(line)
            if sc_m:
                facts.append(fact("db_table", sc_m.group(1), sc_m.group(1), line_no, source="laravel-migration"))
            col_m = MIGRATION_COL.search(line)
            if col_m:
                c_type = col_m.group(1)
                c_name = col_m.group(2) or c_type
                facts.append(fact("db_column", c_name, c_type, line_no, col_type=c_type))
            art_m = ARTISAN_CMD.search(line)
            if art_m:
                cmd_name = art_m.group(1).split()[0]
                facts.append(fact("artisan_command", cmd_name, art_m.group(1), line_no))
            freq_m = FORM_REQ.search(line)
            if freq_m:
                facts.append(fact("form_request", freq_m.group(1), freq_m.group(1), line_no))

            # CakePHP facts
            cr_m = CAKE_ROUTE.search(line)
            if cr_m:
                facts.append(fact("route", cr_m.group(1), "ANY", line_no, source="cakephp"))
            cres_m = CAKE_RESOURCES.search(line)
            if cres_m:
                facts.append(fact("route", f"/{cres_m.group(1).lstrip('/')}", "RESOURCE", line_no, source="cakephp-resource"))
            ctbl_m = CAKE_TABLE.search(line)
            if ctbl_m:
                facts.append(fact("cake_table", ctbl_m.group(1), ctbl_m.group(1), line_no))
            cent_m = CAKE_ENTITY.search(line)
            if cent_m:
                facts.append(fact("cake_entity", cent_m.group(1), cent_m.group(1), line_no))
            cassoc_m = CAKE_ASSOC.search(line)
            if cassoc_m:
                facts.append(fact("cake_association", cassoc_m.group(2), cassoc_m.group(1), line_no, association_type=cassoc_m.group(1)))
            cmig_m = CAKE_MIGRATION.search(line)
            if cmig_m:
                facts.append(fact("db_table", cmig_m.group(1), cmig_m.group(1), line_no, source="cakephp-migration"))

    # Python: decorators, dataclasses, async flows
    if ext == ".py":
        DECORATOR_RE = _SOURCE_DECORATOR_RE
        ASYNC_DEF_RE = _SOURCE_ASYNC_DEF_RE
        DATACLASS_RE = _SOURCE_DATACLASS_RE
        for m in DECORATOR_RE.finditer(text):
            line_no = text[:m.start()].count("\n") + 1
            facts.append(fact("python_decorator", m.group(1), m.group(0), line_no))
        for m in ASYNC_DEF_RE.finditer(text):
            line_no = text[:m.start()].count("\n") + 1
            facts.append(fact("async_function", m.group(1), m.group(0), line_no))
        if DATACLASS_RE.search(text):
            facts.append(fact("python_dataclass", "dataclass", path, 1))

    # ── Security / secret scanner ─────────────────────────────────────────────
    SECRET_RE = _SOURCE_SECRET_RE
    HARDCODED_IP = _SOURCE_HARDCODED_IP
    for line_no, line in enumerate(text.splitlines(), 1):
        sm = SECRET_RE.search(line)
        if sm:
            # Never store the actual secret value — only flag the location
            facts.append(fact("security_hardcoded_secret", "REDACTED", f"line {line_no}: potential secret detected", line_no))
        if HARDCODED_IP.search(line) and "127.0.0.1" not in line and "localhost" not in line:
            facts.append(fact("security_hardcoded_ip", "hardcoded_ip", line.strip()[:200], line_no))
        # Merge conflict markers
        if line.startswith("<<<<<<< ") or line.startswith(">>>>>>> ") or line == "=======":
            facts.append(fact("merge_conflict", "git_conflict_marker", line.strip()[:80], line_no))

    # ── Test-to-production mapping ────────────────────────────────────────────
    if is_test(path):
        # Extract names of classes/functions being tested from import statements and class names
        IMPORT_FROM = _SOURCE_IMPORT_FROM
        TESTED_CLASS = _SOURCE_TESTED_CLASS
        PHP_TESTED_CLASS = _SOURCE_PHP_TESTED_CLASS
        PHP_USE = _SOURCE_PHP_USE
        JS_IMPORT = _SOURCE_JS_IMPORT
        for m in IMPORT_FROM.finditer(text):
            module = m.group(1) or m.group(3) or ""
            if module and not module.startswith("test") and "mock" not in module.lower():
                facts.append(fact("tests_module", module, path, 1))
            imported_symbols = m.group(2)
            if imported_symbols:
                for sym in imported_symbols.split(","):
                    s = sym.strip()
                    if s and not s.startswith("test"):
                        facts.append(fact("tests_symbol", s, path, 1))
        for m in TESTED_CLASS.finditer(text):
            facts.append(fact("tests_class", m.group(1), path, 1))
        for m in PHP_TESTED_CLASS.finditer(text):
            facts.append(fact("tests_class", m.group(1), path, 1))
        for m in PHP_USE.finditer(text):
            use_target = m.group(1).split("\\")[-1]
            if use_target and not use_target.endswith("Test") and not use_target.startswith("Test"):
                facts.append(fact("tests_symbol", use_target, path, 1))
        for m in JS_IMPORT.finditer(text):
            named = m.group(1)
            default_sym = m.group(2)
            import_src = m.group(3)
            if named:
                for s in named.split(","):
                    clean_s = s.strip().split(" as ")[0].strip()
                    if clean_s and not clean_s.startswith("test"):
                        facts.append(fact("tests_symbol", clean_s, path, 1))
            if default_sym and not default_sym.startswith("test"):
                facts.append(fact("tests_symbol", default_sym, path, 1))
            if import_src and not import_src.startswith("test"):
                facts.append(fact("tests_module", import_src, path, 1))

    # ── General line-by-line patterns ────────────────────────────────────────
    for line_no, line in enumerate(text.splitlines(), 1):
        for _, pattern in ROUTE_PATTERNS:
            m = pattern.search(line)
            if not m:
                continue
            groups = m.groups()
            method, route = "ANY", ""
            if len(groups) >= 2:
                method, route = str(groups[0]).upper(), str(groups[1])
            elif groups:
                route = str(groups[0])
                decorator = m.group(0).lower()
                method = next((x.upper() for x in ("get", "post", "put", "patch", "delete") if x in decorator), "ANY")
            facts.append(fact("route", route, method, line_no, method=method))
        for pattern in ENV_PATTERNS:
            for m in pattern.finditer(line):
                facts.append(fact("env", m.group(1), m.group(1), line_no))
        for pattern in CONFIG_PATTERNS:
            for m in pattern.finditer(line):
                facts.append(fact("config", m.group(1), m.group(1), line_no))
        todo = TODO_RE.search(line)
        if todo:
            facts.append(fact("todo", todo.group(1).upper(), todo.group(2).strip()[:300], line_no))
        if SQL_RE.search(line):
            facts.append(fact("database", "sql", line.strip()[:300], line_no))
            for pattern in (
                _SOURCE_TABLE_INSERT_I,
            ):
                for sm in pattern.finditer(line):
                    facts.append(fact("db_table", sm.group(1), sm.group(1), line_no, source="sql"))
        conc = CONCURRENCY_RE.search(line)
        if conc:
            facts.append(fact("concurrency", conc.group(1).lower(), line.strip()[:300], line_no))
        sec = SECURITY_RE.search(line)
        if sec:
            facts.append(fact("security", sec.group(1).lower(), line.strip()[:300], line_no))
    facts.extend(extract_infra_facts(path, text))
    if is_test(path):
        facts.append(fact("test_file", Path(path).name, path, 1))
    low_name = Path(path).name.lower()
    if low_name in {"main.py", "app.py", "index.js", "index.ts", "server.js", "server.ts", "program.cs", "main.go", "main.rs"}:
        facts.append(fact("entrypoint_file", Path(path).name, path, 1))
    return facts
