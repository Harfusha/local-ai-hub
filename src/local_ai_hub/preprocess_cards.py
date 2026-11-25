from __future__ import annotations

from typing import Any


class PreprocessCardsMixin:
    def _run_background_generate(
        self, model: str, prompt: str, system: str, schema: Any, max_tokens: int, source: str,
        *, allow_model_fallback: bool = True,
    ) -> dict[str, Any]:
        from . import preprocess as services_module
        from .operational_mode import load_operational_mode, operational_mode_gate_error, preprocessing_mode_ready
        from .scheduler import QueueFullError

        state_dir = getattr(self, "state_dir", None) or self.config.get("server", {}).get("state_dir")
        mode = None
        if state_dir is not None:
            try:
                mode = load_operational_mode(state_dir)
            except Exception:
                mode = None
        prep_cfg = self.config.get("preprocessing", {})
        active_cpu_fallback = (
            mode is not None
            and not mode.degraded
            and mode.mode == "active"
            and isinstance(prep_cfg, dict)
            and bool(prep_cfg.get("cpu_runs_during_foreground", False))
            and bool(getattr(self.background_gpu, "cpu_fallback_enabled", False))
        )
        if (
            state_dir is not None
            and (
                mode is None
                or mode.degraded
                or (mode.mode != "active" and not preprocessing_mode_ready(state_dir, mode))
            )
            and not active_cpu_fallback
        ):
            return operational_mode_gate_error(mode, "preprocess")
        if active_cpu_fallback:
            yielded = self._stop.is_set() or self._paused.is_set() or not self._background_work_allowed()
        else:
            yielded = self._gpu_yield()
        if yielded:
            return {"success": False, "preempted": True, "error": "foreground work pending"}

        # Local AI production path: a dedicated Ollama server owns the small background
        # model only after the foreground GPU has been idle long enough. Embeddings
        # and reranking never enter this path.
        if self.background_gpu is not None:
            worker_enabled = bool(getattr(self.background_gpu, "enabled", True))
            worker_ready = bool(getattr(self.background_gpu, "ready", lambda: worker_enabled)())
        else:
            worker_enabled = worker_ready = False
        worker_model = getattr(self.background_gpu, "model", model) if self.background_gpu is not None else model
        if (self.background_gpu is not None and model == worker_model
                and (worker_enabled or worker_ready or active_cpu_fallback)):
            try:
                result = self.background_gpu.generate(
                    prompt=prompt, system=system, schema=schema, max_tokens=int(max_tokens), source=source,
                    preprocessing=True, temperature=0.2,
                )
            except Exception as exc:
                self._record_model_failure_trace(model, prompt, system, schema, max_tokens, source, exc)
                raise
            if not isinstance(result, dict) or result.get("success") is not True:
                self._record_model_failure_trace(model, prompt, system, schema, max_tokens, source, result)
            return result

        generate = getattr(getattr(self, "services", None), "_generate", None)
        if callable(generate):
            try:
                result = generate(
                    model, prompt, system, int(max_tokens), 0.2,
                    source=source, priority=0, internal=True, use_cache=False, format=schema,
                    request_timeout_seconds=float(self.cfg.get("background_request_timeout_seconds", 300)),
                    **({} if allow_model_fallback else {"allow_model_fallback": False}),
                )
            except Exception as exc:
                self._record_model_failure_trace(model, prompt, system, schema, max_tokens, source, exc)
                raise
            if result.get("error_code") == "model_circuit_open":
                self._record_model_failure_trace(model, prompt, system, schema, max_tokens, source, result)
                retry_after = result.get("retry_after_seconds", 60.0)
                raise services_module._RetryablePreprocessingError(
                    f"preprocessing model circuit is open: {model}",
                    retry_after_seconds=float(retry_after),
                    error_code="model_circuit_open",
                )
            if not result.get("success"):
                self._record_model_failure_trace(model, prompt, system, schema, max_tokens, source, result)
                return result
            generated_text = str(result.get("text", "")).strip()
            try:
                data = services_module._parse_generated_json(generated_text)
            except (TypeError, ValueError):
                self._record_model_failure_trace(
                    model, prompt, system, schema, max_tokens, source,
                    {"error": "preprocessing model returned invalid JSON", "error_code": "invalid_preprocess_json", "response": result},
                )
                return {
                    "success": False, "model": result.get("model", model),
                    "error": "preprocessing model returned invalid JSON",
                    "error_code": "invalid_preprocess_json",
                }
            if not isinstance(data, dict):
                self._record_model_failure_trace(
                    model, prompt, system, schema, max_tokens, source,
                    {"error": "preprocessing model returned a non-object card", "error_code": "invalid_preprocess_json", "response": result},
                )
                return {
                    "success": False, "model": result.get("model", model),
                    "error": "preprocessing model returned a non-object card",
                    "error_code": "invalid_preprocess_json",
                }
            return {
                "success": True, "model": result.get("model", model), "data": data,
                "prompt_budget": result.get("prompt_budget"),
                "fallback_used": bool(result.get("fallback_used", False)),
            }

        # Defensive fallback for tests/minimal embeddings that construct the
        # preprocessor without the Local AI idle GPU worker.
        def execute() -> dict[str, services_module.Any]:
            from .budget import estimate_tokens, fit_text

            fixed_input_tokens = estimate_tokens(system) + estimate_tokens(services_module.json_dumps(schema, ensure_ascii=False))
            profile_hint = self.services.model_policy.profile(
                model, role="background", input_tokens=estimate_tokens(prompt) + fixed_input_tokens,
                output_tokens=int(max_tokens), background=True,
            )
            prompt_budget = profile_hint.prompt_budget_tokens - fixed_input_tokens
            if prompt_budget < 64:
                return {"success": False, "error": "context cannot fit the system prompt, output schema and request prompt"}
            prepared = fit_text(prompt, prompt_budget)
            payload, profile = self.services.model_policy.apply_payload(
                model,
                {
                    "model": model, "prompt": prepared.text, "system": system, "format": schema,
                    "keep_alive": self.config.get("ollama", {}).get("keep_alive", "-1"),
                    "options": {"num_predict": int(max_tokens), "temperature": 0.2},
                },
                role="background", input_tokens=prepared.estimated_tokens + fixed_input_tokens,
                output_tokens=int(max_tokens), background=True, preserve_explicit_think=False,
            )
            if prepared.estimated_tokens + fixed_input_tokens > getattr(profile, 'prompt_budget_tokens', getattr(profile_hint, 'prompt_budget_tokens', 8192)):
                return {"success": False, "error": "selected context cannot fit the prepared prompt and system input"}
            # A queued scheduler closure must recheck mode at the runtime handoff.
            if state_dir is not None:
                try:
                    mode = load_operational_mode(state_dir)
                except Exception:
                    mode = None
                rejection = operational_mode_gate_error(mode, "preprocess")
                if rejection is not None:
                    return {
                        **rejection,
                        "preempted": True,
                        "error_code": "operational_mode_paused",
                    }
            response = self.runtime.request_interruptible(
                "/api/generate", payload, self.scheduler.foreground_busy,
                timeout=float(self.cfg.get("background_request_timeout_seconds", 300)),
            )
            if any(response.get(key) for key in ("preempted", "outcome_unknown", "cleanup_unconfirmed", "in_progress", "cancelled")):
                return {**response, "success": False}
            if response.get("done_reason") == "length":
                return {
                    "success": False, "model": model,
                    "error": "local model output reached its token limit",
                    "error_code": "model_output_truncated", "output_truncated": True,
                    "stop_reason": "length", "terminal": True, "retryable": False,
                    **({"_lah_backend_completed": True} if response.get("done") is True else {}),
                }
            if "error" in response:
                return {"success": False, "error": response["error"]}
            text = str(response.get("response", "")).strip()
            try:
                data = services_module._parse_generated_json(text)
            except (TypeError, ValueError):
                failure = {"error": "preprocessing model returned invalid JSON", "error_code": "invalid_preprocess_json", "response": response}
                self._record_model_failure_trace(model, prompt, system, schema, max_tokens, source, failure)
                return {"success": False, "model": model, **failure,
                        **({"_lah_backend_completed": True} if response.get("done") is True else {})}
            if not isinstance(data, dict):
                failure = {"error": "preprocessing model returned a non-object card", "error_code": "invalid_preprocess_json", "response": response}
                self._record_model_failure_trace(model, prompt, system, schema, max_tokens, source, failure)
                return {"success": False, "model": model, **failure,
                        **({"_lah_backend_completed": True} if response.get("done") is True else {})}
            return {"success": True, "model": model, "data": data,
                    "prompt_budget": {"estimated_tokens": prepared.estimated_tokens,
                                      "original_estimated_tokens": prepared.original_tokens,
                                      "truncated": prepared.truncated},
                    "load_duration_ns": response.get("load_duration", 0)}

        try:
            result = self.scheduler.submit(
                model, source=source, execute=execute, priority=0,
                wait_timeout=float(self.cfg.get("background_scheduler_timeout_seconds", 120)), background=True,
            )
            if isinstance(result, dict) and not result.get("success") and not result.get("preempted"):
                self._record_model_failure_trace(model, prompt, system, schema, max_tokens, source, result)
            return result
        except QueueFullError as exc:
            self._record_model_failure_trace(model, prompt, system, schema, max_tokens, source, exc)
            if not exc.retryable:
                raise
            raise services_module._RetryablePreprocessingError(
                f"background scheduler deferred preprocessing: {exc}",
                retry_after_seconds=30.0,
            ) from exc
        except TimeoutError as exc:
            self._record_model_failure_trace(model, prompt, system, schema, max_tokens, source, exc)
            return {"success": False, "preempted": True, "retry_after_seconds": 60.0,
                    "error": "background scheduler wait timed out"}
        except Exception as exc:
            self._record_model_failure_trace(model, prompt, system, schema, max_tokens, source, exc)
            raise

    def _step_file_card(self, row: dict[str, Any]) -> bool:
        from . import preprocess as services_module
        root = str(row["root"])
        enrich_cards = self._file_card_enrichment_enabled()
        bg_cfg = self.config.get("background_gpu", {})
        batch_size = max(1, int(bg_cfg.get("file_batch_size", 64)))
        items = self._find_next_files(root, batch_size)
        if not items:
            def store_oversized(con: services_module.sqlite3.Connection) -> None:
                oversized = con.execute(
                    "SELECT * FROM file_refs WHERE root=? AND card_key IS NULL AND size>?",
                    (root, int(self.cfg.get("file_card_max_bytes", 180000))),
                ).fetchall()
                for item in oversized:
                    content_hash = str(item["content_hash"])
                    card_key = services_module.stable_hash({"app_version": services_module.PREPROCESS_ANALYZER_VERSION, "sha": content_hash, "source": "deterministic-oversized"})
                    data = {"purpose": "oversized source file", "symbols": [], "dependencies": [], "side_effects": [], "risks": [], "tests": [], "keywords": []}
                    con.execute(
                        "INSERT OR REPLACE INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,0)",
                        (card_key, content_hash, "deterministic-oversized", services_module.PREPROCESS_ANALYZER_VERSION, services_module.json_dumps(data), services_module.time.time(), services_module.time.time()),
                    )
                    con.execute("UPDATE file_refs SET card_key=?,updated_at=? WHERE root=? AND path=?", (card_key, services_module.time.time(), root, item["path"]))
            self._write_retry(store_oversized)
            if str(row.get("phase")) == "file_card_enrichment":
                return self._refresh_deferred_card_summaries(row)
            elif str(row.get("phase")) == "files":
                self._set_project(root, phase="serena_optional", force_refresh=0)
            return True

        background_model = self._configured_preprocessing_model()
        candidates = self._file_card_fallbacks(background_model) if background_model else ()
        accepted_models = {background_model, *candidates} if background_model else set()
        pending_tasks: list[dict[str, services_module.Any]] = []
        pending_meta: list[tuple[services_module.sqlite3.Row, str, str, dict[str, services_module.Any] | None]] = []
        progressed = False
        deferred_enrichment = False
        cached_cards: dict[str, str] = {}
        if not bool(row.get("force_refresh")):
            content_hashes = list(dict.fromkeys(
                str(item["content_hash"] or "") for item in items if item["content_hash"]
            ))
            cache_column = "card_key" if enrich_cards else "content_hash"
            cache_keys = [self._content_card_key(digest) for digest in content_hashes] if enrich_cards else content_hashes
            now = services_module.time.time()
            pipeline_version = self._file_card_pipeline_version() if enrich_cards else ""

            def update_cache(con: services_module.sqlite3.Connection) -> tuple[dict[str, str], int, bool]:
                found: dict[str, str] = {}
                linked_keys: list[str] = []
                stale_refs = False
                for batch in services_module.sqlite_batches(cache_keys):
                    placeholders = ",".join("?" for _ in batch)
                    cached_rows = con.execute(
                        f"""SELECT content_hash,card_key,card_json,model FROM content_cards
                            WHERE analyzer_version=? AND {cache_column} IN ({placeholders})
                            ORDER BY content_hash,hits DESC""",
                        (services_module.PREPROCESS_ANALYZER_VERSION, *batch),
                    ).fetchall()
                    for cached_row in cached_rows:
                        if not self._reusable_file_card(cached_row, accepted_models, allow_deterministic=not enrich_cards):
                            continue
                        if enrich_cards:
                            con.execute(
                                """INSERT INTO file_card_enrichment(
                                       content_hash,model,pipeline_version,status,attempts,retry_after,lease_until,last_error,updated_at
                                   ) VALUES(?,?,?,'complete',0,0,0,NULL,?)
                                   ON CONFLICT(content_hash,model,pipeline_version) DO UPDATE SET
                                       status='complete',lease_until=0,last_error=NULL,updated_at=excluded.updated_at""",
                                (str(cached_row["content_hash"]), background_model,
                                 pipeline_version, now),
                            )
                        found.setdefault(str(cached_row["content_hash"]), str(cached_row["card_key"]))
                for item in items:
                    content_hash = str(item["content_hash"] or "")
                    cached_key = found.get(content_hash)
                    if cached_key:
                        linked = con.execute(
                            "UPDATE file_refs SET card_key=?,updated_at=? WHERE root=? AND path=? AND content_hash=?",
                            (cached_key, now, root, item["path"], content_hash),
                        )
                        if linked.rowcount:
                            linked_keys.append(cached_key)
                        else:
                            stale_refs = True
                if linked_keys:
                    con.executemany(
                        "UPDATE content_cards SET hits=hits+1,accessed_at=? WHERE card_key=?",
                        [(now, card_key) for card_key in linked_keys],
                    )
                return found, len(linked_keys), stale_refs

            cached_cards, cache_hits, deferred_enrichment = self._write_retry(update_cache)
            if cache_hits:
                with self._stats_lock:
                    self._stats["file_card_hits"] += cache_hits
                progressed = True

        for item in items:
            content_hash = str(item["content_hash"])
            provisional_data: dict[str, services_module.Any] | None = None

            # 1. Instant global content-addressed cache hit across all branches & worktrees
            if cached_cards.get(content_hash):
                continue

            if enrich_cards and item["card_key"] is not None:
                with self._db_lock, services_module.closing(self._connect()) as con:
                    prior = con.execute(
                        "SELECT model,card_json FROM content_cards WHERE card_key=?",
                        (str(item["card_key"]),),
                    ).fetchone()
                if prior and str(prior["model"]) in {
                    "deterministic", "deterministic-stub", "deterministic-barrel",
                }:
                    try:
                        parsed_prior = services_module.json.loads(str(prior["card_json"]))
                        provisional_data = parsed_prior if isinstance(parsed_prior, dict) else None
                    except (TypeError, ValueError):
                        provisional_data = None

            # 2. Deterministic AST/facts fallback
            if self.deterministic is not None and bool(self.cfg.get("prefer_deterministic_cards", True)):
                try:
                    det = self.deterministic.file_card(root, str(item["path"]))
                except Exception:
                    det = {"success": False}
                if det.get("success"):
                    card_key = services_module.stable_hash({"app_version": services_module.PREPROCESS_ANALYZER_VERSION, "sha": content_hash, "source": "deterministic"})
                    det_card = det.get("card", {})
                    if not self._store_file_card(root, item, card_key, det_card, "deterministic", content_hash):
                        deferred_enrichment = True
                        continue
                    with self._stats_lock:
                        self._stats["deterministic_card_hits"] = self._stats.get("deterministic_card_hits", 0) + 1
                    progressed = True
                    provisional_data = det_card if isinstance(det_card, dict) else None
                    if not enrich_cards:
                        continue

            card_key = self._content_card_key(content_hash)

            slice_result = self.repo_tools.file_slice(
                root, str(item["path"]), 1, int(self.cfg.get("file_card_max_lines", 900)),
                int(self.cfg.get("file_card_max_chars", 18000)),
            )
            if not slice_result.get("success"):
                if enrich_cards and item["card_key"] is not None:
                    deferred_enrichment = True
                    continue
                data = {"purpose": "unreadable/skipped", "symbols": [], "dependencies": [], "side_effects": [], "risks": [], "tests": [], "keywords": []}
                self._store_file_card(root, item, card_key, data, "deterministic-unreadable", content_hash)
                progressed = True
                continue

            file_text = slice_result.get("text", "")
            source_hash = str(slice_result.get("file_sha256") or content_hash)
            if source_hash != content_hash:
                deferred_enrichment = True
                continue
            rel_name = services_module.Path(str(item["path"])).name
            is_trivial_file = services_module.is_trivial_barrel_module(rel_name, int(item["size"] or 0), file_text) or (
                rel_name == "__init__.py" and len(file_text.strip()) < 300
            )
            if is_trivial_file:
                data = services_module.derive_barrel_card_data(rel_name, file_text, str(item["path"]))
                barrel_key = services_module.stable_hash({"app_version": services_module.PREPROCESS_ANALYZER_VERSION, "sha": content_hash, "source": "deterministic-barrel"})
                self._store_file_card(root, item, barrel_key, data, "deterministic-barrel", content_hash)
                progressed = True
                continue

            if provisional_data is None:
                # Always persist deterministic metadata first before any model attempt (LAH-006).
                data = {
                    "purpose": f"source file ({services_module.Path(str(item['path'])).suffix})",
                    "symbols": [],
                    "dependencies": [],
                    "side_effects": [],
                    "risks": [],
                    "tests": [],
                    "keywords": [services_module.Path(str(item["path"])).stem],
                    "epistemic_class": "deterministic_fact",
                    "confidence": 1.0,
                }
                stub_key = services_module.stable_hash({"app_version": services_module.PREPROCESS_ANALYZER_VERSION, "sha": content_hash, "source": "deterministic-stub"})
                self._store_file_card(root, item, stub_key, data, "deterministic-stub", content_hash)
                progressed = True
                provisional_data = data
                if not enrich_cards:
                    continue

            if not enrich_cards:
                continue

            draft_model = self._configured_preprocessing_draft_model()
            if draft_model and self._file_card_enrichment_enabled():
                try:
                    draft_res = self._run_background_generate(
                        draft_model,
                        f"FILE: {item['path']}\n\nCURRENT SOURCE (extract facts):\n{file_text[:4000]}",
                        "Extract basic facts for file card: {\"purpose\":\"\",\"symbols\":[],\"dependencies\":[]}.",
                        services_module.CARD_SCHEMA,
                        384,
                        "preprocess:draft-card",
                        allow_model_fallback=False,
                    )
                    if isinstance(draft_res, dict) and draft_res.get("success"):
                        data_draft = draft_res.get("data") or draft_res.get("card")
                        if isinstance(data_draft, dict) and (data_draft.get("symbols") or data_draft.get("purpose")):
                            # Validate symbols/deps against source (never promote hallucinations)
                            source_lower = file_text.casefold()
                            valid_symbols = [
                                str(s) for s in (data_draft.get("symbols") or [])
                                if isinstance(s, str) and s.strip() and s.strip().casefold() in source_lower
                            ]
                            valid_deps = [
                                str(d) for d in (data_draft.get("dependencies") or [])
                                if isinstance(d, str) and d.strip() and d.strip().casefold() in source_lower
                            ]
                            draft_card = {
                                "purpose": str(data_draft.get("purpose") or provisional_data.get("purpose", "")),
                                "symbols": valid_symbols,
                                "dependencies": valid_deps,
                                "side_effects": list(data_draft.get("side_effects") or []),
                                "risks": list(data_draft.get("risks") or []),
                                "tests": list(data_draft.get("tests") or []),
                                "keywords": list(data_draft.get("keywords") or provisional_data.get("keywords", [])),
                                "epistemic_class": "llm_draft",
                                "model": draft_model,
                                "confidence": 0.5,
                                "read_span": [0, min(len(file_text), 4000)],
                            }
                            draft_key = services_module.stable_hash({"app_version": services_module.PREPROCESS_ANALYZER_VERSION, "sha": content_hash, "source": f"draft-{draft_model}"})
                            self._store_file_card(root, item, draft_key, draft_card, draft_model, content_hash)
                            progressed = True
                            provisional_data = draft_card
                except Exception as exc:
                    services_module.logger.debug("Draft generation failed for %s: %s", item.get("path"), exc)

            item_model = background_model

            # Diff-based update: if old card exists and fewer than 15% lines changed, use diff prompt
            old_card_text: str | None = None
            is_minor_diff = False
            diff_section = ""
            with self._db_lock, services_module.closing(self._connect()) as con:
                old_src_row = con.execute(
                    "SELECT content_hash, text FROM source_index WHERE root=? AND path=? AND content_hash<>? ORDER BY updated_at DESC LIMIT 1",
                    (root, str(item["path"]), content_hash),
                ).fetchone()
                if old_src_row:
                    old_hash = str(old_src_row[0])
                    old_src_text = str(old_src_row[1])
                    prev = con.execute(
                        "SELECT card_key, card_json FROM content_cards WHERE content_hash=? AND analyzer_version=? LIMIT 1",
                        (old_hash, services_module.PREPROCESS_ANALYZER_VERSION),
                    ).fetchone()
                    if prev:
                        old_card_text = str(prev[1])
                        import difflib, re
                        old_lines = [re.sub(r"^\d+:\s*", "", l) for l in old_src_text.splitlines()]
                        new_lines = [re.sub(r"^\d+:\s*", "", l) for l in file_text.splitlines()]
                        if old_lines and new_lines:
                            matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
                            if matcher.ratio() >= 0.85:
                                is_minor_diff = True
                                diff_lines = [
                                    line for line in difflib.unified_diff(old_lines, new_lines, lineterm="")
                                    if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
                                ]
                                diff_section = "\n".join(diff_lines[:40])

            file_text = slice_result.get("text", "")
            neighborhood_section = ""
            try:
                from .preprocess_context import find_file_neighbors, format_neighborhood_prompt_section
                with self._db_lock, services_module.closing(self._connect()) as con:
                    neighbors = find_file_neighbors(con, root, str(item["path"]))
                    if neighbors:
                        neighborhood_section = format_neighborhood_prompt_section(neighbors) + "\n\n"
            except Exception as exc:
                services_module.logger.debug("Neighborhood resolution failed for %s: %s", item.get("path"), exc)

            if old_card_text and is_minor_diff:
                prompt_text = f"FILE: {item['path']}\n\n{neighborhood_section}PREVIOUS SUMMARY:\n{old_card_text[:800]}\n\nDIFF (<15% lines changed):\n{diff_section[:1200]}\n\nCURRENT SOURCE (authority):\n{file_text}"
            else:
                prompt_text = f"FILE: {item['path']}\n\n{neighborhood_section}DETERMINISTIC BASELINE (preserve valid parsed facts and complement with semantic details):\n{services_module.json_dumps(provisional_data, ensure_ascii=False)[:1800] if provisional_data else 'none'}\n\nCURRENT SOURCE (authority):\n{file_text}"

            pending_tasks.append({
                "prompt": prompt_text,
                "model": item_model,
                "system": "Complete the file card using CURRENT SOURCE as authority and DETERMINISTIC BASELINE as starting facts. Preserve all correct deterministic symbols, dependencies, and keywords; add semantic purpose, risks, side effects, tests, and any missing symbols or dependencies found in source. Return empty arrays only when source truly contains no fact for that field. Provide supporting evidence with an exact quote copied from CURRENT SOURCE for purpose and key claims. Return exactly one JSON object with schema: {\"purpose\":\"\",\"symbols\":[],\"dependencies\":[],\"side_effects\":[],\"risks\":[],\"tests\":[],\"keywords\":[],\"evidence\":[{\"field\":\"purpose\",\"value\":\"...\",\"quote\":\"...\"}]}. No markdown or prose.",
                "schema": services_module.CARD_SCHEMA,
                "max_tokens": int(self.cfg.get("file_card_output_tokens", 3072)),
                "temperature": 0.2,
                "source": "preprocess:file-card",
            })
            pending_meta.append((item, card_key, source_hash, provisional_data))

        if not pending_tasks:
            return progressed or not deferred_enrichment

        # Do not even start/lease the background GPU until the full foreground idle
        # grace is satisfied. This avoids pointless unload/reload churn between users.
        use_background_gpu = False
        if self.background_gpu is not None:
            worker_enabled = bool(getattr(self.background_gpu, "enabled", True))
            worker_ready = bool(getattr(self.background_gpu, "ready", lambda: worker_enabled)())
            use_background_gpu = worker_ready
            if not worker_ready and worker_enabled:
                return progressed
        claimed_tasks: list[dict[str, services_module.Any]] = []
        claimed_meta: list[tuple[services_module.sqlite3.Row, str, services_module._FileCardClaim, dict[str, services_module.Any] | None]] = []
        for task, meta in zip(pending_tasks, pending_meta):
            item, card_key, source_hash, provisional_data = meta
            claim = self._claim_file_card_enrichment(source_hash, background_model)
            if claim is not None:
                claimed_tasks.append(task)
                claimed_meta.append((item, card_key, claim, provisional_data))
        if not claimed_tasks:
            return progressed

        def defer_remaining(start: int, exc: services_module._RetryablePreprocessingError) -> None:
            for _item, _card_key, claim, _baseline in claimed_meta[start:]:
                self._finish_file_card_enrichment(
                    claim, success=False, preempted=True,
                    retry_after_seconds=exc.retry_after_seconds,
                )

        def invalid_scheduled_card(result: dict[str, services_module.Any], model: str) -> bool:
            backend_repeat_limit = any(
                "prediction aborted, token repeat limit reached" in str(result.get(key) or "").casefold()
                for key in ("error", "error_message", "message")
            )
            repetition_loop = (
                (
                    result.get("_lah_repetition_loop_detected") is True
                    and result.get("_lah_backend_completed") is True
                )
                or backend_repeat_limit
            )
            model_circuit_open = result.get("error_code") == "model_circuit_open"
            if (model not in accepted_models or result.get("stop_reason") == "length"
                    or (
                        self._file_card_deferral_delay(result) is not None
                        and not (model_circuit_open or repetition_loop)
                    )
                    or (result.get("terminal") and not repetition_loop)
                    or any(result.get(key) for key in (
                        "outcome_unknown", "cleanup_unconfirmed", "in_progress",
                        "cancelled", "output_truncated",
                    ))):
                return False
            if repetition_loop or model_circuit_open:
                return True
            if result.get("success") is True:
                return not self._valid_enriched_file_card(result.get("data"))
            return result.get("error_code") == "invalid_preprocess_json"

        resilience = self.config.get("resilience", {})
        max_fallbacks = (
            services_module._safe_int(resilience.get("max_model_fallbacks"), 2)
            if resilience.get("model_fallback_enabled", True) else 0
        )

        def fallback_scheduled_card(task: dict[str, services_module.Any], generated: dict[str, services_module.Any]) -> dict[str, services_module.Any]:
            args = task["prompt"], task["system"], task["schema"], int(task["max_tokens"]), str(task["source"])
            attempted = {background_model, str(generated.get("model") or "")}
            remaining = max_fallbacks
            for candidate in candidates:
                if candidate in attempted:
                    continue
                if not remaining or not invalid_scheduled_card(generated, str(generated.get("model") or "")):
                    break
                attempted.add(candidate)
                remaining -= 1
                try:
                    generated = self._run_background_generate(candidate, *args, allow_model_fallback=False)
                except services_module._RetryablePreprocessingError as exc:
                    if exc.error_code != "model_circuit_open":
                        raise
                    # An open breaker rejected this candidate before dispatch.
                    # Continue with the next distinct model instead of deferring
                    # the whole card while a healthy fallback remains available.
                    generated = {
                        "success": False,
                        "model": candidate,
                        "error": str(exc),
                        "error_code": exc.error_code,
                        "retryable": True,
                        "retry_after_seconds": exc.retry_after_seconds,
                    }
            return generated

        def scheduled_results():
            for index, task in enumerate(claimed_tasks):
                args = task["prompt"], task["system"], task["schema"], int(task["max_tokens"]), str(task["source"])
                try:
                    generated = self._run_background_generate(background_model, *args)
                    yield fallback_scheduled_card(task, generated)
                except services_module._RetryablePreprocessingError as exc:
                    defer_remaining(index, exc)
                    raise

        if use_background_gpu:
            results = self.background_gpu.generate_many(claimed_tasks, preprocessing=True)
            for index, (task, generated) in enumerate(zip(claimed_tasks, results)):
                try:
                    results[index] = fallback_scheduled_card(task, generated)
                except services_module._RetryablePreprocessingError as exc:
                    defer_remaining(index, exc)
                    raise
        else:
            results = scheduled_results()

        for index, ((item, card_key, claim, baseline), generated) in enumerate(zip(claimed_meta, results)):
            source_hash = claim.content_hash
            retry_after = self._file_card_deferral_delay(generated)
            if retry_after is not None:
                self._finish_file_card_enrichment(
                    claim, success=False, preempted=True,
                    retry_after_seconds=retry_after,
                )
                continue
            if not generated.get("success"):
                recorded = self._finish_file_card_enrichment(
                    claim, success=False,
                    error=str(generated.get("error") or generated.get("error_code") or "model generation failed"),
                )
                if recorded:
                    with self._stats_lock:
                        self._stats["file_card_failures"] = self._stats.get("file_card_failures", 0) + 1
                continue
            generated_model = str(generated.get("model") or "")
            if generated_model not in accepted_models or not self._valid_enriched_file_card(generated.get("data")):
                recorded = self._finish_file_card_enrichment(
                    claim, success=False, error="model card failed schema or model validation",
                )
                if recorded:
                    with self._stats_lock:
                        self._stats["file_card_failures"] = self._stats.get("file_card_failures", 0) + 1
                continue
            latest = self.repo_tools.file_slice(
                root, str(item["path"]), 1, int(self.cfg.get("file_card_max_lines", 900)),
                int(self.cfg.get("file_card_max_chars", 18000)),
            )
            if not latest.get("success") or str(latest.get("file_sha256") or "") != source_hash:
                self._finish_file_card_enrichment(claim, success=False,
                                                  error="source changed during enrichment")
                continue
            grounded_data = self._ground_card_data(
                self._generated_card_data(generated),
                str(item["path"]),
                str(latest.get("text") or ""),
                baseline,
            )
            if not self._valid_enriched_file_card(grounded_data):
                self._finish_file_card_enrichment(
                    claim, success=False, error="model card claim is missing source-grounded evidence",
                )
                continue
            if not self._store_file_card(root, item, card_key, grounded_data,
                                         generated_model, source_hash, enrichment_claim=claim):
                self._finish_file_card_enrichment(claim, success=False,
                                                  error="source hash changed before card commit")
                continue
            progressed = True
            with self._stats_lock:
                self._stats["file_card_generations"] = self._stats.get("file_card_generations", 0) + 1
            self._record_progress(root, 1)
        return progressed

    def _step_module(self, row: dict[str, Any]) -> bool:
        from . import preprocess as services_module
        root = str(row["root"])
        needed = self._modules_needing_card(root)
        if not needed:
            if row.get("phase") == "file_card_enrichment":
                return self._step_project(row)
            self._set_project(root, phase="project")
            return True

        bg_cfg = self.config.get("background_gpu", {})
        batch_size = max(1, int(bg_cfg.get("module_batch_size", bg_cfg.get("parallel", 4))))
        background_model = str(self.config.get("preprocessing", {}).get("model") or self.config.get("models", {}).get("background_code", "qwen2.5-coder:0.5b"))
        pending_tasks: list[dict[str, services_module.Any]] = []
        pending_meta: list[tuple[str, str]] = []
        progressed = False

        bg_ready = bool(self.background_gpu and self.background_gpu.ready())
        for module, revision, cards in needed[:batch_size]:
            compact_cards = [{"path": x["path"], "card": x["card"]} for x in cards[: int(self.cfg.get("module_max_files", 80))]]
            module_data = None
            if self.deterministic is not None and bool(self.cfg.get("prefer_deterministic_modules", True)):
                try:
                    det = self.deterministic.module_card(root, module, compact_cards)
                except Exception:
                    det = {"success": False}
                if det.get("success") and (float(det.get("confidence", 0.0)) >= float(self.cfg.get("deterministic_module_confidence", 0.75)) or not bg_ready):
                    module_data = det.get("card", {})
                    with self._stats_lock:
                        self._stats["deterministic_module_hits"] += 1
            if module_data is not None:
                self._store_module_card(root, module, revision, module_data)
                progressed = True
                continue

            llm_cards = [{"path": x["path"], **x["card"]} for x in cards[: int(self.cfg.get("module_max_files", 80))]]
            pending_tasks.append({
                "prompt": f"MODULE: {module}\nFILE CARDS:\n{services_module.json_dumps(llm_cards, ensure_ascii=False)[:30000]}",
                "system": "Synthesize a compact module card from supplied factual file cards. Do not invent code. Optimize for future debugging/refactor/navigation queries.",
                "schema": services_module.MODULE_SCHEMA,
                "max_tokens": int(self.cfg.get("module_output_tokens", 420)),
                "source": "preprocess:module",
            })
            pending_meta.append((module, revision))

        if not pending_tasks:
            return progressed or True
        if self.background_gpu is not None:
            if not self.background_gpu.ready():
                return False
            results = self.background_gpu.generate_many(pending_tasks, preprocessing=True)
        else:
            results = [
                self._run_background_generate(background_model, t["prompt"], t["system"], t["schema"], int(t["max_tokens"]), str(t["source"]))
                for t in pending_tasks
            ]

        preempted = False
        for (module, revision), generated in zip(pending_meta, results):
            if generated.get("preempted"):
                preempted = True
                continue
            if not generated.get("success"):
                with self._stats_lock:
                    self._stats["module_failures"] = self._stats.get("module_failures", 0) + 1
                continue
            self._store_module_card(root, module, revision, self._generated_card_data(generated))
            progressed = True
            with self._stats_lock:
                self._stats["module_generations"] += 1
        return False if preempted else progressed

    def _step_project(self, row: dict[str, Any]) -> bool:
        from . import preprocess as services_module
        root = str(row["root"])
        with self._db_lock, services_module.closing(self._connect()) as con:
            modules = con.execute("SELECT module,revision_hash,card_json FROM module_cards WHERE root=? ORDER BY module", (root,)).fetchall()
            current = con.execute("SELECT revision_hash FROM project_cards WHERE root=?", (root,)).fetchone()
            obsolete = self._obsolete_module_names(con, root, {item["module"] for item in modules})
        modules = [item for item in modules if item["module"] not in obsolete]
        revision = services_module.stable_hash([(x["module"], x["revision_hash"]) for x in modules] + [("struct", row.get("structural_hash"))])
        if current and current["revision_hash"] == revision:
            if obsolete and not self._write_retry(lambda con: self._prune_obsolete_module_cards(con, root, obsolete)):
                return False
            self._finish_project_card_step(row)
            return True
        profile = self._project_profile(root, self.services.repo_profile(root))
        repo_map = self.services.repo_map(root, int(self.cfg.get("preprocess_symbol_sample", 300)))
        module_data = []
        for x in modules:
            try:
                module_data.append({"module": x["module"], **services_module.json.loads(x["card_json"] or "{}")})
            except (KeyError, services_module.json.JSONDecodeError, TypeError, ValueError) as card_exc:
                services_module.logger.warning("Malformed module card skipped (%s)", type(card_exc).__name__)
                pass
        project_data = None
        bg_ready = bool(self.background_gpu and self.background_gpu.ready())
        if self.deterministic is not None and bool(self.cfg.get("prefer_deterministic_project", True)):
            try:
                det = self.deterministic.project_card(root, profile, repo_map, module_data)
            except Exception:
                det = {"success": False}
            if det.get("success") and (float(det.get("confidence", 0.0)) >= float(self.cfg.get("deterministic_project_confidence", 0.75)) or not bg_ready):
                project_data = det.get("card", {})
                with self._stats_lock:
                    self._stats["deterministic_project_hits"] += 1
        if project_data is None:
            if self._gpu_yield():
                return False
            prompt = services_module.json_dumps({"profile": profile, "repo_map": repo_map, "modules": module_data}, ensure_ascii=False)[:40000]
            bg_model = self._configured_preprocessing_model() or str(self.config.get("models", {}).get("background_code", "qwen2.5-coder:0.5b"))
            generated = self._run_background_generate(
                bg_model, prompt,
                "Build a compact factual project navigation card. Optimize it for future coding agents: architecture, entry points, tests, config, data flow, security/concurrency hot spots and validation. Do not invent unseen facts.",
                services_module.PROJECT_SCHEMA, int(self.cfg.get("project_output_tokens", 650)), "preprocess:project",
            )
            if generated.get("preempted"):
                return False
            if not generated.get("success"):
                project_data = {"summary": f"project generation error: {str(generated.get('error', ''))[:200]}", "architecture": {}, "entry_points": [], "modules": module_data[:10], "tests": []}
            else:
                project_data = self._generated_card_data(generated)
            with self._stats_lock:
                self._stats["project_generations"] += 1
        def store(con: services_module.sqlite3.Connection) -> bool:
            if obsolete and not self._prune_obsolete_module_cards(con, root, obsolete):
                return False
            con.execute(
                "INSERT OR REPLACE INTO project_cards(root,revision_hash,card_json,updated_at) VALUES(?,?,?,?)",
                (root, revision, services_module.json_dumps(project_data, ensure_ascii=False), services_module.time.time()),
            )
            return True

        if not self._write_retry(store):
            return False
        self._finish_project_card_step(row)
        return True

    def _step_hot_query(self, row: dict[str, Any]) -> bool:
        from . import preprocess as services_module
        root = str(row["root"])
        workspace = str(row["workspace"])
        if not bool(self.cfg.get("hot_queries_enabled", True)):
            self._set_project(root, phase="diagnostics")
            return True
        revision = self.rag.revision(workspace=workspace)
        queries = []
        if self.learner is not None:
            try:
                for q in self.learner.hot_queries(root, int(self.cfg.get("learned_hot_queries", 12))):
                    q_str = str(q).strip()
                    if q_str and len(q_str) <= 120 and len(q_str.split()) <= 15 and "\n" not in q_str:
                        queries.append(q_str)
            except Exception as learner_exc:
                services_module.logger.debug("Learned hot-query lookup unavailable (%s)", type(learner_exc).__name__)
                pass
        for q in self._hot_queries():
            if q not in queries:
                queries.append(q)
        with self._db_lock, services_module.closing(self._connect()) as con:
            existing = {r["query"]: r["revision_hash"] for r in con.execute("SELECT query,revision_hash FROM hot_query_state WHERE root=?", (root,)).fetchall()}
        query = next((q for q in queries if existing.get(q) != revision), None)
        if query is None:
            self._set_project(root, phase="diagnostics")
            return True
        if self._yield():
            return False
        # Local AI: do not spend embeddings/reranking on hot intents that parser/index facts
        # already answer with high confidence. The RAG path remains the fallback for
        # architecture/general intents that need semantic synthesis.
        det = {}
        if self.deterministic is not None:
            try:
                det = self.deterministic.query(root, query, limit=30)
            except Exception:
                det = {}
        deterministic_hot = bool(det.get("direct_answer")) and float(det.get("confidence", 0.0)) >= float(self.cfg.get("deterministic_hot_query_confidence", 0.94))
        graph = self.code_index.query(root, query, 20) if self.code_index is not None else {}
        if deterministic_hot:
            result = {"success": True, "results": [], "deterministic": True}
            paths = self.deterministic.related_paths(root, query, 8) if self.deterministic is not None else []
            evidence_ids = [str(x.get("evidence_id")) for x in det.get("evidence", []) if x.get("evidence_id")][:10]
            with self._stats_lock:
                self._stats["deterministic_hot_query_hits"] += 1
        else:
            use_reranker = bool(self.cfg.get("hot_query_use_reranker", False))
            self.rag.require_workspace_root(workspace=workspace, root=root)
            result = self.rag.search(query, workspace=workspace, top_k=int(self.cfg.get("hot_query_top_k", 8)), use_reranker=use_reranker, priority=0)
            if not result.get("success"):
                raise RuntimeError(str(result.get("error", "hot query failed")))
            hybrid = self.services._hybrid_context(root, query, workspace=workspace, max_tokens=int(self.cfg.get("hot_context_tokens", 1800)))
            paths = [str(x.get("path")) for x in result.get("results", [])[:8] if x.get("path")]
            evidence_ids = [str(x.get("evidence_id")) for x in (hybrid.get("evidence", []) if isinstance(hybrid, dict) else []) if x.get("evidence_id")][:10]
        capsule = {
            "intent": query,
            "paths": paths,
            "evidence_ids": evidence_ids,
            "symbols": graph.get("symbols", [])[:12] if isinstance(graph, dict) else [],
            "references": graph.get("references", [])[:12] if isinstance(graph, dict) else [],
            "deterministic": deterministic_hot,
        }
        with self._db_lock, services_module.closing(self._connect()) as con:
            con.execute(
                "INSERT OR REPLACE INTO hot_query_state(root,query,revision_hash,updated_at) VALUES(?,?,?,?)",
                (root, query, revision, services_module.time.time()),
            )
            con.execute(
                "INSERT OR REPLACE INTO task_capsules(root,query,revision_hash,capsule_json,updated_at) VALUES(?,?,?,?,?)",
                (root, query, revision, services_module.json_dumps(capsule, ensure_ascii=False), services_module.time.time()),
            )
            con.commit()
        with self._stats_lock:
            self._stats["hot_queries"] += 1
        return True

    def _step_diagnostics(self, row: dict[str, Any]) -> bool:
        from . import preprocess as services_module
        root = str(row["root"])
        if not bool(self.cfg.get("idle_diagnostics_enabled", False)):
            completed_at = services_module.time.time()
            interval = max(30, int(self.cfg.get("auto_recheck_seconds", 1800)))
            self._set_project(root, phase="complete", status="complete", last_complete_at=completed_at, next_check_at=completed_at + interval, force_refresh=0)
            return True
        if self._gpu_yield() or not self._scheduler_background_allowed():
            return False

        profile = self._project_profile(root, self.services.repo_profile(root))
        validation_cmds = profile.get("validation_commands", [])
        if not validation_cmds:
            completed_at = services_module.time.time()
            interval = max(30, int(self.cfg.get("auto_recheck_seconds", 1800)))
            self._set_project(root, phase="complete", status="complete", last_complete_at=completed_at, next_check_at=completed_at + interval, force_refresh=0)
            return True

        cmd_info = validation_cmds[0]
        cmd_value = (
            cmd_info.get("argv", cmd_info.get("command"))
            if isinstance(cmd_info, dict)
            else cmd_info
        )
        cmd_str = (
            services_module.json_dumps(cmd_value)
            if isinstance(cmd_value, (list, tuple))
            else str(cmd_value or "")
        )
        if not cmd_value:
            completed_at = services_module.time.time()
            interval = max(30, int(self.cfg.get("auto_recheck_seconds", 1800)))
            self._set_project(root, phase="complete", status="complete", last_complete_at=completed_at, next_check_at=completed_at + interval, force_refresh=0)
            return True

        import subprocess
        from .process_utils import (
            ProcessCancelledError,
            hidden_run_kwargs,
            run_hidden,
        )
        cleanup_error: BaseException | None = None

        class _DiagnosticCancelEvent:
            def is_set(cancel_event_self) -> bool:
                return self._gpu_yield()

        try:
            if isinstance(cmd_value, (list, tuple)):
                argv = [str(value) for value in cmd_value]
            else:
                argv = services_module.shlex.split(cmd_str, posix=(services_module.os.name != "nt"))
                if services_module.os.name == "nt":
                    argv = [
                        value[1:-1]
                        if len(value) >= 2
                        and (
                            (value.startswith('"') and value.endswith('"'))
                            or (value.startswith("'") and value.endswith("'"))
                        )
                        else value
                        for value in argv
                    ]
            if not argv or not argv[0]:
                raise ValueError("diagnostic command must contain an executable")
            if services_module.os.name == "nt" and services_module.Path(argv[0]).suffix.casefold() in {".cmd", ".bat"}:
                raise ValueError(
                    "Windows batch files are not permitted as idle diagnostic commands"
                )
            child_env = services_module.os.environ.copy()
            if services_module.Path(argv[0]).name.casefold().startswith(("python", "pypy")):
                # Python otherwise uses the active Windows code page for stdout,
                # while this capture is decoded as UTF-8 below.
                child_env["PYTHONIOENCODING"] = "utf-8"
            completed = run_hidden(
                argv,
                shell=False,
                cwd=root,
                env=child_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15.0,
                cancel_event=_DiagnosticCancelEvent(),
                **hidden_run_kwargs(),
            )
            stdout, stderr = completed.stdout or "", completed.stderr or ""
            exit_code = completed.returncode
            preview = (stderr or stdout or "")[:2000]
            error_count = preview.lower().count("error")
        except ProcessCancelledError as exc:
            if getattr(exc, "cleanup_confirmed", True):
                return False
            cleanup_error = exc
            exit_code = -1
            detail = "diagnostic process-tree cleanup could not be verified"
            output = str(getattr(exc, "stderr", None) or getattr(exc, "output", None) or "").strip()
            preview = f"{detail}: {output}"[:2000] if output else detail
            error_count = 1
        except subprocess.TimeoutExpired as exc:
            exit_code = -1
            if getattr(exc, "cleanup_confirmed", True) is False:
                cleanup_error = exc
                output = str(exc.stderr or exc.output or "").strip()
                detail = "diagnostic process-tree cleanup could not be verified"
                preview = f"{detail}: {output}"[:2000] if output else detail
            else:
                preview = "diagnostic timed out after 15s"
            error_count = 1
        except Exception as exc:
            exit_code = -1
            cleanup_unconfirmed = (
                getattr(exc, "cleanup_confirmed", True) is False
                or getattr(exc, "tree_termination_confirmed", True) is False
            )
            if cleanup_unconfirmed:
                cleanup_error = exc
                detail = "diagnostic process-tree cleanup could not be verified"
                output = str(getattr(exc, "stderr", None) or getattr(exc, "output", None) or "").strip()
                preview = f"{detail}: {output}"[:2000] if output else detail
            else:
                preview = f"diagnostic failed: {exc}"
            error_count = 1

        with self._db_lock, services_module.closing(self._connect()) as con:
            con.execute(
                "INSERT OR REPLACE INTO diagnostic_baselines(root, command, exit_code, error_count, stdout_preview, updated_at) VALUES(?, ?, ?, ?, ?, ?)",
                (root, cmd_str, exit_code, error_count, preview, services_module.time.time()),
            )
            con.commit()

        if cleanup_error is not None:
            raise cleanup_error

        completed_at = services_module.time.time()
        interval = max(30, int(self.cfg.get("auto_recheck_seconds", 1800)))
        self._set_project(root, phase="complete", status="complete", last_complete_at=completed_at, next_check_at=completed_at + interval, force_refresh=0)
        return True

