CREATE TABLE desktop_plugin_qq_target (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    robot_qq TEXT NOT NULL,
    robot_name TEXT NOT NULL
);

INSERT INTO desktop_plugin_qq_target (id, robot_qq, robot_name)
SELECT 1, robot_qq, robot_name FROM desktop_plugin_qq_connection WHERE id = 1;
