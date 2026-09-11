"""Contract tests for the reconstructed backend modules.

``github_client.py`` and ``cloud_sync.py`` are not in the upstream repository,
so these tests pin the API the launcher actually depends on: every name imported
from them, the ``requests``-like ``Response`` surface, the ``CloudSyncManager``
signals/attributes/methods used by ``launcher.pyw``, plus live behaviour that can
be verified offline (local file downloads, cancellation, DNS failures).

Run:  python tools/test_github_client.py            (offline safe)
      python tools/test_github_client.py --live     (also hits api.github.com)
"""

import ast
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
LAUNCHER = os.path.dirname(HERE)
sys.path.insert(0, LAUNCHER)

LIVE = "--live" in sys.argv

PASS = FAIL = SKIP = 0


def check(condition, label, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ok    {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}" + (f"  -> {detail}" if detail else ""))


def skip(label, detail=""):
    global SKIP
    SKIP += 1
    print(f"  skip  {label}" + (f"  ({detail})" if detail else ""))


def section(title):
    print(f"\n=== {title} ===")


# --------------------------------------------------------------------------- #
section("imports used by the launcher exist")
import github_client                                          # noqa: E402

WANTED = {}
PLAIN_IMPORTS = set()
for name in os.listdir(LAUNCHER):
    if not name.endswith((".py", ".pyw")) or name.startswith("github_client"):
        continue
    path = os.path.join(LAUNCHER, name)
    try:
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("github_client", "cloud_sync"):
            for alias in node.names:
                WANTED.setdefault(node.module, set()).add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("github_client", "cloud_sync"):
                    PLAIN_IMPORTS.add(alias.name)

check("github_client" in WANTED or "github_client" in PLAIN_IMPORTS,
      "the repo really imports github_client")
for module, names in sorted(WANTED.items()):
    if module == "cloud_sync":
        continue                                              # checked below (needs Qt)
    for symbol in sorted(names):
        check(hasattr(github_client, symbol), f"github_client.{symbol} exists")

import cloud_sync                                             # noqa: E402
for symbol in sorted(WANTED.get("cloud_sync", ())):
    check(hasattr(cloud_sync, symbol), f"cloud_sync.{symbol} exists")

check(github_client.RequestException is not Exception, "RequestException is a real class")
check(issubclass(github_client.DownloadCancelled, github_client.RequestException),
      "DownloadCancelled is a RequestException")


# --------------------------------------------------------------------------- #
section("Response mimics requests.Response")
response = github_client.Response(
    "https://example/x", 200,
    [("Content-Type", "application/json"), ("X-RateLimit-Remaining", "42")],
    body=b'{"a": 1}')
check(response.status_code == 200, ".status_code")
check(response.headers.get("content-type") == "application/json", ".headers is case-insensitive")
check(response.headers.get("X-RATELIMIT-REMAINING") == "42", ".headers lookup by any case")
check(response.headers.get("missing", "d") == "d", ".headers.get default")
check(response.json() == {"a": 1}, ".json()")
check(response.text == '{"a": 1}', ".text")
check(response.content == b'{"a": 1}', ".content")
check(response.ok is True, ".ok")
check(list(response.iter_content(chunk_size=4)) == [b'{"a"', b": 1}"], ".iter_content on a buffered body")
try:
    github_client.Response("u", 404, [], body=b"").raise_for_status()
    check(False, "raise_for_status() raises on 4xx")
except github_client.RequestException as exc:
    check(exc.status_code == 404, "raise_for_status() raises with the status code")

bad_json = github_client.Response("u", 200, [], body=b"<html>")
try:
    bad_json.json()
    check(False, ".json() on garbage raises RequestException")
except github_client.RequestException:
    check(True, ".json() on garbage raises RequestException")

# multipart body used by the Drive upload
body, content_type = github_client._encode_multipart(
    {"a": "1"}, {"file": ("backup.zip", b"PK\x03\x04", "application/zip")})
check(content_type.startswith("multipart/form-data; boundary="), "multipart content type")
check(b'name="a"' in body and b"1" in body, "multipart carries the metadata field")
check(b'filename="backup.zip"' in body and b"PK\x03\x04" in body, "multipart carries the file part")


# --------------------------------------------------------------------------- #
section("offline behaviour")
try:
    github_client.github_api_get("https://no-such-host-ima-menu.invalid/x",
                                max_retries=1, timeout=3)
    check(False, "unreachable host raises RequestException")
except github_client.RequestException as exc:
    check(True, f"unreachable host raises RequestException ({str(exc)[:40]}...)")

source = os.path.join(tempfile.mkdtemp(), "payload.bin")
with open(source, "wb") as handle:
    handle.write(b"x" * 500000)

target = os.path.join(tempfile.mkdtemp(), "nested", "payload.bin")
seen = []
github_client.download_file(source, target, progress_callback=seen.append)
check(os.path.getsize(target) == 500000, "download_file copies a local path")
check(seen and seen[-1] == 100, "progress ends at 100")

state = {"calls": 0}


def cancel_after_two_calls():
    state["calls"] += 1
    return state["calls"] > 2


cancelled_target = os.path.join(tempfile.mkdtemp(), "nope.bin")
try:
    github_client.download_file(f"file://{source}", cancelled_target,
                               cancel_check=cancel_after_two_calls, chunk_size=1024)
    check(False, "cancel_check stops the download")
except github_client.DownloadCancelled:
    check(True, "cancel_check stops the download")
check(not os.path.exists(cancelled_target) and not os.path.exists(cancelled_target + ".part"),
      "a cancelled download leaves no partial file")

try:
    github_client.download_file(f"file://{source}", os.path.join(tempfile.mkdtemp(), "bad.bin"),
                               expected_sha256="0" * 64)
    check(False, "checksum mismatch is detected")
except github_client.RequestException:
    check(True, "checksum mismatch is detected")

check(github_client.get_latest_tree_sha("", "main") == "", "empty repo returns '' without network")
check(github_client.get_latest_tree_sha("iMAboud/does-not-exist-xyz", "main", timeout=6) == "",
      "unknown repo returns '' (callers fall back to their cache)")


# --------------------------------------------------------------------------- #
section("CloudSyncManager contract (launcher.pyw)")
from PyQt5.QtCore import QCoreApplication                    # noqa: E402

_app = QCoreApplication.instance() or QCoreApplication(sys.argv)

root = tempfile.mkdtemp()
manager = cloud_sync.CloudSyncManager(root)

for signal in ("auth_finished", "sync_progress", "sync_finished", "profile_updated"):
    check(hasattr(manager, signal), f"signal .{signal}")
for attr in ("access_token", "user_name", "user_email"):
    check(hasattr(manager, attr), f"attribute .{attr}")
for method in ("login", "logout", "backup", "restore", "fetch_user_profile",
               "load_token", "save_token"):
    check(callable(getattr(manager, method, None)), f"method .{method}()")

received = []
manager.auth_finished.connect(lambda ok, msg: received.append(("auth", ok, msg)))
manager.sync_finished.connect(lambda ok, msg: received.append(("sync", ok, msg)))
manager.sync_progress.connect(lambda pct, msg: received.append(("progress", pct, msg)))
profile_events = []
manager.profile_updated.connect(lambda: profile_events.append(True))

manager.login()                       # no credentials configured -> instant answer
manager.backup()
manager.restore()
deadline = threading.Event()
deadline.wait(0.2)                    # let queued signals settle
check(any(kind == "auth" and ok is False for kind, ok, _ in received),
      "login() without credentials reports failure instead of hanging")
check(any(kind == "sync" and ok is False for kind, ok, _ in received),
      "backup()/restore() without a token report failure")
check(cloud_sync.is_configured() is False, "is_configured() is False for the placeholder ids")

# token round-trip through the DPAPI/base64 wrapper
manager.access_token = "ya29.fake"
manager.refresh_token = "1//fake"
manager.user_email = "user@example.com"
manager.user_name = "Test User"
manager.save_token()
check(os.path.exists(manager.token_file), "save_token() writes .cloud_token.dat")
raw = open(manager.token_file, encoding="utf-8").read()
check("ya29.fake" not in raw, "the stored token is not plain text")
reloaded = cloud_sync.CloudSyncManager(root)
check(reloaded.access_token == "ya29.fake" and reloaded.user_email == "user@example.com"
      and reloaded.user_name == "Test User", "load_token() restores the session")
reloaded.profile_updated.connect(lambda: profile_events.append(True))
reloaded.logout()
check(reloaded.access_token is None and not os.path.exists(reloaded.token_file),
      "logout() clears the session and the token file")
check(profile_events, "logout() emits profile_updated so the UI refreshes")


# --------------------------------------------------------------------------- #
section("live GitHub API")
if not LIVE:
    skip("live checks", "run with --live")
else:
    try:
        limit = github_client.github_api_get(f"{github_client.GITHUB_API}/rate_limit",
                                             max_retries=1, timeout=8)
        check(limit.status_code == 200, "GET /rate_limit -> 200")
        check("resources" in limit.json(), "the JSON body parses")

        sha = github_client.get_latest_tree_sha("iMAboud/iMA-Menu-Plugins", "main", timeout=8)
        check(len(sha) == 40 and all(c in "0123456789abcdef" for c in sha),
              f"get_latest_tree_sha returns a tree sha ({sha[:10]}...)")

        tree = github_client.github_api_get(
            f"{github_client.GITHUB_API}/repos/iMAboud/iMA-Menu-Plugins/git/trees/{sha}?recursive=true",
            max_retries=2, timeout=10)
        check(tree.status_code == 200 and isinstance(tree.json().get("tree"), list),
              "the tree sha feeds /git/trees/{sha}?recursive=true")

        missing = github_client.github_api_get(
            "https://api.github.com/repos/iMAboud/nope-does-not-exist", max_retries=1, timeout=8)
        check(missing.status_code == 404 and missing.ok is False, "404 comes back as a Response")

        stream = github_client.cdn_get(
            "https://codeload.github.com/iMAboud/iMA-Menu-Updater/tar.gz/refs/heads/main",
            max_retries=1, timeout=30, stream=True)
        first = next(stream.iter_content(chunk_size=4096), b"")
        stream.close()
        check(first[:2] == b"\x1f\x8b", "cdn_get(stream=True) yields raw body chunks")
    except github_client.RequestException as exc:
        skip("live checks aborted", str(exc)[:60])


# --------------------------------------------------------------------------- #
print("\n" + "=" * 62)
if FAIL:
    print(f"{FAIL} of {PASS + FAIL} checks FAILED ({SKIP} skipped).")
    sys.exit(1)
print(f"All {PASS} checks passed" + (f" ({SKIP} skipped)." if SKIP else "."))
