-- 分支标签采用固定、短名称：主线、分支1、分支2……

WITH normalized AS (
  SELECT id,
         CASE
           WHEN fork_reason = 'root' THEN '主线'
           ELSE '分支' || row_number() OVER (
             PARTITION BY chat_id, (fork_reason = 'root')
             ORDER BY created_at, id
           )::text
         END AS normalized_name
  FROM app.chat_branches
)
UPDATE app.chat_branches branch
SET name = normalized.normalized_name,
    system_name = normalized.normalized_name
FROM normalized
WHERE branch.id = normalized.id
  AND (branch.name IS DISTINCT FROM normalized.normalized_name
       OR branch.system_name IS DISTINCT FROM normalized.normalized_name);

COMMENT ON COLUMN app.chat_branches.name IS
  '客户端线路标签：根线路为主线，其余按创建顺序为分支1、分支2……';
