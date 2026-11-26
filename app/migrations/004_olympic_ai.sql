BEGIN;

ALTER TABLE "Problem" ADD COLUMN kind VARCHAR(10) NOT NULL DEFAULT 'code'
    CONSTRAINT problem_kind_check CHECK (kind IN ('code', 'predict'));
ALTER TABLE "Problem" DROP CONSTRAINT problem_topic_check;
ALTER TABLE "Problem" ADD CONSTRAINT problem_topic_check CHECK (topic IN
    ('array', 'string', 'recursion', 'tree_graph', 'sorting', 'searching',
     'ml_basic', 'deep_learning', 'nlp', 'cv', 'gen_ai', 'ai_tools', 'ai_math', 'data_analysis'));
CREATE INDEX idx_problem_kind ON "Problem" (kind, topic, difficulty) WHERE is_publish;

ALTER TABLE "Question" ADD COLUMN code TEXT NOT NULL DEFAULT '';
ALTER TABLE "Question" ADD COLUMN image VARCHAR(255);
ALTER TABLE "Question" ADD COLUMN explain TEXT NOT NULL DEFAULT '';
ALTER TABLE "Question" DROP CONSTRAINT question_topic_check;
ALTER TABLE "Question" ADD CONSTRAINT question_topic_check CHECK (topic IN
    ('array', 'string', 'recursion', 'tree_graph', 'sorting', 'searching',
     'ml_basic', 'deep_learning', 'nlp', 'cv', 'gen_ai', 'ai_tools', 'ai_math', 'data_analysis'));

ALTER TABLE "Contest" ADD COLUMN "privMin" INTEGER NOT NULL DEFAULT 0
    CONSTRAINT contest_privmin_check CHECK ("privMin" >= 0);

ALTER TABLE "Draft" ADD COLUMN kind VARCHAR(10) NOT NULL DEFAULT 'code'
    CONSTRAINT draft_kind_check CHECK (kind IN ('code', 'question', 'predict'));
ALTER TABLE "Draft" DROP CONSTRAINT draft_topic_check;
ALTER TABLE "Draft" ADD CONSTRAINT draft_topic_check CHECK (topic IN
    ('array', 'string', 'recursion', 'tree_graph', 'sorting', 'searching',
     'ml_basic', 'deep_learning', 'nlp', 'cv', 'gen_ai', 'ai_tools', 'ai_math', 'data_analysis'));

CREATE TABLE "Task" (
    "taskId"       SERIAL PRIMARY KEY,
    "problemId"    INTEGER NOT NULL CONSTRAINT task_problemid_fkey REFERENCES "Problem"("problemId") ON DELETE CASCADE,
    "dataDesc"     TEXT NOT NULL DEFAULT '',
    "submitFormat" TEXT NOT NULL DEFAULT '',
    baseline     TEXT NOT NULL DEFAULT '',
    "pubLimit"     INTEGER NOT NULL DEFAULT 20,
    "priLimit"     INTEGER NOT NULL DEFAULT 5,
    CONSTRAINT task_problemid_key UNIQUE ("problemId"),
    CONSTRAINT task_limits_check CHECK ("pubLimit" >= 0 AND "priLimit" >= 0)
);

CREATE TABLE "Metric" (
    "metricId" SERIAL PRIMARY KEY,
    "taskId"   INTEGER NOT NULL CONSTRAINT metric_taskid_fkey REFERENCES "Task"("taskId") ON DELETE CASCADE,
    name     VARCHAR(100) NOT NULL,
    metric   VARCHAR(30) NOT NULL
             CONSTRAINT metric_metric_check
             CHECK (metric IN ('accuracy', 'f1', 'macro_f1', 'triple_f1', 'detect_f1', 'align_f1',
                               'bleu', 'rmse_gain', 'cf1', 'recall_at_1', 'ppa')),
    "fileName" VARCHAR(100) NOT NULL,
    config   JSONB NOT NULL DEFAULT '{}',
    weight   REAL NOT NULL DEFAULT 1 CONSTRAINT metric_weight_check CHECK (weight >= 0),
    "minScore" REAL NOT NULL DEFAULT 0,
    "maxScore" REAL,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_metric_task ON "Metric" ("taskId", position, "metricId");

CREATE TABLE "Dataset" (
    "dataId"   SERIAL PRIMARY KEY,
    "taskId"   INTEGER NOT NULL CONSTRAINT dataset_taskid_fkey REFERENCES "Task"("taskId") ON DELETE CASCADE,
    role     VARCHAR(20) NOT NULL
             CONSTRAINT dataset_role_check
             CHECK (role IN ('train', 'public_test', 'private_test', 'public_key', 'private_key', 'other')),
    "fileName" VARCHAR(255) NOT NULL,
    path     VARCHAR(255) NOT NULL,
    size     INTEGER NOT NULL DEFAULT 0,
    created  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_dataset_task ON "Dataset" ("taskId", role);

CREATE TABLE "Prediction" (
    "predId"    SERIAL PRIMARY KEY,
    "userId"    INTEGER NOT NULL CONSTRAINT prediction_userid_fkey REFERENCES "User"("userId"),
    "taskId"    INTEGER NOT NULL CONSTRAINT prediction_taskid_fkey REFERENCES "Task"("taskId"),
    "attemptId" INTEGER CONSTRAINT prediction_attemptid_fkey REFERENCES "ContestAttempt"("attemptId"),
    phase     VARCHAR(10) NOT NULL DEFAULT 'public'
              CONSTRAINT prediction_phase_check CHECK (phase IN ('public', 'private')),
    "fileName"  VARCHAR(255) NOT NULL,
    path      VARCHAR(255) NOT NULL,
    status    VARCHAR(20) NOT NULL DEFAULT 'queued'
              CONSTRAINT prediction_status_check
              CHECK (status IN ('queued', 'scoring', 'done', 'invalid', 'system_error')),
    score     REAL,
    detail    JSONB,
    "errMess"   TEXT,
    created   TIMESTAMPTZ NOT NULL DEFAULT now(),
    judged    TIMESTAMPTZ
);
CREATE INDEX idx_prediction_board   ON "Prediction" ("taskId", phase, "userId", score DESC) WHERE status = 'done';
CREATE INDEX idx_prediction_user    ON "Prediction" ("userId", "predId" DESC);
CREATE INDEX idx_prediction_attempt ON "Prediction" ("attemptId", "taskId") WHERE "attemptId" IS NOT NULL;

CREATE TABLE "PracticeAnswer" (
    "practiceAId" SERIAL PRIMARY KEY,
    "userId"      INTEGER NOT NULL CONSTRAINT practiceanswer_userid_fkey REFERENCES "User"("userId"),
    "questionId"  INTEGER NOT NULL CONSTRAINT practiceanswer_questionid_fkey REFERENCES "Question"("questionId") ON DELETE CASCADE,
    selected    CHAR(1) CONSTRAINT practiceanswer_selected_check CHECK (selected IN ('A', 'B', 'C', 'D')),
    is_correct  BOOLEAN NOT NULL DEFAULT FALSE,
    created     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_practiceanswer_user ON "PracticeAnswer" ("userId", "questionId");

COMMIT;
