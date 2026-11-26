BEGIN;

UPDATE "Standard" SET config = jsonb_set(config, '{dup}', '50')
WHERE config ? 'dup' AND (config->>'dup')::int = 80;

UPDATE "Standard" SET config = config || jsonb_build_object('dup_hint', 15)
WHERE config IS NOT NULL AND NOT config ? 'dup_hint';

UPDATE "Standard" SET config = config || '{"min_gain": 10}'::jsonb
WHERE kind = 'predict' AND config IS NOT NULL AND NOT config ? 'min_gain';

COMMIT;
