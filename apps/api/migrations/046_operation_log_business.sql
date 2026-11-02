-- ============================================================
-- 046: 操作日志业务化
--
-- 为 operation_log 增加业务字段，使"下单/付款/自动发货"等业务事件
-- （尤其是 WebSocket 内部不经 HTTP 的自动发货）可以落库并被前端展示。
--
-- 1. status                 记录状态 completed/pending/failed/unknown/rejected
-- 2. request_params         脱敏后的请求参数（JSON 文本）
-- 3. response_result        脱敏后的执行结果（JSON 文本）
-- 4. requires_reconciliation 是否需要人工核对：0否 1是
-- 5. duration_ms            耗时（毫秒）
--
-- 兼容性：
--   - 全部使用 information_schema 存在性检查的 ADD COLUMN，可安全重放
--   - 仅追加列，不修改已有列，不删除任何数据
--   - 新列可为空/带默认值，旧代码只写 7 列的 INSERT 不受影响
-- ============================================================

SET NAMES utf8mb4;

-- --------------------------------------------------------------------------
-- 1. status 记录状态
-- --------------------------------------------------------------------------
SET @ddl = IF(
  EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'operation_log' AND column_name = 'status'),
  'SELECT 1',
  'ALTER TABLE `operation_log` ADD COLUMN `status` VARCHAR(32) NULL COMMENT ''记录状态：completed/pending/failed/unknown/rejected'''
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- --------------------------------------------------------------------------
-- 2. request_params 脱敏后的请求参数
-- --------------------------------------------------------------------------
SET @ddl = IF(
  EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'operation_log' AND column_name = 'request_params'),
  'SELECT 1',
  'ALTER TABLE `operation_log` ADD COLUMN `request_params` TEXT NULL COMMENT ''脱敏后的请求参数（JSON 文本）'''
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- --------------------------------------------------------------------------
-- 3. response_result 脱敏后的执行结果
-- --------------------------------------------------------------------------
SET @ddl = IF(
  EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'operation_log' AND column_name = 'response_result'),
  'SELECT 1',
  'ALTER TABLE `operation_log` ADD COLUMN `response_result` TEXT NULL COMMENT ''脱敏后的执行结果（JSON 文本）'''
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- --------------------------------------------------------------------------
-- 4. requires_reconciliation 是否需要人工核对
-- --------------------------------------------------------------------------
SET @ddl = IF(
  EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'operation_log' AND column_name = 'requires_reconciliation'),
  'SELECT 1',
  'ALTER TABLE `operation_log` ADD COLUMN `requires_reconciliation` TINYINT NOT NULL DEFAULT 0 COMMENT ''是否需要人工核对：0否 1是'''
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- --------------------------------------------------------------------------
-- 5. duration_ms 耗时（毫秒）
-- --------------------------------------------------------------------------
SET @ddl = IF(
  EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'operation_log' AND column_name = 'duration_ms'),
  'SELECT 1',
  'ALTER TABLE `operation_log` ADD COLUMN `duration_ms` INT NULL COMMENT ''耗时（毫秒）'''
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- --------------------------------------------------------------------------
-- 6. 索引：按类型 + 倒序主键、按人工核对标记筛选
-- --------------------------------------------------------------------------
SET @ddl = IF(
  EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'operation_log' AND index_name = 'idx_operation_log_type_id'),
  'SELECT 1',
  'CREATE INDEX `idx_operation_log_type_id` ON `operation_log` (`operation_type`, `id`)'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = IF(
  EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'operation_log' AND index_name = 'idx_operation_log_reconciliation'),
  'SELECT 1',
  'CREATE INDEX `idx_operation_log_reconciliation` ON `operation_log` (`requires_reconciliation`, `id`)'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
