CREATE TABLE desktop_plugin_qq_send_attempt_new (
    id TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('sending', 'submitted', 'rejected', 'uncertain', 'receipt_success', 'receipt_capped'))
);

INSERT INTO desktop_plugin_qq_send_attempt_new (id, payload_hash, state)
SELECT id, payload_hash,
    CASE WHEN state IN ('receipt_success', 'receipt_capped') THEN 'submitted' ELSE state END
FROM desktop_plugin_qq_send_attempt;

DROP TABLE desktop_plugin_qq_send_attempt;
ALTER TABLE desktop_plugin_qq_send_attempt_new RENAME TO desktop_plugin_qq_send_attempt;
