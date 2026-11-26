BEGIN;

ALTER TABLE "Problem" ADD COLUMN is_model BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE "Question" ADD COLUMN is_model BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE "Draft" ADD COLUMN context JSONB;

CREATE TABLE "Standard" (
    "standardId" SERIAL PRIMARY KEY,
    kind       VARCHAR(10) NOT NULL
               CONSTRAINT standard_kind_check CHECK (kind IN ('code', 'question', 'predict')),
    rules      TEXT NOT NULL,
    examples   INTEGER NOT NULL DEFAULT 2
               CONSTRAINT standard_examples_check CHECK (examples BETWEEN 0 AND 5),
    config     JSONB NOT NULL DEFAULT '{}',
    "updatedBy"  INTEGER CONSTRAINT standard_updatedby_fkey REFERENCES "User"("userId"),
    updated    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT standard_kind_key UNIQUE (kind)
);

COMMIT;
