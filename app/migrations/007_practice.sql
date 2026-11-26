BEGIN;

ALTER TABLE "Contest" ADD COLUMN kind VARCHAR(10) NOT NULL DEFAULT 'exam'
    CONSTRAINT contest_kind_check CHECK (kind IN ('exam', 'practice'));
DROP INDEX IF EXISTS idx_contest_open;
CREATE INDEX idx_contest_open ON "Contest" (kind, open DESC);

COMMIT;
