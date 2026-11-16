CREATE TABLE desktop_plugin_qq_connection (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    endpoint TEXT NOT NULL,
    qq_account TEXT NOT NULL,
    robot_qq TEXT NOT NULL,
    robot_name TEXT NOT NULL,
    encrypted_token TEXT NOT NULL,
    checked_at TEXT NOT NULL
);
