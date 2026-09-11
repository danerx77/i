"""Extract user-facing strings from the launcher sources into a worklist JSON.

The scanner is AST based: it only looks at string literals that are passed to
Qt setters / widget constructors that are known to render text, which keeps CSS
blobs, registry keys, NSS tokens and font names out of the result.

Usage
-----
    python tools/i18n_extract.py --stats              # print coverage stats
    python tools/i18n_extract.py --out tools/work.json
    python tools/i18n_extract.py --missing            # strings without a Polish entry
"""
import argparse
import ast
import json
import os
import re
import sys

LAUNCHER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALES_DIR = os.path.join(LAUNCHER_DIR, "locales")

SOURCE_FILES = [
    "launcher.pyw",
    "utils.py",
    "modify_widget.py",
    "menu_builder_widget.py",
    "cursor_widget.py",
    "theme_editor_widget.py",
    "theme_switcher_widget.py",
    "plugin_registry.py",
    "plugin_workers.py",
    "nss_parser.py",
    "nss_error_monitor.py",
    "svg_manager.py",
    "cloud_sync.py",
    "github_client.py",
]

# method names whose string arguments end up on screen
UI_METHODS = {
    "setText", "setPlainTextLabel", "setWindowTitle", "setPlaceholderText",
    "setToolTip", "setStatusTip", "setWhatsThis", "setTabText", "setTabToolTip",
    "setButtonText", "setInformativeText", "setDetailedText", "setTitle",
    "setLabelText", "add_button", "show_message", "set_status", "set_description",
    "question", "information", "warning", "critical", "about",
    "getText", "getMultiLineText", "getInt", "getDouble", "getItem",
    "getOpenFileName", "getOpenFileNames", "getSaveFileName", "getExistingDirectory",
}

# constructor -> tuple of argument positions that hold display text
UI_CLASS_ARGS = {
    "QLabel": (0,), "QPushButton": (0,), "QCheckBox": (0,), "QRadioButton": (0,),
    "QGroupBox": (0,), "QToolButton": (0,), "QCommandLinkButton": (0, 1),
    "QAction": (0,), "QTabWidget": (), "QProgressDialog": (0, 1),
    "PillPushButton": (0,), "PillTabButton": (0,), "PillLineEdit": (0,),
    "CapsuleActionButton": (1,), "NavTabButton": (1,), "FilterTag": (0,),
    "CriteriaPill": (0,), "VisibilityCard": (0, 1), "TypePill": (0,),
    "ModernDialog": (1, 2), "CustomMessageBox": (1, 2), "ModernSwitch": (),
    "UnsavedChangesDialog": (1, 2), "AccountProfileDialog": (),
    "StyledConfirmDialog": (1, 2), "CustomConfirmDialog": (1, 2),
    "ItemConfigDialog": (), "AddThemeDialog": (), "EditThemeDialog": (),
    "AddSVGDialog": (), "GlyphBrowserDialog": (), "LocalIconTintDialog": (),
    "ImportEditorDialog": (), "MultiItemEditDialog": (), "ModifyRuleEditorDialog": (),
    "IDPopupDialog": (), "ManualSyncConflictDialog": (), "StandaloneSVGManager": (),
    "MinimalColorPickerDialog": (), "QMessageBox": (2, 3),
}

# values that look like text but are API identifiers / style names
DENY = {
    "primary", "secondary", "danger", "ghost", "subtle", "accent",
    "installButton", "uninstallButton", "sideButton", "secondaryButton",
    "primaryButton", "dangerButton", "cancelButton", "confirmButton",
    "Segoe UI", "Segoe UI Variable Display", "Segoe UI Variable Text",
    "Segoe MDL2 Assets", "Segoe Fluent Icons", "Arial", "Tahoma", "Consolas",
    "Times New Roman", "Trebuchet MS", "Verdana", "Nilesoft Shell Symbol",
    "Acrylic", "Blur", "Transparent", "None", "none",
}

GLYPH_RE = re.compile(r"^[\s\ue000-\uf8ff\W\d]*$")
NOISE_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|@|https?://|[A-Za-z]:\\|/|\.)")
CODE_HINTS = ("rgba(", "border:", "background", "padding:", "font-size", "QFrame {",
              "QPushButton {", "QLabel {", "symbol.", "image.res", "menu=", "vis=",
              "sel(", "command.", "start \"", "--dir", "--new", "blob ", "\\x00")


def is_noise(text):
    stripped = text.strip()
    if not stripped or len(stripped) > 300:
        return True
    if text in DENY:
        return True
    if GLYPH_RE.match(text):
        return True
    if NOISE_RE.match(stripped):
        return True
    if any(hint in text for hint in CODE_HINTS):
        return True
    if text.count("{") and text.count(":") and ";" in text:      # CSS / NSS block
        return True
    if re.search(r"\.(exe|dll|nss|png|jpg|jpeg|json|ico|svg|css|txt|reg|py|cur|ani|ttf|zip)\b", text):
        return True
    if re.search(r"^[A-Z][A-Z0-9_]{2,}$", stripped):              # env var / constant
        return True
    if "\n" in text and text.count("\n") > 2:                     # docstring / NSS dump
        return True
    if re.match(r"^[a-z_][a-z0-9_.]*$", stripped):                # snake_case identifier
        return True
    if re.match(r"^[a-z]+[A-Z][A-Za-z]*$", stripped):             # camelCase identifier
        return True
    if not re.search(r"[A-Za-z]{3}", stripped):
        return True
    return False


def literal_of(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, False
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append("{}")
        return "".join(parts), True
    return None


class Visitor(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename = filename
        self.hits = []

    def record(self, text, is_template, node, context):
        self.hits.append({
            "msgid": text, "template": is_template, "file": self.filename,
            "line": getattr(node, "lineno", 0), "context": context,
        })

    def visit_Call(self, node):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else None)

        if name in UI_METHODS:
            start = 1 if name in ("question", "information", "warning", "critical",
                                  "about", "getText", "getMultiLineText", "getInt",
                                  "getDouble", "getItem") else 0
            for arg in node.args[start:start + 4]:
                lit = literal_of(arg)
                if lit:
                    self.record(lit[0], lit[1], arg, name)
            for kw in node.keywords:
                if kw.arg in ("text", "title", "label", "caption", "placeholderText",
                              "toolTip", "informativeText", "detailedText", "windowTitle"):
                    lit = literal_of(kw.value)
                    if lit:
                        self.record(lit[0], lit[1], kw.value, f"{name}({kw.arg}=)")
        elif name in UI_CLASS_ARGS:
            positions = UI_CLASS_ARGS[name]
            for position in positions:
                if position < len(node.args):
                    lit = literal_of(node.args[position])
                    if lit:
                        self.record(lit[0], lit[1], node.args[position], name)
            for kw in node.keywords:
                if kw.arg in ("text", "title", "label", "placeholderText", "toolTip"):
                    lit = literal_of(kw.value)
                    if lit:
                        self.record(lit[0], lit[1], kw.value, f"{name}({kw.arg}=)")
        self.generic_visit(node)


def scan():
    all_hits = []
    for filename in SOURCE_FILES:
        path = os.path.join(LAUNCHER_DIR, filename)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        try:
            tree = ast.parse(source)
        except SyntaxError as error:
            print(f"skip {filename}: {error}", file=sys.stderr)
            continue
        visitor = Visitor(filename)
        visitor.visit(tree)
        all_hits.extend(visitor.hits)

    grouped = {}
    for hit in all_hits:
        if is_noise(hit["msgid"]):
            continue
        key = (hit["msgid"], hit["template"])
        entry = grouped.setdefault(key, {
            "msgid": hit["msgid"], "template": hit["template"],
            "count": 0, "files": [], "contexts": [], "lines": []})
        entry["count"] += 1
        if hit["file"] not in entry["files"]:
            entry["files"].append(hit["file"])
        if hit["context"] not in entry["contexts"]:
            entry["contexts"].append(hit["context"])
        entry["lines"].append(hit["line"])
    return sorted(grouped.values(), key=lambda e: e["msgid"].lower())


# --------------------------------------------------------------------------- #
# Broad pass — catches literals handed to project specific helpers
# (create_nav_item, _create_setting_row, show_sync_status, _add_badge, ...)
# that the strict UI-method pass cannot know about.
# --------------------------------------------------------------------------- #

DATA_KWARGS = {
    "title", "cmd", "args", "arg", "icon", "image", "id", "type", "name", "path",
    "key", "value", "mode", "pos", "sep", "vis", "target", "dir", "ext", "font",
    "color", "data", "props", "style", "object_name", "property", "role", "glyph",
    "code",
}

SKIP_CALLS = {
    "get", "set", "pop", "setdefault", "update", "write", "dump", "loads", "dumps",
    "append", "join", "split", "replace", "format", "startswith", "endswith",
    "find", "index", "lower", "upper", "strip", "lstrip", "rstrip", "sub",
    "search", "match", "compile", "setStyleSheet", "setProperty", "setObjectName",
    "setFont", "makedirs", "remove", "exists", "open", "print", "getenv",
    "expandvars", "OpenKey", "CreateKey", "SetValueEx", "unpack", "rfind",
    "SetEnvironmentVariableW", "RegisterWindowMessageW", "normalize",
}

DOCSTRING_START = (
    "Returns", "Ensures", "Compiles", "Generates", "Serializes", "Safely", "Finds",
    "Called", "Clip", "Commits", "Thread-safe", "Vector", "High-quality",
    "Segmented", "Sleek", "Anti-aliased", "Scrollable", "Modern", "Interactive",
    "Large", "Circular", "Mouse", "Fast", "If running", "Force", "Get absolute",
    "Resolves", "Processes", "Renders", "Dedicated", "Used by", "Handles",
    "Creates", "Builds", "Draws", "Paints", "Wrapper", "Helper", "Note:",
    "A single", "Clickable", "Only", "Provides", "Manages", "Represents",
    "Stores", "Keeps", "Prevents", "Fires", "Triggers", "Converts", "Maps",
    "Caches", "Fetches", "Downloads", "Uploads", "Adds", "Shows", "Sets", "Gets",
    "Used", "Runs", "Executes", "Enables", "Disables", "Toggles", "Refreshes",
    "Prepares", "Waits", "Blocks", "Emits", "Emitted", "Full ", "100% ",
)


class _DocstringCollector(ast.NodeVisitor):
    def __init__(self):
        self.nodes = set()

    def _mark(self, node):
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            self.nodes.add(id(body[0].value))

    def visit_Module(self, node):
        self._mark(node); self.generic_visit(node)

    def visit_ClassDef(self, node):
        self._mark(node); self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self._mark(node); self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


class BroadVisitor(ast.NodeVisitor):
    """Collect literals that reach the screen through project helpers."""

    def __init__(self, filename, docstrings):
        self.filename = filename
        self.docstrings = docstrings
        self.hits = []
        self.in_dict = 0

    def visit_Dict(self, node):
        self.in_dict += 1
        self.generic_visit(node)
        self.in_dict -= 1

    def visit_Call(self, node):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else None)
        if name not in SKIP_CALLS:
            for arg in node.args:
                lit = literal_of(arg)
                if lit:
                    self.record(lit[0], lit[1], arg, name or "?")
        for kw in node.keywords:
            if kw.arg and kw.arg.lower() in DATA_KWARGS:
                continue
            lit = literal_of(kw.value)
            if lit:
                self.record(lit[0], lit[1], kw.value, f"{name}({kw.arg}=)")
        self.generic_visit(node)

    def record(self, text, is_template, node, context):
        if self.in_dict or id(node) in self.docstrings:
            return
        if is_noise(text):
            return
        stripped = text.strip()
        if not re.search(r"[A-Za-z]{2}", stripped):
            return
        if re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", stripped):
            return
        if re.match(r"^[a-z]", stripped) and " " not in stripped:
            return
        if stripped.startswith(DOCSTRING_START) and stripped.endswith("."):
            return
        self.hits.append({"msgid": text, "template": is_template, "file": self.filename,
                          "line": getattr(node, "lineno", 0), "context": context})


def _parse(filename):
    path = os.path.join(LAUNCHER_DIR, filename)
    if not os.path.exists(path):
        return None, None
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    try:
        return ast.parse(source), path
    except SyntaxError as error:
        print(f"skip {filename}: {error}", file=sys.stderr)
        return None, None


def scan_broad():
    hits = []
    for filename in SOURCE_FILES:
        tree, path = _parse(filename)
        if tree is None:
            continue
        collector = _DocstringCollector()
        collector.visit(tree)
        visitor = BroadVisitor(filename, collector.nodes)
        visitor.visit(tree)
        hits.extend(visitor.hits)
    return hits


def scan_all():
    """Strict UI-context scan + broad helper scan, grouped and de-duplicated."""
    grouped = {}

    def add(msgid, template, filename, context, line, count=1):
        entry = grouped.setdefault((msgid, template), {
            "msgid": msgid, "template": template, "count": 0,
            "files": [], "contexts": [], "lines": []})
        entry["count"] += count
        if filename and filename not in entry["files"]:
            entry["files"].append(filename)
        if context and context not in entry["contexts"]:
            entry["contexts"].append(context)
        if line:
            entry["lines"].append(line)

    for entry in scan():
        add(entry["msgid"], entry["template"], entry["files"][0] if entry["files"] else None,
            entry["contexts"][0] if entry["contexts"] else None,
            entry["lines"][0] if entry["lines"] else 0, entry["count"])
        grouped[(entry["msgid"], entry["template"])]["files"] = list(entry["files"])
        grouped[(entry["msgid"], entry["template"])]["contexts"] = list(entry["contexts"])
    for hit in scan_broad():
        add(hit["msgid"], hit["template"], hit["file"], hit["context"], hit["line"])
    return sorted(grouped.values(), key=lambda e: e["msgid"].lower())


def load_catalog(language):
    path = os.path.join(LOCALES_DIR, f"{language}.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    keys = set((data.get("messages") or {}).keys())
    keys |= set((data.get("patterns") or {}).keys())
    for group in (data.get("contexts") or {}).values():
        if isinstance(group, dict):
            keys |= set(group.keys())
    for pair in (data.get("plurals") or {}).keys():
        keys |= set(pair.split("|"))
    return keys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(LAUNCHER_DIR, "tools", "worklist.json"))
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--missing", action="store_true",
                        help="list extracted strings that have no Polish translation")
    args = parser.parse_args()

    entries = scan()
    payload = {"unique": len(entries),
               "occurrences": sum(e["count"] for e in entries),
               "entries": entries}
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    if args.stats:
        templates = sum(1 for e in entries if e["template"])
        print(f"occurrences={payload['occurrences']} unique={len(entries)} templates={templates}")
        by_file = {}
        for entry in entries:
            for filename in entry["files"]:
                by_file[filename] = by_file.get(filename, 0) + 1
        for filename, count in sorted(by_file.items(), key=lambda kv: -kv[1]):
            print(f"  {filename}: {count}")
        for language in ("en", "pl"):
            keys = load_catalog(language)
            covered = sum(1 for e in entries if e["msgid"] in keys)
            print(f"  {language}: {covered}/{len(entries)} extracted strings in catalogue")

    if args.missing:
        keys = load_catalog("pl")
        missing = [e for e in entries if e["msgid"] not in keys]
        print(f"missing Polish entries: {len(missing)}")
        for entry in missing:
            print(f"  {entry['msgid']!r}  <- {entry['contexts'][:2]} {entry['files'][:1]}")

    print(f"written -> {args.out}")


if __name__ == "__main__":
    main()
