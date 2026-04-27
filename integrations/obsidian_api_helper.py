"""
Obsidian REST API helper with fallback support.
Usage: from obsidian_api_helper import obsidian_put, obsidian_get
"""
import requests
from pathlib import Path

_HOSTS = ["100.127.0.9", "100.127.0.8"]  # 사무실 PC → 서피스 순
_PORT = 27124
_KEY = "99d25dd9153c5b061525b25ba9837759cb146a7a8a6948a68f609e2e5f97b02c"
_USE_HTTPS = True

def _cfg():
    """호스트별 키 매핑 반환: [(host, key), ...]"""
    conf = Path.home() / ".obsidian_api.conf"
    if conf.exists():
        d = dict(l.strip().split("=", 1) for l in conf.read_text().splitlines() if "=" in l and not l.startswith("#"))
        # 형식 1: OBSIDIAN_API_KEY=... (단일 키)
        if "OBSIDIAN_API_KEY" in d:
            return [(h, d["OBSIDIAN_API_KEY"]) for h in _HOSTS], int(d.get("OBSIDIAN_PORT", _PORT))
        # 형식 2: 호스트별 키
        pairs = []
        mini_host = d.get("OBSIDIAN_HOST_MINI", "100.127.0.9")
        mini_key  = d.get("OBSIDIAN_KEY_MINI", _KEY)
        svc_host  = d.get("OBSIDIAN_HOST_SERVICE", "100.127.0.8")
        svc_key   = d.get("OBSIDIAN_KEY_SERVICE", _KEY)
        pairs = [(mini_host, mini_key), (svc_host, svc_key)]
        return pairs, _PORT
    return [(h, _KEY) for h in _HOSTS], _PORT

def _request(method, path, **kwargs):
    host_keys, port = _cfg()
    extra_headers = kwargs.pop("headers", {})
    for host, key in host_keys:
        scheme = "https" if _USE_HTTPS else "http"
        url = f"{scheme}://{host}:{port}{path}"
        headers = dict(extra_headers)
        headers["Authorization"] = f"Bearer {key}"
        try:
            r = requests.request(method, url, headers=headers, timeout=5, verify=False, **kwargs)
            return r
        except Exception:
            continue
    raise ConnectionError(f"Obsidian API 연결 실패: {[h for h,_ in host_keys]}")

def obsidian_put(vault_path, content):
    from urllib.parse import quote
    return _request("PUT", f"/vault/{quote(vault_path)}",
                    headers={"Content-Type": "text/markdown"},
                    data=content.encode() if isinstance(content, str) else content)

def obsidian_get(vault_path):
    from urllib.parse import quote
    return _request("GET", f"/vault/{quote(vault_path)}")
