"""
i18n — lightweight runtime translation layer for the iMA Menu Launcher.

Design goals
------------
1. **Zero-touch coverage** — the launcher builds its UI in many places and stores
   data in the same widgets that display it.  Instead of editing thousands of call
   sites, this module installs thin wrappers around the *display only* Qt setters
   (``QLabel.setText``, ``QAbstractButton.setText``, ``setWindowTitle``,
   ``setToolTip``, ``setPlaceholderText``, ``QGroupBox.setTitle``,
   ``QTabWidget.setTabText``, ``QMessageBox``/``QInputDialog``/``QFileDialog``
   static helpers, ...).  Every string that flows through them is looked up in the
   active catalogue; unknown strings pass through untouched.

   Data bearing widgets are deliberately **not** hooked: ``QLineEdit.setText``,
   ``QPlainTextEdit``/``QTextEdit``/``QTextBrowser`` content and ``QComboBox``
   items keep their original value because the app reads them back (``.text()``,
   ``currentText()``) and writes them into ``shell.nss``.

2. **Live retranslation** — whenever a widget receives a translated string the
   binding ``(widget, setter, msgid)`` is remembered through a weak reference, so
   switching the language re-applies every string on screen without restarting.

3. **Safety valve** — :func:`raw` marks a widget as "never translate" and
   :func:`canonical` maps a translated string back to its English source, which
   keeps logic such as ``if button.text() == "Close"`` working in any language.

Catalogue format (``locales/<lang>.json``)::

    {
      "meta": {"language": "pl", "name": "Polski"},
      "messages": {"Settings": "Ustawienia"},
      "contexts": {"separator": {"None": "Brak"}},
      "patterns": {"Syncing {} colors...": "Synchronizowanie kolorów: {}..."},
      "plurals": {"{} item|{} items": ["{} element", "{} elementy", "{} elementów"]}
    }
"""

import json
import os
import re
import sys
import warnings
import weakref

# --------------------------------------------------------------------------- #
# Language registry
# --------------------------------------------------------------------------- #

DEFAULT_LANGUAGE = "en"

LANGUAGES = [
    # (code, native name, english name)
    ("en", "English", "English"),
    ("pl", "Polski", "Polish"),
]

_LANGUAGE_CODES = [code for code, _native, _english in LANGUAGES]

SETTINGS_KEY = "language"
ENV_OVERRIDE = "IMA_MENU_LANG"

_HERE = os.path.dirname(os.path.abspath(__file__))
LOCALES_DIR = os.path.join(_HERE, "locales")

_state = {
    "language": DEFAULT_LANGUAGE,
    "catalog": {},          # lang -> {"messages": {}, "contexts": {}, ...}
    "patterns": [],         # list of (compiled_regex, translation, template)
    "pattern_heads": {},    # first literal char -> [(prefix, entry)]
    "pattern_tails": {},    # last literal char  -> [(suffix, entry)]
    "reverse": {},          # translated text -> msgid (active language)
    "settings_path": None,
    "hooks_installed": False,
    "hooked": [],
    "failed_hooks": [],
    "signal": None,
    "missing": {},          # msgid -> count (for tooling / diagnostics)
    "track_missing": False,
}

# widget -> {"setter": (msgid, context, pre_args, post_args)}  (bindings for replay)
_bindings = weakref.WeakKeyDictionary()
# widget -> list of callables(widget) used for custom (painted) text
_custom_bindings = weakref.WeakKeyDictionary()
# widgets that must never be translated
_raw_widgets = weakref.WeakSet()
# original, un-hooked Qt methods: (class, method) -> callable
_originals = {}


# --------------------------------------------------------------------------- #
# Catalogue loading
# --------------------------------------------------------------------------- #

def locales_dir():
    """Directory that holds the ``<lang>.json`` catalogues (PyInstaller aware)."""
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        candidate = os.path.join(frozen, "locales")
        if os.path.isdir(candidate):
            return candidate
    return LOCALES_DIR


def _load_catalog(lang):
    if lang in _state["catalog"]:
        return _state["catalog"][lang]
    path = os.path.join(locales_dir(), f"{lang}.json")
    data = {"messages": {}, "contexts": {}, "patterns": {}, "plurals": {}, "meta": {}}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            for key in ("messages", "contexts", "patterns", "plurals", "meta"):
                value = loaded.get(key)
                if isinstance(value, dict):
                    data[key] = value
    except FileNotFoundError:
        pass
    except Exception as error:                                    # pragma: no cover
        sys.stderr.write(f"[i18n] failed to load '{path}': {error}\n")
    _state["catalog"][lang] = data
    return data


def available_languages():
    """Return [(code, native_name, english_name)] for every loadable catalogue."""
    result = []
    directory = locales_dir()
    for code, native, english in LANGUAGES:
        if code == DEFAULT_LANGUAGE or os.path.exists(os.path.join(directory, f"{code}.json")):
            result.append((code, native, english))
    return result


def reload_catalogs():
    _state["catalog"].clear()
    _state["reverse"].clear()
    _rebuild_patterns()


def _rebuild_patterns():
    """Compile the pattern catalogue and index it for a fast pre-filter.

    ``setText`` runs thousands of times, so an unknown string must not be pushed
    through every regex: patterns are bucketed by their first literal character
    (and, for templates that start with ``{}``, by their last one).
    """
    catalog = _state["catalog"].get(_state["language"], {})
    patterns = catalog.get("patterns", {}) or {}
    compiled = []
    heads, tails = {}, {}
    for template, translation in patterns.items():
        regex = _template_to_regex(template)
        if regex is None:
            continue
        entry = (regex, translation, template)
        compiled.append(entry)
        head = template.split("{}", 1)[0]
        if head:
            heads.setdefault(head[0], []).append((head, entry))
        else:
            tail = template.rsplit("{}", 1)[-1]
            if tail:
                tails.setdefault(tail[-1], []).append((tail, entry))
    # longest templates first: they are the most specific ones
    for bucket in list(heads.values()) + list(tails.values()):
        bucket.sort(key=lambda item: -len(item[0]))
    compiled.sort(key=lambda item: -len(item[2]))
    _state["patterns"] = compiled
    _state["pattern_heads"] = heads
    _state["pattern_tails"] = tails


def _template_to_regex(template):
    """'Syncing {} colors...' -> compiled regex with one group per '{}'."""
    if "{}" not in template:
        return None
    parts = template.split("{}")
    if any(len(part) == 0 for part in parts[1:-1]):
        return None                       # ambiguous: '{}' '{}'
    body = "(.*?)".join(re.escape(part) for part in parts)
    try:
        return re.compile("^" + body + "$", re.DOTALL)
    except re.error:                                          # pragma: no cover
        return None


# --------------------------------------------------------------------------- #
# Settings (language persistence)
# --------------------------------------------------------------------------- #

def default_settings_path():
    """``<launcher dir>/cache/settings.json`` — same location the launcher uses."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = _HERE
    return os.path.join(base, "cache", "settings.json")


def configure(settings_path=None, language=None, track_missing=False):
    """Point i18n at the launcher settings file and load the stored language."""
    _state["settings_path"] = settings_path or default_settings_path()
    _state["track_missing"] = bool(track_missing)
    chosen = language or _read_language() or DEFAULT_LANGUAGE
    _apply_language(chosen, notify=False)
    return _state["language"]


def _read_language():
    # explicit override wins (useful for tests and "--lang pl")
    for arg_index, arg in enumerate(sys.argv):
        if arg in ("--lang", "--language") and arg_index + 1 < len(sys.argv):
            return _normalize_code(sys.argv[arg_index + 1])
        if arg.startswith("--lang="):
            return _normalize_code(arg.split("=", 1)[1])
    env_value = os.environ.get(ENV_OVERRIDE)
    if env_value:
        return _normalize_code(env_value)
    path = _state["settings_path"] or default_settings_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return _normalize_code(data.get(SETTINGS_KEY))
    except Exception:
        return None


def save_language(language=None):
    """Persist the active language next to the other launcher settings."""
    language = language or _state["language"]
    path = _state["settings_path"] or default_settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle) or {}
            except Exception:
                data = {}
        data[SETTINGS_KEY] = language
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=4)
        return True
    except Exception as error:                                # pragma: no cover
        sys.stderr.write(f"[i18n] could not save language: {error}\n")
        return False


def _normalize_code(code):
    if not code or not isinstance(code, str):
        return None
    code = code.strip().lower().replace("_", "-")
    if code in _LANGUAGE_CODES:
        return code
    base = code.split("-")[0]
    if base in _LANGUAGE_CODES:
        return base
    return None


# --------------------------------------------------------------------------- #
# Translation API
# --------------------------------------------------------------------------- #

def get_language():
    return _state["language"]


def get_language_name(code=None):
    code = code or _state["language"]
    for entry in LANGUAGES:
        if entry[0] == code:
            return entry[1]
    return code


def set_language(language, save=True, notify=True):
    """Switch the UI language; ``True`` when something actually changed."""
    code = _normalize_code(language)
    if not code:
        return False
    if code == _state["language"] and _state["catalog"].get(code) is not None:
        return False
    _apply_language(code, notify=notify)
    if save:
        save_language(code)
    if notify:
        retranslate_all()
        _emit_changed(code)
    return True


def _apply_language(code, notify=True):
    _state["language"] = code
    _load_catalog(code)
    _rebuild_reverse()
    _rebuild_patterns()


def _rebuild_reverse():
    catalog = _state["catalog"].get(_state["language"], {})
    reverse = {}
    for msgid, translated in (catalog.get("messages") or {}).items():
        if isinstance(translated, str) and translated and translated != msgid:
            reverse.setdefault(translated, msgid)
    for group in (catalog.get("contexts") or {}).values():
        if not isinstance(group, dict):
            continue
        for msgid, translated in group.items():
            if isinstance(translated, str) and translated and translated != msgid:
                reverse.setdefault(translated, msgid)
    _state["reverse"] = reverse


def translate(msgid, context=None, **variables):
    """Return ``msgid`` translated into the active language.

    Unknown strings are returned unchanged, so wrapping a string is always safe.
    Optional ``variables`` are substituted with :meth:`str.format` after lookup.
    """
    if not msgid or not isinstance(msgid, str):
        return msgid
    catalog = _state["catalog"].get(_state["language"])
    if catalog is None:
        catalog = _load_catalog(_state["language"])

    result = None
    if context:
        result = (catalog.get("contexts") or {}).get(context, {}).get(msgid)
    if result is None:
        result = (catalog.get("messages") or {}).get(msgid)
    if result is None:
        result = _match_pattern(msgid)
    if result is None:
        if _state["track_missing"] and _looks_translatable(msgid):
            _state["missing"][msgid] = _state["missing"].get(msgid, 0) + 1
        result = msgid

    if variables:
        try:
            return result.format(**variables)
        except Exception:
            return result
    return result


def _match_pattern(text):
    if not _state["patterns"]:
        return None
    candidates = _state["pattern_heads"].get(text[0], ())
    for head, (regex, translation, _template) in candidates:
        if text.startswith(head):
            match = regex.match(text)
            if match:
                return _fill(translation, match)
    candidates = _state["pattern_tails"].get(text[-1], ())
    for tail, (regex, translation, _template) in candidates:
        if text.endswith(tail):
            match = regex.match(text)
            if match:
                return _fill(translation, match)
    return None


def _fill(translation, match):
    try:
        return translation.format(*match.groups())
    except Exception:
        return translation


def _looks_translatable(text):
    stripped = text.strip()
    if not stripped or len(stripped) > 200:
        return False
    if not re.search(r"[A-Za-z]{3}", stripped):
        return False
    if re.search(r"[\ue000-\uf8ff]", stripped):
        return False
    return True


def format_translation(msgid, *args, **kwargs):
    """``_('Syncing {} colors...').format(n)`` in one call."""
    return translate(msgid).format(*args, **kwargs)


def ngettext(singular, plural, count, context=None):
    """Plural aware translation (Polish uses three forms)."""
    catalog = _state["catalog"].get(_state["language"], {})
    key = f"{singular}|{plural}"
    forms = (catalog.get("plurals") or {}).get(key)
    if isinstance(forms, list) and forms:
        index = _plural_index(_state["language"], count, len(forms))
        template = forms[index]
    else:
        template = singular if count == 1 else plural
    try:
        return template.format(count)
    except Exception:
        try:
            return template.replace("{}", str(count))
        except Exception:
            return template


def _plural_index(lang, count, forms):
    count = abs(int(count))
    if lang == "pl" and forms >= 3:
        if count == 1:
            return 0
        rest10 = count % 10
        rest100 = count % 100
        if 2 <= rest10 <= 4 and not (12 <= rest100 <= 14):
            return 1
        return 2
    return 0 if count == 1 else (forms - 1)


# short, gettext-ish aliases ------------------------------------------------- #

_ = translate
tr = translate
trf = format_translation
npgettext = ngettext


def t(msgid, context=None, **variables):
    """Alias kept for readability at call sites that already build text."""
    return translate(msgid, context, **variables)


_ci_cache = {"lang": None, "map": {}}


def translate_ci(text, context=None):
    """Case-insensitive exact lookup (``repair`` finds ``Repair``).

    Used for display-only translation of user data such as item titles, where
    the stored casing is arbitrary.
    """
    if not text:
        return text
    lang = _state["language"]
    if _ci_cache["lang"] != lang:
        messages = _state["catalog"].get(lang, {}).get("messages", {})
        _ci_cache["lang"] = lang
        _ci_cache["map"] = {k.casefold(): v for k, v in messages.items()}
    hit = _ci_cache["map"].get(text.casefold())
    return hit if hit is not None else text


def canonical(text):
    """Map a (possibly translated) UI string back to its English source text.

    Use it wherever the app compares widget text against an English literal::

        if i18n.canonical(button.text()) == "Close": ...
    """
    if not isinstance(text, str):
        return text
    return _state["reverse"].get(text, text)


def same(actual, msgid):
    """``True`` when ``actual`` is ``msgid`` in any language."""
    if not isinstance(actual, str):
        return False
    if actual == msgid:
        return True
    translated = translate(msgid)
    return actual == translated or canonical(actual) == msgid


def variants(msgid):
    """All known spellings of ``msgid`` (English + active translation)."""
    values = {msgid}
    translated = translate(msgid)
    if translated:
        values.add(translated)
    return values


def missing_report():
    return dict(sorted(_state["missing"].items(), key=lambda item: -item[1]))


# --------------------------------------------------------------------------- #
# Raw (never translated) widgets
# --------------------------------------------------------------------------- #

def raw(widget, text=None):
    """Mark ``widget`` as user-data driven; optionally set untranslatable text."""
    try:
        _raw_widgets.add(widget)
        _bindings.pop(widget, None)
        _custom_bindings.pop(widget, None)
    except TypeError:                                         # pragma: no cover
        pass
    if text is not None and widget is not None:
        try:
            _call_original(widget, "setText", text)
        except Exception:
            try:
                widget.setText(text)
            except Exception:
                pass
    return widget


def set_text_raw(widget, text, setter="setText"):
    """Set ``text`` on a display widget *without* translating it.

    Use for widgets that mix user data (file names, NSS titles) with captions:
    the value is shown verbatim and no live-retranslation binding is stored.
    """
    if widget is None:
        return widget
    try:
        _call_original(widget, setter, text)
    except Exception:                                         # pragma: no cover
        try:
            getattr(widget, setter)(text)
        except Exception:
            pass
    try:
        entries = _bindings.get(widget)
        if entries and setter in entries:
            del entries[setter]
    except Exception:
        pass
    return widget


def is_raw(widget):
    try:
        return widget in _raw_widgets
    except TypeError:                                         # pragma: no cover
        return False


def _bind(original, cls, instance):
    """Return a callable for a stored (sip) method descriptor."""
    getter = getattr(original, "__get__", None)
    if getter is None:                                        # pragma: no cover
        return lambda *a, **k: original(instance, *a, **k)
    return getter(instance, cls)


def _call_original(widget, method, *args):
    """Call the un-hooked Qt method so replays never recurse into the wrapper."""
    for cls in type(widget).__mro__:
        original = _originals.get((cls, method))
        if original is not None:
            try:
                return _bind(original, cls, widget)(*args)
            except TypeError:                                 # pragma: no cover
                continue
    return getattr(widget, method)(*args)


# --------------------------------------------------------------------------- #
# Explicit bindings (for widgets that paint their own text)
# --------------------------------------------------------------------------- #

def bind_text(widget, msgid, setter="setText", context=None):
    """Translate ``msgid`` now and remember how to re-apply it later."""
    if widget is None or not msgid:
        return widget
    try:
        entries = _bindings.setdefault(widget, {})
        entries[setter] = (msgid, context, (), ())
    except TypeError:                                         # pragma: no cover
        pass
    try:
        getattr(widget, setter)(translate(msgid, context))
    except Exception:
        pass
    return widget


def bind_custom(widget, apply_fn, msgid, context=None):
    """Register ``apply_fn(widget, translated_text)`` for live retranslation."""
    if widget is None or not msgid:
        return widget
    try:
        entries = _custom_bindings.setdefault(widget, [])
        entries.append((apply_fn, msgid, context))
    except TypeError:                                         # pragma: no cover
        pass
    try:
        apply_fn(widget, translate(msgid, context))
    except Exception as exc:          # a broken callback must not stay invisible
        warnings.warn(f"i18n.bind_custom callback failed for {msgid!r}: {exc!r}",
                      RuntimeWarning, stacklevel=2)
    return widget


def bind_transform(widget, msgid, transform, setter="setText", context=None):
    """Like :func:`bind_custom` but re-applies ``transform(translated_text)``.

    Used for labels that render an upper-cased / decorated variant of a string::

        i18n.bind_transform(title_lbl, "General", str.upper)
    """
    if widget is None or not msgid:
        return widget
    try:
        _call_original(widget, setter, transform(translate(msgid, context)))
    except Exception:
        try:
            getattr(widget, setter)(transform(translate(msgid, context)))
        except Exception:
            pass

    def apply(widget=widget, msgid=msgid, transform=transform, setter=setter, context=context):
        try:
            _call_original(widget, setter, transform(translate(msgid, context)))
        except Exception:
            pass

    try:
        _custom_bindings.setdefault(widget, []).append((lambda w, _t, fn=apply: fn(), msgid, context))
    except TypeError:                                         # pragma: no cover
        pass
    return widget


# widgets that recompute their own text (painted / derived) on language change
_refresh_callbacks = weakref.WeakKeyDictionary()


def register_refresh(widget, callback):
    """Call ``callback(widget)`` whenever the language changes.

    For widgets that derive their text at paint time (progress capsules, badges)
    instead of storing it with ``setText``.
    """
    if widget is None:
        return widget
    try:
        _refresh_callbacks.setdefault(widget, []).append(callback)
    except TypeError:                                         # pragma: no cover
        pass
    return widget


def retranslate_all():
    """Re-apply every remembered string (live language switch)."""
    for widget, entries in list(_bindings.items()):
        if is_raw(widget):
            continue
        for setter, (msgid, context, pre, post) in list(entries.items()):
            try:
                _call_original(widget, setter, *pre, translate(msgid, context), *post)
            except Exception:
                continue
            _refresh_geometry(widget)
    for widget, callbacks in list(_custom_bindings.items()):
        if is_raw(widget):
            continue
        for apply_fn, msgid, context in callbacks:
            try:
                apply_fn(widget, translate(msgid, context))
            except Exception as exc:
                warnings.warn(f"i18n retranslate failed for {msgid!r}: {exc!r}",
                              RuntimeWarning)
                continue
            _refresh_geometry(widget)
    for widget, callbacks in list(_refresh_callbacks.items()):
        for callback in callbacks:
            try:
                callback(widget)
            except Exception:
                continue
            _refresh_geometry(widget)
    _emit_changed(_state["language"], retranslate=False)


def _refresh_geometry(widget):
    """Repaint + re-measure a widget whose text just changed language."""
    for method in ("updateGeometry", "update"):
        callback = getattr(widget, method, None)
        if callback is None:
            continue
        try:
            callback()
        except Exception:
            continue


# --------------------------------------------------------------------------- #
# Qt integration
# --------------------------------------------------------------------------- #

def _signal():
    """Lazily created QObject exposing ``language_changed(str)``."""
    if _state["signal"] is not None:
        return _state["signal"]
    try:
        from PyQt5.QtCore import QObject, pyqtSignal

        class _I18nSignals(QObject):
            language_changed = pyqtSignal(str)

        _state["signal"] = _I18nSignals()
    except Exception:                                         # pragma: no cover
        _state["signal"] = None
    return _state["signal"]


def _emit_changed(code, retranslate=True):
    signal = _signal()
    if signal is None:
        return
    try:
        signal.language_changed.emit(code)
    except Exception:                                         # pragma: no cover
        pass


def connect(slot):
    """Subscribe to language changes (``slot(language_code)``)."""
    signal = _signal()
    if signal is None:
        return False
    try:
        signal.language_changed.connect(slot)
        return True
    except Exception:                                         # pragma: no cover
        return False


def disconnect(slot):
    signal = _state["signal"]
    if signal is None:
        return
    try:
        signal.language_changed.disconnect(slot)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Hook tables
# --------------------------------------------------------------------------- #
# Setter hooks: class -> [(method, index of the text argument after ``self``)]
SETTER_HOOKS = {
    "QLabel": [("setText", 0)],
    "QAbstractButton": [("setText", 0)],
    "QWidget": [("setWindowTitle", 0), ("setToolTip", 0), ("setStatusTip", 0),
                ("setWhatsThis", 0)],
    "QGroupBox": [("setTitle", 0)],
    "QLineEdit": [("setPlaceholderText", 0)],
    "QTextEdit": [("setPlaceholderText", 0)],
    "QPlainTextEdit": [("setPlaceholderText", 0)],
    "QTabWidget": [("setTabText", 1), ("addTab", 1), ("insertTab", 2)],
    "QTabBar": [("setTabText", 1), ("setTabToolTip", 1)],
    "QMessageBox": [("setInformativeText", 0), ("setDetailedText", 0)],
    "QProgressBar": [("setFormat", 0)],
    "QAction": [("setText", 0), ("setToolTip", 0), ("setStatusTip", 0),
                ("setWhatsThis", 0)],
}

# Constructor hooks: class -> (text argument positions, setter used for replay)
CTOR_HOOKS = {
    "QLabel": ((0,), "setText"),
    "QPushButton": ((0,), "setText"),
    "QCheckBox": ((0,), "setText"),
    "QRadioButton": ((0,), "setText"),
    "QToolButton": ((0,), "setText"),
    "QCommandLinkButton": ((0, 1), "setText"),
    "QGroupBox": ((0,), "setTitle"),
    "QAction": ((0, 1), "setText"),
}

# Static dialog helpers: class -> method -> argument positions to translate.
# Transient dialogs are not registered for live retranslation.
STATIC_HOOKS = {
    "QMessageBox": {
        "information": (1, 2), "warning": (1, 2), "critical": (1, 2),
        "question": (1, 2), "about": (1, 2),
    },
    "QInputDialog": {
        "getText": (1, 2), "getMultiLineText": (1, 2), "getInt": (1, 2),
        "getDouble": (1, 2), "getItem": (1, 2),
    },
    "QFileDialog": {
        "getOpenFileName": (1, 3), "getOpenFileNames": (1, 3),
        "getSaveFileName": (1, 3), "getExistingDirectory": (1,),
    },
}

# Classes that are intentionally never hooked because their text is *data*:
#   QLineEdit/QPlainTextEdit/QTextEdit  -> NSS content, paths, user input
#   QComboBox/QListWidget               -> currentText()/itemText() is read back
NOT_HOOKED = ("QLineEdit.setText", "QComboBox.addItem", "QPlainTextEdit.setPlainText",
              "QTextEdit.setPlainText", "QTextBrowser.setHtml")


def _resolve_class(class_name):
    for module_name in ("PyQt5.QtWidgets", "PyQt5.QtGui", "PyQt5.QtCore"):
        try:
            module = __import__(module_name, fromlist=[class_name])
        except Exception:                                     # pragma: no cover
            continue
        cls = getattr(module, class_name, None)
        if cls is not None:
            return cls
    return None


def _make_instance_wrapper(cls, method_name, arg_index, original):
    def wrapper(*args, **kwargs):
        try:
            if len(args) > arg_index + 1:
                value = args[arg_index + 1]
                if isinstance(value, str) and value:
                    widget = args[0]
                    if not is_raw(widget):
                        translated = translate(value)
                        # remember the binding even when the current language
                        # translates to the same text (e.g. built in English),
                        # otherwise a later switch can never reach this widget
                        _register(widget, method_name, value,
                                  tuple(args[1:arg_index + 1]),
                                  tuple(args[arg_index + 2:]), cls)
                        if translated != value:
                            args = list(args)
                            args[arg_index + 1] = translated
        except Exception:                                     # pragma: no cover
            pass
        return _bind(original, cls, args[0] if args else None)(*args[1:], **kwargs)

    wrapper.__name__ = method_name
    wrapper.__doc__ = original.__doc__
    wrapper._i18n_original = original
    return wrapper


def _make_ctor_wrapper(cls, positions, setter, original):
    def wrapper(self, *args, **kwargs):
        try:
            original(self, *args, **kwargs)
        except TypeError:                                     # pragma: no cover
            _bind(original, cls, self)(*args, **kwargs)
        try:
            if is_raw(self):
                return
            for position in positions:
                if position < len(args) and isinstance(args[position], str) and args[position]:
                    msgid = args[position]
                    translated = translate(msgid)
                    _bindings.setdefault(self, {})[setter] = (msgid, None, (), ())
                    if translated != msgid:
                        _call_original(self, setter, translated)
                    break
            text_kwarg = kwargs.get("text")
            if isinstance(text_kwarg, str) and text_kwarg:
                translated = translate(text_kwarg)
                _bindings.setdefault(self, {})[setter] = (text_kwarg, None, (), ())
                if translated != text_kwarg:
                    _call_original(self, setter, translated)
        except Exception:                                     # pragma: no cover
            pass

    wrapper.__name__ = "__init__"
    wrapper.__doc__ = original.__doc__
    wrapper._i18n_original = original
    return wrapper


def _register(widget, method_name, msgid, pre, post, cls):
    try:
        if is_raw(widget):
            return
        entries = _bindings.setdefault(widget, {})
        if method_name in ("addTab", "insertTab"):
            # replay through setTabText using the widget's live index
            child = pre[0] if pre else None
            setter = _originals.get((cls, "setTabText"))

            def apply_tab(widget=widget, child=child, msgid=msgid, setter=setter):
                if child is None or setter is None:
                    return
                index = widget.indexOf(child)
                if index >= 0:
                    setter(widget, index, translate(msgid))

            callbacks = _custom_bindings.setdefault(widget, [])
            callbacks.append((lambda w, _text, fn=apply_tab: fn(), msgid, None))
            return
        entries[method_name] = (msgid, None, pre, post)
    except TypeError:                                         # pragma: no cover
        pass


def _make_static_wrapper(cls, method_name, positions, original):
    def wrapper(*args, **kwargs):
        try:
            args = list(args)
            for position in positions:
                if len(args) > position and isinstance(args[position], str) and args[position]:
                    translated = translate(args[position])
                    if translated != args[position]:
                        args[position] = translated
        except Exception:                                     # pragma: no cover
            pass
        return _bind(original, cls, None)(*args, **kwargs)

    wrapper.__name__ = method_name
    wrapper.__doc__ = original.__doc__
    wrapper._i18n_original = original
    return wrapper


def _patch(cls, method_name, wrapper, original=None):
    """``setattr`` on a sip type, remembering the original for later replay."""
    try:
        if original is not None:
            _originals[(cls, method_name)] = original
        setattr(cls, method_name, wrapper)
        _state["hooked"].append(f"{cls.__name__}.{method_name}")
        return True
    except Exception as error:                                # pragma: no cover
        _state["failed_hooks"].append(f"{cls.__name__}.{method_name}: {error}")
        _originals.pop((cls, method_name), None)
        return False


def hook_report():
    """Diagnostic helper: what got hooked and what did not."""
    return {"hooked": list(_state["hooked"]), "failed": list(_state["failed_hooks"])}


def install_hooks():
    """Wrap the Qt display setters/constructors. Safe to call more than once."""
    if _state["hooks_installed"]:
        return True

    for class_name, methods in SETTER_HOOKS.items():
        cls = _resolve_class(class_name)
        if cls is None:
            continue
        for method_name, arg_index in methods:
            original = cls.__dict__.get(method_name)
            if original is None:
                for base in cls.__mro__[1:]:
                    if method_name in base.__dict__:
                        original = base.__dict__[method_name]
                        break
            if original is None or getattr(original, "_i18n_original", None):
                continue
            _patch(cls, method_name,
                   _make_instance_wrapper(cls, method_name, arg_index, original),
                   original)

    for class_name, (positions, setter) in CTOR_HOOKS.items():
        cls = _resolve_class(class_name)
        if cls is None:
            continue
        original = cls.__dict__.get("__init__") or getattr(cls, "__init__", None)
        if original is None or getattr(original, "_i18n_original", None):
            continue
        _patch(cls, "__init__",
               _make_ctor_wrapper(cls, positions, setter, original), original)

    for class_name, methods in STATIC_HOOKS.items():
        cls = _resolve_class(class_name)
        if cls is None:
            continue
        for method_name, positions in methods.items():
            original = cls.__dict__.get(method_name)
            if original is None or getattr(original, "_i18n_original", None):
                continue
            _originals[(cls, method_name)] = original
            _patch(cls, method_name,
                   _make_static_wrapper(cls, method_name, positions, original))

    _state["hooks_installed"] = True
    return True


def uninstall_hooks():
    for (cls, method_name), original in list(_originals.items()):
        try:
            setattr(cls, method_name, original)
        except Exception:                                     # pragma: no cover
            continue
    _originals.clear()
    _state["hooked"].clear()
    _state["hooks_installed"] = False


# --------------------------------------------------------------------------- #
# Bootstrapping helper used by launcher.pyw
# --------------------------------------------------------------------------- #

def setup(settings_path=None, language=None, install=True):
    """Configure + load catalogues + install Qt hooks. Returns active language."""
    configure(settings_path=settings_path, language=language)
    if install:
        install_hooks()
    return _state["language"]
