"""Build the launcher translation catalogues (``locales/en.json`` + ``locales/pl.json``).

The English catalogue is the source of truth: it lists every string the UI can
show.  The Polish catalogue holds the translations; anything missing there falls
back to English at runtime (see ``i18n.py``).

Run ``python tools/build_catalog.py`` after editing this file, then
``python tools/i18n_extract.py --stats`` to check coverage.
"""
import json
import os
import re
import sys

LAUNCHER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALES_DIR = os.path.join(LAUNCHER_DIR, "locales")
sys.path.insert(0, LAUNCHER_DIR)

CATALOG_VERSION = 1

# --------------------------------------------------------------------------- #
# Strings that must stay in English because they are *data*, not UI copy:
# Windows registry scheme names, NSS tokens, combo values that are read back
# with currentText(), font names, log lines parsed by nss_error_monitor, ...
# --------------------------------------------------------------------------- #
EXCLUDE = {
    # --- backend modules (github_client.py / cloud_sync.py): URLs, HTTP headers
    #     and developer-facing assertions must never be translated -----------
    "Content-type", "text/html; charset=utf-8", "download_file() needs a URL",
    "{}/rate_limit", "{}/repos/{}/branches/{}", "{}/repos/{}/git/commits/{}",
    "{}/{}?alt=media", "{}/{}?uploadType=media", "{}?uploadType=multipart",

    # --- Windows cursor scheme roles / registry values ---------------------
    "Alternate Select", "AppStarting", "Arrow", "Busy", "Crosshair", "Hand",
    "Handwriting", "Help", "Help Select", "IBeam", "Link Select",
    "Location Select", "Normal Select", "NWPen", "Person", "Person Select",
    "Precision Select", "SizeAll", "SizeNESW", "SizeNS", "SizeNWSE", "SizeWE",
    "Text Select", "UpArrow", "Wait", "Move", "Pin", "Recycle", "Unavailable",
    "Vertical Resize", "Horizontal Resize", "Diagonal Resize 1",
    "Diagonal Resize 2", "Windows Aero", "Windows Default",
    "Windows Default (system scheme)", "Scheme Source",
    # --- combo values read back through currentText()/itemText() -----------
    "None", "Shift", "Control", "Left Mouse", "Main", "Options", "Top",
    "Middle", "Bottom", "Both", "Line", "Space", "Always Visible", "Hidden",
    "Hidden Everywhere", "Part Hidden", "In Right-Click ONLY", "Shift Key Only",
    "Control Key Only", "Left Mouse Only", "Caps Lock Only", "Caps", "Capslock",
    "Ctrl", "Alt", "Left Click", "Right-Click", "Shift + Right-Click",
    "Ctrl + Right-Click", "Left + Right-Click", "Left Mouse Only",
    "Windows Default (system scheme)",
    # --- fonts -------------------------------------------------------------
    "Arial", "Calibri", "Cambria", "Century Gothic", "Comic Sans MS",
    "Consolas", "Courier New", "Franklin Gothic Medium", "Garamond", "Georgia",
    "Helvetica", "Impact", "Inter", "Segoe Fluent Icons", "Segoe MDL2 Assets",
    "Segoe UI", "Segoe UI Variable Display", "Segoe UI Variable Text",
    "Tahoma", "Times New Roman", "Trebuchet MS", "Verdana",
    "Nilesoft Shell Symbol",
    # --- identifiers / plugin data / log lines -----------------------------
    "AccentFlags", "AccentState", "AnimationId", "Attribute", "GradientColor",
    "SizeOfData", "ExecutablePath", "InstallLocation", "Shell_TrayWnd",
    "Nilesoft.Shell", "Nilesoft", "Nilesoft Shell", "ColorPickerWidget",
    "QAbstractButton", "InterruptedError", "DETAILS.md", "README.md",
    "Launcher", "iMA Switcher", "Data", "NUMBER", "STRING", "RIGHT", "LEFT",
    "VISIBILITY", "Riot Client",
    "Riot Games", "Valorant", "Modern Valorant & Riot Games Account Switcher",
    "Google User", "Shell Core", "SystemRoot", "Environment", "Assets",
    "invalid import file", "Could not safely auto-fix",
    "Healed structural errors", "Fixed line {line_num}",
    "Line {line_num} out of range", "Custom local plugin",
    # --- raw f-string sources (the '{}' template variants are the real keys)
    "Could not find folder for plugin '{self.plugin_name}' in repository archive.",
    "No files extracted for plugin '{self.plugin_name}' from repository archive.",
    "Icon: '{i2 or '(none)'}' ➔ '{i1 or '(none)'}'",
    "ID ({self.id_text})", "Logged in as {user_email or user_name}",
    "Logged in as {user_name} ({user_email})", "Match Mode: {self._mode.title()} (Click to change)",
    "Opacity ({self.opacity_val}%)", "Pos: {pos.title()}", "Pos: {props['pos']}",
    "Save setup failed: {str(e)}", "Sep: {sep.title()}",
    "Syncing {mode.title()} colors...", "Syncing {mode.title()} colors ({v}/{t})...",
    "Syncing {v}/{t}", "Target: {typ.title()}",
    "Theme changes committed: {self.selected_theme}",
    "Theme applied (preview): {theme_name}",
    "↳ In: {self.item_data.get('parent')}", "↳ In: {self.parent_title}",
    "↳ In: {clean_m}",
    "⚠️ Draft Item ({self.raw_data.get('error_msg')}) — Commented out to prevent syntax errors.",
    "Edit {self.data.get('type', 'Item').title()}",
    "Failed to save SVG: {str(e)}", "Line {err.line}, col {err.column}: {err.message}",
    "Draft: {err_msg}", "Vis: {v}", "Source: {src}", "Target: {target}",
    "Menu ({children_count})", "Pipeline ({steps_cnt})",
    "All {props['type'].title()}s", "Color for Glyph {i+1}", "Color {i+1}",
    "Added {directory} to system PATH.", "Error adding {directory} to PATH: {e}",
    "Download cancelled ({downloaded}/{total} saved, incomplete files cleaned up)",
    "Downloaded {count} new/updated themes", "Downloaded {downloaded} cursors ({skipped} up to date, {errors} errors): {first_err}",
    "Downloading cursors ({current}/{total}): {msg}",
    "Click to cancel download (0/{total_count})",
    "Click to cancel download ({current}/{total})\nCurrently: {current_theme}",
    "✕  Cancel (0/{total_count})", "✕  Cancel ({current}/{total})",
    "All cursors ready! ({downloaded} downloaded, {skipped} up to date)",
    "Submenu Folder • {children_count} items nested inside ({state_desc})",
    "Are you sure you want to delete '{display}'?",
    "Are you sure you want to delete '{title}'?",
    "The theme '{new_theme_name}' already exists. Overwrite?",
    "Updated '{new_theme_name}' successfully!", "Updated {theme_name}",
    "Edit Theme: {theme_name}", "File '{clean_name}' already exists.",
    "Filtering {fname}... ({processed + 1}/{total})",
    "Failed to write file '{rel_f}' (0 bytes)", "Failed {th_name}",
    "{} up to date", "Error for {plugin_name}",
    "Operation error for {plugin_name}: {error_message}",
    "Authentication failed: {message}", "Save failed: {err}",
    "Error checking plugins: {e}", "Error fetching details: {e}",
    "Network error: {e}", "Dependency {dep_name} not found in any release assets.",
    "Error downloading dependency {dep_name}: {e}",
    "Failed to download repository archive: {last_error}",
    "Could not save theme: {e}", "Could not update theme: {e}",
    "Error applying theme: {e}", "Error reverting theme content: {e}",
    "Error reverting theme file from source: {e}", "Failed to load theme: {e}",
    "Failed to save changes to {fp}: {e}", "Async Write Error: {err}",
    "Error in _write_temporary_theme: {e}", "Error in save_theme: {e}",
    "Git trees resolution fallback: {e}", "IPC Error: {e}",
    "Auto-upgrade shell core error: {e}", "Error committing tinted icon {f}: {e}",
    "Error generating fallback icon for {plugin_name}: {e}",
    "Error opening root folder: {e}", "Error starting error monitor: {e}",
    "Error syncing tools menu: {error}", "Error updating {nss_file_path}: {e}",
    "ERROR: Syntax error in {filename}:{line} - {message}",
    "Error: {error_message}", "Error: {error}", "Failed to auto-launch {launch_file_path}: {e}",
    "Failed to write {filepath}: Invalid NSS syntax detected. Write aborted to prevent corruption.",
    "A new release <b>v{latest_version}</b> was found, but no installer binary is attached to the release yet.",
    "Re-install iMA Menu Launcher <b>v{latest_version}</b> now?",
    "You are running the latest version <b>v{VERSION}</b>.",
    "Could not launch updater:<br>{launch_error}",
    "An error occurred while downloading the update:<br>{result}",
    "<font color='red'>Error: {}</font>",
    "Successfully logged in as {message}",
    "Rule for '{}' already exists — loaded existing settings to edit.",
    "'{}' is in Options section — loaded existing settings to edit.",
    "'{}' is in Shift section — loaded existing settings to edit.",
    "'{}' is in Remove/Hide section — loaded existing settings to edit.",
    "Manifest response is not a valid list", "No files in theme manifest",
    "Cancelled by user", "Cancelling download and cleaning up temporary files...",
    "Cursor catalog is still loading, please wait a moment...",
    "Download cancelled", "Downloaded file is invalid or corrupted",
    "Downloaded file is not a valid binary asset", "Network error",
    "V {VERSION}",
    # --- docstrings / developer comments -----------------------------------
    "A single configurable action step in a multi-action pipeline.",
    "Called when user switches to Add tab.",
    "Clickable pill chip for quick presets (args, cmd, types, etc.).",
    "Clip window to rounded rect at OS level when not maximized.",
    "Commits the currently selected cursor theme.",
    "Compiles pipeline steps into safe, chained cmd and args.",
    "Cursors apply immediately on pick and do not require revert on discard.",
    "Ensures enough cards are rendered to fill the viewport and create a scrollbar even on 4K/maximized windows.",
    "Fast, cached path normalization.",
    "Finds item in self.items whose line in file matches error line.",
    "Force a complete reload of all UI components from disk files. ",
    "Generates live NSS code string and reflects it into the code edit.",
    "Get absolute path to resource, works for dev and for PyInstaller ",
    "Processes online preview thumbnail downloads concurrently in background daemon threads with zero UI freezing.",
    "Resolves role -> rel_file for an online theme file list.",
    "Returns a QIcon containing a vector 5-pointed star.",
    "Returns pre-cached QImage for theme and role, checking memory cache, disk cache and embedded atlas.",
    "Returns the chosen parent menu title or None for top level.",
    "Safely removes an item from self.items or any menu's children at any depth.",
    "Serializes current items and writes safely to current file with log monitoring.",
    "Sleek modal dialog for delete/action confirmation matching launcher theme.",
    "Thread-safe worker for downloading cursor themes using python native daemon threads.",
    "High-quality vector anti-aliased radius option button.",
    "Segmented pill tab button with crisp anti-aliased vector rendering.",
    "Vector anti-aliased circular upload button.",
    "Vector anti-aliased pill-shaped search line edit.",
    "Vector anti-aliased preview container with exactly ONE smooth outline.",
    "If running in frozen onefile mode, sync extracted files to local _internal folder for fast caching.",
    "Anti-aliased vector checkbox with smooth 1.5px border and checkmark.",
    "(Default)", "(none)", "(no icon)",
    "Horizontal separator line between items in the right-click menu.",
    "Horizontal separator line",
    "You can edit it anytime to fix the syntax and re-activate it.",
    "Modified", "Moved", "Renamed", "Visible In...", "Ctrl+Y", "Ctrl+Z",
    "Ctrl+Shift",
    "-NoExit -Command \"Set-Location -LiteralPath '@sel.path'\"",
    "command.copy(sel(true, \"\\n\"))", "command.restart_explorer",
    "Admin", "App", "Args", "After", "Before", "Item", "Submenu", "Path",
    "Position", "Visibility", "Separator", "Title", "Files", "Folders",
    "Icons", "Find Title", "New Title", "No Title", "Unknown Item", "Unnamed",
    "None selected", "Target ID", "Icon Path", "In Menu", "Move to",
    "Show in", "Global Rule", "Modify ID: ", "Modify: ",
    "Draft (Commented)", "Drafts", "All", "Contains", "Exact", "Starts with",
    "Ends with", "Normal", "Custom", "Auto", "Backup", "Message",
    "Noise", "Disabled", "Hue", "Saturation", "Lightness", "Shadow",
    "Colors", "Dimensions", "General", "Borders", "Typography", "Icons",
    "Python", "PowerShell", "This PC", "Desktop", "Taskbar", "Recycle",
    "Tools", "Fav", "Favorited", "Local", "Store", "Explore",
}

# --------------------------------------------------------------------------- #
# Polish translations — exact strings
# --------------------------------------------------------------------------- #
PL = {
    # ---- navigation / window -------------------------------------------- #
    "iMA Menu": "iMA Menu",
    "Plugins": "Wtyczki",
    "Modify": "Modyfikuj",
    "Theme": "Motyw",
    "Settings": "Ustawienia",
    "Refresh": "Odśwież",
    "Minimize": "Zminimalizuj",
    "Maximize": "Zmaksymalizuj",
    "Restore": "Przywróć",
    "Close": "Zamknij",
    "Open Plugin Directory": "Otwórz katalog wtyczki",
    "Loading plugins...": "Ładowanie wtyczek…",
    "No description available.": "Brak opisu.",
    "Search items/menus...": "Szukaj elementów/menu…",
    "Search custom rules...": "Szukaj własnych reguł…",
    "Search glyphs or keywords...": "Szukaj glifów lub słów kluczowych…",
    "Search System IDs...": "Szukaj identyfikatorów systemowych…",

    # ---- common buttons -------------------------------------------------- #
    "OK": "OK",
    "Cancel": "Anuluj",
    "Apply": "Zastosuj",
    "Apply Changes": "Zastosuj zmiany",
    "Save": "Zapisz",
    "Save Changes": "Zapisz zmiany",
    "Save Rule": "Zapisz regułę",
    "Delete": "Usuń",
    "Delete Item": "Usuń element",
    "Delete Menu": "Usuń menu",
    "Rename": "Zmień nazwę",
    "Reset": "Resetuj",
    "Reset to Default": "Przywróć domyślne",
    "Clear": "Wyczyść",
    "Add": "Dodaj",
    "Add New": "Dodaj nowy",
    "Add Icon": "Dodaj ikonę",
    "Add Theme": "Dodaj motyw",
    "Edit": "Edytuj",
    "Edit Item": "Edytuj element",
    "Editor": "Edytor",
    "Import": "Importuj",
    "Overwrite": "Nadpisz",
    "Yes": "Tak",
    "No": "Nie",
    "Later": "Później",
    "Got It": "Jasne",
    "Skip All": "Pomiń wszystkie",
    "Done": "Gotowe",
    "Install": "Zainstaluj",
    "Installed": "Zainstalowano",
    "Installing": "Instalowanie",
    "Installing...": "Instalowanie…",
    "Uninstall": "Odinstaluj",
    "Update": "Aktualizuj",
    "Update Now": "Aktualizuj teraz",
    "Up to Date": "Aktualne",
    "Queued": "W kolejce",
    "Queued...": "W kolejce…",
    "Checking...": "Sprawdzanie…",
    "Downloading...": "Pobieranie…",
    "Stopping...": "Zatrzymywanie…",
    "Syncing...": "Synchronizacja…",
    "Cancelled": "Anulowano",
    "Login": "Zaloguj",
    "Log out": "Wyloguj",
    "Re-install": "Zainstaluj ponownie",
    "Re-install Now": "Zainstaluj ponownie",
    "Re-install Launcher": "Zainstaluj launcher ponownie",
    "Open in Editor": "Otwórz w edytorze",
    "Copy Path": "Kopiuj ścieżkę",
    "Move Up": "Przesuń w górę",
    "Move Down": "Przesuń w dół",
    "Move Out of Menu (To Top Level)": "Przenieś poza menu (na najwyższy poziom)",
    "Collapse Submenu": "Zwiń podmenu",
    "Expand Submenu": "Rozwiń podmenu",
    "Activate / Publish": "Aktywuj / opublikuj",
    "Save as Draft (Comment out)": "Zapisz jako szkic (zakomentuj)",
    "Delete to Recycle Bin": "Usuń do Kosza",
    "Delete Local Plugin": "Usuń lokalną wtyczkę",
    "Unhide": "Odkryj",
    "Hide": "Ukryj",
    "Sync Selected": "Synchronizuj zaznaczone",
    "Sync Colors": "Synchronizuj kolory",
    "Sync with Theme": "Synchronizuj z motywem",
    "Sync with Global Theme": "Synchronizuj z motywem globalnym",
    "Sync with Theme (Remove custom colors)": "Synchronizuj z motywem (usuń własne kolory)",
    "Apply Tint Color": "Zastosuj kolor barwienia",
    "Configure Local Icon": "Skonfiguruj lokalną ikonę",
    "Pick color from screen": "Pobierz kolor z ekranu",
    "Remove Icon": "Usuń ikonę",
    "Upload Custom Image/Icon": "Wgraj własny obraz/ikonę",
    "Add to Favorites": "Dodaj do ulubionych",
    "Download Cursor Pack": "Pobierz paczkę kursorów",
    "Download all cursor packs locally": "Pobierz wszystkie paczki kursorów lokalnie",
    "Uninstall Cursor": "Odinstaluj kursory",
    "Click to Cancel": "Kliknij, aby anulować",
    "Click to Browse Glyphs / Upload Icon": "Kliknij, aby przeglądać glify / wgrać ikonę",
    "Inherit Icon from Target Command/File": "Przejmij ikonę z polecenia/pliku docelowego",
    "Browse System IDs": "Przeglądaj identyfikatory systemowe",

    # ---- settings page --------------------------------------------------- #
    "Check for Update": "Sprawdź aktualizacje",
    "Auto Update Plugins": "Automatyczna aktualizacja wtyczek",
    "Automatically install updates on startup": "Automatycznie instaluj aktualizacje przy starcie",
    "Auto Check Updates": "Automatyczne sprawdzanie aktualizacji",
    "Show notification when updates are available": "Pokaż powiadomienie, gdy dostępne są aktualizacje",
    "Import NSS Files": "Importuj pliki NSS",
    "Copy external files to imports and shell.nss": "Kopiuj zewnętrzne pliki do imports i shell.nss",
    "Manage Imports": "Zarządzaj importami",
    "Review or remove NSS imports from your shell configuration.":
        "Przejrzyj lub usuń importy NSS ze swojej konfiguracji powłoki.",
    "No imports found.": "Nie znaleziono importów.",
    "Google Drive Sync": "Synchronizacja Google Drive",
    "Not logged in": "Niezalogowano",
    "Google Account Profile": "Profil konta Google",
    "Language": "Język",
    "Interface language": "Język interfejsu",
    "Select NSS Files": "Wybierz pliki NSS",
    "NSS Files (*.nss)": "Pliki NSS (*.nss)",
    "All Files (*.*)": "Wszystkie pliki (*.*)",
    "File Conflict": "Konflikt plików",
    "New name:": "Nowa nazwa:",
    "Success": "Sukces",
    "Selected NSS files imported.": "Wybrane pliki NSS zostały zaimportowane.",
    "Error": "Błąd",
    "Warning": "Ostrzeżenie",
    "Information": "Informacja",

    # ---- update flow ----------------------------------------------------- #
    "Update Available": "Dostępna aktualizacja",
    "Update Error": "Błąd aktualizacji",
    "Update Required": "Wymagana aktualizacja",
    "Downloading Update": "Pobieranie aktualizacji",
    "Download Failed": "Pobieranie nie powiodło się",
    "Please wait while the new version is being downloaded...":
        "Poczekaj, trwa pobieranie nowej wersji…",
    "Shell Core Update Required": "Wymagana aktualizacja Shell Core",
    "Update Shell Core": "Aktualizuj Shell Core",
    "Core Updated": "Shell Core zaktualizowany",
    "<b>Shell Core v2.0.0.2</b> has been installed successfully!":
        "<b>Shell Core v2.0.0.2</b> został zainstalowany pomyślnie!",
    "Would you like to update the Shell Core now?<br>":
        "Czy chcesz teraz zaktualizować Shell Core?<br>",

    # ---- plugin store ---------------------------------------------------- #
    "Local": "Lokalne",
    "Store": "Sklep",
    "Explore": "Przeglądaj",
    "Assets": "Zasoby",
    "Cloud Sync": "Synchronizacja w chmurze",
    "Cloud Sync Error": "Błąd synchronizacji w chmurze",
    "Details": "Szczegóły",
    "Version": "Wersja",
    "Author": "Autor",
    "Description": "Opis",

    # ---- modify / menu builder ------------------------------------------- #
    "Edit Items/Menus": "Edytuj elementy/menu",
    "Modify Rule Configuration": "Konfiguracja reguły modyfikacji",
    "Adjust the settings for your rule.": "Dostosuj ustawienia swojej reguły.",
    "Adjust properties and appearance.": "Dostosuj właściwości i wygląd.",
    "Configure shortcut target, icon, appearance, and position.":
        "Skonfiguruj element docelowy skrótu, ikonę, wygląd i pozycję.",
    "Actions to Perform": "Akcje do wykonania",
    "Target Criteria": "Kryteria docelowe",
    "Advanced Command": "Polecenie zaawansowane",
    "Simple Shortcut": "Prosty skrót",
    "Shortcut Action": "Akcja skrótu",
    "Shortcut Item": "Element skrótu",
    "Master Configuration File": "Główny plik konfiguracyjny",
    "Create New NSS File": "Utwórz nowy plik NSS",
    "Glyph Browser": "Przeglądarka glifów",
    "Select up to 2 glyphs. Single = image, Dual = layered icon.":
        "Wybierz do 2 glifów. Jeden = obraz, dwa = ikona warstwowa.",
    "Enable color for glyph 1": "Włącz kolor dla glifu 1",
    "Enable color for glyph 2": "Włącz kolor dla glifu 2",
    "Color for Glyph 1": "Kolor glifu 1",
    "Color for Glyph 2": "Kolor glifu 2",
    "Quick Presets:": "Szybkie ustawienia:",
    "Icon Path or Glyph": "Ścieżka ikony lub glif",
    "Icon / Image": "Ikona / obraz",
    "Icon / Image:": "Ikona / obraz:",
    "Icon Title / Name:": "Tytuł / nazwa ikony:",
    "Icon Path": "Ścieżka ikony",
    "Search Keywords (comma-separated):": "Słowa kluczowe (oddzielone przecinkami):",
    "SVG Content or Path(s):": "Zawartość SVG lub ścieżki:",
    "Paste raw <svg>...</svg> code or d=\"...\" path string":
        "Wklej kod <svg>…</svg> lub ścieżkę d=\"…\"",
    "Add & Save SVG": "Dodaj i zapisz SVG",
    "Add Custom SVG Icon": "Dodaj własną ikonę SVG",
    "Custom SVG Icon Manager": "Menedżer własnych ikon SVG",
    "iMA Custom SVG Icon Manager": "Menedżer własnych ikon SVG iMA",
    "Please provide SVG content or path d string.":
        "Podaj zawartość SVG lub ścieżkę d.",
    "Please provide an Icon Title / Name.": "Podaj tytuł / nazwę ikony.",
    "Could not extract valid SVG path data (d attribute) from input.":
        "Nie udało się odczytać poprawnych danych ścieżki SVG (atrybut d) z wejścia.",
    "Parse Error": "Błąd parsowania",
    "Validation Error": "Błąd walidacji",
    "Save Error": "Błąd zapisu",
    "Error saving SVG:": "Błąd zapisu SVG:",
    "Syntax Error Caught": "Wykryto błąd składni",
    "Manual Color Conflicts Found": "Znaleziono konflikty kolorów",
    "We found some items that you previously edited with custom colors.\nSelect which ones you want to overwrite and sync with the new global theme.":
        "Znaleziono elementy, które wcześniej edytowano z własnymi kolorami.\nWybierz, które mają zostać nadpisane i zsynchronizowane z nowym motywem globalnym.",
    "Overwrite with current theme changes": "Nadpisz bieżącymi zmianami motywu",
    "+ New Item": "+ Nowy element",
    "+ New Menu": "+ Nowe menu",
    "+ New File": "+ Nowy plik",
    "+ New Rule": "+ Nowa reguła",
    "+ Add Action Step": "+ Dodaj krok akcji",
    "+ Add Inside ▾": "+ Dodaj wewnątrz ▾",
    "+ Shortcut Item": "+ Element skrótu",
    "+ Add Shortcut Item Inside": "+ Dodaj element skrótu wewnątrz",
    "+ Insert Argument...": "+ Wstaw argument…",
    "📁 Add Submenu Folder Inside": "📁 Dodaj folder podmenu wewnątrz",
    "📁 Submenu Folder": "📁 Folder podmenu",
    "Click '+ New Item' or '+ New Menu' above to create a context menu item.":
        "Kliknij „+ Nowy element” lub „+ Nowe menu” powyżej, aby utworzyć element menu kontekstowego.",
    "Click the star icon on the top-left of any cursor pack\nto add it to your favorites.":
        "Kliknij ikonę gwiazdki w lewym górnym rogu dowolnej paczki kursorów,\naby dodać ją do ulubionych.",
    "No items found in this file": "Nie znaleziono elementów w tym pliku",
    "No Favorite Cursors": "Brak ulubionych kursorów",
    "Enter a title": "Wprowadź tytuł",
    "Enter a new title (optional)": "Wprowadź nowy tytuł (opcjonalnie)",
    "Enter new theme name...": "Wprowadź nazwę nowego motywu…",
    "Title:": "Tytuł:",
    "Command:": "Polecenie:",
    "Arguments:": "Argumenty:",
    "Working Dir:": "Katalog roboczy:",
    "Target:": "Element docelowy:",
    "Position:": "Pozycja:",
    "Separator:": "Separator:",
    "Visibility:": "Widoczność:",
    "Show in:": "Pokaż w:",
    "Move to:": "Przenieś do:",
    "In Menu:": "W menu:",
    "Parent Menu:": "Menu nadrzędne:",
    "Type:": "Typ:",
    "Theme:": "Motyw:",
    "Find Title:": "Znajdź tytuł:",
    "New Title:": "Nowy tytuł:",
    "Arguments e.g. @sel.path.quote": "Argumenty, np. @sel.path.quote",
    "Arguments e.g. @sel.path.quote, /k pushd \"@sel.path\"":
        "Argumenty, np. @sel.path.quote, /k pushd \"@sel.path\"",
    "Working Dir e.g. @sel.dir": "Katalog roboczy, np. @sel.dir",
    "Select file or folder to open...": "Wybierz plik lub folder do otwarcia…",
    "Upload / browse executable, file, or script...":
        "Wgraj / przeglądnij plik wykonywalny, plik lub skrypt…",
    "Upload / browse program, file, or script...":
        "Wgraj / przeglądnij program, plik lub skrypt…",
    "Select Executable / Script": "Wybierz plik wykonywalny / skrypt",
    "Select Program or File": "Wybierz program lub plik",
    "Select File to Open": "Wybierz plik do otwarcia",
    "Select Executable/Shortcut/Icon to Inherit From":
        "Wybierz plik wykonywalny/skrót/ikonę do przejęcia",
    "Select Icon": "Wybierz ikonę",
    "Select Icon / Image": "Wybierz ikonę / obraz",
    "Select Image": "Wybierz obraz",
    "Select Color": "Wybierz kolor",
    "e.g. Refresh": "np. Refresh",
    "e.g. chrome, refresh, download": "np. chrome, refresh, download",
    "e.g. Discord": "np. Discord",
    "e.g. open with": "np. otwórz za pomocą",
    "e.g. game, riot, fps, shooter, play": "np. gra, riot, fps, shooter, play",
    "e.g. Valorant, Discord, Custom Logo": "np. Valorant, Discord, własne logo",
    "Recent Colors": "Ostatnie kolory",
    "+\nUpload Image": "+\nWgraj obraz",
    "PowerShell Here": "PowerShell tutaj",
    "Terminal Here": "Terminal tutaj",
    "Restart Explorer": "Uruchom Eksploratora ponownie",
    "Run Python": "Uruchom Pythona",
    "🚀 Launch App / Exe": "🚀 Uruchom aplikację / exe",
    "📄 Open File or Folder": "📄 Otwórz plik lub folder",
    "📋 Copy Path to Clipboard": "📋 Kopiuj ścieżkę do schowka",
    "💻 CMD Command": "💻 Polecenie CMD",
    "⚡ PowerShell Command": "⚡ Polecenie PowerShell",
    "🐍 Python Script": "🐍 Skrypt Python",
    "⚡ Action Pipeline": "⚡ Potok akcji",
    "💻 CMD: Open Here": "💻 CMD: otwórz tutaj",
    "💻 CMD: Keep Open": "💻 CMD: pozostaw otwarte",
    "💻 CMD: Run & Exit": "💻 CMD: uruchom i zamknij",
    "💻 CMD: Run Script": "💻 CMD: uruchom skrypt",
    "⚡ PS: Open Folder Here": "⚡ PS: otwórz folder tutaj",
    "⚡ PS: Hidden Window": "⚡ PS: ukryte okno",
    "⚡ PS: Run Script File": "⚡ PS: uruchom plik skryptu",
    "🐍 Python: Run File": "🐍 Python: uruchom plik",
    "🐍 Python: Install Req": "🐍 Python: zainstaluj zależności",
    "👁️ Toggle Hidden Files": "👁️ Przełącz ukryte pliki",
    "🔄 Restart Explorer": "🔄 Restart Eksploratora",
    "🛡️ Run as Admin": "🛡️ Uruchom jako administrator",
    "📁 Selected Path (Quoted)": "📁 Zaznaczona ścieżka (w cudzysłowie)",
    "📁 Selected Path (Raw)": "📁 Zaznaczona ścieżka (bez cudzysłowu)",
    "📂 Directory (Quoted)": "📂 Katalog (w cudzysłowie)",
    "📂 Directory (Raw)": "📂 Katalog (bez cudzysłowu)",
    "📄 File Name (Quoted)": "📄 Nazwa pliku (w cudzysłowie)",
    "📄 File Name (Raw)": "📄 Nazwa pliku (bez cudzysłowu)",
    "🏷️ File Title (No Ext)": "🏷️ Tytuł pliku (bez rozszerzenia)",
    "🏷️ File Extension": "🏷️ Rozszerzenie pliku",
    "📑 All Selected (Lines)": "📑 Wszystkie zaznaczone (linie)",
    "📑 All Selected (Spaces)": "📑 Wszystkie zaznaczone (spacje)",
    "🔢 Selected Count": "🔢 Liczba zaznaczonych",
    "🖥️ Desktop Dir": "🖥️ Katalog pulpitu",
    "🖥️ Temp Dir": "🖥️ Katalog tymczasowy",
    "🖥️ Windows Dir": "🖥️ Katalog Windows",
    "▶  Manual Edit": "▶  Edycja ręczna",
    "▼  Manual Edit": "▼  Edycja ręczna",

    # ---- themes ---------------------------------------------------------- #
    "Theme Editor": "Edytor motywu",
    "My Themes": "Moje motywy",
    "Custom Themes": "Własne motywy",
    "Themes": "Motywy",
    "Theme Saved": "Zapisano motyw",
    "Theme Refreshed": "Odświeżono motyw",
    "Theme Exists": "Motyw istnieje",
    "Invalid Name": "Nieprawidłowa nazwa",
    "Please enter a valid theme name.": "Wprowadź prawidłową nazwę motywu.",
    "Confirm Delete": "Potwierdź usunięcie",
    "Added theme successfully!": "Motyw dodany pomyślnie!",
    "Background Color": "Kolor tła",
    "Background Image": "Obraz tła",
    "Background Opacity": "Krycie tła",
    "Background Effect": "Efekt tła",
    "Border Color": "Kolor obramowania",
    "Border Size": "Grubość obramowania",
    "Border Radius": "Promień zaokrąglenia",
    "Border Opacity": "Krycie obramowania",
    "Border Padding": "Odstęp obramowania",
    "Enable Border": "Włącz obramowanie",
    "Enable Image": "Włącz obraz",
    "Enable Shadow": "Włącz cień",
    "Item Radius": "Promień elementu",
    "Item Borders": "Obramowania elementów",
    "Normal Text": "Tekst normalny",
    "Selected Text": "Tekst zaznaczony",
    "Disabled Text": "Tekst wyłączony",
    "Disabled Selected Text": "Tekst zaznaczony (wyłączony)",
    "Normal BG": "Tło normalne",
    "Selected BG": "Tło zaznaczone",
    "Disabled BG": "Tło wyłączone",
    "Disabled Selected BG": "Tło zaznaczone (wyłączone)",
    "Normal Border": "Obramowanie normalne",
    "Selected Border": "Obramowanie zaznaczone",
    "Disabled Border": "Obramowanie wyłączone",
    "Disabled Selected Border": "Obramowanie zaznaczone (wyłączone)",
    "Font Name": "Czcionka",
    "Font Size": "Rozmiar czcionki",
    "Bold": "Pogrubienie",
    "Italic": "Kursywa",
    "Shadow Size": "Rozmiar cienia",
    "Shadow Color": "Kolor cienia",
    "Shadow Opacity": "Krycie cienia",
    "Shadow & Separator": "Cień i separator",
    "Separator Size": "Rozmiar separatora",
    "Separator Color": "Kolor separatora",
    "Separator Opacity": "Krycie separatora",
    "Symbol Effect": "Efekt symbolu",
    "Symbol Color": "Kolor symbolu",
    "Image Effect": "Efekt obrazu",
    "Image Color": "Kolor obrazu",
    "Dark Mode": "Tryb ciemny",
    "Theme Mode": "Tryb motywu",
    "Typography": "Typografia",
    "Typography & Icons": "Typografia i ikony",
    "Dimensions": "Wymiary",
    "Colors": "Kolory",
    "General": "Ogólne",
    "Borders": "Obramowania",
    "Items": "Elementy",
    "Menus": "Menu",
    "Opacity (100%)": "Krycie (100%)",
    "Default": "Domyślne",
    "Gradient": "Gradient",
    "Rainbow": "Tęcza",

    # ---- status messages ------------------------------------------------- #
    "Changes Saved": "Zapisano zmiany",
    "Changes Reverted": "Cofnięto zmiany",
    "Rules Saved": "Zapisano reguły",
    "Rules Refreshed": "Odświeżono reguły",
    "Settings Refreshed": "Odświeżono ustawienia",
    "UI Refreshed": "Odświeżono interfejs",
    "Colors Synced": "Zsynchronizowano kolory",
    "Synced Theme": "Zsynchronizowano motyw",
    "Synced Themes": "Zsynchronizowano motywy",
    "Synced Rules": "Zsynchronizowano reguły",
    "Synced Imports": "Zsynchronizowano importy",
    "Synced Plugins & Icons": "Zsynchronizowano wtyczki i ikony",
    "Working in Background": "Działa w tle",
    "Successfully downloaded.": "Pobrano pomyślnie.",
    "Rules": "Reguły",
    "Imports": "Importy",

    # ---- dialogs --------------------------------------------------------- #
    "Unsaved Changes": "Niezapisane zmiany",
    "You have unsaved changes. Do you want to save them?":
        "Masz niezapisane zmiany. Czy chcesz je zapisać?",
    "You have unsaved changes in this item. Do you want to save them?":
        "Masz niezapisane zmiany w tym elemencie. Czy chcesz je zapisać?",
    "You have unsaved changes in these items. Do you want to save them?":
        "Masz niezapisane zmiany w tych elementach. Czy chcesz je zapisać?",
    "You have unsaved changes in this rule. Do you want to save them?":
        "Masz niezapisane zmiany w tej regule. Czy chcesz je zapisać?",
    "File Exists": "Plik istnieje",
    "Discard": "Odrzuć",
    "Discard Changes": "Odrzuć zmiany",
    "Don't Save": "Nie zapisuj",
    "Message": "Komunikat",
    "Details": "Szczegóły",

    # ---- upper-cased section headers ------------------------------------ #
    "MENU LOCATION": "LOKALIZACJA MENU",
    "OTHER FILES": "INNE PLIKI",
    "TARGET FILE": "PLIK DOCELOWY",
    "VISIBILITY": "WIDOCZNOŚĆ",

    # ---- item config dialog: composed titles / placeholders / sentinels ---
    "Add New Shortcut Item": "Dodaj nowy element skrótu",
    "Add New Submenu": "Dodaj nowe podmenu",
    "Add New Separator": "Dodaj nowy separator",
    "Edit Shortcut Item": "Edytuj element skrótu",
    "Edit Submenu": "Edytuj podmenu",
    "Edit Separator": "Edytuj separator",
    "Browse executable (.exe), script (.bat, .py, .ps1), or document...": "Przeglądaj plik wykonywalny (.exe), skrypt (.bat, .py, .ps1) lub dokument…",
    "Upload / browse local image file (.png, .ico, .svg)": "Wgraj / przeglądaj lokalny plik obrazu (.png, .ico, .svg)",
    "Command e.g. cmd.exe, powershell.exe": "Polecenie, np. cmd.exe, powershell.exe",
    "(Default)": "(Domyślnie)",
    "Top": "Góra",
    "Bottom": "Dół",
    "Middle": "Środek",
    "Before": "Przed",
    "After": "Po",
    "Both": "Oba",

    # ---- "Show in" / visibility presets (data lives in the widget key) ----
    "Right-Click": "Prawy przycisk myszy",
    "Capslock": "Caps Lock",
    "Left Click": "Lewy przycisk myszy",
    "Always Visible": "Zawsze widoczne",
    "Hidden Everywhere": "Ukryte wszędzie",
    "In Right-Click ONLY": "Tylko w menu kontekstowym",
    "Shift + Right-Click": "Shift + prawy przycisk myszy",
    "Ctrl + Right-Click": "Ctrl + prawy przycisk myszy",
    "Caps + Right-Click": "Caps Lock + prawy przycisk myszy",
    "Left + Right-Click": "Lewy + prawy przycisk myszy",
    "Shift Key Only": "Tylko klawisz Shift",
    "Control Key Only": "Tylko klawisz Control",
    "Caps Lock Only": "Tylko Caps Lock",
    "Left Mouse Only": "Tylko lewy przycisk myszy",
    "Visible In...": "Widoczne w…",
    "Recycle": "Kosz",
    "Background": "Tło",

    # ---- item / rule card captions -------------------------------------- #
    "Item": "Element",
    "Submenu": "Podmenu",
    "All": "Wszystkie",
    "Items": "Elementy",
    "Menus": "Menu",
    "Drafts": "Szkice",
    "Draft": "Szkic",
    "Files": "Pliki",
    "Folders": "Foldery",
    "Icons": "Ikony",
    "Icon Path": "Ścieżka ikony",
    "Find Title": "Znajdź tytuł",
    "New Title": "Nowy tytuł",
    "No Title": "Brak tytułu",
    "(Unnamed)": "(Bez nazwy)",
    "(no icon)": "(brak ikony)",
    "(none)": "(brak)",
    "Unknown Item": "Nieznany element",
    "Unnamed": "Bez nazwy",
    "None selected": "Nic nie zaznaczono",
    "No modifications defined": "Nie zdefiniowano modyfikacji",
    "Target ID": "ID docelowe",
    "In Menu": "W menu",
    "Move to": "Przenieś do",
    "Show in": "Pokaż w",
    "Global Rule": "Reguła globalna",
    "Modify ID: ": "Modyfikuj ID: ",
    "Modify: ": "Modyfikuj: ",
    "Renamed": "Zmieniono nazwę",
    "Moved": "Przeniesiono",
    "Modified": "Zmodyfikowano",
    "Hidden": "Ukryte",
    "Part Hidden": "Częściowo ukryte",
    "in": "w",
    "Contains": "Zawiera",
    "Exact": "Dokładnie",
    "Starts with": "Zaczyna się od",
    "Ends with": "Kończy się na",
    "Normal": "Normalny",
    "Hue": "Barwa",
    "Saturation": "Nasycenie",
    "Lightness": "Jasność",
    "Shadow": "Cień",
    "This PC": "Ten komputer",
    "Desktop": "Pulpit",
    "Taskbar": "Pasek zadań",
    "Fav": "Ulub.",
    "Favorited": "Dodano do ulubionych",
    "Args": "Argumenty",
    "Admin": "Administrator",
    "App": "Aplikacja",
    "CMD": "CMD",
    "Python": "Python",
    "PowerShell": "PowerShell",
    "Ctrl": "Ctrl",
    "Shift": "Shift",
    "Ctrl+Shift": "Ctrl+Shift",
    "Backup": "Kopia zapasowa",
    "Auto": "Automatycznie",
    "Message": "Komunikat",
    "Noise": "Szum",
    "Horizontal separator line": "Pozioma linia separatora",
    "Horizontal separator line between items in the right-click menu.":
        "Pozioma linia separatora między elementami menu kontekstowego.",
    "Shortcut Action": "Akcja skrótu",

    # ---- tab labels with a leading space (icon + text pills) ------------- #
    " Themes": " Motywy",
    " Editor": " Edytor",
    " Mouse": " Mysz",
    " Edit": " Edytuj",
    " Add": " Dodaj",
    "  All Imports": "  Wszystkie importy",
    "  Custom Rules": "  Własne reguły",
    "Background": "Tło",
    "Enable": "Włącz",
    "Disable": "Wyłącz",
    "Menu Border": "Obramowanie menu",
    "\ue105  Update": "\ue105  Aktualizuj",
    "\ue107  Delete": "\ue107  Usuń",
    "\ue109  Add Theme": "\ue109  Dodaj motyw",
    "\ue118  Download All": "\ue118  Pobierz wszystkie",
    "\ue73e  Done": "\ue73e  Gotowe",

    # ---- cloud_sync.py: progress + result messages (shown in dialogs) ---- #
    "Compressing files...": "Kompresowanie plików…",
    "Syncing with Google Drive...": "Synchronizacja z Google Drive…",
    "Backup complete!": "Kopia zapasowa gotowa!",
    "Backup successfully synced to Google Drive.": "Kopia zapasowa zsynchronizowana z Google Drive.",
    "Searching for backup...": "Wyszukiwanie kopii zapasowej…",
    "Downloading from Google Drive...": "Pobieranie z Google Drive…",
    "Extracting files...": "Rozpakowywanie plików…",
    "Restore complete!": "Przywracanie zakończone!",
    "Settings successfully restored. Please restart the app.": "Ustawienia zostały przywrócone. Uruchom aplikację ponownie.",
    "No backup found in Google Drive.": "Nie znaleziono kopii zapasowej w Google Drive.",
    "Login timed out or cancelled.": "Logowanie przekroczyło limit czasu lub zostało anulowane.",
    "Permission denied: You must check the Google Drive box for sync to work.": "Odmowa dostępu: aby synchronizacja działała, zaznacz pole Google Drive.",
    "Cloud Sync is not configured: set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.": "Synchronizacja w chmurze nie jest skonfigurowana: ustaw GOOGLE_CLIENT_ID i GOOGLE_CLIENT_SECRET.",
}

# --------------------------------------------------------------------------- #
# Polish translations — dynamic strings (matched with '{}' patterns)
# --------------------------------------------------------------------------- #
PL_PATTERNS = {
    "Syncing {} colors...": "Synchronizowanie kolorów: {}…",
    "Syncing {} colors ({}/{})...": "Synchronizowanie kolorów {} ({}/{})…",
    "Syncing {}/{}": "Synchronizacja {}/{}",
    "Filtering {}... ({}/{})": "Filtrowanie {}… ({}/{})",
    "Error: {}": "Błąd: {}",
    # cloud_sync.py failures (the tail is the provider's own error text)
    "Upload failed: {}": "Wysyłanie nie powiodło się: {}",
    "Download failed: {}": "Pobieranie nie powiodło się: {}",
    "Search failed: {}": "Wyszukiwanie nie powiodło się: {}",
    "Token exchange failed: {}": "Wymiana tokena nie powiodła się: {}",
    "Restore failed: {}": "Przywracanie nie powiodło się: {}",
    # github_client.py transport errors (surfaced as str(exc) in dialogs)
    "Cannot start the local login server on port {}: {}": "Nie można uruchomić lokalnego serwera logowania na porcie {}: {}",
    "Cannot write {}: {}": "Nie można zapisać {}: {}",
    "Checksum mismatch for {}": "Niezgodna suma kontrolna dla {}",
    "Download cancelled: {}": "Pobieranie anulowane: {}",
    "Downloaded file is empty: {}": "Pobrany plik jest pusty: {}",
    "HTTP {} for {}": "Błąd HTTP {} dla {}",
    "HTTP {} while downloading {}": "Błąd HTTP {} podczas pobierania {}",
    "Incomplete download from {}: {}/{} bytes": "Niekompletne pobieranie z {}: {}/{} bajtów",
    "Invalid JSON from {}: {}": "Nieprawidłowy JSON z {}: {}",
    "Network error for {}: {}": "Błąd sieci dla {}: {}",
    "No internet connection or unknown host for {}": "Brak połączenia z internetem lub nieznany host: {}",
    "Request failed for {}: {}": "Żądanie nie powiodło się dla {}: {}",
    "Request failed: {}": "Żądanie nie powiodło się: {}",
    "TLS error for {}: {}": "Błąd TLS dla {}: {}",
    "TLS/certificate problem for {}: {}": "Problem z TLS/certyfikatem dla {}: {}",
    "Timeout after {}s: {} ({})": "Przekroczony limit czasu po {} s: {} ({})",
    "Timeout while contacting {}": "Przekroczony limit czasu podczas łączenia z {}",
    # modify_widget delegate: badges and card sub-lines (values are NSS data)
    "Pos: {}": "Poz.: {}",
    "Source: {}": "Źródło: {}",
    "Source: <span style='color: #ea999c;'>{}</span>": "Źródło: <span style='color: #ea999c;'>{}</span>",
    " \u2022 Cmd: <span style='color: #b0b0b0;'>{}...</span>": " \u2022 Polecenie: <span style='color: #b0b0b0;'>{}…</span>",
    "Source: <span style='color: #ea999c;'>{}</span> \u2022 Cmd: <span style='color: #b0b0b0;'>{}...</span>": "Źródło: <span style='color: #ea999c;'>{}</span> \u2022 Polecenie: <span style='color: #b0b0b0;'>{}…</span>",
    "ID: <span style='color: #e78284;'>{}</span>": "ID: <span style='color: #e78284;'>{}</span>",
    "Modify: <span style='color: #e78284;'>{}</span>": "Modyfikuj: <span style='color: #e78284;'>{}</span>",
    "Vis: <span style='color: #e78284;'>{}</span>": "Widoczność: <span style='color: #e78284;'>{}</span>",
    "Move to <span style='color: #e78284;'>{}</span>": "Przenieś do <span style='color: #e78284;'>{}</span>",
    "Pos: <span style='color: #e78284;'>{}</span>": "Poz.: <span style='color: #e78284;'>{}</span>",
    "Error for {}": "Błąd: {}",
    "Save failed: {}": "Zapis nie powiodło się: {}",
    "Save setup failed: {}": "Zapis konfiguracji nie powiódł się: {}",
    "Failed to save SVG: {}": "Nie udało się zapisać SVG: {}",
    "Failed {}": "Nie powiodło się: {}",
    "Updated {}": "Zaktualizowano {}",
    "Updated '{}' successfully!": "Zaktualizowano „{}” pomyślnie!",
    "Added theme successfully!": "Motyw dodany pomyślnie!",
    "Edit Theme: {}": "Edytuj motyw: {}",
    "Edit {}": "Edytuj: {}",
    "Action Step #{}": "Krok akcji #{}",
    "Menu ({})": "Menu ({})",
    "Pipeline ({})": "Potok ({})",
    "Pos: {}": "Poz.: {}",
    "Sep: {}": "Sep.: {}",
    "Source: {}": "Źródło: {}",
    "Target: {}": "Cel: {}",
    "Vis: {}": "Wid.: {}",
    "Color {}": "Kolor {}",
    "Color for Glyph {}": "Kolor glifu {}",
    "Opacity ({}%)": "Krycie ({}%)",
    "Match Mode: {} (Click to change)": "Tryb dopasowania: {} (kliknij, aby zmienić)",
    "All {}s": "Wszystkie: {}",
    "Submenu Folder • {} items nested inside ({})":
        "Folder podmenu • zagnieżdżone elementy: {} ({})",
    "⚠️ Draft Item ({}) — Commented out to prevent syntax errors.":
        "⚠️ Szkic ({}) — zakomentowano, aby uniknąć błędów składni.",
    "⚠️ Draft Item — This item is currently commented out to prevent context menu syntax errors.":
        "⚠️ Szkic — ten element jest zakomentowany, aby uniknąć błędów składni menu kontekstowego.",
    "Are you sure you want to delete '{}'?": "Czy na pewno usunąć „{}”?",
    "Are you sure you want to delete local plugin '{}'?\n\nThis will move the plugin files to the Recycle Bin and remove it from your shell menu.":
        "Czy na pewno usunąć lokalną wtyczkę „{}”?\n\nPliki wtyczki trafią do Kosza, a ona sama zniknie z menu powłoki.",
    "File '{}' already exists.": "Plik „{}” już istnieje.",
    "'{}' already exists in imports.": "„{}” już istnieje w importach.",
    "'{}' is in Options section — loaded existing settings to edit.":
        "„{}” znajduje się w sekcji Options — wczytano istniejące ustawienia do edycji.",
    "'{}' is in Shift section — loaded existing settings to edit.":
        "„{}” znajduje się w sekcji Shift — wczytano istniejące ustawienia do edycji.",
    "'{}' is in Remove/Hide section — loaded existing settings to edit.":
        "„{}” znajduje się w sekcji Remove/Hide — wczytano istniejące ustawienia do edycji.",
    "Rule for '{}' already exists — loaded existing settings to edit.":
        "Reguła dla „{}” już istnieje — wczytano istniejące ustawienia do edycji.",
    "The theme '{}' already exists. Overwrite?": "Motyw „{}” już istnieje. Nadpisać?",
    "Successfully logged in as {}": "Zalogowano jako {}",
    "Could not save theme: {}": "Nie udało się zapisać motywu: {}",
    "Could not update theme: {}": "Nie udało się zaktualizować motywu: {}",
    "Could not launch updater:<br>{}": "Nie udało się uruchomić aktualizatora:<br>{}",
    "An error occurred while downloading the update:<br>{}":
        "Wystąpił błąd podczas pobierania aktualizacji:<br>{}",
    "A new release <b>v{}</b> was found, but no installer binary is attached to the release yet.":
        "Znaleziono nową wersję <b>v{}</b>, ale nie zawiera ona jeszcze instalatora.",
    "You are running the latest version <b>v{}</b>.":
        "Korzystasz z najnowszej wersji <b>v{}</b>.",
    "Authentication failed: {}": "Uwierzytelnianie nie powiodło się: {}",
    "Network error: {}": "Błąd sieci: {}",
    "Error checking plugins: {}": "Błąd podczas sprawdzania wtyczek: {}",
    "Error fetching details: {}": "Błąd podczas pobierania szczegółów: {}",
    "Failed to download repository archive: {}":
        "Nie udało się pobrać archiwum repozytorium: {}",
    "Dependency {} not found in any release assets.":
        "Nie znaleziono zależności {} w zasobach żadnego wydania.",
    "Could not find folder for plugin '{}' in repository archive.":
        "Nie znaleziono folderu wtyczki „{}” w archiwum repozytorium.",
    "No files extracted for plugin '{}' from repository archive.":
        "Nie wyodrębniono żadnych plików wtyczki „{}” z archiwum repozytorium.",
    "Failed to save icon. The file may be in use by another process.\n\nError: {}":
        "Nie udało się zapisać ikony. Plik może być używany przez inny proces.\n\nBłąd: {}",
    "Failed to write {}: Invalid NSS syntax detected. Write aborted to prevent corruption.":
        "Nie udało się zapisać {}: wykryto nieprawidłową składnię NSS. Zapis przerwano, aby uniknąć uszkodzeń.",
    "Failed to write file '{}' (0 bytes)": "Nie udało się zapisać pliku „{}” (0 bajtów)",
    "Download cancelled ({}/{} saved, incomplete files cleaned up)":
        "Pobieranie anulowano ({}/{} zapisanych, niekompletne pliki usunięte)",
    "Downloading cursors ({}/{}): {}": "Pobieranie kursorów ({}/{}): {}",
    "Click to cancel download ({}/{})": "Kliknij, aby anulować pobieranie ({}/{})",
    "Click to cancel download ({}/{})\nCurrently: {}":
        "Kliknij, aby anulować pobieranie ({}/{})\nBieżący: {}",
    "Click to cancel download (0/{})": "Kliknij, aby anulować pobieranie (0/{})",
    "✕  Cancel ({}/{})": "✕  Anuluj ({}/{})",
    "✕  Cancel (0/{})": "✕  Anuluj (0/{})",
    "\ue783  {} Errors": "\ue783  Błędy: {}",
    "{} up to date": "{} aktualnych",
    "All cursors ready! ({} downloaded, {} up to date)":
        "Wszystkie kursory gotowe! (pobrane: {}, aktualne: {})",
    "Downloaded {} new/updated themes": "Pobrano nowe/zaktualizowane motywy: {}",
    "Downloaded {} cursors ({} up to date, {} errors): {}":
        "Pobrano kursory: {} (aktualne: {}, błędy: {}): {}",
    "Logged in as {} ({})": "Zalogowano jako {} ({})",
    "Logged in as {}": "Zalogowano jako {}",
    "Added {} to system PATH.": "Dodano {} do systemowej zmiennej PATH.",
    "Error adding {} to PATH: {}": "Błąd podczas dodawania {} do PATH: {}",
    "Operation error for {}: {}": "Błąd operacji dla {}: {}",
    # ---- composed rich-text captions (item / rule cards) ------------------
    "Submenu Folder • {} items nested inside (collapsed)":
        "Folder podmenu • zagnieżdżone elementy: {} (zwinięty)",
    "Submenu Folder • {} items nested inside (expanded)":
        "Folder podmenu • zagnieżdżone elementy: {} (rozwinięty)",
    "↳ In: {}": "↳ W: {}",
    "ID: <span style='color: #e78284;'>{}</span>":
        "ID: <span style='color: #e78284;'>{}</span>",
    "Modify: <span style='color: #e78284;'>{}</span>":
        "Modyfikacja: <span style='color: #e78284;'>{}</span>",
    "Rule: <span style='color: #e78284;'>{}</span>":
        "Reguła: <span style='color: #e78284;'>{}</span>",
    "All <span style='color: #ea999c;'>{}s</span>":
        "Wszystkie <span style='color: #ea999c;'>{}</span>",
    "Rename to <span style='color: #ffffff;'>'{}'</span>":
        "Zmień nazwę na <span style='color: #ffffff;'>'{}'</span>",
    "<span style='color: #e78284;'>Hidden</span>":
        "<span style='color: #e78284;'>Ukryte</span>",
    "<span style='color: #e78284;'>New Icon</span>":
        "<span style='color: #e78284;'>Nowa ikona</span>",
    "<span style='color: #333333;'>Separator</span>":
        "<span style='color: #333333;'>Separator</span>",
    "Vis: <span style='color: #e78284;'>{}</span>":
        "Wid.: <span style='color: #e78284;'>{}</span>",
    "Pos: <span style='color: #e78284;'>{}</span>":
        "Poz.: <span style='color: #e78284;'>{}</span>",
    "Move to <span style='color: #e78284;'>Main</span>":
        "Przenieś do <span style='color: #e78284;'>Main</span>",
    "Move to <span style='color: #e78284;'>Options</span>":
        "Przenieś do <span style='color: #e78284;'>Options</span>",
    "Move to <span style='color: #e78284;'>{}</span>":
        "Przenieś do <span style='color: #e78284;'>{}</span>",
    "Item: <span style='color: #e78284;'>{}</span>":
        "Element: <span style='color: #e78284;'>{}</span>",
    "Menu: <span style='color: #e78284;'>{}</span>":
        "Menu: <span style='color: #e78284;'>{}</span>",
    "Source: <span style='color: #ea999c;'>{}</span>":
        "Źródło: <span style='color: #ea999c;'>{}</span>",
    "Source: <span style='color: #ea999c;'>{}</span> • Cmd: <span style='color: #b0b0b0;'>{}...</span>":
        "Źródło: <span style='color: #ea999c;'>{}</span> • Polecenie: <span style='color: #b0b0b0;'>{}…</span>",
    "Draft Item": "Szkic",
    "Current: {} | <span style='color: #e78284;'>Latest: {}</span>":
        "Bieżąca: {} | <span style='color: #e78284;'>Najnowsza: {}</span>",
    "Re-install iMA Menu Launcher <b>v{}</b> now?":
        "Zainstalować ponownie iMA Menu Launcher <b>v{}</b>?",
    "A new version of iMA Menu Launcher is available: <b>v{}</b><br><br>Would you like to download and install it now?":
        "Dostępna jest nowa wersja iMA Menu Launcher: <b>v{}</b><br><br>Czy chcesz ją teraz pobrać i zainstalować?",
    "V {}": "Wersja {}",
    "Current: {} | Latest: {}": "Bieżąca: {} | Najnowsza: {}",
    "Syncing": "Synchronizacja",
}

# --------------------------------------------------------------------------- #
# Context sensitive words (only translated when explicitly requested)
# --------------------------------------------------------------------------- #
PL_CONTEXTS = {
    "separator": {"None": "Brak", "Line": "Linia", "Space": "Odstęp"},
    "position": {"Top": "Góra", "Middle": "Środek", "Bottom": "Dół",
                 "Before": "Przed", "After": "Po", "Both": "Oba"},
    "visibility": {"None": "Brak", "Shift": "Shift", "Control": "Control",
                   "Left Mouse": "Lewy przycisk myszy",
                   "Always Visible": "Zawsze widoczne",
                   "Hidden Everywhere": "Ukryte wszędzie",
                   "Part Hidden": "Częściowo ukryte",
                   "In Right-Click ONLY": "Tylko w menu kontekstowym",
                   "Shift Key Only": "Tylko klawisz Shift",
                   "Control Key Only": "Tylko klawisz Control",
                   "Caps Lock Only": "Tylko Caps Lock",
                   "Left Mouse Only": "Tylko lewy przycisk myszy"},
    "menu": {"None": "Brak", "Main": "Główne", "Options": "Opcje"},
    "action": {"Install": "Zainstaluj", "Uninstall": "Odinstaluj",
               "Update": "Aktualizuj", "Delete": "Usuń", "Enable": "Włącz",
               "Disable": "Wyłącz", "Queued": "W kolejce",
               "Installing": "Instalowanie", "Cancel": "Anuluj"},
}

PL_PLURALS = {
    "{} item|{} items": ["{} element", "{} elementy", "{} elementów"],
    "{} menu|{} menus": ["{} menu", "{} menu", "{} menu"],
    "{} color|{} colors": ["{} kolor", "{} kolory", "{} kolorów"],
    "{} cursor|{} cursors": ["{} kursor", "{} kursory", "{} kursorów"],
    "{} theme|{} themes": ["{} motyw", "{} motywy", "{} motywów"],
    "{} plugin|{} plugins": ["{} wtyczka", "{} wtyczki", "{} wtyczek"],
    "{} file|{} files": ["{} plik", "{} pliki", "{} plików"],
    "{} error|{} errors": ["{} błąd", "{} błędy", "{} błędów"],
}

# --------------------------------------------------------------------------- #
# Strings the scanners cannot see (built from variables) — add them manually
# --------------------------------------------------------------------------- #
SUPPLEMENT = [
    "Plugins", "Modify", "Theme", "Settings", "Refresh", "Minimize", "Maximize",
    "Restore", "Close", "Language", "Interface language", "English", "Polski",
    "Automatic (system)", "Install", "Uninstall", "Update", "Delete", "Enable",
    "Disable", "Queued", "Installing", "Cancel", "Done", "Details", "Version",
    "Author", "Description", "Rules", "Imports", "Themes", "Cursors",
    "Discard", "Discard Changes", "Don't Save", "Warning", "Information",
    "Gradient", "Select Color", "Google Drive Sync", "Not logged in",
    "Google Account Profile", "Sync Now", "Sign in with Google",
    "Sync your settings, themes and rules to Google Drive.",
    "Sign in to enable cloud sync", "Signed in", "Sync failed",
    "Uploading...", "Downloading...", "Download", "Retry",
    "Change language", "Restart required", "Favorites", "Download All",
    "Apply", "Restore Defaults", "Preview", "Search", "Search themes...",
    "Search cursors...", "No results", "No themes found", "Loading...",
    "Please wait...", "Copy", "Paste", "Undo", "Redo", "Select All",
    "Open Folder", "Open File", "Browse", "Choose Folder", "Choose File",
    "Name", "Size", "Type", "Date", "Status", "Progress", "Total",
    "Item", "Menu", "Separator", "Position", "Visibility", "Title", "Path",
    "Icon", "Command", "Arguments", "Working Directory", "Target",
    "Keyword", "Keywords", "Category", "Options", "Advanced", "Basic",
    "Enabled", "Disabled", "On", "Off", "None", "Custom", "Default",
    "Reset All", "Save All", "Reload", "Reload Shell", "Restart Explorer",
    "Exit", "Quit", "About", "About iMA Menu", "Documentation", "Website",
    "Report a Problem", "Check Logs", "Show Logs", "Hide Logs",
    "No errors found", "Errors found", "Line", "Column",
    "Draft", "Active", "Inactive", "New", "Existing", "Conflict",
    "Keep Both", "Replace", "Merge", "Compare", "Differences",
]

SUPPLEMENT_PL = {
    "Sync Now": "Synchronizuj teraz",
    "Sign in with Google": "Zaloguj się przez Google",
    "Sync your settings, themes and rules to Google Drive.":
        "Synchronizuj ustawienia, motywy i reguły z Google Drive.",
    "Sign in to enable cloud sync": "Zaloguj się, aby włączyć synchronizację w chmurze",
    "Signed in": "Zalogowano",
    "Sync failed": "Synchronizacja nie powiodła się",
    "Uploading...": "Wysyłanie…",
    "Download": "Pobierz",
    "Retry": "Spróbuj ponownie",
    "Change language": "Zmień język",
    "Restart required": "Wymagane ponowne uruchomienie",
    "Favorites": "Ulubione",
    "Download All": "Pobierz wszystkie",
    "Restore Defaults": "Przywróć domyślne",
    "Preview": "Podgląd",
    "Search": "Szukaj",
    "Search themes...": "Szukaj motywów…",
    "Search cursors...": "Szukaj kursorów…",
    "No results": "Brak wyników",
    "No themes found": "Nie znaleziono motywów",
    "Loading...": "Ładowanie…",
    "Please wait...": "Proszę czekać…",
    "Copy": "Kopiuj",
    "Paste": "Wklej",
    "Undo": "Cofnij",
    "Redo": "Ponów",
    "Select All": "Zaznacz wszystko",
    "Open Folder": "Otwórz folder",
    "Open File": "Otwórz plik",
    "Browse": "Przeglądaj",
    "Choose Folder": "Wybierz folder",
    "Choose File": "Wybierz plik",
    "Name": "Nazwa",
    "Size": "Rozmiar",
    "Type": "Typ",
    "Date": "Data",
    "Status": "Status",
    "Progress": "Postęp",
    "Total": "Razem",
    "Item": "Element",
    "Menu": "Menu",
    "Separator": "Separator",
    "Position": "Pozycja",
    "Visibility": "Widoczność",
    "Title": "Tytuł",
    "Path": "Ścieżka",
    "Icon": "Ikona",
    "Command": "Polecenie",
    "Arguments": "Argumenty",
    "Working Directory": "Katalog roboczy",
    "Target": "Element docelowy",
    "Keyword": "Słowo kluczowe",
    "Keywords": "Słowa kluczowe",
    "Category": "Kategoria",
    "Options": "Opcje",
    "Advanced": "Zaawansowane",
    "Basic": "Podstawowe",
    "Enabled": "Włączone",
    "Disabled": "Wyłączone",
    "On": "Wł.",
    "Off": "Wył.",
    "None": "Brak",
    "Custom": "Własne",
    "Default": "Domyślne",
    "Reset All": "Resetuj wszystko",
    "Save All": "Zapisz wszystko",
    "Reload": "Wczytaj ponownie",
    "Reload Shell": "Przeładuj powłokę",
    "Restart Explorer": "Uruchom Eksploratora ponownie",
    "Exit": "Zamknij",
    "Quit": "Zakończ",
    "About": "O programie",
    "About iMA Menu": "O iMA Menu",
    "Documentation": "Dokumentacja",
    "Website": "Strona internetowa",
    "Report a Problem": "Zgłoś problem",
    "Check Logs": "Sprawdź logi",
    "Show Logs": "Pokaż logi",
    "Hide Logs": "Ukryj logi",
    "No errors found": "Nie znaleziono błędów",
    "Errors found": "Znaleziono błędy",
    "Line": "Linia",
    "Column": "Kolumna",
    "Draft": "Szkic",
    "Active": "Aktywny",
    "Inactive": "Nieaktywny",
    "New": "Nowy",
    "Existing": "Istniejący",
    "Conflict": "Konflikt",
    "Keep Both": "Zachowaj oba",
    "Replace": "Zastąp",
    "Merge": "Scal",
    "Compare": "Porównaj",
    "Differences": "Różnice",
    "Automatic (system)": "Automatyczny (systemowy)",
    "Cursors": "Kursory",
    "English": "English",
    "Polski": "Polski",
}


def collect_source_keys():
    """Every string the scanners found in the sources, minus the exclusions.

    Existing ``locales/en.json`` keys are merged in so a re-run never drops an
    entry that was curated by hand earlier.
    """
    sys.path.insert(0, os.path.join(LAUNCHER_DIR, "tools"))
    keys, patterns = set(), set()
    try:
        import i18n_extract
        for entry in i18n_extract.scan_all():
            msgid = entry["msgid"]
            if msgid in EXCLUDE or normalize_pattern(msgid) in EXCLUDE:
                continue
            if entry.get("template") or re.search(r"\{[^{}]*\}", msgid):
                patterns.add(normalize_pattern(msgid))
            else:
                keys.add(msgid)
    except Exception as error:
        print(f"warning: source scan failed ({error}) — reusing the existing catalogue")

    existing = os.path.join(LOCALES_DIR, "en.json")
    if os.path.exists(existing):
        try:
            data = json.load(open(existing, encoding="utf-8"))
            keys |= set(data.get("messages", {})) - EXCLUDE
            patterns |= {normalize_pattern(p) for p in data.get("patterns", {})} - EXCLUDE
        except Exception as error:
            print(f"warning: could not read en.json ({error})")
    return keys, patterns


def normalize_pattern(template):
    """Turn ``'{name}' already exists`` style sources into ``'{}' already exists``."""
    return re.sub(r"\{[^{}]*\}", "{}", template) if template else template


def build():
    keys, raw_patterns = collect_source_keys()
    keys |= set(SUPPLEMENT)
    patterns = {normalize_pattern(p) for p in raw_patterns}
    # f-string sources with named placeholders collapse into '{}' templates
    patterns = {p for p in patterns if "{}" in p}

    en_messages = {k: k for k in sorted(keys)}
    en_patterns = {p: p for p in sorted(patterns)}

    pl_messages = {}
    for key in sorted(keys):
        if key in PL:
            pl_messages[key] = PL[key]
        elif key in SUPPLEMENT_PL:
            pl_messages[key] = SUPPLEMENT_PL[key]
    for key in sorted(PL):
        if key not in en_messages:
            en_messages[key] = key
            pl_messages[key] = PL[key]
    for key in sorted(SUPPLEMENT_PL):
        en_messages.setdefault(key, key)
        pl_messages[key] = SUPPLEMENT_PL[key]

    pl_patterns = {}
    for template in sorted(PL_PATTERNS):
        translation = PL_PATTERNS[template]
        if "{}" not in template:
            # not a template at all — keep it as a plain message
            en_messages[template] = template
            pl_messages[template] = translation
            continue
        en_patterns.setdefault(template, template)
        pl_patterns[template] = translation

    en = {
        "meta": {
            "language": "en", "name": "English", "english_name": "English",
            "version": CATALOG_VERSION, "source": True,
            "comment": "Source catalogue — values are identical to the keys.",
        },
        "messages": en_messages,
        "contexts": {ctx: {k: k for k in sorted(values)} for ctx, values in PL_CONTEXTS.items()},
        "patterns": en_patterns,
        "plurals": {k: [k.split("|")[0], k.split("|")[1]] for k in sorted(PL_PLURALS)},
    }
    pl = {
        "meta": {
            "language": "pl", "name": "Polski", "english_name": "Polish",
            "version": CATALOG_VERSION,
            "comment": "Polskie tłumaczenie interfejsu iMA Menu Launcher.",
        },
        "messages": pl_messages,
        "contexts": {ctx: dict(sorted(values.items())) for ctx, values in PL_CONTEXTS.items()},
        "patterns": pl_patterns,
        "plurals": dict(sorted(PL_PLURALS.items())),
    }

    os.makedirs(LOCALES_DIR, exist_ok=True)
    for name, payload in (("en.json", en), ("pl.json", pl)):
        path = os.path.join(LOCALES_DIR, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=False)
            handle.write("\n")
        print(f"wrote {path}: {len(payload['messages'])} messages, "
              f"{len(payload['patterns'])} patterns")

    # ---- diagnostics -----------------------------------------------------
    unknown_pl = sorted(k for k in PL if k not in en_messages)
    if unknown_pl:
        print(f"\nWARNING: {len(unknown_pl)} PL keys are not present in the sources:")
        for key in unknown_pl:
            print(f"   {key!r}")
    untranslated = sorted(k for k in keys if k not in pl_messages)
    untranslated_patterns = sorted(p for p in patterns if p not in pl_patterns)
    print(f"\ncoverage: {len(pl_messages)}/{len(en_messages)} messages, "
          f"{len(pl_patterns)}/{len(en_patterns)} patterns")
    if untranslated:
        print(f"missing Polish for {len(untranslated)} messages (first 40):")
        for key in untranslated[:40]:
            print(f"   {key!r}")
    if untranslated_patterns:
        print(f"missing Polish for {len(untranslated_patterns)} patterns:")
        for key in untranslated_patterns:
            print(f"   {key!r}")


if __name__ == "__main__":
    build()
