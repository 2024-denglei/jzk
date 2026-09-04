-- 去掉用不到的运营/检测字段；标本数量默认改为 10
DROP INDEX IF EXISTS donor.idx_donors_availability;

ALTER TABLE donor.donors
    DROP COLUMN IF EXISTS availability,
    DROP COLUMN IF EXISTS semen_test,
    DROP COLUMN IF EXISTS blood_test,
    DROP COLUMN IF EXISTS chromosome_test,
    DROP COLUMN IF EXISTS microbio_test,
    DROP COLUMN IF EXISTS remark;

ALTER TABLE donor.donors
    ALTER COLUMN specimen_count SET DEFAULT 10;

UPDATE donor.donors
SET specimen_count = 10
WHERE specimen_count IS NULL OR specimen_count = 0;
