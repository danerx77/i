"""Minimal HTTP client for the iMA Menu launcher.

The launcher is packaged without ``requests`` (see the ``excludes`` list in
``launcher.spec``), so this module implements the small slice of the
``requests`` API that the launcher, the plugin workers, the theme switcher and
the cursor browser actually use -- on top of :mod:`urllib` from the standard
library.

Public API
----------
``github_api_get(url, max_retries=2, timeout=10)``
    GET against ``api.github.com`` with the headers GitHub expects.
``cdn_get(url, max_retries=2, timeout=15, stream=False)``
    GET against anything else (raw.githubusercontent.com, release assets,
    image CDNs...).  ``stream=True`` keeps the body unread so the caller can
    consume it with :meth:`Response.iter_content`.
``get_latest_tree_sha(repo, branch="main", timeout=10)``
    Tree SHA of a branch head, ready for ``/git/trees/{sha}?recursive=true``.
``download_file(url, dest_path, progress_callback=None, cancel_check=None, ...)``
    Streaming download with integer progress (0-100) and cancellation.
``http_request(method, url, ...)`` / ``http_get`` / ``http_post`` / ``http_patch``
    Generic helpers used by ``cloud_sync.py`` (JSON, urlencoded and multipart
    bodies).

``Response`` mimics ``requests.Response``: ``status_code``, ``headers``
(case-insensitive), ``content``, ``text``, ``json()``, ``ok``,
``raise_for_status()`` and ``iter_content(chunk_size=...)``.

Failures raise :class:`RequestException` (never a bare urllib error), so the
workers can catch one exception type.  Network problems are retried with a
short backoff and ``Retry-After`` is honoured for rate limited calls.

Setting ``GITHUB_TOKEN`` (or ``IMA_GITHUB_TOKEN``) in the environment raises
the API rate limit from 60 to 5000 requests/hour; the launcher works fine
without it.
"""

import gzip
import json as _json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib

__all__ = [
    "RequestException", "DownloadCancelled", "Response",
    "github_api_get", "cdn_get", "get_latest_tree_sha", "download_file",
    "http_request", "http_get", "http_post", "http_patch",
    "USER_AGENT", "GITHUB_API",
]

USER_AGENT = "iMA-Menu-Launcher/2.0 (+https://github.com/iMAboud/iMA-Menu)"
GITHUB_API = "https://api.github.com"

# statuses worth another attempt
_RETRY_STATUS = frozenset((408, 425, 429, 500, 502, 503, 504))
_DEFAULT_CHUNK = 262144


# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #
class RequestException(Exception):
    """Any transport level failure (DNS, TLS, timeout, HTTP error, bad JSON)."""

    def __init__(self, message, status_code=None, url=None):
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class DownloadCancelled(RequestException):
    """Raised by :func:`download_file` when ``cancel_check`` becomes true."""


# --------------------------------------------------------------------------- #
# response object
# --------------------------------------------------------------------------- #
class _CaseInsensitiveDict(dict):
    """Dict with case-insensitive keys, like ``requests.structures``."""

    def __init__(self, items=()):
        super().__init__()
        for key, value in items:
            self[key] = value

    def __setitem__(self, key, value):
        super().__setitem__(key.lower(), value)

    def __getitem__(self, key):
        return super().__getitem__(key.lower())

    def __contains__(self, key):
        return super().__contains__(key.lower())

    def get(self, key, default=None):
        return super().get(key.lower(), default)

    def pop(self, key, *args):
        return super().pop(key.lower(), *args)


class Response:
    """A tiny stand-in for ``requests.Response``."""

    def __init__(self, url, status_code, headers, body=None, raw=None, reason=""):
        self.url = url
        self.status_code = int(status_code)
        self.headers = _CaseInsensitiveDict(headers or ())
        self.reason = reason
        self.encoding = "utf-8"
        self._body = body            # None while the body is still streaming
        self._raw = raw              # open urllib response for streamed bodies

    # -- body ------------------------------------------------------------- #
    @property
    def content(self):
        if self._body is None:
            self._body = self._read_all()
        return self._body

    @property
    def text(self):
        return self.content.decode(self.encoding, errors="replace")

    def json(self):
        try:
            return _json.loads(self.content.decode(self.encoding, errors="replace"))
        except ValueError as exc:
            raise RequestException(f"Invalid JSON from {self.url}: {exc}",
                                   self.status_code, self.url) from exc

    def iter_content(self, chunk_size=_DEFAULT_CHUNK, decode_unicode=False):
        """Yield the body in chunks.  Reads whatever is still on the wire."""
        if self._body is not None:                     # already buffered
            data = self._body
            for i in range(0, len(data), chunk_size):
                yield data[i:i + chunk_size]
            return
        if self._raw is None:
            return
        while True:
            chunk = self._raw.read(chunk_size)
            if not chunk:
                break
            yield chunk
        self.close()

    # -- helpers ---------------------------------------------------------- #
    @property
    def ok(self):
        return self.status_code < 400

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RequestException(
                f"HTTP {self.status_code} for {self.url}", self.status_code, self.url)
        return self

    def close(self):
        if self._raw is not None:
            try:
                self._raw.close()
            except Exception:
                pass
            self._raw = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def __repr__(self):
        return f"<Response [{self.status_code}] {self.url}>"

    # -- internals -------------------------------------------------------- #
    def _read_all(self):
        if self._raw is None:
            return b""
        try:
            data = self._raw.read()
        finally:
            self.close()
        return _decompress(data, self.headers.get("content-encoding"))


def _decompress(data, encoding):
    if not data or not encoding:
        return data
    encoding = encoding.lower()
    try:
        if "gzip" in encoding:
            return gzip.decompress(data)
        if "deflate" in encoding:
            try:
                return zlib.decompress(data)
            except zlib.error:
                return zlib.decompress(data, -zlib.MAX_WBITS)
        if "br" in encoding:
            try:
                import brotli  # optional, not bundled
            except ImportError:
                return data
            return brotli.decompress(data)
    except Exception:
        return data
    return data


# --------------------------------------------------------------------------- #
# transport
# --------------------------------------------------------------------------- #
def _github_token():
    return (os.getenv("IMA_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()


def _build_request(method, url, headers=None, data=None, json=None, files=None):
    body = None
    hdrs = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "close",
    }
    if json is not None:
        body = _json.dumps(json).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    elif files:
        body, content_type = _encode_multipart(data or {}, files)
        hdrs["Content-Type"] = content_type
    elif data is not None:
        if isinstance(data, (bytes, bytearray)):
            body = bytes(data)
        elif isinstance(data, str):
            body = data.encode("utf-8")
        else:
            body = urllib.parse.urlencode(data).encode("utf-8")
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    if body is not None:
        hdrs["Content-Length"] = str(len(body))
    for key, value in (headers or {}).items():
        if value is None:
            hdrs.pop(key, None)
        else:
            hdrs[key] = value
    return urllib.request.Request(url, data=body, headers=hdrs, method=method.upper())


def _encode_multipart(fields, files):
    """Build a ``multipart/form-data`` body (``requests``-style ``files=``).

    ``files`` maps a field name to ``(filename, data)`` or
    ``(filename, data, content_type)``.
    """
    boundary = uuid.uuid4().hex
    lines = []
    for name, value in fields.items():
        lines += [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="{name}"'.encode(),
            b"",
            value if isinstance(value, (bytes, bytearray)) else str(value).encode("utf-8"),
        ]
    for name, spec in files.items():
        filename, data = spec[0], spec[1]
        content_type = spec[2] if len(spec) > 2 else "application/octet-stream"
        if isinstance(data, str):
            data = data.encode("utf-8")
        lines += [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'.encode(),
            f"Content-Type: {content_type}".encode(),
            b"",
            bytes(data),
        ]
    lines += [f"--{boundary}--".encode(), b""]
    return b"\r\n".join(lines), f"multipart/form-data; boundary={boundary}"


def _open(request, timeout, context):
    """urlopen that turns every transport failure into a Response or raises."""
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler(urllib.request.getproxies()),
        urllib.request.HTTPSHandler(context=context),
    )
    return opener.open(request, timeout=timeout)


def http_request(method, url, headers=None, data=None, json=None, files=None,
                 timeout=15, max_retries=2, stream=False, retry_statuses=_RETRY_STATUS,
                 raise_for_status=False):
    """Perform an HTTP request and return a :class:`Response`.

    Retries on network errors and on ``retry_statuses`` with a short backoff.
    """
    context = ssl.create_default_context()
    last_error = None
    attempts = max(1, int(max_retries))
    for attempt in range(attempts):
        request = _build_request(method, url, headers, data, json, files)
        response = None
        try:
            try:
                response = _wrap(_open(request, timeout, context), url, stream=stream)
            except urllib.error.HTTPError as exc:             # a real HTTP status
                response = _wrap(exc, exc.geturl() or url, stream=stream,
                                 status=exc.code, reason=getattr(exc, "reason", "") or "")
                if exc.code in retry_statuses and attempt + 1 < attempts:
                    delay = _retry_delay(response.headers, attempt)
                    response.close()
                    response = None
                    time.sleep(delay)
                    continue
        except urllib.error.URLError as exc:
            last_error = _transport_error(url, exc.reason if hasattr(exc, "reason") else exc)
        except (socket.timeout, TimeoutError) as exc:
            last_error = RequestException(f"Timeout after {timeout}s: {url} ({exc})", url=url)
        except ssl.SSLError as exc:
            last_error = RequestException(f"TLS error for {url}: {exc}", url=url)
        except OSError as exc:
            last_error = _transport_error(url, exc)
        except Exception as exc:                               # pragma: no cover
            last_error = RequestException(f"Request failed for {url}: {exc}", url=url)

        if response is not None:
            if raise_for_status and response.status_code >= 400:
                response.raise_for_status()
            return response

        if attempt + 1 < attempts:
            time.sleep(min(2 ** attempt * 0.4, 5.0))

    raise last_error or RequestException(f"Request failed: {url}", url=url)


def _wrap(raw, url, stream=False, status=None, reason=None):
    """Turn an open urllib response (or HTTPError) into a :class:`Response`."""
    headers = raw.headers
    items = list(headers.items()) if headers else []
    code = status if status is not None else getattr(raw, "status", None)
    if code is None:
        try:
            code = raw.getcode()
        except Exception:
            code = None
    if code is None:
        code = 200            # non-HTTP handlers (file://) report no status
    final_url = raw.geturl() if hasattr(raw, "geturl") else url
    response = Response(final_url, code, items, raw=raw,
                        reason=reason if reason is not None else getattr(raw, "reason", "") or "")
    if not stream:
        response.content                     # buffer now, free the socket
    return response


def _transport_error(url, reason):
    text = str(reason)
    lowered = text.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return RequestException(f"Timeout while contacting {url}", url=url)
    if "name or service not known" in lowered or "getaddrinfo" in lowered or "nodename" in lowered:
        return RequestException(f"No internet connection or unknown host for {url}", url=url)
    if "certificate" in lowered or "ssl" in lowered:
        return RequestException(f"TLS/certificate problem for {url}: {text}", url=url)
    return RequestException(f"Network error for {url}: {text}", url=url)


def _retry_delay(headers, attempt):
    retry_after = (headers or {}).get("retry-after")
    if retry_after:
        try:
            return max(0.0, min(float(retry_after), 10.0))
        except ValueError:
            pass
    return min(2 ** attempt * 0.5, 6.0)


# --------------------------------------------------------------------------- #
# public helpers
# --------------------------------------------------------------------------- #
def github_api_get(url, max_retries=2, timeout=10, headers=None, token=None,
                   raise_for_status=False):
    """GET a ``api.github.com`` endpoint with the headers GitHub expects."""
    hdrs = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = token or _github_token()
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    hdrs.update(headers or {})
    response = http_request("GET", url, headers=hdrs, timeout=timeout,
                            max_retries=max_retries, raise_for_status=raise_for_status)
    if response.status_code in (403, 429) and "rate limit" in response.text.lower():
        remaining = response.headers.get("x-ratelimit-remaining")
        reset = response.headers.get("x-ratelimit-reset")
        detail = ""
        if reset:
            try:
                detail = f" (resets in {max(0, int(int(reset) - time.time()) // 60 + 1)} min)"
            except ValueError:
                detail = ""
        raise RequestException(
            f"GitHub API rate limit reached{detail}"
            + (" - set GITHUB_TOKEN to raise it" if not token else ""),
            response.status_code, url)
    return response


def cdn_get(url, max_retries=2, timeout=15, stream=False, headers=None,
            raise_for_status=False):
    """GET a raw file / release asset / image from any CDN.

    With ``stream=True`` the body stays on the wire: consume it with
    :meth:`Response.iter_content` (and read ``Content-Length`` from
    ``response.headers``).
    """
    hdrs = {"Accept": "*/*"}
    hdrs.update(headers or {})
    return http_request("GET", url, headers=hdrs, timeout=timeout,
                        max_retries=max_retries, stream=stream,
                        raise_for_status=raise_for_status)


def http_get(url, **kwargs):
    return http_request("GET", url, **kwargs)


def http_post(url, **kwargs):
    return http_request("POST", url, **kwargs)


def http_patch(url, **kwargs):
    return http_request("PATCH", url, **kwargs)


def get_latest_tree_sha(repo, branch="main", timeout=10, max_retries=2):
    """Return the git *tree* SHA of ``repo``'s ``branch`` head (``""`` on failure).

    The value feeds ``GET /repos/{repo}/git/trees/{sha}?recursive=true``.
    Callers treat an empty string as "remote unavailable" and fall back to
    their local cache, so no exception is raised here.
    """
    repo = (repo or "").strip().strip("/")
    branch = (branch or "main").strip()
    if not repo:
        return ""
    try:
        response = github_api_get(f"{GITHUB_API}/repos/{repo}/branches/{urllib.parse.quote(branch)}",
                                  max_retries=max_retries, timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            tree_sha = ((data.get("commit") or {}).get("commit") or {}).get("tree", {}).get("sha")
            if tree_sha:
                return tree_sha
            commit_sha = (data.get("commit") or {}).get("sha")
            if commit_sha:
                detail = github_api_get(f"{GITHUB_API}/repos/{repo}/git/commits/{commit_sha}",
                                        max_retries=max_retries, timeout=timeout)
                if detail.status_code == 200:
                    return (detail.json().get("tree") or {}).get("sha", "")
    except RequestException:
        pass
    except Exception:
        pass
    return ""


def download_file(url, dest_path, progress_callback=None, cancel_check=None,
                  timeout=120, chunk_size=_DEFAULT_CHUNK, max_retries=3,
                  expected_sha256=None):
    """Download ``url`` to ``dest_path``, reporting integer progress 0-100.

    ``progress_callback(percent)`` is called whenever the percentage changes and
    once more with ``100``.  ``cancel_check()`` is polled between chunks; when
    it returns true the partial file is removed and :class:`DownloadCancelled`
    is raised.
    """
    if not url:
        raise RequestException("download_file() needs a URL", url=url)
    if isinstance(url, str) and os.path.exists(url) and os.path.isfile(url):
        # a local path slipped through: copy instead of downloading
        import shutil
        _ensure_dir(dest_path)
        shutil.copy2(url, dest_path)
        _report(progress_callback, 100)
        return dest_path

    response = cdn_get(url, max_retries=max_retries, timeout=timeout, stream=True)
    if response.status_code >= 400:
        response.close()
        raise RequestException(f"HTTP {response.status_code} while downloading {url}",
                               response.status_code, url)

    total = 0
    try:
        total = int(response.headers.get("content-length") or 0)
    except (TypeError, ValueError):
        total = 0

    _ensure_dir(dest_path)
    part_path = f"{dest_path}.part"
    written = 0
    last_percent = -1
    digest = None
    if expected_sha256:
        import hashlib
        digest = hashlib.sha256()

    try:
        with open(part_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if cancel_check is not None and cancel_check():
                    raise DownloadCancelled(f"Download cancelled: {url}", url=url)
                if not chunk:
                    continue
                handle.write(chunk)
                written += len(chunk)
                if digest is not None:
                    digest.update(chunk)
                if total > 0:
                    percent = min(99, int(written * 100 / total))
                    if percent != last_percent:
                        last_percent = percent
                        _report(progress_callback, percent)
    except DownloadCancelled:
        _remove(part_path)
        raise
    except RequestException:
        _remove(part_path)
        raise
    except OSError as exc:
        _remove(part_path)
        raise RequestException(f"Cannot write {dest_path}: {exc}", url=url) from exc
    finally:
        response.close()

    if written == 0:
        _remove(part_path)
        raise RequestException(f"Downloaded file is empty: {url}", url=url)
    if total > 0 and written < total:
        _remove(part_path)
        raise RequestException(
            f"Incomplete download from {url}: {written}/{total} bytes", url=url)
    if digest is not None and digest.hexdigest().lower() != expected_sha256.lower():
        _remove(part_path)
        raise RequestException(f"Checksum mismatch for {url}", url=url)

    os.replace(part_path, dest_path)
    _report(progress_callback, 100)
    return dest_path


def _ensure_dir(dest_path):
    folder = os.path.dirname(os.path.abspath(dest_path))
    if folder:
        os.makedirs(folder, exist_ok=True)


def _remove(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _report(callback, percent):
    if callback is None:
        return
    try:
        callback(int(percent))
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# diagnostics
# --------------------------------------------------------------------------- #
def connectivity_check(timeout=4):
    """Return ``True`` when api.github.com answers -- used by the workers to
    tell "offline" apart from "no data"."""
    try:
        return github_api_get(f"{GITHUB_API}/rate_limit", max_retries=1,
                              timeout=timeout).status_code == 200
    except RequestException:
        return False


if __name__ == "__main__":  # tiny manual smoke test: python github_client.py
    print("python", sys.version.split()[0])
    print("rate_limit:", github_api_get(f"{GITHUB_API}/rate_limit", max_retries=1, timeout=8).status_code)
    print("tree sha  :", get_latest_tree_sha("iMAboud/iMA-Menu-Plugins", "main", timeout=8))
