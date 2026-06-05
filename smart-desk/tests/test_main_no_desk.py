"""Tests verifying main.py works without desk_coordinator dependency."""
import pytest


def test_app_imports_without_desk_coordinator():
    """Verify app can be imported without desk_coordinator being loaded as dependency."""
    import sys
    # Remove desk_coordinator from sys.modules to force fresh import check
    desk_mod = sys.modules.pop("backend.services.desk_coordinator", None)
    try:
        from backend.main import app
        assert app is not None
        assert len(app.routes) > 0
    finally:
        # Restore module if it was removed
        if desk_mod is not None:
            sys.modules["backend.services.desk_coordinator"] = desk_mod


def test_main_does_not_import_desk_coordinator():
    """Verify main.py module source does not import desk_coordinator."""
    import inspect
    from backend import main as main_module
    source = inspect.getsource(main_module)
    # desk_coordinator should not be imported at top level in main.py
    assert "from backend.services.desk_coordinator import" not in source, (
        "main.py should not import from desk_coordinator"
    )
