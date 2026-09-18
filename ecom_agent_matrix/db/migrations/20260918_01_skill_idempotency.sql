CREATE TABLE IF NOT EXISTS skill_execution_idempotency (
    idempotency_key CHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    store_id VARCHAR(64) NOT NULL,
    task_id VARCHAR(64) NOT NULL,
    skill_name VARCHAR(128) NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('running','succeeded','failed')),
    result_json JSONB,
    error_code VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_skill_idempotency_scope
ON skill_execution_idempotency(tenant_id, store_id, task_id);

ALTER TABLE skill_execution_idempotency ENABLE ROW LEVEL SECURITY;
ALTER TABLE skill_execution_idempotency FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_store_isolation ON skill_execution_idempotency;
CREATE POLICY tenant_store_isolation ON skill_execution_idempotency
USING (
  tenant_id = current_setting('app.tenant_id', true)
  AND store_id = current_setting('app.store_id', true)
)
WITH CHECK (
  tenant_id = current_setting('app.tenant_id', true)
  AND store_id = current_setting('app.store_id', true)
);
