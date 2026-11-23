"""Enable query and cache comparisons in the isolated benchmark process."""

import os
from contextvars import ContextVar
from functools import wraps
from uuid import uuid4

from django.db import connection
from server.asgi import application as application

# Import models only after Django ASGI initializes the application registry.
from tickets import timeline, views  # noqa: E402

dashboard_cache = ContextVar("dashboard_cache", default=None)
_CACHE_MISS = object()


def without_timeline_prefetch(objects, *lookups):
    (ticket,) = objects
    for lookup in lookups:
        rows = lookup.queryset.select_related(None)
        stop = rows.query.high_mark
        rows.query.clear_limits()
        setattr(ticket, lookup.to_attr, list(rows.filter(ticket=ticket)[:stop]))


class MeasuredDashboardCache:
    def __init__(self, backend):
        self.backend = backend

    def __getattr__(self, name):
        return getattr(self.backend, name)

    def get(self, key, default=None, *args, **kwargs):
        result = self.backend.get(key, _CACHE_MISS, *args, **kwargs)
        if result is _CACHE_MISS:
            dashboard_cache.set("miss")
            return default
        dashboard_cache.set("hit")
        return result


def unique_dashboard_key(original):
    @wraps(original)
    def key(*args, **kwargs):
        return f"{original(*args, **kwargs)}:{uuid4().hex}"

    return key


def measure_queries(handler):
    @wraps(handler)
    def measured(self, request, *args, **kwargs):
        queries = 0

        def count(execute, sql, params, many, context):
            nonlocal queries
            queries += 1
            return execute(sql, params, many, context)

        token = dashboard_cache.set(None)
        try:
            with connection.execute_wrapper(count):
                response = handler(self, request, *args, **kwargs)
            response["X-Load-Queries"] = str(queries)
            if status := dashboard_cache.get():
                response["X-Load-Dashboard"] = status
            return response
        finally:
            dashboard_cache.reset(token)

    return measured


def configure():
    orm = os.environ["TF_LOAD_ORM"]
    dashboard = os.environ["TF_LOAD_DASHBOARD"]
    if orm not in {"n+1", "optimized"} or dashboard not in {"cold", "hot"}:
        raise ValueError("Use TF_LOAD_ORM=n+1|optimized and TF_LOAD_DASHBOARD=cold|hot")
    if orm == "n+1":
        views.TicketViewSet.auto_prefetch_related = False
        views.TicketViewSet.select_related_fields = ()
        timeline.prefetch_related_objects = without_timeline_prefetch
    if dashboard == "cold":
        views.dashboard_key = unique_dashboard_key(views.dashboard_key)
    views.cache = MeasuredDashboardCache(views.cache)
    for action in ("list", "retrieve", "dashboard"):
        handler = getattr(views.TicketViewSet, action)
        setattr(views.TicketViewSet, action, measure_queries(handler))


configure()
