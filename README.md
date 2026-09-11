<div align="center">

# iMA Menu ✨

![ima](https://github.com/user-attachments/assets/c91b3569-4365-452c-a97b-17bda181a216)

![GitHub All Releases](https://img.shields.io/github/downloads/iMAboud/iMA-Menu/total.svg)
[![Release](https://img.shields.io/badge/release-v2.0.23-blue)](https://github.com/iMAboud/iMA-Menu/releases/download/2.0.23/iMA.Menu.exe)
[![License](https://img.shields.io/badge/license-Proprietary-red)](LICENSE)

--- 
<img width="150" height="181" alt="screenshot_20260902_054803" src="https://github.com/user-attachments/assets/5ce0ea90-ae01-4bca-9484-8d25bb3ee969" /> <img width="142" height="173" alt="screenshot_20260902_054757" src="https://github.com/user-attachments/assets/11bb8bcf-bd6d-4245-a6c9-b1098ffb1373" />
 <img width="151" height="172" alt="screenshot_20260902_054842" src="https://github.com/user-attachments/assets/d9dccdbd-c0af-447e-b088-911bc2f77b5d" /> <img width="148" height="174" alt="screenshot_20260902_054739" src="https://github.com/user-attachments/assets/13745380-a700-4ee9-a2cf-9f8ec5df3fa5" /> <img width="151" height="172" alt="screenshot_20260902_054807" src="https://github.com/user-attachments/assets/1855d579-1053-4268-ac66-692a4d7a32fb" />






iMA Menu is a powerful, customizable desktop enhancement suite designed to streamline your workflow and personalize your Windows experience. Rebuilt for robustness and efficiency, it offers unparalleled control over your context menus, a modular plugin system, advanced theming options, and a suite of integrated productivity tools.

---
</div>

## Installation 💻

**Install the latest Release v2.0.23** [Download](https://github.com/iMAboud/iMA-Menu/releases/download/2.0.23/iMA.Menu.exe).

---

## Key Features 🌟

<details>
  <summary>✨ Enhanced Context Menu Customization</summary>
  
  Tailor your right-click context menu with options to modify, remove, or change icons for menu items.
</details>

<details>
  <summary>🔌 Modular Plugin System & Manager</summary>
  
  Extend iMA Menu's capabilities with a growing library of plugins, easily managed through an integrated system.
</details>

<details>
  <summary>🎨 Advanced Theming Options</summary>
  
  Personalize the look and feel of your iMA Menu with a flexible theming engine, offering presets and live editing.
</details>

<details>
  <summary>🚀 Integrated Productivity Tools</summary>
  
  Access a suite of handy tools for file management, screen drawing, color picking, file transfer, quick file creation, and Windows Security exclusions.
</details>

---

## Screenshots 📸

<img width="425" height="325" alt="plugins" src="https://github.com/user-attachments/assets/0e0327a1-6a8c-4191-8f5b-8a6c0260eec2" />
<img width="425" height="325" alt="rules" src="https://github.com/user-attachments/assets/52c7f89f-438f-45ea-9080-fa4157236b86" />
<img width="425" height="325" alt="imports" src="https://github.com/user-attachments/assets/ffc64776-6b13-48f5-818d-e49f7ef0060c" />
<img width="425" height="325" alt="themes" src="https://github.com/user-attachments/assets/212c3466-6db8-41ec-8e9e-cdc2c4a9b78a" />
<img width="425" height="325" alt="cursors" src="https://github.com/user-attachments/assets/c50ba5f4-c6ed-4bbd-9959-a91728939fae" />
<img width="425" height="325" alt="editor" src="https://github.com/user-attachments/assets/989266f7-fa93-4d5d-a3f7-951207efabed" />


<img src="https://i.imgur.com/59R59gy.gif" width="850" height="550">

---

## Usage 💡

Right-Click on Taskbar > iMA Menu > Settings

<img width="365" height="206" alt="screenshot_20260513_012457" src="https://github.com/user-attachments/assets/45ba1904-40ba-49d7-8527-5c2b0120f65e" />

---

## Localization 🌍

The launcher UI is fully localizable at runtime — no restart needed.

* **English** is the source language and the default.
* **Polski (Polish)** ships built in: open **Settings → Language** and pick *Polski*; every screen, dialog, tooltip and status message switches instantly and the choice is stored in `cache/settings.json`.

Translations live in [`iMA Menu/Launcher/locales/`](iMA%20Menu/Launcher/locales) as plain JSON catalogues (`en.json` is the source of truth, `pl.json` the Polish translation), driven by the [`i18n.py`](iMA%20Menu/Launcher/i18n.py) runtime layer. Adding another language means copying `en.json`, translating the values and registering the code in `i18n.LANGUAGES` — see [`iMA Menu/Launcher/I18N.md`](iMA%20Menu/Launcher/I18N.md) for details and for the tooling (`tools/i18n_extract.py`, `tools/build_catalog.py`, `tools/test_i18n.py`).

> **PL:** Interfejs launchera jest w pełni tłumaczony w trakcie działania. W **Ustawienia → Język** wybierz *Polski* — wszystkie ekrany, okna dialogowe, podpowiedzi i komunikaty przełączą się natychmiast, a wybór zostanie zapisany.

---

## Running the launcher from source 🐍

The launcher is a Python 3 / PyQt5 app that lives in [`iMA Menu/Launcher/`](iMA%20Menu/Launcher):

```bat
cd "iMA Menu\Launcher"
pip install PyQt5
python launcher.pyw            :: add --lang pl to start in Polish
python build_launcher.py       :: package dist\launcher.exe with PyInstaller
```

Two backend modules were missing from this repository and are included again:

* **`github_client.py`** – the HTTP layer used by the update check, the plugin
  store, the theme switcher and the cursor browser (GitHub REST API, the
  `raw.githubusercontent.com` CDN, tree SHAs and streamed downloads with
  progress/cancel). It is built on `urllib` only, because `requests` is excluded
  from the packaged exe. Set `GITHUB_TOKEN` to raise the API rate limit from 60
  to 5 000 requests/hour — everything works without it.
* **`cloud_sync.py`** – Google Drive backup/restore of `shell.nss`, `imports/`
  and `theme/`, with the token protected by Windows DPAPI (no `pywin32` needed).
  It requires OAuth credentials of your own: create a *Desktop app* client in
  the Google Cloud Console, enable the Drive API, allow the redirect URI
  `http://localhost:54321` and export `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.
  Until then **Settings → Cloud Sync** reports that it is not configured instead
  of failing.

`fonts/glyphs.json` (the searchable glyph database, 3 966 icons) and
`fonts/nilesoft.ttf` are committed as well — the Modify page needs them and
PyInstaller bundles them into the exe. `build_launcher.py` also copies
`shell.exe`/`shell.dll` from the project root before building and skips optional
assets that a fresh checkout does not have, instead of aborting.

Verification (headless, `QT_QPA_PLATFORM=offscreen` on Linux):

```bash
python tools/test_i18n.py                # catalogues, hooks, live retranslation
python tools/test_i18n_integration.py    # the real launcher widgets
python tools/test_github_client.py       # backend API contract  (--live hits GitHub)
```

---

## Contributing 🤝

We welcome contributions! If you have suggestions, bug reports, or want to contribute code, please open an issue or pull request on GitHub.

For plugin contributions, please visit the [iMA Menu Plugins repository](https://github.com/iMAboud/iMA-Menu-Plugins).

---

## License 📄

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Credits 🙏

*   [Nilesoft Shell](https://github.com/moudey/Shell)
*   [Shollz . croc](https://github.com/schollz/croc)
