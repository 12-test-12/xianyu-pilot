-- Extend the original SQLite schema for the complete, existing Web console.
-- Generated from the original application models; append-only migration.

CREATE TABLE admin_user (
	id INTEGER NOT NULL, 
	username VARCHAR(100) NOT NULL, 
	email VARCHAR(200), 
	password_hash VARCHAR(255) NOT NULL, 
	is_super SMALLINT DEFAULT 0, 
	status SMALLINT DEFAULT 1, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_admin_user_email ON admin_user (email);

CREATE UNIQUE INDEX ix_admin_user_username ON admin_user (username);

CREATE TABLE ai_auto_reply_attempt (
	id INTEGER NOT NULL, 
	event_key VARCHAR(64) NOT NULL, 
	account_id BIGINT NOT NULL, 
	source_message_digest VARCHAR(64) NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	session_id VARCHAR(200) NOT NULL, 
	peer_id VARCHAR(200) NOT NULL, 
	goods_id VARCHAR(200), 
	seller_external_uid VARCHAR(200), 
	state VARCHAR(32) DEFAULT 'pending' NOT NULL, 
	retry_scope VARCHAR(32), 
	retry_safe SMALLINT DEFAULT 1 NOT NULL, 
	attempt_count INTEGER DEFAULT 0 NOT NULL, 
	lease_token VARCHAR(64), 
	lease_until DATETIME, 
	generation_started_at DATETIME, 
	message_started_at DATETIME, 
	message_confirmed_at DATETIME, 
	local_confirmed_at DATETIME, 
	reply_digest VARCHAR(64), 
	encrypted_reply TEXT, 
	local_message_id BIGINT, 
	quota_date DATE, 
	quota_status VARCHAR(16), 
	policy_timezone VARCHAR(64), 
	last_error_code VARCHAR(64), 
	error_message VARCHAR(500), 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_ai_auto_reply_attempt_event UNIQUE (event_key), 
	CONSTRAINT uk_ai_auto_reply_attempt_source UNIQUE (account_id, source_message_digest)
);

CREATE INDEX idx_ai_auto_reply_account_created ON ai_auto_reply_attempt (account_id, created_time);

CREATE INDEX idx_ai_auto_reply_state_lease ON ai_auto_reply_attempt (state, lease_until);

CREATE TABLE ai_auto_reply_daily_quota (
	account_id INTEGER NOT NULL, 
	quota_date DATE NOT NULL, 
	occupied_count INTEGER DEFAULT 0 NOT NULL, 
	consumed_count INTEGER DEFAULT 0 NOT NULL, 
	released_count INTEGER DEFAULT 0 NOT NULL, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (account_id, quota_date)
);

CREATE INDEX idx_ai_reply_quota_date ON ai_auto_reply_daily_quota (quota_date);

CREATE TABLE auto_reply_log (
	id INTEGER NOT NULL, 
	account_id BIGINT, 
	conversation_id BIGINT, 
	rule_id BIGINT, 
	trigger_message TEXT, 
	reply_content TEXT, 
	hit_type VARCHAR(60), 
	status SMALLINT DEFAULT 1, 
	fail_reason VARCHAR(500), 
	action VARCHAR(40), 
	safety_reasons TEXT, 
	deleted SMALLINT DEFAULT 0, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE auto_reply_rule (
	id INTEGER NOT NULL, 
	account_id BIGINT, 
	rule_name VARCHAR(200), 
	match_type VARCHAR(50) DEFAULT 'keyword', 
	match_keywords TEXT, 
	reply_content TEXT, 
	reply_mode VARCHAR(50) DEFAULT 'keyword', 
	status SMALLINT DEFAULT 1, 
	priority INTEGER DEFAULT 0, 
	deleted SMALLINT DEFAULT 0, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE external_operation_attempt (
	id INTEGER NOT NULL, 
	operation_type VARCHAR(32) NOT NULL, 
	account_id BIGINT NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	target_local_id BIGINT, 
	remote_reference_id VARCHAR(200), 
	remote_reference_url TEXT, 
	state VARCHAR(32) DEFAULT 'pending' NOT NULL, 
	retry_scope VARCHAR(32), 
	retry_safe SMALLINT DEFAULT 1 NOT NULL, 
	attempt_count INTEGER DEFAULT 0 NOT NULL, 
	lease_token VARCHAR(64), 
	lease_until DATETIME, 
	remote_started_at DATETIME, 
	remote_confirmed_at DATETIME, 
	local_confirmed_at DATETIME, 
	local_result_id BIGINT, 
	last_error_code VARCHAR(64), 
	error_message VARCHAR(500), 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_external_operation_attempt_key UNIQUE (idempotency_key)
);

CREATE INDEX idx_external_operation_state_lease ON external_operation_attempt (operation_type, state, lease_until);

CREATE INDEX idx_external_operation_target_created ON external_operation_attempt (operation_type, target_local_id, created_time, id);

CREATE TABLE goods_off_shelf_attempt (
	id INTEGER NOT NULL, 
	goods_id BIGINT NOT NULL, 
	account_id BIGINT NOT NULL, 
	external_goods_id VARCHAR(200) NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	state VARCHAR(32) DEFAULT 'pending' NOT NULL, 
	retry_safe SMALLINT DEFAULT 1 NOT NULL, 
	attempt_count INTEGER DEFAULT 0 NOT NULL, 
	lease_token VARCHAR(64), 
	lease_until DATETIME, 
	remote_started_at DATETIME, 
	remote_confirmed_at DATETIME, 
	local_confirmed_at DATETIME, 
	last_error_code VARCHAR(64), 
	error_message VARCHAR(500), 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_goods_off_shelf_attempt_key UNIQUE (idempotency_key)
);

CREATE INDEX idx_goods_off_shelf_goods_created ON goods_off_shelf_attempt (goods_id, created_time);

CREATE INDEX idx_goods_off_shelf_state_lease ON goods_off_shelf_attempt (state, lease_until);

CREATE TABLE manual_delivery_attempt (
	id INTEGER NOT NULL, 
	order_id BIGINT NOT NULL, 
	account_id BIGINT NOT NULL, 
	external_order_id VARCHAR(200) NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	content_digest VARCHAR(64) NOT NULL, 
	delivery_record_id BIGINT, 
	delivery_mode VARCHAR(32) DEFAULT 'text' NOT NULL, 
	quantity_requested INTEGER DEFAULT 1 NOT NULL, 
	session_id VARCHAR(200) NOT NULL, 
	peer_id VARCHAR(200) NOT NULL, 
	item_id VARCHAR(200) NOT NULL, 
	state VARCHAR(32) DEFAULT 'pending' NOT NULL, 
	retry_scope VARCHAR(32), 
	retry_safe SMALLINT DEFAULT 1 NOT NULL, 
	attempt_count INTEGER DEFAULT 0 NOT NULL, 
	lease_token VARCHAR(64), 
	lease_until DATETIME, 
	message_started_at DATETIME, 
	message_confirmed_at DATETIME, 
	platform_confirmed_at DATETIME, 
	last_error_code VARCHAR(64), 
	error_message VARCHAR(500), 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_manual_delivery_attempt_order UNIQUE (order_id), 
	CONSTRAINT uk_manual_delivery_attempt_key UNIQUE (idempotency_key)
);

CREATE INDEX idx_manual_delivery_attempt_state_lease ON manual_delivery_attempt (state, lease_until);

CREATE TABLE manual_message_attempt (
	id INTEGER NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	account_id BIGINT NOT NULL, 
	session_digest VARCHAR(64) NOT NULL, 
	peer_digest VARCHAR(64) NOT NULL, 
	payload_digest VARCHAR(64) NOT NULL, 
	message_type VARCHAR(16) NOT NULL, 
	state VARCHAR(32) DEFAULT 'pending' NOT NULL, 
	retry_safe SMALLINT DEFAULT 1 NOT NULL, 
	attempt_count INTEGER DEFAULT 0 NOT NULL, 
	lease_token VARCHAR(64), 
	lease_until DATETIME, 
	send_started_at DATETIME, 
	confirmed_at DATETIME, 
	local_message_id BIGINT, 
	platform_message_digest VARCHAR(64), 
	last_error_code VARCHAR(64), 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_manual_message_attempt_key UNIQUE (idempotency_key)
);

CREATE INDEX idx_manual_message_attempt_account_created ON manual_message_attempt (account_id, created_time);

CREATE INDEX idx_manual_message_attempt_state_lease ON manual_message_attempt (state, lease_until);

CREATE TABLE message_automation_outbox (
	id INTEGER NOT NULL, 
	account_id BIGINT NOT NULL, 
	chat_message_id BIGINT NOT NULL, 
	source_message_digest VARCHAR(64) NOT NULL, 
	branch VARCHAR(16) NOT NULL, 
	state VARCHAR(32) DEFAULT 'pending' NOT NULL, 
	retry_safe SMALLINT DEFAULT 1 NOT NULL, 
	attempt_count INTEGER DEFAULT 0 NOT NULL, 
	lease_token VARCHAR(64), 
	lease_until DATETIME, 
	next_attempt_at DATETIME, 
	completed_at DATETIME, 
	last_error_code VARCHAR(64), 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_message_automation_message_branch UNIQUE (chat_message_id, branch), 
	CONSTRAINT uk_message_automation_source_branch UNIQUE (account_id, source_message_digest, branch)
);

CREATE INDEX idx_message_automation_account_created ON message_automation_outbox (account_id, created_time);

CREATE INDEX idx_message_automation_claim ON message_automation_outbox (state, retry_safe, next_attempt_at, lease_until);

CREATE TABLE model_config (
	id INTEGER NOT NULL, 
	model_name VARCHAR(200) NOT NULL, 
	provider VARCHAR(100), 
	model_type VARCHAR(50) DEFAULT 'chat', 
	api_key TEXT, 
	base_url VARCHAR(500), 
	real_model VARCHAR(200), 
	params_json JSON, 
	is_default SMALLINT DEFAULT 0, 
	status SMALLINT DEFAULT 1, 
	remark TEXT, 
	deleted SMALLINT DEFAULT 0, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE model_config_image_prompt (
	id INTEGER NOT NULL, 
	model_config_id BIGINT NOT NULL, 
	prompt_name VARCHAR(200) NOT NULL, 
	prompt_content TEXT, 
	negative_prompt TEXT, 
	params_json JSON, 
	status SMALLINT DEFAULT 1, 
	deleted SMALLINT DEFAULT 0, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE notification (
	id INTEGER NOT NULL, 
	notification_type VARCHAR(50), 
	title VARCHAR(300), 
	content TEXT, 
	reference_type VARCHAR(100), 
	reference_id BIGINT, 
	is_read SMALLINT DEFAULT 0, 
	read_time DATETIME, 
	priority SMALLINT DEFAULT 0, 
	deleted SMALLINT DEFAULT 0, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE notification_event_attempt (
	id INTEGER NOT NULL, 
	event_type VARCHAR(64) NOT NULL, 
	account_id BIGINT NOT NULL, 
	target_digest VARCHAR(64) NOT NULL, 
	generation INTEGER NOT NULL, 
	state VARCHAR(32) DEFAULT 'pending' NOT NULL, 
	attempt_count INTEGER DEFAULT 0 NOT NULL, 
	lease_token VARCHAR(64), 
	lease_until DATETIME, 
	send_started_at DATETIME, 
	confirmed_at DATETIME, 
	generation_expires_at DATETIME, 
	next_retry_at DATETIME, 
	provider_called SMALLINT, 
	delivered SMALLINT, 
	outcome_known SMALLINT, 
	last_error_code VARCHAR(64), 
	resolved_at DATETIME, 
	resolution_code VARCHAR(64), 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_notification_event_generation UNIQUE (event_type, account_id, target_digest, generation)
);

CREATE INDEX idx_notification_event_retry ON notification_event_attempt (state, next_retry_at);

CREATE INDEX idx_notification_event_state_lease ON notification_event_attempt (state, lease_until);

CREATE INDEX idx_notification_event_target_created ON notification_event_attempt (event_type, account_id, target_digest, created_time, id);

CREATE TABLE notification_test_attempt (
	id INTEGER NOT NULL, 
	user_id BIGINT NOT NULL, 
	channel_key VARCHAR(80) NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	payload_digest VARCHAR(64) NOT NULL, 
	state VARCHAR(32) DEFAULT 'pending' NOT NULL, 
	retry_safe SMALLINT DEFAULT 1 NOT NULL, 
	attempt_count INTEGER DEFAULT 0 NOT NULL, 
	lease_token VARCHAR(64), 
	lease_until DATETIME, 
	send_started_at DATETIME, 
	confirmed_at DATETIME, 
	provider_success SMALLINT, 
	provider_status_code INTEGER, 
	cost_ms INTEGER, 
	result_code VARCHAR(64), 
	log_persisted SMALLINT DEFAULT 0 NOT NULL, 
	last_error_code VARCHAR(64), 
	resolved_at DATETIME, 
	resolution_code VARCHAR(64), 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_notification_test_attempt_key UNIQUE (idempotency_key)
);

CREATE INDEX idx_notification_test_state_lease ON notification_test_attempt (state, lease_until);

CREATE INDEX idx_notification_test_target_created ON notification_test_attempt (user_id, channel_key, created_time, id);

CREATE TABLE operation_log (
	id INTEGER NOT NULL, 
	operator VARCHAR(100), 
	operation_type VARCHAR(100), 
	operation_desc TEXT, 
	target_type VARCHAR(100), 
	target_id VARCHAR(100), 
	ip_address VARCHAR(50), 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE quick_reply_template (
	id INTEGER NOT NULL, 
	account_id BIGINT, 
	title VARCHAR(200) NOT NULL, 
	content TEXT NOT NULL, 
	sort_order INTEGER DEFAULT 0, 
	status SMALLINT DEFAULT 1, 
	deleted SMALLINT DEFAULT 0, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE rag_chunk (
	id INTEGER NOT NULL, 
	kb_id BIGINT NOT NULL, 
	doc_id BIGINT NOT NULL, 
	chunk_index INTEGER DEFAULT 0, 
	content TEXT, 
	embedding TEXT, 
	token_count INTEGER DEFAULT 0, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE rag_document (
	id INTEGER NOT NULL, 
	kb_id BIGINT NOT NULL, 
	file_name VARCHAR(500), 
	file_url TEXT, 
	file_type VARCHAR(50), 
	file_size BIGINT DEFAULT 0, 
	chunk_count INTEGER DEFAULT 0, 
	parse_status VARCHAR(30) DEFAULT 'pending', 
	error_message TEXT, 
	deleted SMALLINT DEFAULT 0, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE rag_knowledge_base (
	id INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	description TEXT, 
	embedding_model VARCHAR(200), 
	embedding_api_key TEXT, 
	embedding_base_url VARCHAR(500), 
	doc_count INTEGER DEFAULT 0, 
	chunk_count INTEGER DEFAULT 0, 
	status SMALLINT DEFAULT 1, 
	deleted SMALLINT DEFAULT 0, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE realtime_delivery_attempt (
	id INTEGER NOT NULL, 
	event_key VARCHAR(64) NOT NULL, 
	account_id BIGINT NOT NULL, 
	external_order_id VARCHAR(200), 
	source_event_id VARCHAR(200) NOT NULL, 
	session_id VARCHAR(200) NOT NULL, 
	peer_id VARCHAR(200) NOT NULL, 
	item_id VARCHAR(200) NOT NULL, 
	rule_id BIGINT, 
	delivery_record_id BIGINT, 
	delivery_mode VARCHAR(32) NOT NULL, 
	content_digest VARCHAR(64) NOT NULL, 
	quantity_requested INTEGER DEFAULT 1 NOT NULL, 
	card_group_id BIGINT, 
	auto_confirm_shipment SMALLINT DEFAULT 0 NOT NULL, 
	state VARCHAR(32) DEFAULT 'pending' NOT NULL, 
	retry_scope VARCHAR(32), 
	retry_safe SMALLINT DEFAULT 1 NOT NULL, 
	attempt_count INTEGER DEFAULT 0 NOT NULL, 
	lease_token VARCHAR(64), 
	lease_until DATETIME, 
	message_started_at DATETIME, 
	message_confirmed_at DATETIME, 
	platform_confirm_started_at DATETIME, 
	platform_confirmed_at DATETIME, 
	last_error_code VARCHAR(64), 
	error_message VARCHAR(500), 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_realtime_delivery_attempt_event UNIQUE (event_key)
);

CREATE INDEX idx_realtime_delivery_attempt_account_order ON realtime_delivery_attempt (account_id, external_order_id);

CREATE INDEX idx_realtime_delivery_attempt_record ON realtime_delivery_attempt (delivery_record_id);

CREATE INDEX idx_realtime_delivery_attempt_state_lease ON realtime_delivery_attempt (state, lease_until);

CREATE TABLE remote_goods_delete_attempt (
	id INTEGER NOT NULL, 
	goods_id BIGINT NOT NULL, 
	account_id BIGINT NOT NULL, 
	external_goods_id VARCHAR(200) NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	state VARCHAR(32) DEFAULT 'pending' NOT NULL, 
	retry_safe SMALLINT DEFAULT 1 NOT NULL, 
	attempt_count INTEGER DEFAULT 0 NOT NULL, 
	lease_token VARCHAR(64), 
	lease_until DATETIME, 
	remote_started_at DATETIME, 
	remote_confirmed_at DATETIME, 
	local_deleted_at DATETIME, 
	last_error_code VARCHAR(64), 
	error_message VARCHAR(500), 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_remote_goods_delete_attempt_goods UNIQUE (goods_id), 
	CONSTRAINT uk_remote_goods_delete_attempt_key UNIQUE (idempotency_key)
);

CREATE INDEX idx_remote_goods_delete_attempt_state_lease ON remote_goods_delete_attempt (state, lease_until);

CREATE TABLE scheduled_task (
	id INTEGER NOT NULL, 
	task_name VARCHAR(200), 
	task_type VARCHAR(80), 
	cron_expr VARCHAR(120), 
	config JSON, 
	last_run_time DATETIME, 
	next_run_time DATETIME, 
	last_status VARCHAR(32), 
	last_result JSON, 
	lease_token VARCHAR(64), 
	lease_until DATETIME, 
	lease_owner VARCHAR(128), 
	status SMALLINT DEFAULT 1, 
	deleted SMALLINT DEFAULT 0, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE sensitive_word (
	id INTEGER NOT NULL, 
	word VARCHAR(200) NOT NULL, 
	category VARCHAR(50), 
	replace_to VARCHAR(200), 
	status SMALLINT DEFAULT 1, 
	deleted SMALLINT DEFAULT 0, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE xianyu_account_auto_rate_config (
	id INTEGER NOT NULL, 
	account_id BIGINT NOT NULL, 
	enabled SMALLINT DEFAULT 0 NOT NULL, 
	rate_type VARCHAR(20) DEFAULT 'text' NOT NULL, 
	text_content TEXT, 
	api_url VARCHAR(500), 
	schedule_hour INTEGER DEFAULT 9 NOT NULL, 
	deleted SMALLINT DEFAULT 0 NOT NULL, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_xyaarc_account UNIQUE (account_id)
);

CREATE INDEX idx_xyaarc_enabled_hour ON xianyu_account_auto_rate_config (enabled, schedule_hour, deleted);

CREATE TABLE xianyu_account_membership (
	id INTEGER NOT NULL, 
	account_id BIGINT NOT NULL, 
	level VARCHAR(20) DEFAULT 'normal' NOT NULL, 
	expired_time DATETIME, 
	status INTEGER DEFAULT 1 NOT NULL, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_account_membership UNIQUE (account_id)
);

CREATE INDEX idx_membership_level ON xianyu_account_membership (level);

CREATE TABLE xianyu_ai_provider (
	id INTEGER NOT NULL, 
	provider_name VARCHAR(100), 
	api_key TEXT, 
	base_url VARCHAR(500), 
	model_name VARCHAR(200), 
	status INTEGER DEFAULT 1, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE xianyu_auto_rate_log (
	id INTEGER NOT NULL, 
	account_id BIGINT NOT NULL, 
	run_time DATETIME NOT NULL, 
	schedule_hour INTEGER, 
	trigger_type VARCHAR(20) DEFAULT 'scheduled' NOT NULL, 
	status VARCHAR(20) DEFAULT 'success' NOT NULL, 
	total_pending INTEGER DEFAULT 0 NOT NULL, 
	total_success INTEGER DEFAULT 0 NOT NULL, 
	total_failed INTEGER DEFAULT 0 NOT NULL, 
	total_skipped INTEGER DEFAULT 0 NOT NULL, 
	error_message VARCHAR(500), 
	details_json TEXT, 
	duration_seconds FLOAT DEFAULT 0 NOT NULL, 
	deleted SMALLINT DEFAULT 0 NOT NULL, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX idx_arl_account_time ON xianyu_auto_rate_log (account_id, run_time);

CREATE INDEX idx_arl_status ON xianyu_auto_rate_log (status, deleted);

CREATE TABLE xianyu_chat_message (
	id INTEGER NOT NULL, 
	account_id BIGINT NOT NULL, 
	seller_external_uid VARCHAR(64), 
	pnm_id VARCHAR(200), 
	message_uid VARCHAR(128), 
	s_id VARCHAR(200), 
	content_type INTEGER DEFAULT 1, 
	msg_content TEXT, 
	sender_user_id VARCHAR(200), 
	receiver_user_id VARCHAR(64), 
	sender_user_name VARCHAR(200), 
	peer_external_uid VARCHAR(64), 
	xy_goods_id VARCHAR(200), 
	message_time BIGINT DEFAULT 0, 
	direction VARCHAR(20) DEFAULT 'IN', 
	parse_status VARCHAR(16) DEFAULT 'ok', 
	reminder_content TEXT, 
	reminder_url VARCHAR(500), 
	complete_msg JSON, 
	raw_payload JSON, 
	read_status SMALLINT DEFAULT 0, 
	deleted SMALLINT DEFAULT 0, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE INDEX idx_chat_msg_lookup ON xianyu_chat_message (account_id, deleted, s_id, message_time);

CREATE TABLE xianyu_conversation (
	id INTEGER NOT NULL, 
	account_id BIGINT, 
	seller_external_uid VARCHAR(64), 
	external_buyer_id VARCHAR(200), 
	peer_external_uid VARCHAR(64), 
	peer_key VARCHAR(128), 
	buyer_name VARCHAR(200), 
	buyer_avatar TEXT, 
	goods_title VARCHAR(500), 
	goods_id VARCHAR(200), 
	goods_cover_pic TEXT, 
	s_id VARCHAR(200), 
	status SMALLINT DEFAULT 0, 
	last_message_time DATETIME, 
	last_message_content TEXT, 
	unread_count INTEGER DEFAULT 0, 
	auto_reply_paused SMALLINT DEFAULT 0, 
	auto_reply_manual_disabled SMALLINT DEFAULT 0, 
	last_manual_reply_at BIGINT, 
	last_auto_reply_at BIGINT, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE xianyu_goods_edit_snapshot (
	id INTEGER NOT NULL, 
	account_id BIGINT NOT NULL, 
	external_goods_id VARCHAR(128) NOT NULL, 
	snapshot_json JSON NOT NULL, 
	source VARCHAR(32) DEFAULT 'publish' NOT NULL, 
	account_type VARCHAR(16) DEFAULT 'fish_shop' NOT NULL, 
	deleted SMALLINT DEFAULT 0 NOT NULL, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE xianyu_goods_property (
	id INTEGER NOT NULL, 
	account_id BIGINT NOT NULL, 
	goods_id BIGINT NOT NULL, 
	property_name VARCHAR(100) NOT NULL, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE xianyu_goods_property_value (
	id INTEGER NOT NULL, 
	property_id BIGINT NOT NULL, 
	value_name VARCHAR(200) NOT NULL, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE xianyu_goods_sku (
	id INTEGER NOT NULL, 
	account_id BIGINT NOT NULL, 
	goods_id BIGINT NOT NULL, 
	sku_id VARCHAR(64) NOT NULL, 
	property_key VARCHAR(500) NOT NULL, 
	property_list_json TEXT, 
	price DECIMAL(10, 2), 
	stock INTEGER, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE xianyu_goods_sync_task (
	id INTEGER NOT NULL, 
	sync_id VARCHAR(80) NOT NULL, 
	account_id BIGINT NOT NULL, 
	status VARCHAR(30) DEFAULT 'queued' NOT NULL, 
	progress INTEGER DEFAULT 0, 
	total_count INTEGER DEFAULT 0, 
	new_count INTEGER DEFAULT 0, 
	updated_count INTEGER DEFAULT 0, 
	skipped_count INTEGER DEFAULT 0, 
	off_shelf_count INTEGER DEFAULT 0, 
	detail_synced_count INTEGER DEFAULT 0, 
	duration_seconds FLOAT DEFAULT 0, 
	error_message TEXT, 
	started_time DATETIME, 
	finished_time DATETIME, 
	deleted SMALLINT DEFAULT 0, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	UNIQUE (sync_id)
);

CREATE TABLE xianyu_message (
	id INTEGER NOT NULL, 
	account_id BIGINT, 
	conversation_id BIGINT, 
	session_id VARCHAR(200), 
	from_user_id VARCHAR(200), 
	to_user_id VARCHAR(200), 
	content TEXT, 
	message_type VARCHAR(50) DEFAULT 'text', 
	direction VARCHAR(20) DEFAULT 'received', 
	is_auto_reply SMALLINT DEFAULT 0, 
	deleted SMALLINT DEFAULT 0, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE xianyu_rate (
	id INTEGER NOT NULL, 
	account_id BIGINT NOT NULL, 
	external_order_id VARCHAR(64) NOT NULL, 
	external_item_id VARCHAR(64), 
	buyer_id VARCHAR(120), 
	buyer_nick VARCHAR(255), 
	buyer_icon TEXT, 
	item_title VARCHAR(500), 
	item_pic_url TEXT, 
	item_info_lines TEXT, 
	order_status VARCHAR(64), 
	seller_rate_status VARCHAR(16), 
	in_refund VARCHAR(16), 
	consign_time DATETIME, 
	order_create_time DATETIME, 
	pay_success_time DATETIME, 
	finish_time DATETIME, 
	logistics_company VARCHAR(128), 
	logistics_mail_no VARCHAR(128), 
	buyer_rate_content TEXT, 
	buyer_rate_level VARCHAR(16), 
	buyer_rate_time DATETIME, 
	buyer_rate_images TEXT, 
	seller_rate_content TEXT, 
	seller_rate_level VARCHAR(16), 
	seller_rate_time DATETIME, 
	seller_rate_images TEXT, 
	seller_rate_id VARCHAR(64), 
	has_seller_rate SMALLINT DEFAULT 0 NOT NULL, 
	rate_reviewable SMALLINT DEFAULT 0 NOT NULL, 
	raw_json TEXT, 
	sync_status VARCHAR(32) DEFAULT 'synced' NOT NULL, 
	last_synced_time DATETIME, 
	deleted SMALLINT DEFAULT 0 NOT NULL, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_rate_account_order UNIQUE (account_id, external_order_id)
);

CREATE INDEX idx_rate_account ON xianyu_rate (account_id, deleted);

CREATE INDEX idx_rate_status ON xianyu_rate (deleted, rate_reviewable);

CREATE INDEX idx_rate_sync_status ON xianyu_rate (account_id, sync_status);

CREATE INDEX idx_rate_time ON xianyu_rate (deleted, finish_time);

CREATE TABLE xianyu_rate_account_state (
	id INTEGER NOT NULL, 
	account_id BIGINT NOT NULL, 
	last_sync_time DATETIME, 
	last_sync_status VARCHAR(30), 
	last_sync_error VARCHAR(500), 
	last_total_count INTEGER, 
	is_syncing SMALLINT DEFAULT 0 NOT NULL, 
	sync_started_time DATETIME, 
	last_full_sync_time DATETIME, 
	deleted SMALLINT DEFAULT 0 NOT NULL, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_rate_state_account UNIQUE (account_id)
);

CREATE TABLE xianyu_rate_sync_task (
	id INTEGER NOT NULL, 
	sync_id VARCHAR(80) NOT NULL, 
	account_id BIGINT, 
	scope VARCHAR(20) DEFAULT 'single' NOT NULL, 
	status VARCHAR(30) DEFAULT 'queued' NOT NULL, 
	progress INTEGER DEFAULT 0 NOT NULL, 
	total_count INTEGER DEFAULT 0 NOT NULL, 
	new_count INTEGER DEFAULT 0 NOT NULL, 
	updated_count INTEGER DEFAULT 0 NOT NULL, 
	failed_count INTEGER DEFAULT 0 NOT NULL, 
	succeeded_count INTEGER DEFAULT 0 NOT NULL, 
	duration_seconds FLOAT DEFAULT 0 NOT NULL, 
	error_message TEXT, 
	started_time DATETIME, 
	finished_time DATETIME, 
	deleted SMALLINT DEFAULT 0 NOT NULL, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE xianyu_refund (
	id INTEGER NOT NULL, 
	account_id BIGINT NOT NULL, 
	external_refund_id VARCHAR(64) NOT NULL, 
	external_order_id VARCHAR(64), 
	external_item_id VARCHAR(64), 
	item_title VARCHAR(500), 
	item_pic_url TEXT, 
	item_info_lines TEXT, 
	buy_num VARCHAR(32), 
	refund_fee DECIMAL(18, 4), 
	auction_price DECIMAL(18, 4), 
	order_status VARCHAR(64), 
	order_simple_remark VARCHAR(255), 
	refund_status VARCHAR(64), 
	refund_status_desc VARCHAR(500), 
	common_refund_status VARCHAR(64), 
	refund_reason VARCHAR(500), 
	cs_status VARCHAR(64), 
	logistics_company VARCHAR(128), 
	logistics_mail_no VARCHAR(128), 
	consign_time DATETIME, 
	refund_create_time DATETIME, 
	common_create_time DATETIME, 
	buyer_nick VARCHAR(255), 
	right_buttons_json TEXT, 
	ext_total_refund_fee DECIMAL(18, 4), 
	raw_json TEXT, 
	sync_status VARCHAR(32) DEFAULT 'synced' NOT NULL, 
	last_synced_time DATETIME, 
	deleted SMALLINT DEFAULT 0 NOT NULL, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE xianyu_refund_account_state (
	id INTEGER NOT NULL, 
	account_id BIGINT NOT NULL, 
	last_sync_time DATETIME, 
	last_sync_status VARCHAR(30), 
	last_sync_error VARCHAR(500), 
	last_total_count INTEGER, 
	is_syncing SMALLINT DEFAULT 0 NOT NULL, 
	sync_started_time DATETIME, 
	last_full_sync_time DATETIME, 
	deleted SMALLINT DEFAULT 0 NOT NULL, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE xianyu_refund_sync_task (
	id INTEGER NOT NULL, 
	sync_id VARCHAR(80) NOT NULL, 
	account_id BIGINT, 
	scope VARCHAR(20) DEFAULT 'single' NOT NULL, 
	status VARCHAR(30) DEFAULT 'queued' NOT NULL, 
	progress INTEGER DEFAULT 0 NOT NULL, 
	total_count INTEGER DEFAULT 0 NOT NULL, 
	new_count INTEGER DEFAULT 0 NOT NULL, 
	updated_count INTEGER DEFAULT 0 NOT NULL, 
	failed_count INTEGER DEFAULT 0 NOT NULL, 
	succeeded_count INTEGER DEFAULT 0 NOT NULL, 
	duration_seconds FLOAT DEFAULT 0 NOT NULL, 
	error_message TEXT, 
	started_time DATETIME, 
	finished_time DATETIME, 
	deleted SMALLINT DEFAULT 0 NOT NULL, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE xianyu_remote_slider_solve_record (
	id INTEGER NOT NULL, 
	request_id VARCHAR(64) NOT NULL, 
	account_id BIGINT, 
	account_name VARCHAR(128), 
	trigger_scene VARCHAR(32) DEFAULT 'manual' NOT NULL, 
	status VARCHAR(32) DEFAULT 'retrying' NOT NULL, 
	failure_reason VARCHAR(64) DEFAULT '' NOT NULL, 
	error_message TEXT, 
	duration_ms INTEGER DEFAULT 0 NOT NULL, 
	token_charged INTEGER DEFAULT 0 NOT NULL, 
	remote_status VARCHAR(32) DEFAULT '' NOT NULL, 
	remote_solved SMALLINT DEFAULT 0 NOT NULL, 
	client_ip VARCHAR(64) DEFAULT '' NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	UNIQUE (request_id)
);

CREATE TABLE xianyu_sys_setting (
	id INTEGER NOT NULL, 
	setting_key VARCHAR(100), 
	setting_value TEXT, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE notification_event_target_mutex (
	event_type VARCHAR(64) NOT NULL, 
	account_id INTEGER NOT NULL, 
	target_digest VARCHAR(64) NOT NULL, 
	latest_attempt_id BIGINT, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (event_type, account_id, target_digest), 
	FOREIGN KEY(latest_attempt_id) REFERENCES notification_event_attempt (id) ON DELETE RESTRICT ON UPDATE RESTRICT
);

CREATE INDEX idx_notification_event_target_latest ON notification_event_target_mutex (latest_attempt_id);

CREATE TABLE notification_test_target_mutex (
	user_id INTEGER NOT NULL, 
	channel_key VARCHAR(80) NOT NULL, 
	latest_attempt_id BIGINT, 
	created_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_time DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (user_id, channel_key), 
	FOREIGN KEY(latest_attempt_id) REFERENCES notification_test_attempt (id) ON DELETE RESTRICT ON UPDATE RESTRICT
);

CREATE INDEX idx_notification_test_target_latest ON notification_test_target_mutex (latest_attempt_id);

CREATE TABLE "user_notification_setting" (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `user_id` BIGINT NOT NULL,
  `config_json` JSON NOT NULL,
  `created_time` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_time` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  `deleted` TINYINT NULL DEFAULT 0,
  UNIQUE (`user_id`)
);

CREATE TABLE "notification_delivery_log" (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `user_id` BIGINT NULL,
  `channel_key` VARCHAR(80) NULL,
  `channel_name` VARCHAR(120) NULL,
  `event_type` VARCHAR(80) NULL,
  `success` TINYINT NULL DEFAULT 0,
  `status_code` INT NULL DEFAULT 0,
  `cost_ms` BIGINT NULL DEFAULT 0,
  `message` VARCHAR(500) NULL,
  `request_body` TEXT NULL,
  `response_body` TEXT NULL,
  `retry_count` INT NULL DEFAULT 0,
  `created_time` DATETIME NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE "delivery_text_source" (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `title` VARCHAR(200) NOT NULL,
  `content` TEXT NULL,
  `remark` TEXT NULL,
  `deleted` SMALLINT DEFAULT 0,
  `created_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `updated_time` DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE "delivery_template" (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `name` VARCHAR(200) NOT NULL,
  `type` INT DEFAULT 6,
  `status` SMALLINT DEFAULT 1,
  `content` TEXT NULL,
  `random_enabled` SMALLINT DEFAULT 0,
  `deleted` SMALLINT DEFAULT 0,
  `created_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `updated_time` DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE "delivery_statement" (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `enabled` SMALLINT DEFAULT 0,
  `content` TEXT NULL,
  `scope` VARCHAR(50) DEFAULT 'all',
  `deleted` SMALLINT DEFAULT 0,
  `created_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `updated_time` DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE "user_business_setting" (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `user_id` BIGINT NOT NULL DEFAULT 0,
  `setting_key` VARCHAR(100) NOT NULL,
  `config_json` TEXT NOT NULL,
  `created_time` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_time` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  `deleted` TINYINT NULL DEFAULT 0,
  UNIQUE (`user_id`, `setting_key`)
);

CREATE TABLE "audit_retention_state" (
  `id` SMALLINT NOT NULL,
  `last_run_at` DATETIME NULL,
  `next_run_at` DATETIME NULL,
  `last_deleted_count` INT NOT NULL DEFAULT 0,
  `updated_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
);

CREATE TABLE "item_polish_task" (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `task_id` VARCHAR(64) NOT NULL,
  `account_id` BIGINT NOT NULL,
  `idempotency_key` VARCHAR(128) NOT NULL,
  `request_digest` CHAR(64) NOT NULL,
  `status` VARCHAR(32) NOT NULL DEFAULT 'pending',
  `retry_safe` SMALLINT NOT NULL DEFAULT 1,
  `total_count` INT NOT NULL DEFAULT 0,
  `processed_count` INT NOT NULL DEFAULT 0,
  `polished_count` INT NOT NULL DEFAULT 0,
  `already_done_count` INT NOT NULL DEFAULT 0,
  `failed_count` INT NOT NULL DEFAULT 0,
  `unknown_count` INT NOT NULL DEFAULT 0,
  `lease_token` VARCHAR(64) NULL,
  `lease_until` DATETIME NULL,
  `last_error_code` VARCHAR(64) NULL,
  `error_message` VARCHAR(500) NULL,
  `started_time` DATETIME NULL,
  `finished_time` DATETIME NULL,
  `created_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (`task_id`),
  UNIQUE (`idempotency_key`)
);

CREATE TABLE "item_polish_task_item" (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `task_db_id` BIGINT NOT NULL,
  `goods_id` BIGINT NOT NULL,
  `account_id` BIGINT NOT NULL,
  `external_goods_id` VARCHAR(200) NOT NULL,
  `title_snapshot` VARCHAR(500) NULL,
  `status` VARCHAR(32) NOT NULL DEFAULT 'pending',
  `retry_safe` SMALLINT NOT NULL DEFAULT 1,
  `attempt_count` INT NOT NULL DEFAULT 0,
  `lease_token` VARCHAR(64) NULL,
  `remote_started_at` DATETIME NULL,
  `remote_confirmed_at` DATETIME NULL,
  `last_error_code` VARCHAR(64) NULL,
  `error_message` VARCHAR(500) NULL,
  `created_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (`task_db_id`, `goods_id`)
);

CREATE TABLE "xianyu_captcha_solve_record" (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `account_id` BIGINT NOT NULL,
  `account_name` VARCHAR(128) DEFAULT '',
  `event_desc` VARCHAR(255) NOT NULL,
  `open_reason` VARCHAR(255) DEFAULT '',
  `solve_reason` VARCHAR(255) DEFAULT '',
  `trigger_scene` VARCHAR(64) DEFAULT '',
  `result` VARCHAR(32) DEFAULT '',
  `status` VARCHAR(32) NOT NULL DEFAULT 'retrying',
  `engine` VARCHAR(64) DEFAULT 'Playwright',
  `retry_count` INT DEFAULT 0,
  `error_message` TEXT,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `deleted` TINYINT DEFAULT 0
);

CREATE TABLE "xianyu_captcha_backoff" (
  `account_id` BIGINT NOT NULL,
  `fail_count` INT NOT NULL DEFAULT 0,
  `next_allowed_at` DATETIME NULL,
  `last_fail_at` DATETIME NULL,
  `last_success_at` DATETIME NULL,
  `last_error` VARCHAR(512) DEFAULT '',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`account_id`)
);

CREATE TABLE "delivery_global_config" (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `config_json` TEXT NOT NULL,
  `deleted` SMALLINT NOT NULL DEFAULT 0,
  `created_time` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_time` DATETIME NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE "delivery_statement_session" (
  `id` INTEGER PRIMARY KEY AUTOINCREMENT,
  `account_id` INT  NOT NULL,
  `order_id` VARCHAR(128) NOT NULL,
  `buyer_id` VARCHAR(128) NOT NULL DEFAULT '',
  `buyer_nick` VARCHAR(255) NOT NULL DEFAULT '',
  `xy_goods_id` VARCHAR(128) NOT NULL DEFAULT '',
  `goods_title` VARCHAR(255) NOT NULL DEFAULT '',
  `s_id` VARCHAR(128) NOT NULL DEFAULT '',
  `pnm_id` VARCHAR(128) NOT NULL DEFAULT '',
  `statement_content` TEXT NULL,
  `status` TEXT NOT NULL DEFAULT 'waiting' CHECK (`status` IN ('declaring','waiting','confirmed','cancelled')),
  `confirm_source` VARCHAR(32) NULL,
  `cancel_source` VARCHAR(32) NULL,
  `reply_msg_id` VARCHAR(128) NULL,
  `sent_at` DATETIME NULL,
  `confirmed_at` DATETIME NULL,
  `cancelled_at` DATETIME NULL,
  `created_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `deleted` TINYINT NOT NULL DEFAULT 0
);


-- Preserve original database uniqueness contracts for shared upsert operations.
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_xianyu_sys_setting_uk_sys_setting_key" ON "xianyu_sys_setting" ("setting_key");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_user_notification_setting_uk_uns_user" ON "user_notification_setting" ("user_id");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_manual_delivery_attempt_uk_manual_delivery_attempt_order" ON "manual_delivery_attempt" ("order_id");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_manual_delivery_attempt_uk_manual_delivery_attempt_key" ON "manual_delivery_attempt" ("idempotency_key");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_delivery_goods_config_uk_delivery_goods_config_goods" ON "delivery_goods_config" ("goods_id");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_remote_goods_delete_attempt_uk_remote_goods_delete_attempt_goods" ON "remote_goods_delete_attempt" ("goods_id");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_remote_goods_delete_attempt_uk_remote_goods_delete_attempt_key" ON "remote_goods_delete_attempt" ("idempotency_key");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_external_operation_attempt_uk_external_operation_attempt_key" ON "external_operation_attempt" ("idempotency_key");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_user_business_setting_uk_user_business_setting_user_key" ON "user_business_setting" ("user_id", "setting_key");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_realtime_delivery_attempt_uk_realtime_delivery_attempt_event" ON "realtime_delivery_attempt" ("event_key");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_ai_auto_reply_attempt_uk_ai_auto_reply_attempt_event" ON "ai_auto_reply_attempt" ("event_key");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_ai_auto_reply_attempt_uk_ai_auto_reply_attempt_source" ON "ai_auto_reply_attempt" ("account_id", "source_message_digest");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_manual_message_attempt_uk_manual_message_attempt_key" ON "manual_message_attempt" ("idempotency_key");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_goods_off_shelf_attempt_uk_goods_off_shelf_attempt_key" ON "goods_off_shelf_attempt" ("idempotency_key");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_message_automation_outbox_uk_message_automation_source_branch" ON "message_automation_outbox" ("account_id", "source_message_digest", "branch");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_message_automation_outbox_uk_message_automation_message_branch" ON "message_automation_outbox" ("chat_message_id", "branch");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_notification_test_attempt_uk_notification_test_attempt_key" ON "notification_test_attempt" ("idempotency_key");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_notification_event_attempt_uk_notification_event_generation" ON "notification_event_attempt" ("event_type", "account_id", "target_digest", "generation");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_item_polish_task_uk_item_polish_task_id" ON "item_polish_task" ("task_id");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_item_polish_task_uk_item_polish_task_key" ON "item_polish_task" ("idempotency_key");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_item_polish_task_item_uk_item_polish_task_goods" ON "item_polish_task_item" ("task_db_id", "goods_id");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_admin_user_uk_admin_user_username" ON "admin_user" ("username");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_admin_user_uk_admin_user_email" ON "admin_user" ("email");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_xianyu_goods_sync_task_sync_id" ON "xianyu_goods_sync_task" ("sync_id");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_xianyu_remote_slider_solve_record_uk_request_id" ON "xianyu_remote_slider_solve_record" ("request_id");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_xianyu_refund_uk_refund_account_external" ON "xianyu_refund" ("account_id", "external_refund_id");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_xianyu_refund_sync_task_uk_refund_sync_id" ON "xianyu_refund_sync_task" ("sync_id");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_xianyu_refund_account_state_uk_refund_state_account" ON "xianyu_refund_account_state" ("account_id");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_xianyu_account_membership_uk_account_membership" ON "xianyu_account_membership" ("account_id");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_xianyu_goods_sku_uk_goods_sku" ON "xianyu_goods_sku" ("goods_id", "sku_id");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_xianyu_rate_uk_rate_account_order" ON "xianyu_rate" ("account_id", "external_order_id");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_xianyu_rate_sync_task_uk_rate_sync_id" ON "xianyu_rate_sync_task" ("sync_id");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_xianyu_rate_account_state_uk_rate_state_account" ON "xianyu_rate_account_state" ("account_id");
CREATE UNIQUE INDEX IF NOT EXISTS "desktop_xianyu_account_auto_rate_config_uk_xyaarc_account" ON "xianyu_account_auto_rate_config" ("account_id");

-- Additional original raw-SQL compatibility columns.
ALTER TABLE "delivery_text_source" ADD COLUMN "source_type" VARCHAR(50) NOT NULL DEFAULT 'text';
ALTER TABLE "delivery_text_source" ADD COLUMN "delivery_mode" VARCHAR(20) NOT NULL DEFAULT 'text';
ALTER TABLE "delivery_text_source" ADD COLUMN "card_group_id" BIGINT NULL;
ALTER TABLE "delivery_text_source" ADD COLUMN "segments" JSON NULL;
ALTER TABLE "card_group" ADD COLUMN "sku_property_key" VARCHAR(500) NULL;
