"""刷新进程内捐精人缓存：仓储取数 + 领域编码器。"""

from core.runtime_cache import refresh_donor_cache as apply_donor_cache
from core.runtime_cache import update_donor_status_cache
from db.donors_repo import load_donor_data


def refresh_donor_cache(app) -> dict:
    return apply_donor_cache(app, load_donor_data())


__all__ = ["refresh_donor_cache", "update_donor_status_cache"]
