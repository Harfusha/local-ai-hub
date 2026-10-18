"""Exact source fingerprints for the bounded preceding Agent State stores.

Data-only input contract for the offline converter. Values were captured from
private, sidecar-aware snapshots; runtime code must never load this module.
"""

HISTORICAL_SOURCE_OBJECT_HASHES = {
    # Historical artifacts store and its tenant schema marker.
    ("artifacts", "index", "idx_artifacts_created"): "213ec2e9d529ff33ec804e303ff6b57a6f664979e19b85526b4636468445af2f",
    ("artifacts", "table", "artifact_paging_metadata"): "9d93082f0e2682cb623e7be509e9f6c4917a30a02fe4a84dd1b1b5d54c28c6c9",
    ("artifacts", "table", "artifact_schema_meta"): "6f4a71b7b75f41d5a40e0e11ce806b1c3154a224da2539fff0778ed5c45f4cab",
    ("artifacts", "table", "artifacts"): "125fab09f71dd1d8696b67b0e0e244bae92d4d4c45cc5f0b3b24fb647fc996e3",
    # Historical async-job store.
    ("async_jobs", "index", "idx_async_jobs_active_dedupe"): "2613e1aa9d3555a166846a7d65ea42b383d60ae170d5e43eb636094814ff83b9",
    ("async_jobs", "index", "idx_async_jobs_dispatch"): "360e4bab4f273c43d953043e3faa064abcc37dae33e8c5649dff3fc52f876ede",
    ("async_jobs", "index", "idx_async_jobs_request_id"): "6c1381c76b0966856954acb8367ecba118a0a86e2698ba076ede0e0c16c9ec2a",
    ("async_jobs", "index", "idx_async_jobs_state"): "c28fc04bb0e9b771b30b8da844bf6516b2643438dba7e725a7560fc40e3cd6ad",
    ("async_jobs", "table", "async_job_progress"): "434f373700d608a23d2fc7203ef19b9a74aac806b7672aace2883557e4381c10",
    ("async_jobs", "table", "async_jobs"): "529006f43e5e2019bc9a06167430febcbaad8405a93c7e525e3ac5de6fa8534f",
    # Historical work-order store.
    ("work_orchestrator", "index", "idx_work_orders_state_created"): "09a1233ca293cabbbf00f6ed83a5fba8bcd4c75f5e262600adc70fad88a206de",
    ("work_orchestrator", "index", "idx_work_orders_tenant_updated"): "d7b5bbdd3d686c8d8e109607b5f31ab5a45424c7c178627e7ce24db4da0c67e5",
    ("work_orchestrator", "table", "work_orders"): "5886af4b29270e8bd95feca1e9b3f1dd5a4f150b113b9f3cee5ae5dffaca0084",
    # Historical telemetry store. The event table has a registered appended-column order.
    ("telemetry", "index", "idx_errors_fp_created"): "b2b710954df0a305c966ba5d4f9d463cc078c9af2d4f1f4a8b2c0a900adf1d1b",
    ("telemetry", "index", "idx_events_action_created"): "7729e259c0e1987ae41b091108d4950da58acceb31789b90646d79e2052a1486",
    ("telemetry", "index", "idx_events_created"): "855395fa409042c3df8660c4859593ca9c573a70828ac1d10e1d1ef1eda5916d",
    ("telemetry", "index", "idx_events_error"): "3596568847704eb9d04fbf310407b5cfb21710e66a81ef7f37bd98a3681fe282",
    ("telemetry", "index", "idx_events_model"): "180706f957ab0ab871d9957a2387ac7097200d2cb5574180625a20f2d5e5ecc2",
    ("telemetry", "index", "idx_events_savings_created"): "2019d16e38151a31f9eb93478c64caeeac1635c8985a8b9390d6e97086ec6364",
    ("telemetry", "index", "idx_events_type_created"): "90bc2bef354083ad0499ccdb3a175c1cc02a524f56540a4c408eafb8a84f4153",
    ("telemetry", "index", "idx_process_sessions_started"): "e5135e76132db9478c328122ebdc783a08390771a59056bf93e5bbfbca954479",
    ("telemetry", "index", "idx_snapshots_name_created"): "8206e1edb63ed1adbb13d56d146df3ddc5f6b790057e9b336573ed20abb693a6",
    ("telemetry", "table", "daily_rollups"): "204f71396ada8ba043af8375b86f46fe00a1c4b891cef4324159ab0f014e5552",
    ("telemetry", "table", "errors"): "20d0be77e06e812a376b7b241b4259f92d7dc37ef6e938ef52a7eeef27c94ff3",
    ("telemetry", "table", "events"): "2c0d5357db33cb778e31428bb59fc96336052f85d99d076cd4fc4b42c1159ca1",
    ("telemetry", "table", "process_sessions"): "ee2fd78afc992cc0e91839c7485942461d8ed2b90c588eeed9e79b68749fd475",
    ("telemetry", "table", "snapshots"): "83ca05cab9a6425289e4c7afe951c8ef3b835aaebd16b7884075f29d9dae2dd1",
}

HISTORICAL_RETIRED_COLUMNS = {
    "artifacts": {
        "artifacts": ("tenant", "tenant_identity"),
        "artifact_paging_metadata": (),
    },
    "async_jobs": {
        "async_jobs": ("tenant",),
        "async_job_progress": ("tenant",),
    },
    "work_orchestrator": {"work_orders": ("tenant",)},
    "telemetry": {"events": ("tenant",), "errors": ("tenant",)},
}

HISTORICAL_INDEX_ACTIONS = {
    "agent_state": {
        "idx_agent_incidents_scope": ("map", "idx_agent_incidents_scope", "tenant_key"),
        "idx_agent_questions_session": ("map", "idx_agent_questions_session", "tenant"),
        "idx_agent_memory_provenance_tenant": ("drop", "", ""),
        "idx_lease_waits_tenant": ("map", "idx_lease_waits_owner", "tenant", "owner"),
    },
    "async_jobs": {
        "idx_async_jobs_active_dedupe": ("map", "idx_async_jobs_active_dedupe", "tenant"),
        "idx_async_jobs_request_id": ("map", "idx_async_jobs_request_id", "tenant"),
    },
    "work_orchestrator": {
        "idx_work_orders_tenant_updated": ("map", "idx_work_orders_updated", "tenant"),
    },
}

HISTORICAL_ARTIFACT_PAGING = {
    "legacy_columns": ("artifact_id", "char_count", "section_names", "page_text", "nul_mask"),
    "target_columns": ("artifact_id", "char_count", "section_json", "section_checksum", "page_text", "nul_mask"),
    "maximum_names": 50,
    "maximum_name_chars": 512,
}
