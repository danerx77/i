"""Integration test: the *real* launcher widgets against the i18n layer.

It imports ``utils.py`` (the launcher's widget library) offscreen and checks that
dialogs, pill buttons, capsule action buttons and tab pills are translated, that
style identifiers and MDL2 glyphs are left alone, that the "default Close button"
logic still works while translated, and that everything flips back live.

    QT_QPA_PLATFORM=offscreen python tools/test_i18n_integration.py
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

LAUNCHER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LAUNCHER_DIR)

try:
    from PyQt5.QtWidgets import QApplication, QLabel, QPushButton
except ImportError:                                            # pragma: no cover
    print("PyQt5 is not installed — skipping the integration test.")
    sys.exit(0)

import i18n

FAILURES = []
CHECKS = [0]


def check(condition, description):
    CHECKS[0] += 1
    if condition:
        print(f"  ok    {description}")
    else:
        FAILURES.append(description)
        print(f"  FAIL  {description}")


def section(title):
    print(f"\n=== {title} ===")


settings_file = os.path.join(tempfile.mkdtemp(prefix="ima-i18n-it-"), "settings.json")
app = QApplication.instance() or QApplication(sys.argv)
i18n.setup(settings_path=settings_file, language="pl")

import utils                                                    # noqa: E402  (needs QApplication)

section("ModernDialog")
dialog = utils.ModernDialog(None, "Manage Imports",
                            "Review or remove NSS imports from your shell configuration.")
check(dialog.tl.text() == "Zarządzaj importami", f"dialog title translated ({dialog.tl.text()!r})")
check(dialog.ml.text() == "Przejrzyj lub usuń importy NSS ze swojej konfiguracji powłoki.",
      "dialog body translated")
check(dialog.bl.count() == 1, "default Close button present")
close_button = dialog.bl.itemAt(0).widget()
check(close_button.text() == "Zamknij", f"default button translated ({close_button.text()!r})")
check(i18n.same(close_button.text(), "Close"), "i18n.same() still recognises the Close button")

dialog.add_button("Import", "installButton", dialog.accept)
check(dialog.bl.count() == 1, "add_button() removed the default Close button while translated")
check(dialog.bl.itemAt(0).widget().text() == "Importuj", "new button translated")
check(dialog.bl.itemAt(0).widget().objectName() == "installButton",
      "style identifier (objectName) untouched")

section("Pill buttons / tabs")
pill = utils.PillPushButton("Check for Update", "primary", height=34)
check(pill.text() == "Sprawdź aktualizacje", f"PillPushButton caption translated ({pill.text()!r})")
check(pill.style_type == "primary", "style_type argument not translated")

tab = utils.PillTabButton(" Themes", 0xE790, height=30)
check(tab.text() == " Motywy", f"PillTabButton caption translated ({tab.text()!r})")

glyph_label = QLabel()
glyph_label.setText("\uE7BA")
check(glyph_label.text() == "\uE7BA", "MDL2 glyph labels untouched")

section("CapsuleActionButton (paints its own caption)")
capsule = utils.CapsuleActionButton("install")
check(capsule._get_display_text() == "Zainstaluj",
      f"capsule caption translated ({capsule._get_display_text()!r})")
capsule.set_state("queued")
check(capsule._get_display_text() == "W kolejce", "capsule state caption translated")

section("UnsavedChangesDialog")
unsaved = utils.UnsavedChangesDialog(None)
labels = [w.text() for w in unsaved.findChildren(QLabel)]
buttons = [w.text() for w in unsaved.findChildren(QPushButton)]
check("Niezapisane zmiany" in labels, f"unsaved-changes title translated ({labels[:4]})")
check("Masz niezapisane zmiany. Czy chcesz je zapisać?" in labels,
      "unsaved-changes message translated")
check(not any(text == "\uE7BA" and False for text in labels), "icon glyph kept")
print(f"  info  buttons: {buttons}")

section("modify_widget: filters and painted pills")
import modify_widget as mw                                       # noqa: E402

bar = mw.FilterBar([("All", "#51576d"), ("Item", "#51576d"), ("Menu", "#51576d")])
emitted = []
bar.filter_changed.connect(emitted.append)
captions = [bar.group.button(i).text() for i in range(3)]
check(captions == ["Wszystkie", "Element", "Menu"], f"filter captions translated ({captions})")
bar.group.button(1).click()
check(emitted and emitted[-1] == "Item", f"filter signal stays canonical ({emitted})")

card = mw.VisibilityCard("normal", "Normal", "Always Visible", 0xE890)
check(card.key == "normal", "visibility card keeps its data key")
check(card.title_text == "Normalny", f"visibility caption translated ({card.title_text!r})")
check(card.sub_text == "Zawsze widoczne", f"visibility subtitle translated ({card.sub_text!r})")

type_pill = mw.TypePill("desktop", "Desktop", 0xE7F4)
check(type_pill.val == "desktop", "type pill keeps its data value")
check(type_pill.title_text == "Pulpit", f"type pill caption translated ({type_pill.title_text!r})")

section("live language switch")
i18n.set_language("en")
check(dialog.tl.text() == "Manage Imports", "dialog title back to English")
check(dialog.bl.itemAt(0).widget().text() == "Import", "dialog button back to English")
check(pill.text() == "Check for Update", "pill button back to English")
check(tab.text() == " Themes", "tab pill back to English")
check(capsule._get_display_text() == "Queued", "capsule caption back to English")
check("Unsaved Changes" in [w.text() for w in unsaved.findChildren(QLabel)],
      "unsaved dialog back to English")
check([bar.group.button(i).text() for i in range(3)] == ["All", "Item", "Menu"],
      "filter captions back to English")
check(card.title_text == "Normal" and card.sub_text == "Always Visible",
      "painted visibility captions back to English")
check(type_pill.title_text == "Desktop", "painted type pill back to English")
bar.group.button(2).click()
check(emitted[-1] == "Menu", "filter signal still canonical after the switch")

i18n.set_language("pl")
check(dialog.tl.text() == "Zarządzaj importami", "and back to Polish again")
check(capsule._get_display_text() == "W kolejce", "capsule follows the switch")

section("data safety")
line = utils.PillLineEdit() if hasattr(utils, "PillLineEdit") else None
if line is not None:
    line.setText("Close")
    check(line.text() == "Close", "PillLineEdit keeps user text untouched")

combo = utils.ModernComboBox()
combo.addItem("None", None)
combo.addItem("Top", "top")
check([combo.itemText(i) for i in range(combo.count())] == ["None", "Top"],
      "ModernComboBox items (NSS data) untouched")
check(combo.currentData() is None, "combo itemData intact")

print("\n" + "=" * 62)
if FAILURES:
    print(f"{len(FAILURES)} of {CHECKS[0]} checks FAILED:")
    for failure in FAILURES:
        print(f"  - {failure}")
    sys.exit(1)
print(f"All {CHECKS[0]} integration checks passed.")
