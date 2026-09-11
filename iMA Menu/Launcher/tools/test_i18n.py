"""Headless test-suite for the launcher i18n layer.

Run it with::

    python tools/test_i18n.py            # Windows / any machine with PyQt5
    QT_QPA_PLATFORM=offscreen python tools/test_i18n.py

It verifies the catalogues, the translation helpers and — most importantly —
that the Qt hooks translate display text, never touch data bearing widgets and
survive a live language switch in both directions.
"""
import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

LAUNCHER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LAUNCHER_DIR)

from PyQt5.QtWidgets import (QApplication, QLabel, QPushButton, QWidget, QLineEdit,   # noqa: E402
                             QComboBox, QGroupBox, QTabWidget, QPlainTextEdit,
                             QCheckBox, QToolButton)

import i18n                                                                            # noqa: E402

FAILURES = []
CHECKS = [0]


def check(condition, description):
    CHECKS[0] += 1
    if not condition:
        FAILURES.append(description)
        print(f"  FAIL  {description}")
    else:
        print(f"  ok    {description}")


def section(title):
    print(f"\n=== {title} ===")


# --------------------------------------------------------------------------- #
section("catalogues")
locales = os.path.join(LAUNCHER_DIR, "locales")
en = json.load(open(os.path.join(locales, "en.json"), encoding="utf-8"))
pl = json.load(open(os.path.join(locales, "pl.json"), encoding="utf-8"))

check(isinstance(en.get("messages"), dict) and len(en["messages"]) > 300,
      f"en.json has a message catalogue ({len(en.get('messages', {}))} entries)")
check(isinstance(pl.get("messages"), dict) and len(pl["messages"]) > 300,
      f"pl.json has a message catalogue ({len(pl.get('messages', {}))} entries)")
missing_in_en = [k for k in pl["messages"] if k not in en["messages"]]
check(not missing_in_en, f"every Polish key exists in en.json (offenders: {missing_in_en[:3]})")
empty = [k for k, v in pl["messages"].items() if not str(v).strip()]
check(not empty, f"no empty Polish translations (offenders: {empty[:3]})")
identity = [k for k, v in en["messages"].items() if v != k]
check(not identity, "en.json is the identity catalogue (source of truth)")
bad_patterns = [k for k in pl.get("patterns", {}) if "{}" not in k]
check(not bad_patterns, f"all Polish patterns keep their placeholders (offenders: {bad_patterns[:3]})")
same_pl = sum(1 for k, v in pl["messages"].items() if k == v)
print(f"  info  {same_pl} entries are intentionally identical in Polish (brands, 'OK', 'iMA Menu', ...)")

# --------------------------------------------------------------------------- #
section("translation helpers")
settings_file = os.path.join(tempfile.mkdtemp(prefix="ima-i18n-"), "settings.json")
i18n.setup(settings_path=settings_file, language="en")
check(i18n.get_language() == "en", "defaults to English")
check(i18n._("Settings") == "Settings", "English passthrough")
check(i18n.translate("Settings") is i18n._("Settings"), "translate() and _() agree")

i18n.set_language("pl")
check(i18n.get_language() == "pl", "switch to Polish")
check(i18n._("Settings") == "Ustawienia", "exact translation")
check(i18n._("Plugins") == "Wtyczki", "nav label translation")
check(i18n._("Totally unknown string") == "Totally unknown string", "unknown strings pass through")
check(i18n._("None", "separator") == "Brak", "contextual translation")
check(i18n._("Syncing 12 colors...") == "Synchronizowanie kolorów: 12…", "pattern translation")
check(i18n.ngettext("{} item", "{} items", 1) == "1 element", "Polish plural: one")
check(i18n.ngettext("{} item", "{} items", 3) == "3 elementy", "Polish plural: few")
check(i18n.ngettext("{} item", "{} items", 25) == "25 elementów", "Polish plural: many")
check(i18n.ngettext("{} file", "{} files", 3) == "3 pliki", "plural form few (files)")
check(i18n.canonical("Ustawienia") == "Settings", "canonical() reverse lookup")
check(i18n.same("Ustawienia", "Settings"), "same() compares across languages")
check(i18n.same("Settings", "Settings"), "same() accepts the source text")
check(json.load(open(settings_file, encoding="utf-8")).get("language") == "pl",
      "language is persisted to settings.json")

# --------------------------------------------------------------------------- #
section("Qt hooks (display text)")
app = QApplication.instance() or QApplication(sys.argv)
i18n.install_hooks()

window = QWidget()
window.setWindowTitle("Settings")
label = QLabel("Plugins")
button = QPushButton("Close")
checkbox = QCheckBox("Bold")
tool = QToolButton()
tool.setText("Apply")
tool.setToolTip("Apply Changes")
group = QGroupBox("Theme Editor")
line_edit = QLineEdit()
line_edit.setPlaceholderText("Search items/menus...")
tabs = QTabWidget()
child = QWidget()
tabs.addTab(child, "My Themes")
tabs.setTabText(0, "Custom Themes")

check(window.windowTitle() == "Ustawienia", "setWindowTitle translated")
check(label.text() == "Wtyczki", "QLabel constructor text translated")
check(button.text() == "Zamknij", "QPushButton constructor text translated")
check(checkbox.text() == "Pogrubienie", "QCheckBox constructor text translated")
check(tool.text() == "Zastosuj", "setText translated")
check(tool.toolTip() == "Zastosuj zmiany", "setToolTip translated")
check(group.title() == "Edytor motywu", "QGroupBox title translated")
check(line_edit.placeholderText() == "Szukaj elementów/menu…", "placeholder translated")
check(tabs.tabText(0) == "Własne motywy", "setTabText translated")

label.setText("Syncing 5 colors...")
check(label.text() == "Synchronizowanie kolorów: 5…", "setText pattern translation")

# --------------------------------------------------------------------------- #
section("data bearing widgets stay untouched")
data_line = QLineEdit()
data_line.setText("Close")
combo = QComboBox()
combo.addItem("None")
combo.addItem("Top")
editor = QPlainTextEdit()
editor.setPlainText("Settings\nPlugins")

check(data_line.text() == "Close", "QLineEdit text is never translated")
check(combo.itemText(0) == "None" and combo.itemText(1) == "Top",
      "QComboBox items are never translated")
check(editor.toPlainText() == "Settings\nPlugins", "code editors are never translated")

glyph_button = QPushButton("\uE921")
check(glyph_button.text() == "\uE921", "MDL2 glyph captions are untouched")

# --------------------------------------------------------------------------- #
section("live retranslation")
raw_label = QLabel()
i18n.raw(raw_label, "Plugins")
check(raw_label.text() == "Plugins", "raw() widgets are never translated")

mixed = QLabel()
i18n.set_text_raw(mixed, "None")
check(mixed.text() == "None", "set_text_raw() bypasses the catalogue")

painted = {"text": None}


class FakePaintedWidget(QWidget):
    def apply(self, translated):
        painted["text"] = translated


custom = FakePaintedWidget()
i18n.bind_custom(custom, FakePaintedWidget.apply, "Settings")
check(painted["text"] == "Ustawienia", "bind_custom applies immediately")

upper_label = QLabel("")
i18n.bind_transform(upper_label, "General", str.upper)
check(upper_label.text() == "OGÓLNE", "bind_transform applies the transform")

refreshed = []
refresh_widget = QWidget()
i18n.register_refresh(refresh_widget, lambda w: refreshed.append(True))

i18n.set_language("en")
check(label.text() == "Syncing 5 colors...", "dynamic pattern re-applied in English")
check(button.text() == "Close", "button retranslated to English")
check(window.windowTitle() == "Settings", "window title retranslated to English")
check(group.title() == "Theme Editor", "group title retranslated to English")
check(tabs.tabText(0) == "Custom Themes", "tab text retranslated to English")
check(painted["text"] == "Settings", "custom binding retranslated")
check(upper_label.text() == "GENERAL", "transform binding retranslated")
check(refreshed and len(refreshed) == 1, "register_refresh callback fired once")
check(raw_label.text() == "Plugins", "raw widget untouched by the switch")

i18n.set_language("pl")
check(button.text() == "Zamknij", "button retranslated back to Polish")
check(painted["text"] == "Ustawienia", "custom binding retranslated back")
check(refreshed and len(refreshed) == 2, "refresh callback fired again")

# --------------------------------------------------------------------------- #
section("app level invariants")
# ModernDialog.add_button() detects its default button by caption
close_button = QPushButton("Close")
check(i18n.same(close_button.text(), "Close"),
      "'Close' detection keeps working while translated")
# menu_builder filter tags keep their canonical filter value
filter_tag = QPushButton("All")
check(i18n.canonical(filter_tag.text()) == "All",
      "filter tag value stays canonical while translated")

hook_report = i18n.hook_report()
check(not hook_report["failed"], f"all Qt hooks installed (failed: {hook_report['failed']})")
print(f"  info  hooked methods: {len(hook_report['hooked'])}")

# --------------------------------------------------------------------------- #
print("\n" + "=" * 62)
if FAILURES:
    print(f"{len(FAILURES)} of {CHECKS[0]} checks FAILED:")
    for failure in FAILURES:
        print(f"  - {failure}")
    sys.exit(1)
print(f"All {CHECKS[0]} checks passed.")
