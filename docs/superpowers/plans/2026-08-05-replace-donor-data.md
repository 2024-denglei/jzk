# 替换捐精人数据 Implementation Plan

> **For agentic workers:** 按任务逐步执行。

**Goal:** 清空 PG 旧捐精人，导入新 3000 条 Excel，详情页按新表字段展示并去掉检测/标本板块。

**Architecture:** Excel → `import_excel_bytes(replace=True)` → `donor.donors` → `refresh_donor_cache`；前端详情读 API 已有字段补齐展示。

**Tech Stack:** PostgreSQL, FastAPI, React/TS, pandas/openpyxl

---

### Task 1: 配置与清库导入

- Modify: `agent/config.py`
- Modify: `agent/db/donors_repo.py`（`clear_all_donors`）
- Modify: `agent/db/donor_import.py`（`replace`）
- Modify: `agent/scripts/seed_donors_from_excel.py`

### Task 2: 前端详情同步

- Modify: `agent/web/src/types.ts`
- Modify: `agent/web/src/components/DonorDetailPanel.tsx`

### Task 3: 执行导入并核对

- 运行 seed `--replace`
- 抽查 API / 字段映射
