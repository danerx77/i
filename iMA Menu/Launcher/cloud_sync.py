"""Google Drive cloud sync for iMA Menu (settings backup / restore).

Backs up ``shell.nss`` plus the ``imports/`` and ``theme/`` folders into a zip
stored in the signed-in user's Google Drive *appDataFolder* (hidden, app-only
space) and restores it 1:1 on another machine.

Ported from the upstream implementation with two changes that the packaged
launcher needs:

* no ``requests`` -- every call goes through :mod:`github_client` (urllib),
  because ``requests``/``urllib3``/``certifi`` are excluded from the
  PyInstaller build;
* no ``pywin32`` -- the token is protected with DPAPI through :mod:`ctypes`
  (``win32crypt`` is excluded too).

Compared with the upstream module this version also provides what the current
``launcher.pyw`` expects: ``user_name``, the ``profile_updated`` signal and
``fetch_user_profile(background=True)`` (which downloads the account avatar to
``cache/profile_avatar.png``).

Configuration
-------------
Cloud Sync needs OAuth credentials of your own.  Create an "Desktop app" client
in the Google Cloud Console, enable the Google Drive API, add
``http://localhost:54321`` as an authorised redirect URI and then either export

    set GOOGLE_CLIENT_ID=...
    set GOOGLE_CLIENT_SECRET=...

or replace the defaults below.  Until that is done :meth:`CloudSyncManager.login`
reports "not configured" instead of opening a browser window that cannot work.
"""

import base64
import ctypes
import json
import os
import shutil
import sys
import threading
import time
import webbrowser
import zipfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import quote, urlparse, parse_qs

from PyQt5.QtCore import QObject, pyqtSignal

from github_client import (RequestException, cdn_get, http_get, http_patch,
                           http_post)

# --------------------------------------------------------------------------- #
# OAuth configuration
# --------------------------------------------------------------------------- #
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "YOUR_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "YOUR_CLIENT_SECRET")
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:54321")
LOCAL_PORT = int(os.getenv("GOOGLE_REDIRECT_PORT", "54321"))
SCOPES = [
    "https://www.googleapis.com/auth/drive.appdata",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"

BACKUP_NAME = "backup.zip"
TOKEN_FILE = ".cloud_token.dat"
DPAPI_LABEL = "iMA Menu Cloud Sync"
LOGIN_TIMEOUT = 300          # seconds to wait for the browser round-trip
PLACEHOLDERS = ("", "YOUR_CLIENT_ID", "YOUR_CLIENT_SECRET")


def is_configured():
    """True when real OAuth credentials are available."""
    return (CLIENT_ID not in PLACEHOLDERS and CLIENT_SECRET not in PLACEHOLDERS)


# --------------------------------------------------------------------------- #
# DPAPI (CryptProtectData) without pywin32
# --------------------------------------------------------------------------- #
class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi():
    if sys.platform != "win32":
        return None
    try:
        return ctypes.windll.crypt32          # noqa: F401  (Windows only)
    except Exception:
        return None


def _blob(data):
    blob = _DATA_BLOB()
    blob.cbData = len(data)
    blob.pbData = ctypes.cast(ctypes.create_string_buffer(data, len(data)),
                              ctypes.POINTER(ctypes.c_char))
    return blob


def _protect(text):
    """Encrypt with DPAPI; fall back to base64 so nothing is ever lost."""
    crypt32 = _dpapi()
    payload = text.encode("utf-8")
    if crypt32 is not None:
        try:
            in_blob = _blob(payload)
            out_blob = _DATA_BLOB()
            ok = crypt32.CryptProtectData(ctypes.byref(in_blob), DPAPI_LABEL, None,
                                          None, None, 0, ctypes.byref(out_blob))
            if ok and out_blob.cbData:
                data = ctypes.string_at(out_blob.pbData, out_blob.cbData)
                try:
                    ctypes.windll.kernel32.LocalFree(out_blob.pbData)
                except Exception:
                    pass
                return "dpapi:" + base64.b64encode(data).decode("ascii")
        except Exception:
            pass
    return "b64:" + base64.b64encode(payload).decode("ascii")


def _unprotect(stored):
    if not stored:
        return None
    try:
        if stored.startswith("dpapi:"):
            crypt32 = _dpapi()
            if crypt32 is None:
                return None
            in_blob = _blob(base64.b64decode(stored[6:]))
            out_blob = _DATA_BLOB()
            ok = crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None,
                                            None, None, 0, ctypes.byref(out_blob))
            if not ok or not out_blob.cbData:
                return None
            data = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            try:
                ctypes.windll.kernel32.LocalFree(out_blob.pbData)
            except Exception:
                pass
            return data.decode("utf-8")
        if stored.startswith("b64:"):
            return base64.b64decode(stored[4:]).decode("utf-8")
        return stored                          # legacy: written in clear text
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# localhost redirect handler
# --------------------------------------------------------------------------- #
class OAuthHandler(BaseHTTPRequestHandler):
    """Catches ``http://localhost:54321/?code=...`` after the browser login."""

    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            self.server.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family: sans-serif; background: #1e1e2e;"
                b" color: white; display: flex; align-items: center;"
                b" justify-content: center; height: 100vh;'><div><h1>Success!</h1>"
                b"<p>Authentication complete. You can close this window and"
                b" return to the app.</p></div></body></html>")
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):      # keep the console clean
        pass


# --------------------------------------------------------------------------- #
# manager
# --------------------------------------------------------------------------- #
class CloudSyncManager(QObject):
    auth_finished = pyqtSignal(bool, str)
    sync_progress = pyqtSignal(int, str)
    sync_finished = pyqtSignal(bool, str)
    profile_updated = pyqtSignal()

    def __init__(self, project_root):
        super().__init__()
        self.project_root = project_root or os.getcwd()
        self.access_token = None
        self.refresh_token = None
        self.user_email = None
        self.user_name = None
        self.token_file = os.path.join(self.project_root, TOKEN_FILE)
        self.local_port = LOCAL_PORT
        self.load_token()

    # -- credentials ---------------------------------------------------- #
    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.access_token}"}

    def _ensure_token(self):
        """Refresh the access token when the API says it expired."""
        return bool(self.access_token) or self._refresh_access_token()

    def _refresh_access_token(self):
        if not self.refresh_token or not is_configured():
            return False
        try:
            response = http_post(TOKEN_URL, data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            }, timeout=20, max_retries=2)
            if response.status_code == 200:
                payload = response.json()
                self.access_token = payload.get("access_token") or self.access_token
                self.save_token()
                return bool(self.access_token)
        except (RequestException, ValueError):
            pass
        return False

    def load_token(self):
        if not os.path.exists(self.token_file):
            return
        try:
            with open(self.token_file, "r", encoding="utf-8") as handle:
                stored = handle.read().strip()
            decrypted = _unprotect(stored)
            if not decrypted:
                return
            data = json.loads(decrypted)
            self.access_token = data.get("access_token") or None
            self.refresh_token = data.get("refresh_token") or None
            self.user_email = data.get("email") or None
            self.user_name = data.get("name") or None
        except Exception:
            pass

    def save_token(self):
        payload = json.dumps({
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "email": self.user_email,
            "name": self.user_name,
        })
        try:
            with open(self.token_file, "w", encoding="utf-8") as handle:
                handle.write(_protect(payload))
        except OSError:
            pass

    def logout(self):
        self.access_token = None
        self.refresh_token = None
        self.user_email = None
        self.user_name = None
        try:
            if os.path.exists(self.token_file):
                os.remove(self.token_file)
        except OSError:
            pass
        avatar = self._avatar_path()
        try:
            if avatar and os.path.exists(avatar):
                os.remove(avatar)
        except OSError:
            pass
        self.profile_updated.emit()

    # -- profile -------------------------------------------------------- #
    def _avatar_path(self):
        return os.path.join(self.project_root, "cache", "profile_avatar.png")

    def fetch_user_profile(self, background=True):
        """Load name/e-mail/avatar; emits :attr:`profile_updated` when done."""
        if not self.access_token:
            return
        if background:
            threading.Thread(target=self._fetch_profile_thread, daemon=True).start()
        else:
            self._fetch_profile_thread()

    def _fetch_profile_thread(self):
        try:
            if not self._ensure_token():
                return
            response = http_get(USERINFO_URL, headers=self._auth_headers(),
                                timeout=15, max_retries=2)
            if response.status_code == 401 and self._refresh_access_token():
                response = http_get(USERINFO_URL, headers=self._auth_headers(),
                                    timeout=15, max_retries=2)
            if response.status_code != 200:
                return
            info = response.json()
            self.user_name = info.get("name") or self.user_name or ""
            self.user_email = info.get("email") or self.user_email
            self.save_token()
            picture = info.get("picture")
            if picture:
                self._download_avatar(picture)
            self.profile_updated.emit()
        except (RequestException, ValueError, OSError):
            pass

    def _download_avatar(self, picture_url):
        try:
            response = cdn_get(picture_url, max_retries=2, timeout=15)
            if response.status_code != 200 or not response.content:
                return
            avatar = self._avatar_path()
            os.makedirs(os.path.dirname(avatar), exist_ok=True)
            tmp = avatar + ".part"
            with open(tmp, "wb") as handle:
                handle.write(response.content)
            os.replace(tmp, avatar)
        except (RequestException, OSError):
            pass

    # -- login ---------------------------------------------------------- #
    def login(self):
        if not is_configured():
            self.auth_finished.emit(False, "Cloud Sync is not configured: set "
                                           "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.")
            return
        threading.Thread(target=self._login_thread, daemon=True).start()

    def _login_thread(self):
        server = None
        try:
            server = HTTPServer(("localhost", self.local_port), OAuthHandler)
            server.auth_code = None
            server.timeout = 1

            auth_url = (
                f"{AUTH_URL}?client_id={quote(CLIENT_ID)}"
                f"&redirect_uri={quote(REDIRECT_URI)}"
                "&response_type=code"
                f"&scope={quote(' '.join(SCOPES))}"
                "&access_type=offline&prompt=consent"
            )
            webbrowser.open(auth_url)

            started = time.time()
            while not server.auth_code and time.time() - started < LOGIN_TIMEOUT:
                server.handle_request()

            if not server.auth_code:
                self.auth_finished.emit(False, "Login timed out or cancelled.")
                return

            response = http_post(TOKEN_URL, data={
                "code": server.auth_code,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            }, timeout=30, max_retries=2)

            if response.status_code != 200:
                self.auth_finished.emit(False, f"Token exchange failed: {response.text[:300]}")
                return

            payload = response.json()
            granted = (payload.get("scope") or "").split()
            if "https://www.googleapis.com/auth/drive.appdata" not in granted:
                self.auth_finished.emit(False, "Permission denied: You must check the "
                                               "Google Drive box for sync to work.")
                return

            self.access_token = payload.get("access_token")
            self.refresh_token = payload.get("refresh_token")
            self.user_email = None
            self.user_name = None
            self.save_token()
            self._fetch_profile_thread()          # fills user_email/user_name
            self.auth_finished.emit(True, self.user_email or self.user_name or "")
        except RequestException as exc:
            self.auth_finished.emit(False, str(exc))
        except OSError as exc:
            self.auth_finished.emit(False, f"Cannot start the local login server on port "
                                           f"{self.local_port}: {exc}")
        except Exception as exc:                   # pragma: no cover
            self.auth_finished.emit(False, str(exc))
        finally:
            if server is not None:
                try:
                    server.server_close()
                except Exception:
                    pass

    # -- backup --------------------------------------------------------- #
    def backup(self):
        if not self.access_token:
            self.sync_finished.emit(False, "Not logged in")
            return
        if not is_configured():
            self.sync_finished.emit(False, "Cloud Sync is not configured: set "
                                           "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.")
            return
        threading.Thread(target=self._backup_thread, daemon=True).start()

    def _build_backup_zip(self, zip_path):
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for folder in ("imports", "theme"):
                path = os.path.join(self.project_root, folder)
                if not os.path.exists(path):
                    continue
                for root, _dirs, files in os.walk(path):
                    for name in files:
                        full = os.path.join(root, name)
                        try:
                            archive.write(full, os.path.relpath(full, self.project_root))
                        except OSError:
                            continue
            shell_nss = os.path.join(self.project_root, "shell.nss")
            if os.path.exists(shell_nss):
                archive.write(shell_nss, "shell.nss")

    def _find_backup(self, headers):
        """Return ``(file_id, response)``; ``response`` may need a token refresh."""
        search_url = f"{DRIVE_FILES_URL}?spaces=appDataFolder&q=name='{BACKUP_NAME}'"
        response = http_get(search_url, headers=headers, timeout=20, max_retries=2)
        if response.status_code == 401 and self._refresh_access_token():
            response = http_get(search_url, headers=self._auth_headers(),
                                timeout=20, max_retries=2)
        if response.status_code != 200:
            return None, response
        files = (response.json() or {}).get("files", [])
        return (files[0].get("id") if files else None), response

    def _backup_thread(self):
        zip_path = os.path.join(self.project_root, BACKUP_NAME)
        try:
            self.sync_progress.emit(10, "Compressing files...")
            self._build_backup_zip(zip_path)
            with open(zip_path, "rb") as handle:
                payload = handle.read()

            self.sync_progress.emit(40, "Syncing with Google Drive...")
            file_id, response = self._find_backup(self._auth_headers())
            if response.status_code != 200:
                self.sync_finished.emit(False, f"Search failed: {response.text[:300]}")
                return
            headers = self._auth_headers()

            if file_id:
                response = http_patch(f"{DRIVE_UPLOAD_URL}/{file_id}?uploadType=media",
                                      headers=headers, data=payload,
                                      timeout=120, max_retries=2)
            else:
                metadata = json.dumps({"name": BACKUP_NAME, "parents": ["appDataFolder"]})
                response = http_post(f"{DRIVE_UPLOAD_URL}?uploadType=multipart",
                                     headers=headers,
                                     files={"data": ("metadata", metadata, "application/json"),
                                            "file": (BACKUP_NAME, payload, "application/zip")},
                                     timeout=120, max_retries=2)

            if response.status_code in (200, 201):
                self.sync_progress.emit(100, "Backup complete!")
                self.sync_finished.emit(True, "Backup successfully synced to Google Drive.")
            else:
                self.sync_finished.emit(False, f"Upload failed: {response.text[:300]}")
        except RequestException as exc:
            self.sync_finished.emit(False, str(exc))
        except Exception as exc:                   # pragma: no cover
            self.sync_finished.emit(False, str(exc))
        finally:
            try:
                if os.path.exists(zip_path):
                    os.remove(zip_path)
            except OSError:
                pass

    # -- restore -------------------------------------------------------- #
    def restore(self):
        if not self.access_token:
            self.sync_finished.emit(False, "Not logged in")
            return
        if not is_configured():
            self.sync_finished.emit(False, "Cloud Sync is not configured: set "
                                           "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.")
            return
        threading.Thread(target=self._restore_thread, daemon=True).start()

    def _restore_thread(self):
        zip_path = os.path.join(self.project_root, "restore.zip")
        try:
            self.sync_progress.emit(10, "Searching for backup...")
            file_id, response = self._find_backup(self._auth_headers())
            if response.status_code != 200:
                self.sync_finished.emit(False, f"Search failed: {response.text[:300]}")
                return
            if not file_id:
                self.sync_finished.emit(False, "No backup found in Google Drive.")
                return

            self.sync_progress.emit(30, "Downloading from Google Drive...")
            response = http_get(f"{DRIVE_FILES_URL}/{file_id}?alt=media",
                                headers=self._auth_headers(), timeout=120,
                                max_retries=2, stream=True)
            if response.status_code != 200:
                self.sync_finished.emit(False, f"Download failed: {response.text[:300]}")
                return

            with open(zip_path, "wb") as handle:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        handle.write(chunk)
            response.close()

            self.sync_progress.emit(70, "Extracting files...")
            with zipfile.ZipFile(zip_path, "r") as archive:
                # a 1:1 restore: drop the managed folders before unpacking
                for folder in ("imports", "theme"):
                    path = os.path.join(self.project_root, folder)
                    if os.path.exists(path):
                        shutil.rmtree(path, ignore_errors=True)
                archive.extractall(self.project_root)

            self.sync_progress.emit(100, "Restore complete!")
            self.sync_finished.emit(True, "Settings successfully restored. "
                                          "Please restart the app.")
        except RequestException as exc:
            self.sync_finished.emit(False, str(exc))
        except (zipfile.BadZipFile, OSError) as exc:
            self.sync_finished.emit(False, f"Restore failed: {exc}")
        except Exception as exc:                   # pragma: no cover
            self.sync_finished.emit(False, str(exc))
        finally:
            try:
                if os.path.exists(zip_path):
                    os.remove(zip_path)
            except OSError:
                pass
