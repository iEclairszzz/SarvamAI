import os
import tempfile
import pytest
from pathlib import Path

@pytest.fixture(autouse=True, scope="session")
def setup_test_database():
    """Ensure tests run against a dedicated temporary database, never touching narrator.db."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        test_db_path = tmp.name

    os.environ["DATABASE_PATH"] = test_db_path
    
    # Reload db module with new DB_PATH
    import app.db
    app.db.DB_PATH = Path(test_db_path)
    app.db.init_db()

    yield test_db_path

    try:
        os.remove(test_db_path)
    except OSError:
        pass
