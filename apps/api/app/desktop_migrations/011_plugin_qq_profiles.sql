CREATE TABLE desktop_plugin_qq_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    qq_account TEXT NOT NULL,
    robot_qq TEXT NOT NULL,
    robot_name TEXT NOT NULL,
    backup INTEGER NOT NULL DEFAULT 0 CHECK (backup IN (0, 1)),
    UNIQUE (qq_account, robot_qq)
);

CREATE UNIQUE INDEX desktop_plugin_qq_legacy_profile
ON desktop_plugin_qq_profile (qq_account) WHERE qq_account = '';

INSERT INTO desktop_plugin_qq_profile (qq_account, robot_qq, robot_name)
SELECT '', robot_qq, robot_name FROM desktop_plugin_qq_target WHERE id = 1;

CREATE TABLE desktop_plugin_qq_send_attempt (
    id TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('sending', 'submitted', 'rejected', 'uncertain'))
);
