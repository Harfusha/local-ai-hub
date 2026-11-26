from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .preprocess import _FileCardClaim  # noqa: F401


class PreprocessCardStoreMixin:
    def candidate_paths(
        self, root: str, query: str, limit: int = 32, *, include_semantic: bool = True,
    ) -> list[str]:
        """Fast deterministic candidate selection; exact source verification happens later."""
        from . import preprocess as services_module
        resolved = self._root(root)
        limit = max(0, min(int(limit), 64))
        if not limit:
            return []
        terms = self.repo_tools._terms(query)
        paths: list[str] = []
        if terms:
            expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms[:12])
            try:
                with self._db_lock, services_module.closing(self._connect()) as con:
                    paths.extend(self._ranked_lexical_paths(con, resolved, expression, limit))
            except services_module.sqlite3.OperationalError as fts_exc:
                services_module.logger.debug("Preprocessing FTS candidate search unavailable (%s)", type(fts_exc).__name__)
                pass
        if include_semantic:
            # Semantic cards cover vocabulary mismatch and FTS-unavailable builds.
            try:
                cards = self.lookup(resolved, query, limit=max(5, min(int(limit), 16)))
                paths.extend(str(x.get("path")) for x in cards.get("files", []) if x.get("path"))
            except Exception as lookup_exc:
                services_module.logger.debug("Semantic card candidate lookup unavailable (%s)", type(lookup_exc).__name__)
                pass
        if not paths:
            return []
        settings = self._project_settings(resolved)
        out: list[str] = []
        seen: set[str] = set()
        for path in paths:
            relative = str(path).replace("\\", "/")
            try:
                candidate = (services_module.Path(resolved) / relative).resolve(strict=True)
                candidate.relative_to(services_module.Path(resolved))
                if not candidate.is_file():
                    continue
                size = int(candidate.stat().st_size)
            except (OSError, RuntimeError, ValueError):
                continue
            relative = candidate.relative_to(services_module.Path(resolved)).as_posix()
            if relative not in seen and self._project_path_allowed(
                resolved, relative, settings, phase="search", size_bytes=size
            ):
                seen.add(relative)
                out.append(relative)
            if len(out) >= limit:
                break
        if out:
            try:
                context = services_module.resolve_project_context(resolved, self.state_dir)
                usage = context.prioritize_paths(
                    out,
                    purpose="preprocess_search",
                    scope="candidate_paths",
                    repository_revision=lambda: self._external_revision(resolved),
                )
                out = list(usage.paths)
            except (OSError, RuntimeError, TypeError, ValueError):
                pass
        return out[:limit]

    def candidate_paths_lexical(self, root: str, query: str, limit: int = 32) -> list[str]:
        """Return FTS-only candidates when exact source search makes semantics redundant."""
        return self.candidate_paths(root, query, limit, include_semantic=False)

    def _content_card_key(self, content_hash: str) -> str:
        from . import preprocess as services_module
        bg_model = self._configured_preprocessing_model()
        return services_module.stable_hash({
            "analyzer": services_module.PREPROCESS_ANALYZER_VERSION,
            "sha": content_hash,
            "model": bg_model,
            "prompt_version": services_module.FILE_CARD_PROMPT_VERSION,
            "schema": services_module.CARD_SCHEMA,
        })

    def _file_card_fallbacks(self, model: str) -> tuple[str, ...]:
        graph = self._role_graph()
        if not graph.fallback_enabled:
            return ()
        if model == graph.primary_model:
            return graph.fallback_models
        fallback_models = getattr(getattr(self, "services", None), "_fallback_models", None)
        configured = fallback_models(model) if callable(fallback_models) else ()
        if not isinstance(configured, (list, tuple)):
            return ()
        return tuple(c for c in configured if isinstance(c, str) and c and c != model)

    def _file_card_pipeline_version(self) -> str:
        from . import preprocess as services_module
        graph = self._role_graph()
        return services_module.stable_hash({
            "analyzer": services_module.PREPROCESS_ANALYZER_VERSION,
            "prompt_version": services_module.FILE_CARD_PROMPT_VERSION,
            "schema": services_module.CARD_SCHEMA,
            "primary_model": graph.primary_model,
            "cascade_enabled": graph.cascade_enabled,
            "draft_model": graph.draft_model,
            "refiner_model": graph.refiner_model,
            "fallback_enabled": graph.fallback_enabled,
            "fallback_models": graph.fallback_models,
            "effective_phases": graph.effective_phases,
            "temperature": 0.2,
            "output_tokens": int(self.cfg.get("file_card_output_tokens", 3072)),
            "max_lines": int(self.cfg.get("file_card_max_lines", 900)),
            "max_chars": int(self.cfg.get("file_card_max_chars", 18000)),
            "evidence_policy": "source_quote_required",
        })

    def _reusable_file_card(self, row: sqlite3.Row, models: set[str], *, allow_deterministic: bool = False) -> bool:
        from . import preprocess as services_module
        deterministic = allow_deterministic and row["model"] in services_module._DETERMINISTIC_FILE_CARD_MODELS
        if not deterministic and (
            row["model"] not in models or row["card_key"] != self._content_card_key(row["content_hash"])
        ):
            return False
        try:
            data = services_module.json.loads(str(row["card_json"]))
        except (TypeError, ValueError):
            return False
        return isinstance(data, dict) if deterministic else self._valid_enriched_file_card(data)

    def _claim_file_card_enrichment(self, content_hash: str, model: str) -> _FileCardClaim | None:
        from . import preprocess as services_module
        identity = (content_hash, model, self._file_card_pipeline_version())
        claim = services_module._FileCardClaim(*identity, services_module.uuid4().hex)

        def store_claim(con: sqlite3.Connection) -> bool:
            now = services_module.time.time()
            lease_until = now + 900.0
            cur = con.execute(
                """INSERT INTO file_card_enrichment(
                       content_hash,model,pipeline_version,status,attempts,retry_after,lease_until,claim_id,last_error,updated_at
                   ) VALUES(?,?,?,'running',1,0,?,?,NULL,?)
                   ON CONFLICT(content_hash,model,pipeline_version) DO UPDATE SET
                       status='running',attempts=file_card_enrichment.attempts+1,
                       lease_until=excluded.lease_until,claim_id=excluded.claim_id,last_error=NULL,updated_at=excluded.updated_at
                   WHERE file_card_enrichment.status!='complete'
                     AND file_card_enrichment.attempts<3
                     AND file_card_enrichment.retry_after<=?
                     AND (file_card_enrichment.status!='running' OR file_card_enrichment.lease_until<=?)""",
                (*identity, lease_until, claim.claim_id, now, now, now),
            )
            if cur.rowcount == 1:
                return True
            completed = con.execute(
                """SELECT c.content_hash,c.card_key,c.model,c.card_json
                   FROM file_card_enrichment e
                   LEFT JOIN content_cards c ON c.card_key=? AND c.content_hash=e.content_hash
                     AND c.analyzer_version=?
                   WHERE e.content_hash=? AND e.model=? AND e.pipeline_version=? AND e.status='complete'""",
                (self._content_card_key(content_hash), services_module.PREPROCESS_ANALYZER_VERSION, *identity),
            ).fetchone()
            if completed is None or self._reusable_file_card(
                completed, {model, *self._file_card_fallbacks(model)},
            ):
                return False
            # An orphaned cache entry can expire after the enrichment completed.
            cur = con.execute(
                """UPDATE file_card_enrichment SET status='running',attempts=1,retry_after=0,
                   lease_until=?,claim_id=?,last_error=NULL,updated_at=?
                   WHERE content_hash=? AND model=? AND pipeline_version=? AND status='complete'""",
                (lease_until, claim.claim_id, now, *identity),
            )
            return cur.rowcount == 1

        return claim if self._write_retry(store_claim) else None

    @staticmethod
    def _finish_file_card_claim(
        con: sqlite3.Connection, claim: _FileCardClaim, *, success: bool,
        error: str | None = None, preempted: bool = False, retry_after_seconds: float | None = None,
    ) -> bool:
        from . import preprocess as services_module
        now = services_module.time.time()
        status = "complete" if success else ("pending" if preempted else "failed")
        retry_after = (
            now + services_module._safe_float(retry_after_seconds, 0.0, min_val=0.0, max_val=300.0)
            if preempted else (now + 60.0 if not success else 0.0)
        )

        return con.execute(
            """UPDATE file_card_enrichment SET status=?,
               attempts=CASE WHEN ? THEN MAX(0,attempts-1) ELSE attempts END,
               retry_after=?,lease_until=0,claim_id=NULL,last_error=?,updated_at=?
               WHERE content_hash=? AND model=? AND pipeline_version=? AND claim_id=? AND status='running'""",
            (status, int(preempted), retry_after, (str(error)[:240] if error else None), now, *claim),
        ).rowcount == 1

    def _finish_file_card_enrichment(
        self, claim: _FileCardClaim, *, success: bool, error: str | None = None,
        preempted: bool = False, retry_after_seconds: float | None = None,
    ) -> bool:
        return bool(self._write_retry(lambda con: self._finish_file_card_claim(
            con, claim, success=success, error=error, preempted=preempted, retry_after_seconds=retry_after_seconds,
        )))

    @staticmethod
    def _file_card_deferral_delay(result: dict[str, Any]) -> float | None:
        from . import preprocess as services_module
        if result.get("terminal") is True or result.get("outcome_unknown") or result.get("cleanup_unconfirmed"):
            return None
        missing_estimate = result.get("last_admission_reason") == "target_vram_estimate_unavailable"
        if result.get("preempted"):
            default = 0.0
        elif result.get("retryable") is True or (missing_estimate and result.get("last_admission_state") == "rejected"):
            default = 300.0 if missing_estimate else 60.0
        else:
            return None
        return services_module._safe_float(result.get("retry_after_seconds"), default, min_val=0.0, max_val=300.0)

    def _learned_priority_paths(self, root: str) -> tuple[str, ...]:
        """Use bounded learned queries as advisory background scheduling hints."""
        from . import preprocess as services_module
        learner = getattr(self, "learner", None)
        if learner is None or not getattr(learner, "enabled", True):
            return ()
        cache = getattr(self, "_demand_priority_cache", None)
        lock = getattr(self, "_demand_priority_lock", None)
        now = services_module.time.monotonic()
        try:
            queries = tuple(learner.hot_queries(root, 4)[:4])
            with self._db_lock, services_module.closing(self._connect()) as con:
                has_revision_tracking = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='file_refs_revision'"
                ).fetchone() is not None
                if has_revision_tracking:
                    revision = con.execute(
                        "SELECT revision FROM file_refs_revision WHERE root=?", (root,)
                    ).fetchone()
                    index_signature = (int(revision[0]) if revision else 0,)
                else:
                    # Minimal legacy/test schemas lack startup-installed triggers.
                    columns = {str(row[1]) for row in con.execute("PRAGMA table_info(file_refs)").fetchall()}
                    aggregates = ["COUNT(*)"]
                    for column in ("generation", "updated_at", "size", "needs_hash", "last_accessed_at"):
                        if column in columns:
                            aggregates.append(f"COALESCE(SUM(CAST({column} AS REAL)), 0)")
                    for column in ("content_hash", "rag_hash", "card_key"):
                        if column in columns:
                            aggregates.append(f"COALESCE(SUM(LENGTH(COALESCE({column}, ''))), 0)")
                            aggregates.append(f"COUNT(DISTINCT {column})")
                    revision = con.execute(
                        f"SELECT {', '.join(aggregates)} FROM file_refs WHERE root=?", (root,)
                    ).fetchone()
                    index_signature = tuple(revision)
            if cache is not None and lock is not None:
                with lock:
                    cached = cache.get(root)
                    if (cached is not None and cached[0] > now
                            and cached[1] == queries and cached[2] == index_signature):
                        return cached[3]
            paths: list[str] = []
            with self._db_lock, services_module.closing(self._connect()) as con:
                for query in queries[:4]:
                    if not isinstance(query, str) or len(query) > 120:
                        continue
                    terms = self.repo_tools._terms(query)[:8]
                    if not terms:
                        continue
                    expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
                    paths.extend(self._ranked_lexical_paths(con, root, expression, 16))
            result = tuple(dict.fromkeys(paths))[:32]
        except (AttributeError, OSError, RuntimeError, services_module.sqlite3.Error, TypeError, ValueError):
            return ()
        if cache is not None and lock is not None:
            with lock:
                if len(cache) >= 128 and root not in cache:
                    cache.pop(min(cache, key=lambda key: cache[key][0]), None)
                cache[root] = (now + 15.0, queries, index_signature, result)
        return result

    def _find_next_files(self, root: str, limit: int) -> list[sqlite3.Row]:
        from . import preprocess as services_module
        max_bytes = int(self.cfg.get("file_card_max_bytes", 180000))
        limit = max(1, int(limit))
        priority_paths = self._learned_priority_paths(root) if limit > 1 else ()
        enrich_cards = self._file_card_enrichment_enabled()
        background_model = self._configured_preprocessing_model()
        now = services_module.time.time()
        with self._db_lock, services_module.closing(self._connect()) as con:
            if enrich_cards:
                card_filter = """(card_key IS NULL OR card_key IN (
                    SELECT card_key FROM content_cards
                    WHERE model IN ('deterministic','deterministic-stub','deterministic-barrel')
                )) AND NOT EXISTS (
                    SELECT 1 FROM file_card_enrichment e
                    WHERE e.content_hash=file_refs.content_hash AND e.model=? AND e.pipeline_version=?
                      AND e.status!='complete'
                      AND (e.attempts>=3 OR e.retry_after>?
                           OR (e.status='running' AND e.lease_until>?))
                )"""
                selection_params: tuple[Any, ...] = (
                    root, background_model, self._file_card_pipeline_version(), now, now, max_bytes,
                )
            else:
                card_filter = "card_key IS NULL"
                selection_params = (root, max_bytes)
            selection = f"SELECT * FROM file_refs WHERE root=? AND {card_filter} AND size<=?"
            order = """ ORDER BY
                     (COALESCE(last_accessed_at, 0) > 0) DESC,
                     COALESCE(centrality_score, 0.0) DESC,
                     CASE
                       WHEN path LIKE '%/Controllers/%' THEN 0
                       WHEN path LIKE '%/Runtime/%'     THEN 0
                       WHEN path LIKE '%/Core/%'        THEN 0
                       WHEN path LIKE '%/Services/%'    THEN 0
                       WHEN path LIKE '%Main%'          THEN 0
                       WHEN path LIKE '%Bootstrap%'     THEN 0
                       WHEN path LIKE '%/Tests/%'       THEN 2
                       WHEN path LIKE '%/test/%'        THEN 2
                       WHEN path LIKE '%_test%'         THEN 2
                       WHEN path LIKE '%.test.%'        THEN 2
                       WHEN path LIKE '%/Generated/%'   THEN 3
                       ELSE 1
                     END ASC,
                     size ASC, path ASC
                   LIMIT ?"""
            regular = con.execute(selection + order, (*selection_params, limit)).fetchall()
            if not priority_paths:
                return regular
            placeholders = ",".join("?" for _ in priority_paths)
            quota = min(limit - 1, max(1, limit // 4))
            preferred = con.execute(
                selection + f" AND path IN ({placeholders})" + order,
                (*selection_params, *priority_paths, quota),
            ).fetchall()
            selected = list(preferred)
            seen = {str(row["path"]) for row in selected}
            selected.extend(row for row in regular if str(row["path"]) not in seen)
            return selected[:limit]

    def _find_next_file(self, root: str) -> sqlite3.Row | None:
        rows = self._find_next_files(root, 1)
        return rows[0] if rows else None

    @staticmethod
    def _generated_card_data(result: dict[str, Any]) -> Any:
        data = result.get("data", {})
        budget = result.get("prompt_budget")
        if not isinstance(data, dict):
            return data
        data = {key: value for key, value in data.items() if key != "_input_prompt_budget"}
        if (not isinstance(budget, dict)
                or type(budget.get("truncated")) is not bool
                or type(budget.get("estimated_tokens")) is not int
                or type(budget.get("original_estimated_tokens")) is not int
                or budget["estimated_tokens"] < 0
                or budget["original_estimated_tokens"] < budget["estimated_tokens"]):
            return data
        return {**data, "_input_prompt_budget": {
            "truncated": budget["truncated"],
            "estimated_tokens": budget["estimated_tokens"],
            "original_estimated_tokens": budget["original_estimated_tokens"],
        }}

    @staticmethod
    def _ground_card_data(data: Any, path: str, source_text: str, deterministic: Any = None) -> Any:
        from . import preprocess as services_module
        if not isinstance(data, dict):
            return data
        raw_evidence = data.get("evidence")
        if not isinstance(raw_evidence, list):
            raw_evidence = []
        source_folded = source_text.casefold()
        valid_evidence: list[dict[str, str]] = []
        evidence_by_field: dict[str, list[dict[str, str]]] = {}
        for item in raw_evidence:
            if (
                isinstance(item, dict)
                and isinstance(item.get("field"), str)
                and item["field"] in {"purpose", "symbols", "dependencies", "side_effects", "risks", "tests", "keywords"}
                and isinstance(item.get("quote"), str)
                and item["quote"].strip()
                and item["quote"].casefold() in source_folded
            ):
                valid_item = {
                    "field": str(item["field"]),
                    "value": str(item.get("value", ""))[:500],
                    "quote": str(item["quote"])[:500],
                }
                valid_evidence.append(valid_item)
                evidence_by_field.setdefault(valid_item["field"], []).append(valid_item)

        baseline = deterministic if isinstance(deterministic, dict) else {}
        known_symbols = {
            str(v).casefold() for v in baseline.get("symbols", []) if isinstance(v, str) and v.strip()
        }

        # Purpose validation and grounding
        purpose = str(data.get("purpose", "")).strip()
        purpose_grounded = False
        if purpose:
            if "purpose" in evidence_by_field:
                purpose_grounded = True
            elif any(sym in purpose.casefold() for sym in known_symbols):
                purpose_grounded = True
            elif len(source_folded) < 200 or services_module.Path(path).name.casefold() in purpose.casefold():
                purpose_grounded = True
            elif any(term in source_folded for term in purpose.casefold().split() if len(term) >= 4):
                purpose_grounded = True

        if not purpose_grounded or not purpose:
            baseline_purpose = str(baseline.get("purpose", "")).strip()
            purpose = baseline_purpose if baseline_purpose else f"Source file ({services_module.Path(path).name})"
            if "purpose" not in evidence_by_field:
                first_line = source_text.strip().splitlines()[0][:120] if source_text.strip() else services_module.Path(path).name
                fallback_ev = {"field": "purpose", "value": purpose[:500], "quote": first_line[:500]}
                valid_evidence.insert(0, fallback_ev)
                evidence_by_field.setdefault("purpose", []).append(fallback_ev)
        elif "purpose" not in evidence_by_field:
            first_line = source_text.strip().splitlines()[0][:120] if source_text.strip() else services_module.Path(path).name
            fallback_ev = {"field": "purpose", "value": purpose[:500], "quote": first_line[:500]}
            valid_evidence.insert(0, fallback_ev)
            evidence_by_field.setdefault("purpose", []).append(fallback_ev)

        data["purpose"] = purpose[:500]

        # Field-by-field grounding
        for field in ("symbols", "dependencies", "side_effects", "risks", "tests", "keywords"):
            original = data.get(field, [])
            if not isinstance(original, list):
                original = []
            baseline_values = baseline.get(field)
            known = {
                value.casefold() for value in baseline_values if isinstance(value, str) and value.strip()
            } if isinstance(baseline_values, list) else set()
            field_ev = evidence_by_field.get(field, [])
            grounded_items: list[str] = []
            seen_items: set[str] = set()

            # Always preserve deterministic baseline facts first (only if true deterministic fact)
            is_deterministic = baseline.get("epistemic_class") != "llm_draft"
            if is_deterministic and isinstance(baseline_values, list):
                for val in baseline_values:
                    if isinstance(val, str) and val.strip() and val.casefold() not in seen_items:
                        grounded_items.append(val.strip())
                        seen_items.add(val.casefold())

            # Evaluate model-added values
            for val in original:
                if not isinstance(val, str) or not val.strip():
                    continue
                val_clean = val.strip()
                val_lower = val_clean.casefold()
                if val_lower in seen_items:
                    continue

                is_supported = False
                if val_lower in known:
                    is_supported = True
                elif field in ("symbols", "dependencies"):
                    # For symbols/deps: must appear in source text or in an evidence quote
                    if val_lower in source_folded or any(val_lower in ev["quote"].casefold() for ev in field_ev):
                        is_supported = True
                elif field in ("side_effects", "risks"):
                    # For risks/side-effects: semantic summaries are supported if evidence quote exists,
                    # or if they cite an API/symbol/keyword present in source
                    if field_ev or any(sym in val_lower for sym in known_symbols) or any(
                        kw in source_folded for kw in ("write", "read", "open", "socket", "lock", "exec", "eval", "delete", "post", "get") if kw in val_lower
                    ):
                        is_supported = True
                elif field == "tests":
                    if val_lower in source_folded or "test" in val_lower or field_ev:
                        is_supported = True
                elif field == "keywords":
                    if val_lower in source_folded or val_lower in path.casefold() or val_lower in purpose.casefold() or field_ev:
                        is_supported = True

                if is_supported:
                    grounded_items.append(val_clean)
                    seen_items.add(val_lower)

            data[field] = grounded_items

        ext = services_module.Path(path).suffix.lower()
        if ext in (".md", ".txt", ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".xml", ".svg", ".sql"):
            data["symbols"] = []
            data["dependencies"] = []
        data["evidence"] = valid_evidence
        data["epistemic_class"] = "llm_enriched"
        data["confidence"] = 0.95
        try:
            from .preprocess_ast import extract_ast_symbol_chunks, enrich_card_with_ast_symbols
            chunks = extract_ast_symbol_chunks(path, source_text)
            if chunks:
                data = enrich_card_with_ast_symbols(data, chunks)
        except Exception:
            pass
        return data

    def _store_file_card(self, root: str, item: sqlite3.Row, card_key: str, data: dict[str, Any], model: str,
                         expected_hash: str | None = None, *, enrichment_claim: _FileCardClaim | None = None) -> bool:
        from . import preprocess as services_module
        now = services_module.time.time()
        def store(con: sqlite3.Connection) -> bool:
            source_hash = expected_hash or str(item["content_hash"])
            current = con.execute(
                "SELECT content_hash, card_key FROM file_refs WHERE root=? AND path=?",
                (root, str(item["path"])),
            ).fetchone()
            if current is None or str(current[0]) != source_hash:
                return False
            if enrichment_claim is not None and (
                enrichment_claim.content_hash != source_hash
                or not self._finish_file_card_claim(con, enrichment_claim, success=True)
            ):
                return False
            con.execute(
                "INSERT OR REPLACE INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,COALESCE((SELECT hits FROM content_cards WHERE card_key=?),0))",
                (card_key, source_hash, model, services_module.PREPROCESS_ANALYZER_VERSION, services_module.json_dumps(data, ensure_ascii=False), now, now, card_key),
            )
            con.execute("UPDATE file_refs SET card_key=?,updated_at=? WHERE root=? AND path=? AND content_hash=?",
                         (card_key, now, root, item["path"], source_hash))
            return True

        stored = bool(self._write_retry(store))
        if stored:
            self._publish_knowledge_card_candidate(root, str(item["path"]), expected_hash or str(item["content_hash"]), data, model)
        return stored

    def _publish_knowledge_card_candidate(
        self, root: str, path: str, source_hash: str, card: dict[str, Any], model: str,
    ) -> None:
        from . import preprocess as services_module
        from .repo_knowledge_discovery import publish_file_card_candidate

        try:
            status = publish_file_card_candidate(self.config, root, path, source_hash, card, model)
            if status not in {"not_authorized", "no_candidate", "unchanged"}:
                with self._stats_lock:
                    key = "knowledge_candidate_" + status
                    self._stats[key] = self._stats.get(key, 0) + 1
        except Exception as exc:
            # Candidate publication is optional, never blocks technical indexing.
            services_module.logger.warning("Knowledge candidate publication failed (%s)", type(exc).__name__)

    def _record_model_failure_trace(
        self, model: str, prompt: str, system: str, schema: Any,
        max_tokens: int, source: str, failure: Any,
    ) -> None:
        from . import preprocess as services_module
        store = getattr(self, "debug_traces", None)
        if getattr(store, "enabled", False) is not True:
            return
        details = failure if isinstance(failure, dict) else {
            "error": str(failure), "error_type": type(failure).__name__,
        }
        try:
            trace_id = store.start(
                kind="preprocess", agent="local-ai-preprocessor", action=source,
                source="preprocess", model=model,
                initial_event=("request_received", {"source": source}),
            )
            if not trace_id:
                return
            request = {
                "model": model, "prompt": prompt, "system": system,
                "format": schema, "options": {"num_predict": int(max_tokens)},
            }
            store.update(trace_id, effective_payload=request)
            store.event(trace_id, "model_request", request)
            store.event(trace_id, "failed", details)
            store.finish(
                trace_id, state="failed",
                error=str(details.get("error") or details.get("error_type") or "preprocessing model failed"),
            )
        except Exception as exc:
            services_module.logger.warning("Preprocessing model failure trace could not be saved (%s)", type(exc).__name__)

    @staticmethod
    def _module_for(path: str) -> str:
        parts = path.replace("\\", "/").split("/")
        return parts[0] if len(parts) > 1 else "<root>"

    def _modules_needing_card(self, root: str) -> list[tuple[str, str, list[dict[str, Any]]]]:
        from . import preprocess as services_module
        groups: dict[str, list[dict[str, Any]]] = {}
        with self._db_lock, services_module.closing(self._connect()) as con:
            rows = con.execute(
                """SELECT f.path,f.content_hash,c.card_json FROM file_refs f
                   LEFT JOIN content_cards c ON c.card_key=f.card_key WHERE f.root=? AND f.card_key IS NOT NULL ORDER BY f.path""",
                (root,),
            ).fetchall()
            existing = {r["module"]: r["revision_hash"] for r in con.execute("SELECT module,revision_hash FROM module_cards WHERE root=?", (root,)).fetchall()}
        for r in rows:
            module = self._module_for(str(r["path"]))
            try:
                card = services_module.json.loads(r["card_json"] or "{}")
            except (TypeError, ValueError, RecursionError):
                card = {}
            groups.setdefault(module, []).append({
                "path": r["path"], "hash": r["content_hash"], "card": card if isinstance(card, dict) else {},
            })
        needed: list[tuple[str, str, list[dict[str, Any]]]] = []
        card_limit = int(self.cfg.get("module_max_files", 80))
        for module, cards in sorted(groups.items()):
            revision = services_module.stable_hash({
                "files": [(x["path"], x["hash"]) for x in cards],
                "cards": [x["card"] for x in cards[:card_limit]],
            })
            if existing.get(module) != revision:
                needed.append((module, revision, cards))
        return needed

    def _store_module_card(self, root: str, module: str, revision: str, module_data: dict[str, Any]) -> None:
        from . import preprocess as services_module
        with self._db_lock, services_module.closing(self._connect()) as con:
            con.execute(
                "INSERT OR REPLACE INTO module_cards(root,module,revision_hash,card_json,updated_at) VALUES(?,?,?,?,?)",
                (root, module, revision, services_module.json_dumps(module_data, ensure_ascii=False), services_module.time.time()),
            )
            con.commit()

    def _refresh_deferred_card_summaries(self, row: dict[str, Any]) -> bool:
        if self._project_phase_allowed(str(row["root"]), "modules"):
            return self._step_module(row)
        return self._step_project(row)

    def _finish_project_card_step(self, row: dict[str, Any]) -> None:
        from . import preprocess as services_module
        root = str(row["root"])
        if row.get("phase") == "file_card_enrichment":
            completed_at = services_module.time.time()
            interval = max(30, int(self.cfg.get("auto_recheck_seconds", 1800)))
            self._set_project(root, phase="complete", status="complete", force_refresh=0,
                              last_complete_at=completed_at, next_check_at=completed_at + interval)
        else:
            self._set_project(root, phase="hot_queries")

    def _obsolete_module_names(self, con: sqlite3.Connection, root: str, names: set[str]) -> set[str]:
        remaining = names.copy()
        if remaining:
            for ref in con.execute("SELECT path FROM file_refs WHERE root=?", (root,)):
                remaining.discard(self._module_for(str(ref[0])))
                if not remaining:
                    break
        return remaining

    def _prune_obsolete_module_cards(self, con: sqlite3.Connection, root: str, names: set[str]) -> bool:
        if self._obsolete_module_names(con, root, names) != names:
            return False
        con.executemany("DELETE FROM module_cards WHERE root=? AND module=?",
                        [(root, module) for module in sorted(names)])
        return True

    def _hot_queries(self) -> list[str]:
        configured = self.cfg.get("hot_queries")
        if isinstance(configured, list) and configured:
            return [str(x) for x in configured]
        return [
            "architecture entry points core modules dependencies",
            "tests validation lint static analysis build",
            "configuration environment startup bootstrap",
            "API routes controllers endpoints handlers",
            "database schema models persistence transactions",
            "authentication authorization permissions security",
            "errors exceptions retries recovery logging",
            "concurrency async threads locks queues background jobs",
        ]

    def _repair_attached_file_cards(self, con: sqlite3.Connection, now: float) -> tuple[str, str]:
        from . import preprocess as services_module
        cursor = getattr(self, "_file_card_repair_cursor", ("", ""))
        batch_size = 512
        rows = con.execute(
            """SELECT f.root,f.path,f.content_hash,f.card_key,c.content_hash AS cached_hash,
                      c.card_json,c.analyzer_version,c.model
               FROM file_refs f JOIN projects p ON p.root=f.root
               LEFT JOIN content_cards c ON c.card_key=f.card_key
               WHERE (f.root,f.path)>(?,?) AND f.card_key IS NOT NULL
                 AND f.needs_hash=0 AND f.content_hash<>''
                 AND p.phase='complete' AND p.status='complete' AND p.paused=0
               ORDER BY f.root,f.path LIMIT ?""",
            (*cursor, batch_size),
        ).fetchall()
        model = self._configured_preprocessing_model()
        damaged = []
        for row in rows:
            try:
                data = services_module.json.loads(row["card_json"])
            except (TypeError, ValueError, RecursionError):
                data = None
            valid = row["cached_hash"] == row["content_hash"] and isinstance(data, dict)
            if (valid and model and row["model"] not in services_module._DETERMINISTIC_FILE_CARD_MODELS
                    and row["card_key"] == self._content_card_key(row["content_hash"])):
                valid = row["analyzer_version"] == services_module.PREPROCESS_ANALYZER_VERSION and self._valid_enriched_file_card(data)
            if not valid:
                damaged.append((row["root"], row["path"], row["content_hash"], row["card_key"]))
        if damaged:
            con.executemany(
                "UPDATE file_refs SET card_key=NULL,updated_at=? WHERE root=? AND path=? AND content_hash=? AND card_key=?",
                [(now, *ref) for ref in damaged],
            )
            con.executemany(
                """UPDATE projects SET phase='files',status='queued',retry_after=0,next_check_at=?,updated_at=?,last_error=NULL
                   WHERE root=? AND phase='complete' AND status='complete' AND paused=0""",
                [(now, now, root) for root in sorted({ref[0] for ref in damaged})],
            )
        if len(rows) < batch_size:
            return "", ""
        return rows[-1]["root"], rows[-1]["path"]

    @staticmethod
    def _matching_module_cards(
        modules: list[tuple[str, str, dict[str, Any]]], terms: set[str], limit: int,
    ) -> list[dict[str, Any]]:
        scored: list[tuple[int, dict[str, Any]]] = []
        for name, text, card in modules:
            score = sum(2 for term in terms if term in name) + sum(1 for term in terms if term in text)
            if score:
                scored.append((score, card))
        scored.sort(key=lambda item: -item[0])
        return [card for _, card in scored[:limit]]
