import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from hashlib import sha256
from uuid import uuid4

from django.core.cache import cache
from django_redis import get_redis_connection
from redis.exceptions import RedisError
from rest_framework.exceptions import APIException, Throttled

TICKET_CACHE_KEY_PREFIX = "ticketflow:ticket:"
IDEMPOTENCY_TTL = 86400
WINDOW_SECONDS = 60
LOCK_WAIT_ATTEMPTS = 20
LOCK_WAIT_INTERVAL = 0.05
RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""
SLIDING_WINDOW = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local period = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - period)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return math.ceil((tonumber(oldest[2]) + period - now) / 1000)
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], period)
return 0
"""


class RateLimitUnavailable(APIException):
    status_code = 503
    default_detail = "限流服务暂时不可用，请稍后重试"


def check_rate(user_id: int, action: str, limit: int) -> None:
    key = cache.make_key(f"{TICKET_CACHE_KEY_PREFIX}rate:{action}:{user_id}")
    try:
        wait = int(get_redis_connection().eval(SLIDING_WINDOW, 1, key, WINDOW_SECONDS * 1000, limit, uuid4().hex))
    except RedisError as exc:
        raise RateLimitUnavailable() from exc
    if wait:
        raise Throttled(wait=wait)


@contextmanager
def reserve_create(key: str) -> Iterator[None]:
    """Serialize duplicate create requests in Redis before hitting DB constraints."""
    lock_key = cache.make_key(f"{key}:lock")
    owner = uuid4().hex
    redis = get_redis_connection()
    acquired = False
    try:
        for _ in range(LOCK_WAIT_ATTEMPTS):
            acquired = bool(redis.set(lock_key, owner, nx=True, ex=15))
            if acquired or cache.get(key) is not None:
                break
            time.sleep(LOCK_WAIT_INTERVAL)
    except RedisError:
        acquired = False
    try:
        yield
    finally:
        if acquired:
            try:
                redis.eval(RELEASE, 1, lock_key, owner)
            except RedisError:
                # 短 TTL 回收未释放的占位，数据库唯一约束仍然生效。
                pass


def request_key(user_id: int, key_hash: str) -> str:
    return f"{TICKET_CACHE_KEY_PREFIX}create:{user_id}:{key_hash}"


def _admin_revision_key() -> str:
    return f"{TICKET_CACHE_KEY_PREFIX}dashboard:rev:admin"


def _user_revision_key(user_id: int) -> str:
    return f"{TICKET_CACHE_KEY_PREFIX}dashboard:rev:user:{user_id}"


def invalidate_dashboard(user_ids: Iterable[int | None] | None = None) -> None:
    """Bump admin revision and affected users' dashboard revisions."""
    revision = uuid4().hex
    cache.set(_admin_revision_key(), revision, timeout=None)
    if user_ids is None:
        cache.set(f"{TICKET_CACHE_KEY_PREFIX}dashboard:revision", revision, timeout=None)
        return
    for user_id in {uid for uid in user_ids if uid is not None}:
        cache.set(_user_revision_key(user_id), revision, timeout=None)


def _get_or_init_revision(revision_key: str) -> str:
    revision = cache.get(revision_key)
    if revision is None:
        token = uuid4().hex
        cache.add(revision_key, token, timeout=None)
        revision = cache.get(revision_key) or token
    return str(revision)


def dashboard_key(user_id: int, sql: str, params: tuple[object, ...], *, is_admin: bool = False) -> str:
    global_rev = _get_or_init_revision(f"{TICKET_CACHE_KEY_PREFIX}dashboard:revision")
    scope_rev = _get_or_init_revision(_admin_revision_key() if is_admin else _user_revision_key(user_id))
    digest = sha256(repr((sql, params)).encode()).hexdigest()
    return f"{TICKET_CACHE_KEY_PREFIX}dashboard:{user_id}:{global_rev}:{scope_rev}:{digest}"
