CREATE TABLE desktop_plugin_activation (
    plugin_id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    manifest_hash TEXT NOT NULL
);
