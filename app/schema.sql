DROP TABLE IF EXISTS reviews, generated_drafts, attempt_answers, submission_results, submissions,
    exam_attempts, exam_items, exams, questions, test_cases, problems, users CASCADE;
DROP TABLE IF EXISTS "PracticeAnswer", "Prediction", "Dataset", "Metric", "Task" CASCADE;
DROP TABLE IF EXISTS "Standard", "Review", "Draft", "AttemptAnswer", "SubmissionResult", "Submission",
    "ContestAttempt", "ContestItem", "Contest", "Question", "TestCase", "Problem", "User" CASCADE;
DROP TABLE IF EXISTS review, draft, attempanswer, submissionresult, submission,
    contestattempt, contestitem, contest, question, testcase, problem CASCADE;

CREATE TABLE "User" (
    "userId"    SERIAL PRIMARY KEY,
    "userEmail" VARCHAR(255) NOT NULL CONSTRAINT user_useremail_key UNIQUE,
    username  VARCHAR(255) NOT NULL CONSTRAINT user_username_key UNIQUE,
    "userPass"  VARCHAR(255) NOT NULL,
    role      VARCHAR(20)  NOT NULL DEFAULT 'student'
              CONSTRAINT user_role_check CHECK (role IN ('student', 'supervisor', 'admin')),
    is_active BOOLEAN      NOT NULL DEFAULT TRUE,
    created   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE "Problem" (
    "problemId"   SERIAL PRIMARY KEY,
    title       VARCHAR(255) NOT NULL,
    statement   TEXT NOT NULL,
    input       TEXT NOT NULL DEFAULT '',
    output      TEXT NOT NULL DEFAULT '',
    constraints TEXT NOT NULL DEFAULT '',
    topic       VARCHAR(30) NOT NULL
                CONSTRAINT problem_topic_check
                CHECK (topic IN ('array', 'string', 'recursion', 'tree_graph', 'sorting', 'searching',
                                  'ml_basic', 'deep_learning', 'nlp', 'cv', 'gen_ai', 'ai_tools', 'ai_math', 'data_analysis')),
    difficulty  VARCHAR(10) NOT NULL
                CONSTRAINT problem_difficulty_check CHECK (difficulty IN ('easy', 'medium', 'hard')),
    kind        VARCHAR(10) NOT NULL DEFAULT 'code'
                CONSTRAINT problem_kind_check CHECK (kind IN ('code', 'predict')),
    "timeLimit"   REAL    NOT NULL DEFAULT 2,
    "memoryLimit" INTEGER NOT NULL DEFAULT 128,
    source      VARCHAR(10) NOT NULL DEFAULT 'manual'
                CONSTRAINT problem_source_check CHECK (source IN ('manual', 'llm')),
    is_publish  BOOLEAN NOT NULL DEFAULT TRUE,
    is_model    BOOLEAN NOT NULL DEFAULT FALSE,
    author      INTEGER CONSTRAINT problem_author_fkey REFERENCES "User"("userId"),
    created     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT problem_limits_check CHECK ("timeLimit" > 0 AND "memoryLimit" > 0)
);
CREATE INDEX idx_problem_publish ON "Problem" (topic, difficulty) WHERE is_publish;
CREATE INDEX idx_problem_kind ON "Problem" (kind, topic, difficulty) WHERE is_publish;

CREATE TABLE "TestCase" (
    "TestCaseId" SERIAL PRIMARY KEY,
    "problemId"  INTEGER NOT NULL CONSTRAINT testcase_problemid_fkey REFERENCES "Problem"("problemId") ON DELETE CASCADE,
    input      TEXT NOT NULL,
    output     TEXT NOT NULL,
    sample     BOOLEAN NOT NULL DEFAULT FALSE,
    position   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_testcase_problem ON "TestCase" ("problemId", position, "TestCaseId");

CREATE TABLE "Question" (
    "questionId" SERIAL PRIMARY KEY,
    content    TEXT NOT NULL,
    op1        TEXT NOT NULL,
    op2        TEXT NOT NULL,
    op3        TEXT NOT NULL,
    op4        TEXT NOT NULL,
    key        CHAR(1) NOT NULL
               CONSTRAINT question_key_check CHECK (key IN ('A', 'B', 'C', 'D')),
    code       TEXT NOT NULL DEFAULT '',
    image      VARCHAR(255),
    explain    TEXT NOT NULL DEFAULT '',
    is_model   BOOLEAN NOT NULL DEFAULT FALSE,
    topic      VARCHAR(30) NOT NULL
               CONSTRAINT question_topic_check
               CHECK (topic IN ('array', 'string', 'recursion', 'tree_graph', 'sorting', 'searching',
                                 'ml_basic', 'deep_learning', 'nlp', 'cv', 'gen_ai', 'ai_tools', 'ai_math', 'data_analysis')),
    difficulty VARCHAR(10) NOT NULL DEFAULT 'easy'
               CONSTRAINT question_difficulty_check CHECK (difficulty IN ('easy', 'medium', 'hard')),
    author     INTEGER CONSTRAINT question_author_fkey REFERENCES "User"("userId"),
    created    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE "Contest" (
    "contestId" SERIAL PRIMARY KEY,
    title     VARCHAR(255) NOT NULL,
    descp     TEXT NOT NULL DEFAULT '',
    duration  INTEGER NOT NULL CONSTRAINT contest_duration_check CHECK (duration > 0),
    open      TIMESTAMPTZ NOT NULL,
    close     TIMESTAMPTZ NOT NULL,
    "privMin" INTEGER NOT NULL DEFAULT 0 CONSTRAINT contest_privmin_check CHECK ("privMin" >= 0),
    kind      VARCHAR(10) NOT NULL DEFAULT 'exam' CONSTRAINT contest_kind_check CHECK (kind IN ('exam', 'practice')),
    author    INTEGER CONSTRAINT contest_author_fkey REFERENCES "User"("userId"),
    created   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT contest_window_check CHECK (close > open)
);
CREATE INDEX idx_contest_open ON "Contest" (kind, open DESC);

CREATE TABLE "ContestItem" (
    "itemId"     SERIAL PRIMARY KEY,
    "contestId"  INTEGER NOT NULL CONSTRAINT contestitem_contestid_fkey REFERENCES "Contest"("contestId") ON DELETE CASCADE,
    "itemType"   VARCHAR(10) NOT NULL
               CONSTRAINT contestitem_itemtype_check CHECK ("itemType" IN ('question', 'problem')),
    "questionId" INTEGER CONSTRAINT contestitem_questionid_fkey REFERENCES "Question"("questionId"),
    "problemId"  INTEGER CONSTRAINT contestitem_problemid_fkey REFERENCES "Problem"("problemId"),
    points     REAL NOT NULL DEFAULT 1 CONSTRAINT contestitem_points_check CHECK (points >= 0),
    position   INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT contestitem_target_check
        CHECK (("itemType" = 'question' AND "questionId" IS NOT NULL AND "problemId" IS NULL)
            OR ("itemType" = 'problem'  AND "problemId"  IS NOT NULL AND "questionId" IS NULL)),
    CONSTRAINT contestitem_contest_question_key UNIQUE ("contestId", "questionId"),
    CONSTRAINT contestitem_contest_problem_key  UNIQUE ("contestId", "problemId")
);
CREATE INDEX idx_contestitem_contest  ON "ContestItem" ("contestId", position, "itemId");
CREATE INDEX idx_contestitem_question ON "ContestItem" ("questionId") WHERE "questionId" IS NOT NULL;
CREATE INDEX idx_contestitem_problem  ON "ContestItem" ("problemId")  WHERE "problemId"  IS NOT NULL;

CREATE TABLE "ContestAttempt" (
    "attemptId"  SERIAL PRIMARY KEY,
    "contestId"  INTEGER NOT NULL CONSTRAINT contestattempt_contestid_fkey REFERENCES "Contest"("contestId") ON DELETE CASCADE,
    "userId"     INTEGER NOT NULL CONSTRAINT contestattempt_userid_fkey REFERENCES "User"("userId"),
    start      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deadline   TIMESTAMPTZ NOT NULL,
    finished   TIMESTAMPTZ,
    "totalScore" REAL NOT NULL DEFAULT 0 CONSTRAINT contestattempt_score_check CHECK ("totalScore" >= 0),
    duration   INTEGER CONSTRAINT contestattempt_duration_check CHECK (duration >= 0),
    CONSTRAINT contestattempt_contest_user_key UNIQUE ("contestId", "userId"),
    CONSTRAINT contestattempt_deadline_check CHECK (deadline > start),
    CONSTRAINT contestattempt_finished_check CHECK (finished IS NULL OR finished >= start)
);
CREATE INDEX idx_contestattempt_user ON "ContestAttempt" ("userId");
CREATE INDEX idx_contestattempt_open ON "ContestAttempt" (deadline) WHERE finished IS NULL;
CREATE INDEX idx_contestattempt_rank ON "ContestAttempt" ("contestId", "totalScore" DESC, duration)
    WHERE finished IS NOT NULL;

CREATE TABLE "AttemptAnswer" (
    "attemptAId" SERIAL PRIMARY KEY,
    "attemptId"  INTEGER NOT NULL CONSTRAINT attemptanswer_attemptid_fkey REFERENCES "ContestAttempt"("attemptId") ON DELETE CASCADE,
    "questionId" INTEGER NOT NULL CONSTRAINT attemptanswer_questionid_fkey REFERENCES "Question"("questionId"),
    selected   CHAR(1) CONSTRAINT attemptanswer_selected_check CHECK (selected IN ('A', 'B', 'C', 'D')),
    is_correct BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT attemptanswer_attempt_question_key UNIQUE ("attemptId", "questionId")
);
CREATE INDEX idx_attemptanswer_question ON "AttemptAnswer" ("questionId");

CREATE TABLE "Submission" (
    "submissionId" SERIAL PRIMARY KEY,
    "userId"       INTEGER NOT NULL CONSTRAINT submission_userid_fkey REFERENCES "User"("userId"),
    "problemId"    INTEGER NOT NULL CONSTRAINT submission_problemid_fkey REFERENCES "Problem"("problemId"),
    "attemptId"    INTEGER CONSTRAINT submission_attemptid_fkey REFERENCES "ContestAttempt"("attemptId"),
    "sourceCode"   TEXT NOT NULL,
    status       VARCHAR(20) NOT NULL DEFAULT 'queued'
                 CONSTRAINT submission_status_check CHECK (status IN ('queued', 'judging', 'done', 'system_error')),
    verdict      VARCHAR(5)
                 CONSTRAINT submission_verdict_check CHECK (verdict IN ('AC', 'WA', 'TLE', 'RE', 'CE')),
    passed       INTEGER NOT NULL DEFAULT 0,
    total        INTEGER NOT NULL DEFAULT 0,
    "errMess"      TEXT,
    created      TIMESTAMPTZ NOT NULL DEFAULT now(),
    judged       TIMESTAMPTZ,
    CONSTRAINT submission_tests_check CHECK (passed >= 0 AND passed <= total)
);
CREATE INDEX idx_submission_user         ON "Submission" ("userId", "submissionId" DESC);
CREATE INDEX idx_submission_user_problem ON "Submission" ("userId", "problemId", "submissionId" DESC);
CREATE INDEX idx_submission_attempt      ON "Submission" ("attemptId", "problemId") WHERE "attemptId" IS NOT NULL;
CREATE INDEX idx_submission_problem      ON "Submission" ("problemId");

CREATE TABLE "SubmissionResult" (
    "subResultId"  SERIAL PRIMARY KEY,
    "submissionId" INTEGER NOT NULL CONSTRAINT submissionresult_submissionid_fkey REFERENCES "Submission"("submissionId") ON DELETE CASCADE,
    "TestCaseId"   INTEGER NOT NULL CONSTRAINT submissionresult_testcaseid_fkey REFERENCES "TestCase"("TestCaseId") ON DELETE CASCADE,
    verdict      VARCHAR(5) NOT NULL
                 CONSTRAINT submissionresult_verdict_check CHECK (verdict IN ('AC', 'WA', 'TLE', 'RE', 'CE')),
    time         REAL,
    memory       INTEGER,
    stdout       TEXT,
    stderr       TEXT,
    judge0_token VARCHAR(64),
    CONSTRAINT submissionresult_submission_test_key UNIQUE ("submissionId", "TestCaseId")
);
CREATE INDEX idx_submissionresult_testcase ON "SubmissionResult" ("TestCaseId");

CREATE TABLE "Draft" (
    "draftId"      SERIAL PRIMARY KEY,
    kind         VARCHAR(10) NOT NULL DEFAULT 'code'
                 CONSTRAINT draft_kind_check CHECK (kind IN ('code', 'question', 'predict')),
    topic        VARCHAR(30) NOT NULL
                 CONSTRAINT draft_topic_check
                 CHECK (topic IN ('array', 'string', 'recursion', 'tree_graph', 'sorting', 'searching',
                                   'ml_basic', 'deep_learning', 'nlp', 'cv', 'gen_ai', 'ai_tools', 'ai_math', 'data_analysis')),
    difficulty   VARCHAR(10) NOT NULL
                 CONSTRAINT draft_difficulty_check CHECK (difficulty IN ('easy', 'medium', 'hard')),
    status       VARCHAR(20) NOT NULL DEFAULT 'generating'
                 CONSTRAINT draft_status_check
                 CHECK (status IN ('generating', 'validating', 'failed',
                                   'pending_review', 'approved', 'rejected')),
    payload      JSONB,
    output       JSONB,
    "errMess"      TEXT,
    "inputT"       INTEGER CONSTRAINT draft_inputt_check  CHECK ("inputT"  >= 0),
    "outputT"      INTEGER CONSTRAINT draft_outputt_check CHECK ("outputT" >= 0),
    "problemId"    INTEGER CONSTRAINT draft_problemid_fkey REFERENCES "Problem"("problemId") ON DELETE SET NULL,
    requested_by INTEGER CONSTRAINT draft_requested_by_fkey REFERENCES "User"("userId"),
    context      JSONB,
    created      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_draft_status ON "Draft" (status, "draftId" DESC);

CREATE TABLE "Review" (
    "revId"      SERIAL PRIMARY KEY,
    "draftId"    INTEGER NOT NULL CONSTRAINT review_draftid_fkey REFERENCES "Draft"("draftId") ON DELETE CASCADE,
    "reviewerId" INTEGER NOT NULL CONSTRAINT review_reviewerid_fkey REFERENCES "User"("userId"),
    decision   VARCHAR(10) NOT NULL
               CONSTRAINT review_decision_check CHECK (decision IN ('approved', 'rejected')),
    reason     VARCHAR(30)
               CONSTRAINT review_reason_check
               CHECK (reason IN ('unclear', 'wrong_difficulty', 'weak_tests',
                                 'duplicate', 'wrong_solution', 'other')),
    note       TEXT NOT NULL DEFAULT '',
    created    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT review_draftid_key UNIQUE ("draftId"),
    CONSTRAINT review_reject_reason_check CHECK (decision = 'approved' OR reason IS NOT NULL)
);
CREATE INDEX idx_review_reviewer ON "Review" ("reviewerId");

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
