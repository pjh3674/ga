# ── REST API 폴백 ────────────────────────────────────────────────────────────
try:
    _obsidian_dir = str(Path.home() / "obsidian")
    if _obsidian_dir not in sys.path:
        sys.path.insert(0, _obsidian_dir)
    import importlib

    if "obsidian_api_helper" in sys.modules:
        del sys.modules["obsidian_api_helper"]
    from integrations.obsidian_api_helper import obsidian_put as _obsidian_put
    _REST_AVAILABLE = True
except Exception:
    _REST_AVAILABLE = False
    _obsidian_put = None

