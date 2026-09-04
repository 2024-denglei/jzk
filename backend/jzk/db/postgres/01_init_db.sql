-- 库级初始化（Docker 已创建数据库 jzk；政务侧可先 CREATE DATABASE jzk 再执行本脚本）
-- 扩展与 Schema

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE SCHEMA IF NOT EXISTS donor;
CREATE SCHEMA IF NOT EXISTS admin;
CREATE SCHEMA IF NOT EXISTS app;

COMMENT ON SCHEMA donor IS '捐精人主数据与导入/审计';
COMMENT ON SCHEMA admin IS '管理端账号与角色';
COMMENT ON SCHEMA app IS '前台用户、收藏、历史、偏好、对话';
