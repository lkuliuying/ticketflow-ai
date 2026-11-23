import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

from django.core.cache.backends.locmem import LocMemCache

from tickets import views


def test_load_dashboard_cache_preserves_operations_and_measures_reads(monkeypatch, tmp_path):
    class BenchmarkTicketViewSet(views.TicketViewSet):
        pass

    benchmark_app = Path(__file__).resolve().parents[4] / "tests/load/drf_app.py"
    backend = LocMemCache(str(tmp_path), {})
    monkeypatch.setenv("TF_LOAD_ORM", "optimized")
    monkeypatch.setenv("TF_LOAD_DASHBOARD", "hot")
    monkeypatch.setitem(sys.modules, "server.asgi", SimpleNamespace(application=None))
    monkeypatch.setattr(views, "TicketViewSet", BenchmarkTicketViewSet)
    monkeypatch.setattr(views, "cache", backend)
    measurement = runpy.run_path(str(benchmark_app))["dashboard_cache"]
    measured = views.cache

    assert measured.add("counts", {"OPEN": 1}, timeout=30, version=2)
    assert measured.get_many(["counts"], version=2) == {"counts": {"OPEN": 1}}
    assert measurement.get() is None

    assert measured.get("counts", version=2) == {"OPEN": 1}
    assert measurement.get() == "hit"
    assert measured.delete("counts", version=2)
    assert measurement.get() == "hit"

    assert measured.get("counts", default={}, version=2) == {}
    assert measurement.get() == "miss"
    measured.set("counts", {"OPEN": 2}, version=2)
    assert backend.get("counts", version=2) == {"OPEN": 2}
    assert measurement.get() == "miss"
