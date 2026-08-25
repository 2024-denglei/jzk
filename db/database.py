"""数据库入口：PostgreSQL 官方库（兼容旧 import 路径）。"""

from db.pg import bootstrap_admin, connect, db_session, ensure_schema, init_db

get_connection = connect

__all__ = ["connect", "get_connection", "db_session", "init_db", "ensure_schema", "bootstrap_admin"]
