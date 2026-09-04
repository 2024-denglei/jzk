from jzk.api.rate_limit import rate_limiter
from jzk.api.refresh_sessions import refresh_sessions
from jzk.api.verification_codes import verification_codes


def test_security_services_share_one_redis_connection_pool():
    pool = rate_limiter.client.connection_pool
    assert verification_codes.client.connection_pool is pool
    assert refresh_sessions.client.connection_pool is pool
