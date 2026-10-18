"""Complete source-pinned Agent OS DDL registry for offline conversion.

No project modules are imported and no SQL is executed here. SQLite-generated
objects are tracked separately and must be verified after engine creation.
"""

from __future__ import annotations

COMPLETE_AGENT_STATE_DDL = {
    "tables": {'agent_blackboard': '\n'
                     '                        CREATE TABLE IF NOT EXISTS agent_blackboard (\n'
                     '                            board_id TEXT NOT NULL,\n'
                     '                            section TEXT NOT NULL,\n'
                     '                            content TEXT NOT NULL,\n'
                     '                            author TEXT NOT NULL,\n'
                     '                            vector_clock TEXT NOT NULL,\n'
                     '                            timestamp REAL NOT NULL,\n'
                     '                            version INTEGER NOT NULL,\n'
                     '                            PRIMARY KEY (board_id, section)\n'
                     '                        );\n'
                     '                        ',
 'agent_budgets': '\n'
                  '                            CREATE TABLE IF NOT EXISTS agent_budgets (\n'
                  '                                task_id TEXT PRIMARY KEY,\n'
                  '                                max_tokens INTEGER NOT NULL DEFAULT 100000,\n'
                  '                                used_tokens INTEGER NOT NULL DEFAULT 0,\n'
                  '                                max_compute_seconds REAL NOT NULL DEFAULT '
                  '600.0,\n'
                  '                                used_compute_seconds REAL NOT NULL DEFAULT '
                  '0.0,\n'
                  '                                max_external_calls INTEGER NOT NULL DEFAULT '
                  '50,\n'
                  '                                used_external_calls INTEGER NOT NULL DEFAULT '
                  '0,\n'
                  '                                updated_at REAL NOT NULL\n'
                  '                            )\n'
                  '                            ',
 'agent_change_intents': '\n'
                         '                            CREATE TABLE IF NOT EXISTS '
                         'agent_change_intents (\n'
                         '                                change_id TEXT PRIMARY KEY,\n'
                         '                                task_id TEXT NOT NULL,\n'
                         '                                affected_paths TEXT NOT NULL,\n'
                         '                                affected_symbols TEXT NOT NULL,\n'
                         '                                expected_impact TEXT NOT NULL,\n'
                         '                                rollback_description TEXT NOT NULL,\n'
                         '                                created_at REAL NOT NULL\n'
                         '                            );\n'
                         '                            ',
 'agent_entity_relations': '\n'
                           '                            CREATE TABLE IF NOT EXISTS '
                           'agent_entity_relations (\n'
                           '                                relation_id TEXT PRIMARY KEY,\n'
                           '                                source_entity TEXT NOT NULL,\n'
                           '                                relation TEXT NOT NULL,\n'
                           '                                target_entity TEXT NOT NULL,\n'
                           '                                weight REAL NOT NULL DEFAULT 1.0,\n'
                           "                                metadata TEXT NOT NULL DEFAULT '{}',\n"
                           '                                created_at REAL NOT NULL,\n'
                           '                                updated_at REAL NOT NULL\n'
                           '                            );\n'
                           '                            ',
 'agent_event_cursors': '\n'
                        '                            CREATE TABLE IF NOT EXISTS '
                        'agent_event_cursors (\n'
                        '                                stream_id TEXT PRIMARY KEY,\n'
                        '                                last_seq INTEGER NOT NULL,\n'
                        '                                first_retained_seq INTEGER NOT NULL\n'
                        '                            )\n'
                        '                        ',
 'agent_events': '\n'
                 '                            CREATE TABLE IF NOT EXISTS agent_events (\n'
                 '                                stream_id TEXT NOT NULL,\n'
                 '                                seq INTEGER NOT NULL,\n'
                 '                                event_id TEXT NOT NULL,\n'
                 '                                kind TEXT NOT NULL,\n'
                 '                                payload TEXT NOT NULL,\n'
                 '                                idempotency_key TEXT NOT NULL,\n'
                 '                                correlation_id TEXT NOT NULL,\n'
                 '                                actor TEXT NOT NULL,\n'
                 '                                created_at REAL NOT NULL,\n'
                 '                                PRIMARY KEY (stream_id, seq),\n'
                 '                                UNIQUE (stream_id, idempotency_key)\n'
                 '                            )\n'
                 '                        ',
 'agent_incidents': '\n'
                    '                            CREATE TABLE IF NOT EXISTS agent_incidents (\n'
                    '                                incident_id TEXT PRIMARY KEY,\n'
                    '                                operation_class TEXT NOT NULL,\n'
                    '                                error_class TEXT NOT NULL,\n'
                    '                                signature_hash TEXT NOT NULL,\n'
                    '                                redacted_message TEXT NOT NULL,\n'
                    '                                state_revision TEXT NOT NULL,\n'
                    '                                attempts INTEGER NOT NULL,\n'
                    '                                evidence_ids TEXT NOT NULL,\n'
                    '                                root_cause TEXT,\n'
                    '                                verified_fix TEXT,\n'
                    '                                confidence REAL NOT NULL,\n'
                    '                                resolved INTEGER NOT NULL,\n'
                    '                                created_at REAL NOT NULL,\n'
                    '                                updated_at REAL NOT NULL,\n'
                    '                                expires_at REAL,\n'
                    "                                affected_paths TEXT NOT NULL DEFAULT '[]',\n"
                    '                                ignored INTEGER NOT NULL DEFAULT 0,\n'
                    "                                repository_key TEXT NOT NULL DEFAULT ''\n"
                    '                            );\n'
                    '                            ',
 'agent_knowledge_links': '\n'
                          '                            CREATE TABLE IF NOT EXISTS '
                          'agent_knowledge_links (\n'
                          '                                link_id TEXT PRIMARY KEY,\n'
                          '                                source_id TEXT NOT NULL,\n'
                          '                                target_id TEXT NOT NULL,\n'
                          '                                relationship TEXT NOT NULL,\n'
                          '                                path TEXT NOT NULL,\n'
                          '                                revision TEXT NOT NULL,\n'
                          '                                valid INTEGER NOT NULL,\n'
                          '                                created_at REAL NOT NULL\n'
                          '                            );\n'
                          '                            ',
 'agent_learning_candidates': '\n'
                              '                        CREATE TABLE IF NOT EXISTS '
                              'agent_learning_candidates (\n'
                              '                            candidate_id TEXT PRIMARY KEY,\n'
                              '                            name TEXT NOT NULL,\n'
                              '                            baseline_version TEXT NOT NULL,\n'
                              '                            candidate_version TEXT NOT NULL,\n'
                              '                            status TEXT NOT NULL,\n'
                              '                            slo_thresholds TEXT NOT NULL,\n'
                              '                            metrics TEXT NOT NULL,\n'
                              '                            approver TEXT NOT NULL,\n'
                              '                            created_at REAL NOT NULL,\n'
                              '                            updated_at REAL NOT NULL\n'
                              '                        );\n'
                              '                        ',
 'agent_memory_embeddings': '\n'
                            '                            CREATE TABLE IF NOT EXISTS '
                            'agent_memory_embeddings (\n'
                            '                                record_id TEXT PRIMARY KEY,\n'
                            '                                embedding TEXT NOT NULL,\n'
                            '                                created_at REAL NOT NULL\n'
                            '                            );\n'
                            '                            ',
 'agent_memory_fts': '\n'
                     '                                CREATE VIRTUAL TABLE IF NOT EXISTS '
                     'agent_memory_fts USING fts5(\n'
                     '                                    record_id UNINDEXED,\n'
                     '                                    key,\n'
                     '                                    value,\n'
                     "                                    tokenize='unicode61'\n"
                     '                                );\n'
                     '                                ',
 'agent_memory_records': '\n'
                         '                            CREATE TABLE IF NOT EXISTS '
                         'agent_memory_records (\n'
                         '                                record_id TEXT PRIMARY KEY,\n'
                         '                                kind TEXT NOT NULL,\n'
                         '                                scope TEXT NOT NULL,\n'
                         '                                scope_id TEXT NOT NULL,\n'
                         '                                key TEXT NOT NULL,\n'
                         '                                value TEXT NOT NULL,\n'
                         '                                status TEXT NOT NULL,\n'
                         '                                confidence REAL NOT NULL,\n'
                         '                                source TEXT NOT NULL,\n'
                         '                                evidence_ids TEXT NOT NULL,\n'
                         '                                sensitivity TEXT NOT NULL,\n'
                         '                                contradicts_record_id TEXT,\n'
                         '                                supersedes_record_id TEXT,\n'
                         '                                quarantine_reason TEXT,\n'
                         '                                provenance TEXT NOT NULL,\n'
                         '                                created_at REAL NOT NULL,\n'
                         '                                updated_at REAL NOT NULL,\n'
                         '                                expires_at REAL\n'
                         '                            );\n'
                         '                            ',
 'agent_outcomes': '\n'
                   '                            CREATE TABLE IF NOT EXISTS agent_outcomes (\n'
                   '                                outcome_id TEXT PRIMARY KEY,\n'
                   '                                change_id TEXT NOT NULL,\n'
                   '                                task_id TEXT NOT NULL,\n'
                   '                                kind TEXT NOT NULL,\n'
                   '                                actor TEXT NOT NULL,\n'
                   '                                details TEXT NOT NULL,\n'
                   '                                created_at REAL NOT NULL\n'
                   '                            );\n'
                   '                            ',
 'agent_questions': '\n'
                    '                        CREATE TABLE IF NOT EXISTS agent_questions (\n'
                    '                            question_id TEXT PRIMARY KEY,\n'
                    '                            root TEXT NOT NULL,\n'
                    '                            session_id TEXT NOT NULL,\n'
                    "                            task_id TEXT NOT NULL DEFAULT '',\n"
                    '                            question TEXT NOT NULL,\n'
                    "                            answer TEXT NOT NULL DEFAULT '',\n"
                    '                            status TEXT NOT NULL,\n'
                    '                            asked_by TEXT NOT NULL,\n'
                    "                            answered_by TEXT NOT NULL DEFAULT '',\n"
                    '                            created_at REAL NOT NULL,\n'
                    '                            answered_at REAL\n'
                    '                        );\n'
                    '                        ',
 'agent_snapshots': '\n'
                    '                            CREATE TABLE IF NOT EXISTS agent_snapshots (\n'
                    '                                snapshot_id INTEGER PRIMARY KEY '
                    'AUTOINCREMENT,\n'
                    '                                stream_id TEXT NOT NULL,\n'
                    '                                seq INTEGER NOT NULL,\n'
                    '                                state TEXT NOT NULL,\n'
                    '                                created_at REAL NOT NULL\n'
                    '                            )\n'
                    '                        ',
 'agent_swarms': '\n'
                 '                    CREATE TABLE IF NOT EXISTS agent_swarms (\n'
                 '                        swarm_id TEXT PRIMARY KEY,\n'
                 '                        goal TEXT NOT NULL,\n'
                 '                        target_paths TEXT NOT NULL,\n'
                 '                        test_command TEXT NOT NULL,\n'
                 '                        author TEXT NOT NULL,\n'
                 '                        root TEXT NOT NULL,\n'
                 '                        state TEXT NOT NULL,\n'
                 '                        receipt_id TEXT,\n'
                 '                        history TEXT NOT NULL,\n'
                 '                        created_at REAL NOT NULL,\n'
                 '                        updated_at REAL NOT NULL,\n'
                 '                        version INTEGER NOT NULL\n'
                 '                    )\n'
                 '                    ',
 'agent_task_search_documents': 'CREATE TABLE IF NOT EXISTS agent_task_search_documents (task_id '
                                'TEXT PRIMARY KEY, fields TEXT NOT NULL)',
 'agent_task_search_grams': 'CREATE TABLE IF NOT EXISTS agent_task_search_grams (task_id TEXT NOT '
                            'NULL, gram TEXT NOT NULL, PRIMARY KEY(task_id, gram))',
 'agent_tasks_projection': '\n'
                           '                        CREATE TABLE IF NOT EXISTS '
                           'agent_tasks_projection (\n'
                           '                            task_id TEXT PRIMARY KEY,\n'
                           '                            status TEXT NOT NULL,\n'
                           '                            owner TEXT NOT NULL,\n'
                           '                            lease_id TEXT NOT NULL,\n'
                           '                            contract TEXT NOT NULL,\n'
                           '                            context TEXT NOT NULL,\n'
                           '                            checkpoint TEXT NOT NULL,\n'
                           '                            receipts TEXT NOT NULL,\n'
                           '                            heartbeat_expires_at REAL NOT NULL,\n'
                           '                            created_at REAL NOT NULL,\n'
                           '                            updated_at REAL NOT NULL\n'
                           '                        );\n'
                           '                        ',
 'agent_verification_receipts': '\n'
                                '                            CREATE TABLE IF NOT EXISTS '
                                'agent_verification_receipts (\n'
                                '                                receipt_id TEXT PRIMARY KEY,\n'
                                '                                task_id TEXT NOT NULL,\n'
                                '                                criterion TEXT NOT NULL,\n'
                                '                                change_intent_id TEXT NOT NULL,\n'
                                '                                evidence_id TEXT NOT NULL,\n'
                                '                                command_id TEXT NOT NULL,\n'
                                '                                repository_revision TEXT NOT '
                                'NULL,\n'
                                '                                observed_at REAL NOT NULL,\n'
                                '                                expires_at REAL,\n'
                                '                                passed INTEGER NOT NULL,\n'
                                '                                details TEXT NOT NULL\n'
                                '                            );\n'
                                '                            ',
 'agent_verification_task_outbox': '\n'
                                   '                            CREATE TABLE IF NOT EXISTS '
                                   'agent_verification_task_outbox (\n'
                                   '                                receipt_id TEXT PRIMARY KEY,\n'
                                   '                                task_id TEXT NOT NULL,\n'
                                   '                                criterion TEXT NOT NULL,\n'
                                   '                                status TEXT NOT NULL DEFAULT '
                                   "'pending',\n"
                                   '                                created_at REAL NOT NULL,\n'
                                   '                                completed_at REAL\n'
                                   '                            );\n'
                                   '                            ',
 'lease_waits': 'CREATE TABLE IF NOT EXISTS lease_waits (\n'
                '                                owner TEXT NOT NULL,\n'
                '                                blocked_by TEXT NOT NULL,\n'
                '                                root_id TEXT NOT NULL,\n'
                '                                requested_path TEXT NOT NULL,\n'
                '                                updated_at REAL NOT NULL,\n'
                '                                PRIMARY KEY(root_id, owner, blocked_by, '
                'requested_path)\n'
                '                            )',
 'leases': 'CREATE TABLE IF NOT EXISTS leases (\n'
           '                                lease_id TEXT NOT NULL,\n'
           '                                owner TEXT NOT NULL,\n'
           '                                root_id TEXT NOT NULL,\n'
           '                                root_path TEXT NOT NULL,\n'
           '                                path TEXT NOT NULL,\n'
           '                                purpose TEXT NOT NULL,\n'
           '                                created_at REAL NOT NULL,\n'
           '                                expires_at REAL NOT NULL,\n'
           '                                PRIMARY KEY(lease_id, path)\n'
           '                            )'},
    "indexes": ('CREATE INDEX IF NOT EXISTS idx_agent_events_created ON agent_events (created_at)',
 'CREATE INDEX IF NOT EXISTS idx_agent_events_kind ON agent_events (kind)',
 'CREATE INDEX IF NOT EXISTS idx_agent_snapshots_stream ON agent_snapshots (stream_id, seq DESC)',
 '\n'
 '                            CREATE INDEX IF NOT EXISTS idx_agent_memory_scope_key\n'
 '                            ON agent_memory_records (scope, key, status);\n'
 '                            ',
 '\n'
 '                            CREATE INDEX IF NOT EXISTS idx_agent_memory_scope_identity\n'
 '                            ON agent_memory_records (scope, scope_id, status, updated_at DESC);\n'
 '                            ',
 '\n'
 '                                CREATE INDEX IF NOT EXISTS idx_agent_memory_provenance_root\n'
 '                                ON agent_memory_records (\n'
 '                                    scope,\n'
 '                                    json_extract(CASE WHEN json_valid(provenance) THEN '
 "provenance ELSE '{}' END, '$.root'),\n"
 '                                    status,\n'
 '                                    updated_at DESC\n'
 '                                );\n'
 '                                ',
 '\n'
 '                            CREATE INDEX IF NOT EXISTS idx_agent_memory_provenance_repository\n'
 '                            ON agent_memory_records (\n'
 '                                scope,\n'
 '                                json_extract(CASE WHEN json_valid(provenance) THEN provenance '
 "ELSE '{}' END, '$.repository_id'),\n"
 '                                status,\n'
 '                                updated_at DESC\n'
 '                            );\n'
 '                            ',
 '\n'
 '                            CREATE INDEX IF NOT EXISTS idx_agent_memory_updated\n'
 '                            ON agent_memory_records (updated_at DESC);\n'
 '                            ',
 '\n'
 '                            CREATE INDEX IF NOT EXISTS idx_agent_memory_expires\n'
 '                            ON agent_memory_records (expires_at)\n'
 '                            WHERE expires_at IS NOT NULL;\n'
 '                            ',
 'CREATE INDEX IF NOT EXISTS idx_entity_rel_source ON agent_entity_relations(source_entity);',
 'CREATE INDEX IF NOT EXISTS idx_entity_rel_target ON agent_entity_relations(target_entity);',
 'CREATE INDEX IF NOT EXISTS idx_entity_rel_type ON agent_entity_relations(relation);',
 '\n'
 '                                CREATE INDEX IF NOT EXISTS idx_agent_memory_provenance_branch\n'
 '                                ON agent_memory_records (\n'
 '                                    scope,\n'
 '                                    json_extract(CASE WHEN json_valid(provenance) THEN '
 "provenance ELSE '{}' END, '$.branch'),\n"
 '                                    status,\n'
 '                                    updated_at DESC\n'
 '                                );\n'
 '                                ',
 '\n'
 '                                CREATE INDEX IF NOT EXISTS idx_agent_memory_provenance_clone_id\n'
 '                                ON agent_memory_records (\n'
 '                                    scope,\n'
 '                                    json_extract(CASE WHEN json_valid(provenance) THEN '
 "provenance ELSE '{}' END, '$.clone_id'),\n"
 '                                    status,\n'
 '                                    updated_at DESC\n'
 '                                );\n'
 '                                ',
 '\n'
 '                                CREATE INDEX IF NOT EXISTS '
 'idx_agent_memory_provenance_worktree_id\n'
 '                                ON agent_memory_records (\n'
 '                                    scope,\n'
 '                                    json_extract(CASE WHEN json_valid(provenance) THEN '
 "provenance ELSE '{}' END, '$.worktree_id'),\n"
 '                                    status,\n'
 '                                    updated_at DESC\n'
 '                                );\n'
 '                                ',
 'CREATE INDEX IF NOT EXISTS idx_agent_task_search_grams_gram ON agent_task_search_grams(gram, '
 'task_id)',
 '\n'
 '                        CREATE INDEX IF NOT EXISTS idx_agent_tasks_status\n'
 '                        ON agent_tasks_projection (status, heartbeat_expires_at);\n'
 '                        ',
 '\n'
 '                        CREATE INDEX IF NOT EXISTS idx_agent_tasks_updated\n'
 '                        ON agent_tasks_projection (updated_at DESC);\n'
 '                        ',
 '\n'
 '                        CREATE INDEX IF NOT EXISTS idx_agent_tasks_status_updated\n'
 '                        ON agent_tasks_projection (status, updated_at DESC);\n'
 '                        ',
 '\n'
 '                        CREATE INDEX IF NOT EXISTS idx_agent_questions_session\n'
 '                        ON agent_questions (root, session_id, created_at DESC);\n'
 '                        ',
 '\n'
 '                            CREATE INDEX IF NOT EXISTS idx_agent_verif_task\n'
 '                            ON agent_verification_receipts (task_id, criterion, observed_at '
 'DESC);\n'
 '                            ',
 '\n'
 '                            CREATE INDEX IF NOT EXISTS idx_agent_verif_task_observed\n'
 '                            ON agent_verification_receipts (task_id, observed_at DESC);\n'
 '                            ',
 'CREATE INDEX IF NOT EXISTS idx_agent_verif_task_outbox_pending ON '
 'agent_verification_task_outbox(status, created_at)',
 '\n'
 '                            CREATE INDEX IF NOT EXISTS idx_agent_change_task\n'
 '                            ON agent_change_intents (task_id);\n'
 '                            ',
 '\n'
 '                            CREATE INDEX IF NOT EXISTS idx_agent_outcomes_task\n'
 '                            ON agent_outcomes (task_id);\n'
 '                            ',
 '\n'
 '                            CREATE INDEX IF NOT EXISTS idx_agent_outcomes_change\n'
 '                            ON agent_outcomes (change_id);\n'
 '                            ',
 'CREATE INDEX IF NOT EXISTS idx_blackboard_board ON agent_blackboard(board_id)',
 '\n'
 '                            CREATE INDEX IF NOT EXISTS idx_agent_klinks_path\n'
 '                            ON agent_knowledge_links (path, valid);\n'
 '                            ',
 '\n'
 '                            CREATE INDEX IF NOT EXISTS idx_agent_incidents_fp\n'
 '                            ON agent_incidents (error_class, operation_class, signature_hash, '
 'state_revision);\n'
 '                            ',
 '\n'
 '                            CREATE INDEX IF NOT EXISTS idx_agent_incidents_lookup\n'
 '                            ON agent_incidents (operation_class, signature_hash, state_revision, '
 'updated_at DESC);\n'
 '                            ',
 '\n'
 '                            CREATE INDEX IF NOT EXISTS idx_agent_incidents_recent\n'
 '                            ON agent_incidents (operation_class, signature_hash, updated_at '
 'DESC);\n'
 '                            ',
 '\n'
 '                            CREATE INDEX IF NOT EXISTS idx_agent_incidents_scope\n'
 '                            ON agent_incidents (repository_key, ignored, updated_at DESC);\n'
 '                            ',
 'CREATE INDEX IF NOT EXISTS idx_agent_budgets_task ON agent_budgets(task_id)',
 'CREATE INDEX IF NOT EXISTS idx_leases_root ON leases(root_id, expires_at)',
 'CREATE INDEX IF NOT EXISTS idx_lease_waits_owner ON lease_waits(owner)',
 'CREATE INDEX IF NOT EXISTS idx_lease_waits_blocked ON lease_waits(blocked_by)'),
}

GENERATED_OBJECT_HASHES = {('table', 'agent_memory_fts_config', 'agent_memory_fts_config'): 'e78061e43ffaa4b703c9aa4a44e02c6bae4128c3b1aad6a4324e6d3b97772c02',
 ('table', 'agent_memory_fts_content', 'agent_memory_fts_content'): '3ad7416c82b07bb41be9b2d30e58886c16cef8d5ab7a31f2834dc2d087fd6368',
 ('table', 'agent_memory_fts_data', 'agent_memory_fts_data'): '069959f382044c08715841b26cef2b51fd926354471f1fe5a680d976760ba2b0',
 ('table', 'agent_memory_fts_docsize', 'agent_memory_fts_docsize'): '39dc58937b569ac9aac16ef8e847d4a647b5e35feff50261c75b8eb8447f3567',
 ('table', 'agent_memory_fts_idx', 'agent_memory_fts_idx'): '68d1a21899a38af4e033e9dcd254abe1aff6dfed08bfbaac4916d8873a290cfd',
 ('table', 'sqlite_sequence', 'sqlite_sequence'): '9e042902d97481bf7dccaaff2183d686b3344691bb622fdfc017096ef4080c65'}

SOURCE_OBJECT_HASHES = {('index', 'idx_agent_budgets_task', 'agent_budgets'): 'bcf430cc5b43169c32c9a6493b85943f219431ea8e688bdfe76f7284734c20f9',
 ('index', 'idx_agent_change_task', 'agent_change_intents'): '59e49e948f8ccd127cd4698378e49e66af98e872ec9fcf1e23445854cb88440b',
 ('index', 'idx_agent_events_created', 'agent_events'): 'bc5acedde3a15256f0c4de4628d1beadfe846b30f7b89738f3e7f030de635dba',
 ('index', 'idx_agent_events_kind', 'agent_events'): 'ea38ef5ba6de50080cd324a3a41177914e9b37f12ffc62a76d37b2f7fe7a5b9b',
 ('index', 'idx_agent_incidents_fp', 'agent_incidents'): '4b67662bd5955574d1cce114df205ba62a1e0f5165613b4edd16072d34339709',
 ('index', 'idx_agent_incidents_lookup', 'agent_incidents'): 'f170ab3ca4813c2fde1ef264a4a148c1ad08c0a6ea7243119864d2f7d35e58d9',
 ('index', 'idx_agent_incidents_recent', 'agent_incidents'): '2dabb490a313b3f49ec8cf3bbec38e5dd7d7869db9dc9ea69474d96fe86260a8',
 ('index', 'idx_agent_incidents_scope', 'agent_incidents'): '00d5a148686c8a351822ae7a5a15ad152b05b877f94720f691e56c399a2ddfb0',
 ('index', 'idx_agent_klinks_path', 'agent_knowledge_links'): 'a765bbe0d7e69856c925200094c53bbd726cfaec770d274d4451b18b40e52b32',
 ('index', 'idx_agent_memory_expires', 'agent_memory_records'): '2b572d27d7aeff30fd4f5bac34028828f8cea53b3e7a33a365ecd2ac8d62bda6',
 ('index', 'idx_agent_memory_provenance_branch', 'agent_memory_records'): 'd2bbcbdc38fffca0533cc1fb185773d0d7063c91e7318838a15bfb4a3ef919ff',
 ('index', 'idx_agent_memory_provenance_clone_id', 'agent_memory_records'): '1a9eb17c7d175eecbfadac0a08d55217eef4b0edf1c4c05d66a2eb5730a3682a',
 ('index', 'idx_agent_memory_provenance_repository', 'agent_memory_records'): '54eb35186ea96928612021440a3a8a41e69c7af684011efcc2dd7d97900f80fe',
 ('index', 'idx_agent_memory_provenance_root', 'agent_memory_records'): '368aa7550b0f3c86744f5c88741b5d6fa30fe1fd8a5f218561920cf5aff86c0e',
 ('index', 'idx_agent_memory_provenance_worktree_id', 'agent_memory_records'): 'ede3797ba9a084d4e4a1539166ce72e442830fd0f4a7148ee288bd29e476fa34',
 ('index', 'idx_agent_memory_scope_identity', 'agent_memory_records'): 'e09ea6e01564f92238fa9aac558fff356d8663bb92a1b00a3cc8484d1316e23c',
 ('index', 'idx_agent_memory_scope_key', 'agent_memory_records'): '87c860ab42d5e672c4c6fc123fcca090dc52e6a0382a15855d4dde2b73e49448',
 ('index', 'idx_agent_memory_updated', 'agent_memory_records'): '776e3e88b071833f15e7db3c0b57ca63c9485b092090df307ff29b774c49515a',
 ('index', 'idx_agent_outcomes_change', 'agent_outcomes'): 'dc6d7b5ac5f463fb8abeed07c55fb5c88a2c51430eeb67b16858ee634dfb269b',
 ('index', 'idx_agent_outcomes_task', 'agent_outcomes'): '225296df966ea88b0d47e85fb1a4b90f93b29d666d35da0ae2dfb55bcee3323b',
 ('index', 'idx_agent_questions_session', 'agent_questions'): '895948e4ff978d089295a00870cb4109bc3b86498d592e089e5bdd16073ca6cd',
 ('index', 'idx_agent_snapshots_stream', 'agent_snapshots'): '974fd8531f2206bcfa74ed26c733469ef576b19515b91ce78fe941d83fbcc1e8',
 ('index', 'idx_agent_task_search_grams_gram', 'agent_task_search_grams'): '47289e8fa6b5eb7e6837a56d77ad684e26fbc466f43f0f7af252e77fb8af5e0a',
 ('index', 'idx_agent_tasks_status', 'agent_tasks_projection'): '0ac7b279372bdaed3b7c47acd6c70e4cd7b1e0df1e1890edfc66eac4bdc03330',
 ('index', 'idx_agent_tasks_status_updated', 'agent_tasks_projection'): '1d0fdd9dab8677f811492c31f26bab3af568f441de5e64b4b94b6c710598a211',
 ('index', 'idx_agent_tasks_updated', 'agent_tasks_projection'): '1c25fa23c988e8b730986555513e083454c134172930baf51dad9eb18f11ff67',
 ('index', 'idx_agent_verif_task', 'agent_verification_receipts'): '2b5073bea40ea5e312fc9aa761494ec53718927f90eae8dbe2987ec4765f2760',
 ('index', 'idx_agent_verif_task_observed', 'agent_verification_receipts'): '462c305e52d335c8368e5c0c4540c4936c83a8c3932746402403c5d8e91e8dc1',
 ('index', 'idx_agent_verif_task_outbox_pending', 'agent_verification_task_outbox'): '50dff1b755ee28d10c80d199270f9f6b12fb2ca958b4a8948cb59ac6ff751f48',
 ('index', 'idx_blackboard_board', 'agent_blackboard'): '8766cf9835a46d47cdca628a456ab1b0a807c11d588fa671b64ba19fb699b5e4',
 ('index', 'idx_entity_rel_source', 'agent_entity_relations'): '816b220dbed8e3d6d99610d66e1254d90e381c25fef2902dddba2714220053d5',
 ('index', 'idx_entity_rel_target', 'agent_entity_relations'): 'aa0be23cd9565e612f9252c63fb003fbabcd9fc5fe04df590eb1db2754a91f00',
 ('index', 'idx_entity_rel_type', 'agent_entity_relations'): '77fbc5362e7da269cdc53ee755d690d0f762d8ff3e5ab9c6e87a6e358bdd8330',
 ('index', 'idx_lease_waits_blocked', 'lease_waits'): '366fe3b81e54f9032edecf9d798a2b2d23160bba578438a89591b929c1e87cab',
 ('index', 'idx_lease_waits_owner', 'lease_waits'): '94c3e39e5224c63a4a855ea3843bd86cb490af2c1e993d567af26dc5ba9bc851',
 ('index', 'idx_leases_root', 'leases'): 'a0ede5303197cc5172c5583f33a72ee1636083712d84e9d618a642a34671cc85',
 ('table', 'agent_blackboard', 'agent_blackboard'): 'fb18c17d6581de546f148b5b302188dda9013374d653dc7cb9511021ebc6c1e3',
 ('table', 'agent_budgets', 'agent_budgets'): 'fbcda82d934dce0695d9cb9edd9d7c1386e5320a2aac79c5194eee55471982df',
 ('table', 'agent_change_intents', 'agent_change_intents'): '52ed988b0a31f820b145261f7c586ea869369958b8adcd21d6bd1ad7e1f8a9ca',
 ('table', 'agent_entity_relations', 'agent_entity_relations'): '7cb3cdb25d201d7e2e264eb0d2b3dda5bb831ffd531d7aea2dab79df6db26590',
 ('table', 'agent_event_cursors', 'agent_event_cursors'): '0ecf2e08637aef9d2f4a9167feb61de083e1a9d9b8b927f79ae7a58e74b2ef71',
 ('table', 'agent_events', 'agent_events'): '1dfef49210889dc707aa8405b65262a5a86acbc14bd940ca338293dde150b2a2',
 ('table', 'agent_incidents', 'agent_incidents'): '4b4e60c8124637cb345f05d386428fc7bcb9c23b518af0b17125f3a4bfaf85d7',
 ('table', 'agent_knowledge_links', 'agent_knowledge_links'): '729e5c852a59ef150c488ccfb998a8a4dab606a052d353d94360aa2793a62426',
 ('table', 'agent_learning_candidates', 'agent_learning_candidates'): '3b8650b155c972e370825d72cf2222c005401a696b7f996a991c1f9d552b5caa',
 ('table', 'agent_memory_embeddings', 'agent_memory_embeddings'): '468df99dabe588d9475009d02108f2fdadfcf63e83a7aedf6d7a36a9ead965b5',
 ('table', 'agent_memory_fts', 'agent_memory_fts'): 'a3f3691e421244a8516c26f942a893b8b7a112b7771e9ba84ecded8eab4e3755',
 ('table', 'agent_memory_records', 'agent_memory_records'): '5cd8a7e88151416c741554d667ef08dfd8469b645870f26ccadc436cfddc25c0',
 ('table', 'agent_outcomes', 'agent_outcomes'): '624b2b6c004fe2d59814db6d948d1bd043a73dfc10a9d83127e7450a05d90144',
 ('table', 'agent_questions', 'agent_questions'): '6e32f781ef50c6664ce70e93dbb767a6889d1cffc80f766a83548209eaebd19c',
 ('table', 'agent_snapshots', 'agent_snapshots'): '323b038ec2305f3aa746737408a3a024da0f222285101d5e0bea9729cf5fdb69',
 ('table', 'agent_swarms', 'agent_swarms'): '5ccda29c6b858caae83c2ca78296c4ff939f7ae41cdab14054e67bf374592a81',
 ('table', 'agent_task_search_documents', 'agent_task_search_documents'): 'a291a7122e95c8b2f3f6b9a9a73269489b1794ceea3f4378d9ff6155fd900f93',
 ('table', 'agent_task_search_grams', 'agent_task_search_grams'): 'd2f7c3b733bc0ffcee4d9ee72804edc3fedc36f73f7ceca5ce18662941a13b78',
 ('table', 'agent_tasks_projection', 'agent_tasks_projection'): 'd4283f29e8560ff94ae0877f38c1fdd8020a2d8e2fc6c66aa01a58dca6339cc4',
 ('table', 'agent_verification_receipts', 'agent_verification_receipts'): '6aeb2ffafd9572d5325f56e99f7c62455989c3d44772bd83d3e47b6f3abe953a',
 ('table', 'agent_verification_task_outbox', 'agent_verification_task_outbox'): '2f17423836ca86bf09a701a71a27ead55a2c458d02bb9f29e1445a0c0fc11d17',
 ('table', 'lease_waits', 'lease_waits'): 'f2c1464f4eb093891578b4de6a56e3f36473ac056d700ce2afc7a5a0ec098aaa',
 ('table', 'leases', 'leases'): '7a4ef9cfe8d7f31cef9ee8918b214495454dc551e5888a6125e03b95f93f2254'}

RETIRED_ARCHIVE_TABLES = ("agent_state_migrations", "agent_state_schema_versions")
PRESERVE_SQLITE_SEQUENCE_HIGH_WATER = True
FTS_REBUILD_SOURCE = "agent_memory_records"
FTS_REBUILD_FROM_METADATA_ONLY = True

EXPECTED_OBJECT_SQL_HASHES = {('index', 'idx_agent_budgets_task', 'agent_budgets'): 'bcf430cc5b43169c32c9a6493b85943f219431ea8e688bdfe76f7284734c20f9',
 ('index', 'idx_agent_change_task', 'agent_change_intents'): '59e49e948f8ccd127cd4698378e49e66af98e872ec9fcf1e23445854cb88440b',
 ('index', 'idx_agent_events_created', 'agent_events'): 'bc5acedde3a15256f0c4de4628d1beadfe846b30f7b89738f3e7f030de635dba',
 ('index', 'idx_agent_events_kind', 'agent_events'): 'ea38ef5ba6de50080cd324a3a41177914e9b37f12ffc62a76d37b2f7fe7a5b9b',
 ('index', 'idx_agent_incidents_fp', 'agent_incidents'): '4b67662bd5955574d1cce114df205ba62a1e0f5165613b4edd16072d34339709',
 ('index', 'idx_agent_incidents_lookup', 'agent_incidents'): 'f170ab3ca4813c2fde1ef264a4a148c1ad08c0a6ea7243119864d2f7d35e58d9',
 ('index', 'idx_agent_incidents_recent', 'agent_incidents'): '2dabb490a313b3f49ec8cf3bbec38e5dd7d7869db9dc9ea69474d96fe86260a8',
 ('index', 'idx_agent_incidents_scope', 'agent_incidents'): '00d5a148686c8a351822ae7a5a15ad152b05b877f94720f691e56c399a2ddfb0',
 ('index', 'idx_agent_klinks_path', 'agent_knowledge_links'): 'a765bbe0d7e69856c925200094c53bbd726cfaec770d274d4451b18b40e52b32',
 ('index', 'idx_agent_memory_expires', 'agent_memory_records'): '2b572d27d7aeff30fd4f5bac34028828f8cea53b3e7a33a365ecd2ac8d62bda6',
 ('index', 'idx_agent_memory_provenance_branch', 'agent_memory_records'): 'd2bbcbdc38fffca0533cc1fb185773d0d7063c91e7318838a15bfb4a3ef919ff',
 ('index', 'idx_agent_memory_provenance_clone_id', 'agent_memory_records'): '1a9eb17c7d175eecbfadac0a08d55217eef4b0edf1c4c05d66a2eb5730a3682a',
 ('index', 'idx_agent_memory_provenance_repository', 'agent_memory_records'): '54eb35186ea96928612021440a3a8a41e69c7af684011efcc2dd7d97900f80fe',
 ('index', 'idx_agent_memory_provenance_root', 'agent_memory_records'): '368aa7550b0f3c86744f5c88741b5d6fa30fe1fd8a5f218561920cf5aff86c0e',
 ('index', 'idx_agent_memory_provenance_worktree_id', 'agent_memory_records'): 'ede3797ba9a084d4e4a1539166ce72e442830fd0f4a7148ee288bd29e476fa34',
 ('index', 'idx_agent_memory_scope_identity', 'agent_memory_records'): 'e09ea6e01564f92238fa9aac558fff356d8663bb92a1b00a3cc8484d1316e23c',
 ('index', 'idx_agent_memory_scope_key', 'agent_memory_records'): '87c860ab42d5e672c4c6fc123fcca090dc52e6a0382a15855d4dde2b73e49448',
 ('index', 'idx_agent_memory_updated', 'agent_memory_records'): '776e3e88b071833f15e7db3c0b57ca63c9485b092090df307ff29b774c49515a',
 ('index', 'idx_agent_outcomes_change', 'agent_outcomes'): 'dc6d7b5ac5f463fb8abeed07c55fb5c88a2c51430eeb67b16858ee634dfb269b',
 ('index', 'idx_agent_outcomes_task', 'agent_outcomes'): '225296df966ea88b0d47e85fb1a4b90f93b29d666d35da0ae2dfb55bcee3323b',
 ('index', 'idx_agent_questions_session', 'agent_questions'): '895948e4ff978d089295a00870cb4109bc3b86498d592e089e5bdd16073ca6cd',
 ('index', 'idx_agent_snapshots_stream', 'agent_snapshots'): '974fd8531f2206bcfa74ed26c733469ef576b19515b91ce78fe941d83fbcc1e8',
 ('index', 'idx_agent_task_search_grams_gram', 'agent_task_search_grams'): '47289e8fa6b5eb7e6837a56d77ad684e26fbc466f43f0f7af252e77fb8af5e0a',
 ('index', 'idx_agent_tasks_status', 'agent_tasks_projection'): '0ac7b279372bdaed3b7c47acd6c70e4cd7b1e0df1e1890edfc66eac4bdc03330',
 ('index', 'idx_agent_tasks_status_updated', 'agent_tasks_projection'): '1d0fdd9dab8677f811492c31f26bab3af568f441de5e64b4b94b6c710598a211',
 ('index', 'idx_agent_tasks_updated', 'agent_tasks_projection'): '1c25fa23c988e8b730986555513e083454c134172930baf51dad9eb18f11ff67',
 ('index', 'idx_agent_verif_task', 'agent_verification_receipts'): '2b5073bea40ea5e312fc9aa761494ec53718927f90eae8dbe2987ec4765f2760',
 ('index', 'idx_agent_verif_task_observed', 'agent_verification_receipts'): '462c305e52d335c8368e5c0c4540c4936c83a8c3932746402403c5d8e91e8dc1',
 ('index', 'idx_agent_verif_task_outbox_pending', 'agent_verification_task_outbox'): '50dff1b755ee28d10c80d199270f9f6b12fb2ca958b4a8948cb59ac6ff751f48',
 ('index', 'idx_blackboard_board', 'agent_blackboard'): '8766cf9835a46d47cdca628a456ab1b0a807c11d588fa671b64ba19fb699b5e4',
 ('index', 'idx_entity_rel_source', 'agent_entity_relations'): '816b220dbed8e3d6d99610d66e1254d90e381c25fef2902dddba2714220053d5',
 ('index', 'idx_entity_rel_target', 'agent_entity_relations'): 'aa0be23cd9565e612f9252c63fb003fbabcd9fc5fe04df590eb1db2754a91f00',
 ('index', 'idx_entity_rel_type', 'agent_entity_relations'): '77fbc5362e7da269cdc53ee755d690d0f762d8ff3e5ab9c6e87a6e358bdd8330',
 ('index', 'idx_lease_waits_blocked', 'lease_waits'): '366fe3b81e54f9032edecf9d798a2b2d23160bba578438a89591b929c1e87cab',
 ('index', 'idx_lease_waits_owner', 'lease_waits'): '94c3e39e5224c63a4a855ea3843bd86cb490af2c1e993d567af26dc5ba9bc851',
 ('index', 'idx_leases_root', 'leases'): 'a0ede5303197cc5172c5583f33a72ee1636083712d84e9d618a642a34671cc85',
 ('table', 'agent_blackboard', 'agent_blackboard'): 'fb18c17d6581de546f148b5b302188dda9013374d653dc7cb9511021ebc6c1e3',
 ('table', 'agent_budgets', 'agent_budgets'): 'fbcda82d934dce0695d9cb9edd9d7c1386e5320a2aac79c5194eee55471982df',
 ('table', 'agent_change_intents', 'agent_change_intents'): '52ed988b0a31f820b145261f7c586ea869369958b8adcd21d6bd1ad7e1f8a9ca',
 ('table', 'agent_entity_relations', 'agent_entity_relations'): '7cb3cdb25d201d7e2e264eb0d2b3dda5bb831ffd531d7aea2dab79df6db26590',
 ('table', 'agent_event_cursors', 'agent_event_cursors'): '0ecf2e08637aef9d2f4a9167feb61de083e1a9d9b8b927f79ae7a58e74b2ef71',
 ('table', 'agent_events', 'agent_events'): '1dfef49210889dc707aa8405b65262a5a86acbc14bd940ca338293dde150b2a2',
 ('table', 'agent_incidents', 'agent_incidents'): '4b4e60c8124637cb345f05d386428fc7bcb9c23b518af0b17125f3a4bfaf85d7',
 ('table', 'agent_knowledge_links', 'agent_knowledge_links'): '729e5c852a59ef150c488ccfb998a8a4dab606a052d353d94360aa2793a62426',
 ('table', 'agent_learning_candidates', 'agent_learning_candidates'): '3b8650b155c972e370825d72cf2222c005401a696b7f996a991c1f9d552b5caa',
 ('table', 'agent_memory_embeddings', 'agent_memory_embeddings'): '468df99dabe588d9475009d02108f2fdadfcf63e83a7aedf6d7a36a9ead965b5',
 ('table', 'agent_memory_fts', 'agent_memory_fts'): 'a3f3691e421244a8516c26f942a893b8b7a112b7771e9ba84ecded8eab4e3755',
 ('table', 'agent_memory_fts_config', 'agent_memory_fts_config'): 'e78061e43ffaa4b703c9aa4a44e02c6bae4128c3b1aad6a4324e6d3b97772c02',
 ('table', 'agent_memory_fts_content', 'agent_memory_fts_content'): '3ad7416c82b07bb41be9b2d30e58886c16cef8d5ab7a31f2834dc2d087fd6368',
 ('table', 'agent_memory_fts_data', 'agent_memory_fts_data'): '069959f382044c08715841b26cef2b51fd926354471f1fe5a680d976760ba2b0',
 ('table', 'agent_memory_fts_docsize', 'agent_memory_fts_docsize'): '39dc58937b569ac9aac16ef8e847d4a647b5e35feff50261c75b8eb8447f3567',
 ('table', 'agent_memory_fts_idx', 'agent_memory_fts_idx'): '68d1a21899a38af4e033e9dcd254abe1aff6dfed08bfbaac4916d8873a290cfd',
 ('table', 'agent_memory_records', 'agent_memory_records'): '5cd8a7e88151416c741554d667ef08dfd8469b645870f26ccadc436cfddc25c0',
 ('table', 'agent_outcomes', 'agent_outcomes'): '624b2b6c004fe2d59814db6d948d1bd043a73dfc10a9d83127e7450a05d90144',
 ('table', 'agent_questions', 'agent_questions'): '6e32f781ef50c6664ce70e93dbb767a6889d1cffc80f766a83548209eaebd19c',
 ('table', 'agent_snapshots', 'agent_snapshots'): '323b038ec2305f3aa746737408a3a024da0f222285101d5e0bea9729cf5fdb69',
 ('table', 'agent_swarms', 'agent_swarms'): '5ccda29c6b858caae83c2ca78296c4ff939f7ae41cdab14054e67bf374592a81',
 ('table', 'agent_task_search_documents', 'agent_task_search_documents'): 'a291a7122e95c8b2f3f6b9a9a73269489b1794ceea3f4378d9ff6155fd900f93',
 ('table', 'agent_task_search_grams', 'agent_task_search_grams'): 'd2f7c3b733bc0ffcee4d9ee72804edc3fedc36f73f7ceca5ce18662941a13b78',
 ('table', 'agent_tasks_projection', 'agent_tasks_projection'): 'd4283f29e8560ff94ae0877f38c1fdd8020a2d8e2fc6c66aa01a58dca6339cc4',
 ('table', 'agent_verification_receipts', 'agent_verification_receipts'): '6aeb2ffafd9572d5325f56e99f7c62455989c3d44772bd83d3e47b6f3abe953a',
 ('table', 'agent_verification_task_outbox', 'agent_verification_task_outbox'): '2f17423836ca86bf09a701a71a27ead55a2c458d02bb9f29e1445a0c0fc11d17',
 ('table', 'lease_waits', 'lease_waits'): 'f2c1464f4eb093891578b4de6a56e3f36473ac056d700ce2afc7a5a0ec098aaa',
 ('table', 'leases', 'leases'): '7a4ef9cfe8d7f31cef9ee8918b214495454dc551e5888a6125e03b95f93f2254',
 ('table', 'sqlite_sequence', 'sqlite_sequence'): '9e042902d97481bf7dccaaff2183d686b3344691bb622fdfc017096ef4080c65'}


# Offline-conversion input only; never a supported runtime compatibility contract.
LEGACY_SOURCE_REVISION = 'd40d268f60ba8b27686b652f76cb8edf80c699c4'
LEGACY_SOURCE_OBJECT_HASHES = {('index', 'idx_agent_budgets_task', 'agent_budgets'): 'bcf430cc5b43169c32c9a6493b85943f219431ea8e688bdfe76f7284734c20f9',
 ('index', 'idx_agent_change_task', 'agent_change_intents'): '59e49e948f8ccd127cd4698378e49e66af98e872ec9fcf1e23445854cb88440b',
 ('index', 'idx_agent_events_created', 'agent_events'): 'bc5acedde3a15256f0c4de4628d1beadfe846b30f7b89738f3e7f030de635dba',
 ('index', 'idx_agent_events_kind', 'agent_events'): 'ea38ef5ba6de50080cd324a3a41177914e9b37f12ffc62a76d37b2f7fe7a5b9b',
 ('index', 'idx_agent_incidents_fp', 'agent_incidents'): '4b67662bd5955574d1cce114df205ba62a1e0f5165613b4edd16072d34339709',
 ('index', 'idx_agent_incidents_lookup', 'agent_incidents'): 'f170ab3ca4813c2fde1ef264a4a148c1ad08c0a6ea7243119864d2f7d35e58d9',
 ('index', 'idx_agent_incidents_recent', 'agent_incidents'): '2dabb490a313b3f49ec8cf3bbec38e5dd7d7869db9dc9ea69474d96fe86260a8',
 ('index', 'idx_agent_incidents_scope', 'agent_incidents'): 'fcddf0dcdaa939754d8826b199dc730bfee46c1e3f9f1dc7742757a26b324fc3',
 ('index', 'idx_agent_klinks_path', 'agent_knowledge_links'): 'a765bbe0d7e69856c925200094c53bbd726cfaec770d274d4451b18b40e52b32',
 ('index', 'idx_agent_memory_expires', 'agent_memory_records'): '2b572d27d7aeff30fd4f5bac34028828f8cea53b3e7a33a365ecd2ac8d62bda6',
 ('index', 'idx_agent_memory_provenance_branch', 'agent_memory_records'): 'd2bbcbdc38fffca0533cc1fb185773d0d7063c91e7318838a15bfb4a3ef919ff',
 ('index', 'idx_agent_memory_provenance_clone_id', 'agent_memory_records'): '1a9eb17c7d175eecbfadac0a08d55217eef4b0edf1c4c05d66a2eb5730a3682a',
 ('index', 'idx_agent_memory_provenance_repository', 'agent_memory_records'): '54eb35186ea96928612021440a3a8a41e69c7af684011efcc2dd7d97900f80fe',
 ('index', 'idx_agent_memory_provenance_root', 'agent_memory_records'): '368aa7550b0f3c86744f5c88741b5d6fa30fe1fd8a5f218561920cf5aff86c0e',
 ('index', 'idx_agent_memory_provenance_tenant', 'agent_memory_records'): '38ea86fea71107fccefdd828775544796000b4f5553f3fa327049c5054aebd23',
 ('index', 'idx_agent_memory_provenance_worktree_id', 'agent_memory_records'): 'ede3797ba9a084d4e4a1539166ce72e442830fd0f4a7148ee288bd29e476fa34',
 ('index', 'idx_agent_memory_scope_identity', 'agent_memory_records'): 'e09ea6e01564f92238fa9aac558fff356d8663bb92a1b00a3cc8484d1316e23c',
 ('index', 'idx_agent_memory_scope_key', 'agent_memory_records'): '87c860ab42d5e672c4c6fc123fcca090dc52e6a0382a15855d4dde2b73e49448',
 ('index', 'idx_agent_memory_updated', 'agent_memory_records'): '776e3e88b071833f15e7db3c0b57ca63c9485b092090df307ff29b774c49515a',
 ('index', 'idx_agent_outcomes_change', 'agent_outcomes'): 'dc6d7b5ac5f463fb8abeed07c55fb5c88a2c51430eeb67b16858ee634dfb269b',
 ('index', 'idx_agent_outcomes_task', 'agent_outcomes'): '225296df966ea88b0d47e85fb1a4b90f93b29d666d35da0ae2dfb55bcee3323b',
 ('index', 'idx_agent_questions_session', 'agent_questions'): '0b3b5075a62dc480a596b8ccd14d227b988c0e73236cbd1b70062a1ea46e9ae9',
 ('index', 'idx_agent_snapshots_stream', 'agent_snapshots'): '974fd8531f2206bcfa74ed26c733469ef576b19515b91ce78fe941d83fbcc1e8',
 ('index', 'idx_agent_task_search_grams_gram', 'agent_task_search_grams'): '47289e8fa6b5eb7e6837a56d77ad684e26fbc466f43f0f7af252e77fb8af5e0a',
 ('index', 'idx_agent_tasks_status', 'agent_tasks_projection'): '0ac7b279372bdaed3b7c47acd6c70e4cd7b1e0df1e1890edfc66eac4bdc03330',
 ('index', 'idx_agent_tasks_status_updated', 'agent_tasks_projection'): '1d0fdd9dab8677f811492c31f26bab3af568f441de5e64b4b94b6c710598a211',
 ('index', 'idx_agent_tasks_updated', 'agent_tasks_projection'): '1c25fa23c988e8b730986555513e083454c134172930baf51dad9eb18f11ff67',
 ('index', 'idx_agent_verif_task', 'agent_verification_receipts'): '2b5073bea40ea5e312fc9aa761494ec53718927f90eae8dbe2987ec4765f2760',
 ('index', 'idx_agent_verif_task_observed', 'agent_verification_receipts'): '462c305e52d335c8368e5c0c4540c4936c83a8c3932746402403c5d8e91e8dc1',
 ('index', 'idx_agent_verif_task_outbox_pending', 'agent_verification_task_outbox'): '50dff1b755ee28d10c80d199270f9f6b12fb2ca958b4a8948cb59ac6ff751f48',
 ('index', 'idx_blackboard_board', 'agent_blackboard'): '8766cf9835a46d47cdca628a456ab1b0a807c11d588fa671b64ba19fb699b5e4',
 ('index', 'idx_entity_rel_source', 'agent_entity_relations'): '816b220dbed8e3d6d99610d66e1254d90e381c25fef2902dddba2714220053d5',
 ('index', 'idx_entity_rel_target', 'agent_entity_relations'): 'aa0be23cd9565e612f9252c63fb003fbabcd9fc5fe04df590eb1db2754a91f00',
 ('index', 'idx_entity_rel_type', 'agent_entity_relations'): '77fbc5362e7da269cdc53ee755d690d0f762d8ff3e5ab9c6e87a6e358bdd8330',
 ('index', 'idx_lease_waits_blocked', 'lease_waits'): '366fe3b81e54f9032edecf9d798a2b2d23160bba578438a89591b929c1e87cab',
 ('index', 'idx_lease_waits_tenant', 'lease_waits'): 'dd609992da24cef67dfdcaecef49c82b6451892d43863c9a1ff152701068273a',
 ('index', 'idx_leases_root', 'leases'): 'a0ede5303197cc5172c5583f33a72ee1636083712d84e9d618a642a34671cc85',
 ('table', 'agent_blackboard', 'agent_blackboard'): 'fb18c17d6581de546f148b5b302188dda9013374d653dc7cb9511021ebc6c1e3',
 ('table', 'agent_budgets', 'agent_budgets'): 'fbcda82d934dce0695d9cb9edd9d7c1386e5320a2aac79c5194eee55471982df',
 ('table', 'agent_change_intents', 'agent_change_intents'): '52ed988b0a31f820b145261f7c586ea869369958b8adcd21d6bd1ad7e1f8a9ca',
 ('table', 'agent_entity_relations', 'agent_entity_relations'): '7cb3cdb25d201d7e2e264eb0d2b3dda5bb831ffd531d7aea2dab79df6db26590',
 ('table', 'agent_event_cursors', 'agent_event_cursors'): '0ecf2e08637aef9d2f4a9167feb61de083e1a9d9b8b927f79ae7a58e74b2ef71',
 ('table', 'agent_events', 'agent_events'): '1dfef49210889dc707aa8405b65262a5a86acbc14bd940ca338293dde150b2a2',
 ('table', 'agent_incidents', 'agent_incidents'): 'a2be58a71724133b64d9a7a773680a193488f64414ee245e378b06973454e420',
 ('table', 'agent_knowledge_links', 'agent_knowledge_links'): '729e5c852a59ef150c488ccfb998a8a4dab606a052d353d94360aa2793a62426',
 ('table', 'agent_learning_candidates', 'agent_learning_candidates'): '3b8650b155c972e370825d72cf2222c005401a696b7f996a991c1f9d552b5caa',
 ('table', 'agent_memory_embeddings', 'agent_memory_embeddings'): '468df99dabe588d9475009d02108f2fdadfcf63e83a7aedf6d7a36a9ead965b5',
 ('table', 'agent_memory_fts', 'agent_memory_fts'): 'a3f3691e421244a8516c26f942a893b8b7a112b7771e9ba84ecded8eab4e3755',
 ('table', 'agent_memory_fts_config', 'agent_memory_fts_config'): 'e78061e43ffaa4b703c9aa4a44e02c6bae4128c3b1aad6a4324e6d3b97772c02',
 ('table', 'agent_memory_fts_content', 'agent_memory_fts_content'): '3ad7416c82b07bb41be9b2d30e58886c16cef8d5ab7a31f2834dc2d087fd6368',
 ('table', 'agent_memory_fts_data', 'agent_memory_fts_data'): '069959f382044c08715841b26cef2b51fd926354471f1fe5a680d976760ba2b0',
 ('table', 'agent_memory_fts_docsize', 'agent_memory_fts_docsize'): '39dc58937b569ac9aac16ef8e847d4a647b5e35feff50261c75b8eb8447f3567',
 ('table', 'agent_memory_fts_idx', 'agent_memory_fts_idx'): '68d1a21899a38af4e033e9dcd254abe1aff6dfed08bfbaac4916d8873a290cfd',
 ('table', 'agent_memory_records', 'agent_memory_records'): '5cd8a7e88151416c741554d667ef08dfd8469b645870f26ccadc436cfddc25c0',
 ('table', 'agent_outcomes', 'agent_outcomes'): '624b2b6c004fe2d59814db6d948d1bd043a73dfc10a9d83127e7450a05d90144',
 ('table', 'agent_questions', 'agent_questions'): 'c072993f2caba4dd9b1c7b868a243f02ccbd9d6e71a7c38853f7d27b8b5b0a61',
 ('table', 'agent_snapshots', 'agent_snapshots'): '323b038ec2305f3aa746737408a3a024da0f222285101d5e0bea9729cf5fdb69',
 ('table', 'agent_state_migrations', 'agent_state_migrations'): 'c05fc94a41754f655038115d920ca125256bad65f5fd82bcc8ee4cdc8ce1c164',
 ('table', 'agent_state_schema_versions', 'agent_state_schema_versions'): 'a2884a575e1e67cfbc5b40c2e90370a89d5310197171332b6806c0b4e036a547',
 ('table', 'agent_swarms', 'agent_swarms'): '5ccda29c6b858caae83c2ca78296c4ff939f7ae41cdab14054e67bf374592a81',
 ('table', 'agent_task_search_documents', 'agent_task_search_documents'): 'a291a7122e95c8b2f3f6b9a9a73269489b1794ceea3f4378d9ff6155fd900f93',
 ('table', 'agent_task_search_grams', 'agent_task_search_grams'): 'd2f7c3b733bc0ffcee4d9ee72804edc3fedc36f73f7ceca5ce18662941a13b78',
 ('table', 'agent_tasks_projection', 'agent_tasks_projection'): 'd4283f29e8560ff94ae0877f38c1fdd8020a2d8e2fc6c66aa01a58dca6339cc4',
 ('table', 'agent_verification_receipts', 'agent_verification_receipts'): '6aeb2ffafd9572d5325f56e99f7c62455989c3d44772bd83d3e47b6f3abe953a',
 ('table', 'agent_verification_task_outbox', 'agent_verification_task_outbox'): '2f17423836ca86bf09a701a71a27ead55a2c458d02bb9f29e1445a0c0fc11d17',
 ('table', 'lease_waits', 'lease_waits'): {'314dbe78e360c6c00133c85323b9349936d9cb2e87121e60c8ffb733b46d20aa',
                                           'e9a38812fd120d00228269c2e5f28f02172702355abd9127562ccf78a5c93612'},
 ('table', 'leases', 'leases'): 'f7a165f4f68106fb33b5855d0a66532e63fde78b2675380b67fe8112096f8edd',
 ('table', 'sqlite_sequence', 'sqlite_sequence'): '9e042902d97481bf7dccaaff2183d686b3344691bb622fdfc017096ef4080c65'}
