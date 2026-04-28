with _conn() as c:
    c.executescript("""
    CREATE TABLE IF NOT EXISTS debates (
