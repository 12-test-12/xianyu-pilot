-- 操作日志业务化：新增状态、请求参数、执行结果、人工核对标记与耗时列。
-- 只做加列，历史记录保持 NULL/0，旧代码的 7 列 INSERT 仍然可用。
ALTER TABLE operation_log ADD COLUMN status VARCHAR(32);
ALTER TABLE operation_log ADD COLUMN request_params TEXT;
ALTER TABLE operation_log ADD COLUMN response_result TEXT;
ALTER TABLE operation_log ADD COLUMN requires_reconciliation SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE operation_log ADD COLUMN duration_ms INTEGER;

CREATE INDEX idx_operation_log_type_id ON operation_log (operation_type, id);

CREATE INDEX idx_operation_log_reconciliation ON operation_log (requires_reconciliation, id);
