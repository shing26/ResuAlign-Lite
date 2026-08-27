from pathlib import Path

SRC = Path("src/resualign/job_library.py")
TEXT = SRC.read_text(encoding="utf-8")

OLD_START = "    def update_job(\n"
OLD_END = "    def save_final_draft(\n"

HELPERS = '''    @staticmethod
    def _normalize_job_update_fields(fields: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize editable job fields before any SQL write."""
        normalized = dict(fields)
        functions = _effective_choices(
            JOB_FUNCTIONS, normalized.get("allowed_job_functions")
        )
        seniorities = _effective_choices(
            SENIORITIES, normalized.get("allowed_seniorities")
        )
        if (
            normalized.get("job_function") is not None
            and normalized["job_function"] not in functions
        ):
            raise UserStoreError(
                f"Invalid job_function: {normalized['job_function']}"
            )
        if (
            normalized.get("seniority") is not None
            and normalized["seniority"] not in seniorities
        ):
            raise UserStoreError(f"Invalid seniority: {normalized['seniority']}")
        if normalized.get("status") is not None:
            normalized["status"] = _validate_status(normalized["status"])
        if (
            normalized.get("classification_pending") is not None
            and normalized["classification_pending"] not in (0, 1)
        ):
            raise UserStoreError(
                "classification_pending must be 0 or 1"
            )
        if normalized.get("final_draft") is not None and not str(
            normalized["final_draft"]
        ).strip():
            raise UserStoreError("Final draft cannot be empty")
        if (
            normalized.get("tailor_granularity") is not None
            and normalized["tailor_granularity"] not in TAILOR_GRANULARITIES
        ):
            raise UserStoreError(
                f"Invalid tailor_granularity: {normalized['tailor_granularity']}"
            )
        if (
            normalized.get("tailor_focus") is not None
            and normalized["tailor_focus"] not in TAILOR_FOCUSES
        ):
            raise UserStoreError(f"Invalid tailor_focus: {normalized['tailor_focus']}")
        if normalized.get("custom_prompt") is not None:
            normalized["custom_prompt"] = normalized["custom_prompt"].strip()
        if (
            normalized.get("refresh_enabled") is not None
            and normalized["refresh_enabled"] not in (0, 1)
        ):
            raise UserStoreError("refresh_enabled must be 0 or 1")
        if (
            normalized.get("match_stale") is not None
            and normalized["match_stale"] not in (0, 1)
        ):
            raise UserStoreError("match_stale must be 0 or 1")
        if normalized.get("refresh_status") is not None and normalized[
            "refresh_status"
        ] not in {"queued", "succeeded", "failed", "closed"}:
            raise UserStoreError(
                f"Invalid refresh_status: {normalized['refresh_status']}"
            )
        if normalized.get("jd_text") is not None and not str(
            normalized["jd_text"]
        ).strip():
            raise UserStoreError("Job description text cannot be empty")
        return normalized

    def _apply_status_lifecycle(
        self,
        current: dict[str, Any] | None,
        fields: dict[str, Any],
    ) -> tuple[dict[str, str], bool, str | None]:
        """Resolve status timeline writes or an append-only re-record."""
        lifecycle: dict[str, str] = {}
        append_only_snapshot = False
        snapshot_applied_at: str | None = None
        status = fields.get("status")
        if status is None or current is None:
            return lifecycle, append_only_snapshot, snapshot_applied_at
        if (
            canonical_status(status) == "applied"
            and canonical_status(current["status"]) != "draft"
        ):
            append_only_snapshot = True
            snapshot_applied_at = (
                fields.get("applied_at")
                or current.get("applied_at")
                or time.strftime("%Y-%m-%d")
            )
        else:
            lifecycle = status_lifecycle_fields(
                current,
                status,
                provided={
                    "applied_at": fields.get("applied_at"),
                    "offer_at": fields.get("offer_at"),
                    "rejected_at": fields.get("rejected_at"),
                    "next_step": fields.get("next_step"),
                    "next_step_due_at": fields.get("next_step_due_at"),
                    "interview_stage": fields.get("interview_stage"),
                },
            )
            for field, value in lifecycle.items():
                fields[field] = value
        if append_only_snapshot:
            for field in (
                "applied_at",
                "next_step",
                "notes",
                "offer_at",
                "rejected_at",
                "next_step_due_at",
                "interview_stage",
            ):
                fields[field] = None
        return lifecycle, append_only_snapshot, snapshot_applied_at

    @staticmethod
    def _build_job_update_sql(
        fields: dict[str, Any],
        append_only_snapshot: bool,
    ) -> tuple[list[str], list[Any], bool]:
        """Build the UPDATE column/value lists from normalized fields."""
        sets = ["updated_at = ?"]
        values: list[Any] = [time.time()]
        if fields.get("title") is not None:
            sets.append("title = ?")
            values.append(fields["title"].strip() or "未命名岗位")
        if fields.get("jd_text") is not None:
            sets.append("jd_text = ?")
            values.append(fields["jd_text"].strip())
        for column, key in (
            ("company", "company"),
            ("location", "location"),
            ("salary_min", "salary_min"),
            ("salary_max", "salary_max"),
            ("salary_currency", "salary_currency"),
            ("source_type", "source_type"),
            ("source_url", "source_url"),
            ("job_function", "job_function"),
            ("seniority", "seniority"),
        ):
            if fields.get(key) is not None:
                sets.append(f"{column} = ?")
                values.append(fields[key])
        if fields.get("tech_tags") is not None:
            sets.append("tech_tags = ?")
            values.append(
                json.dumps(
                    JobLibraryStore._normalize_tags(fields["tech_tags"]),
                    ensure_ascii=False,
                )
            )
        if fields.get("status") is not None and not append_only_snapshot:
            sets.append("status = ?")
            values.append(fields["status"])
        if fields.get("classification_pending") is not None:
            sets.append("classification_pending = ?")
            values.append(fields["classification_pending"])
        for column, key in (
            ("final_draft", "final_draft"),
            ("final_draft_updated_at", "final_draft_updated_at"),
            ("final_draft_version", "final_draft_version"),
            ("posting_date", "posting_date"),
        ):
            if fields.get(key) is not None:
                sets.append(f"{column} = ?")
                values.append(fields[key])
        for column, key in (
            ("applied_at", "applied_at"),
            ("next_step", "next_step"),
            ("notes", "notes"),
            ("offer_at", "offer_at"),
            ("rejected_at", "rejected_at"),
            ("next_step_due_at", "next_step_due_at"),
            ("interview_stage", "interview_stage"),
        ):
            value = fields.get(key)
            if value is not None:
                if value == "":
                    sets.append(f"{column} = NULL")
                else:
                    sets.append(f"{column} = ?")
                    values.append(value)
        if (
            (fields.get("status") is not None and not append_only_snapshot)
            or fields.get("next_step_due_at") is not None
            or fields.get("interview_stage") is not None
        ):
            sets.append("reminder_sent_at = NULL")
            sets.append("reminder_attempts = 0")
            sets.append("reminder_next_retry_at = NULL")
        for column, key in (
            ("refresh_enabled", "refresh_enabled"),
            ("last_refresh_at", "last_refresh_at"),
            ("refresh_status", "refresh_status"),
            ("match_stale", "match_stale"),
            ("match_score", "match_score"),
            ("match_reason", "match_reason"),
            ("match_updated_at", "match_updated_at"),
            ("alignment_status", "alignment_status"),
            ("model", "model"),
            ("prompt_version", "prompt_version"),
            ("generated_at", "generated_at"),
            ("workbench_job_id", "workbench_job_id"),
            ("workbench_resume_id", "workbench_resume_id"),
            ("tailor_granularity", "tailor_granularity"),
            ("tailor_focus", "tailor_focus"),
            ("custom_prompt", "custom_prompt"),
        ):
            if fields.get(key) is not None:
                sets.append(f"{column} = ?")
                values.append(fields[key])
        for column, key in (
            ("jd_profile_json", "jd_profile"),
            ("gap_report_json", "gap_report"),
            ("match_score_detail_json", "match_score_detail"),
            ("diffs_json", "diffs"),
            ("invalid_diffs_json", "invalid_diffs"),
            ("eval_score_json", "eval_score"),
        ):
            if fields.get(key) is not None:
                sets.append(f"{column} = ?")
                values.append(
                    json.dumps(fields[key], ensure_ascii=False)
                )
        if fields.get("draft") is not None:
            sets.append("draft = ?")
            values.append(fields["draft"])
        recompute_dedupe = (
            fields.get("jd_text") is not None
            or fields.get("source_type") is not None
            or fields.get("source_url") is not None
        )
        return sets, values, recompute_dedupe

    @staticmethod
    def _invalidate_match_cache(
        fields: dict[str, Any],
        sets: list[str],
    ) -> None:
        """Mark the cached match score stale when its inputs change."""
        if fields.get("match_stale") is not None:
            return
        touched = any(
            fields.get(key) is not None
            for key in ("jd_text", "job_function", "seniority", "tech_tags")
        )
        if touched:
            sets.append("match_stale = 1")

    def _maybe_write_application_snapshot(
        self,
        conn: sqlite3.Connection,
        tenant_id: str,
        job_id: str,
        fields: dict[str, Any],
        append_only_snapshot: bool,
        snapshot_applied_at: str | None,
    ) -> None:
        """Persist an immutable applied snapshot when the transition needs one."""
        should_snapshot = append_only_snapshot or (
            fields.get("status") is not None
            and canonical_status(fields["status"]) == "applied"
        )
        if not should_snapshot:
            return
        row = conn.execute(
            "SELECT final_draft, match_score, workbench_resume_id, applied_at "
            "FROM library_jobs WHERE job_id = ? AND tenant_id = ?",
            (job_id, tenant_id),
        ).fetchone()
        if row is None or not str(row["final_draft"] or "").strip():
            return
        self._insert_application_snapshot(
            conn,
            tenant_id,
            job_id,
            final_draft=row["final_draft"],
            match_score=row["match_score"],
            master_resume_id=row["workbench_resume_id"],
            applied_at=(
                snapshot_applied_at
                if append_only_snapshot
                else row["applied_at"] or time.strftime("%Y-%m-%d")
            ),
        )

    def update_job(
        self,
        tenant_id: str,
        job_id: str,
        title: str | None = None,
        jd_text: str | None = None,
        company: str | None = None,
        location: str | None = None,
        salary_min: float | None = None,
        salary_max: float | None = None,
        salary_currency: str | None = None,
        source_type: str | None = None,
        source_url: str | None = None,
        job_function: str | None = None,
        seniority: str | None = None,
        tech_tags: list[str] | None = None,
        status: str | None = None,
        classification_pending: int | None = None,
        final_draft: str | None = None,
        final_draft_updated_at: float | None = None,
        final_draft_version: int | None = None,
        posting_date: str | None = None,
        applied_at: str | None = None,
        next_step: str | None = None,
        notes: str | None = None,
        offer_at: str | None = None,
        rejected_at: str | None = None,
        next_step_due_at: str | None = None,
        interview_stage: str | None = None,
        refresh_enabled: int | None = None,
        last_refresh_at: float | None = None,
        refresh_status: str | None = None,
        match_stale: int | None = None,
        jd_profile: dict[str, Any] | None = None,
        gap_report: dict[str, Any] | None = None,
        match_score: float | None = None,
        match_score_detail: dict[str, Any] | None = None,
        match_reason: str | None = None,
        match_updated_at: float | None = None,
        alignment_status: str | None = None,
        diffs: list[dict[str, Any]] | None = None,
        invalid_diffs: list[dict[str, Any]] | None = None,
        draft: str | None = None,
        eval_score: dict[str, Any] | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
        generated_at: float | None = None,
        workbench_job_id: str | None = None,
        workbench_resume_id: str | None = None,
        tailor_granularity: str | None = None,
        tailor_focus: str | None = None,
        custom_prompt: str | None = None,
        allowed_job_functions: Sequence[str] | None = None,
        allowed_seniorities: Sequence[str] | None = None,
    ) -> Optional[dict[str, Any]]:
        """Update editable fields. None-valued fields are left unchanged.

        Timeline fields (``applied_at``, ``next_step``, ``notes``,
        ``offer_at``, ``rejected_at``, ``next_step_due_at``,
        ``interview_stage``) follow the clear-on-empty contract: an empty
        string clears the stored value to NULL (U10), while None leaves it
        untouched.
        """
        fields: dict[str, Any] = {
            "title": title,
            "jd_text": jd_text,
            "company": company,
            "location": location,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": salary_currency,
            "source_type": source_type,
            "source_url": source_url,
            "job_function": job_function,
            "seniority": seniority,
            "tech_tags": tech_tags,
            "status": status,
            "classification_pending": classification_pending,
            "final_draft": final_draft,
            "final_draft_updated_at": final_draft_updated_at,
            "final_draft_version": final_draft_version,
            "posting_date": posting_date,
            "applied_at": applied_at,
            "next_step": next_step,
            "notes": notes,
            "offer_at": offer_at,
            "rejected_at": rejected_at,
            "next_step_due_at": next_step_due_at,
            "interview_stage": interview_stage,
            "refresh_enabled": refresh_enabled,
            "last_refresh_at": last_refresh_at,
            "refresh_status": refresh_status,
            "match_stale": match_stale,
            "jd_profile": jd_profile,
            "gap_report": gap_report,
            "match_score": match_score,
            "match_score_detail": match_score_detail,
            "match_reason": match_reason,
            "match_updated_at": match_updated_at,
            "alignment_status": alignment_status,
            "diffs": diffs,
            "invalid_diffs": invalid_diffs,
            "draft": draft,
            "eval_score": eval_score,
            "model": model,
            "prompt_version": prompt_version,
            "generated_at": generated_at,
            "workbench_job_id": workbench_job_id,
            "workbench_resume_id": workbench_resume_id,
            "tailor_granularity": tailor_granularity,
            "tailor_focus": tailor_focus,
            "custom_prompt": custom_prompt,
            "allowed_job_functions": allowed_job_functions,
            "allowed_seniorities": allowed_seniorities,
        }
        fields = self._normalize_job_update_fields(fields)
        if fields.get("status") is not None:
            current = self.get_job(tenant_id, job_id)
            if current is None:
                return None
            _, append_only_snapshot, snapshot_applied_at = (
                self._apply_status_lifecycle(current, fields)
            )
        else:
            append_only_snapshot = False
            snapshot_applied_at = None
        sets, values, recompute_dedupe = self._build_job_update_sql(
            fields, append_only_snapshot
        )
        self._invalidate_match_cache(fields, sets)
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                current = conn.execute(
                    "SELECT jd_text, source_type, source_url "
                    "FROM library_jobs "
                    "WHERE job_id = ? AND tenant_id = ?",
                    (job_id, tenant_id),
                ).fetchone()
                if current is None:
                    return None
                if recompute_dedupe:
                    effective_text = (
                        fields["jd_text"].strip()
                        if fields.get("jd_text") is not None
                        else current["jd_text"]
                    )
                    effective_type = (
                        fields["source_type"]
                        if fields.get("source_type") is not None
                        else current["source_type"]
                    )
                    effective_url = (
                        fields["source_url"]
                        if fields.get("source_url") is not None
                        else current["source_url"]
                    )
                    normalized_url = (
                        _normalize_source_url(effective_url)
                        if effective_type == "url" and effective_url
                        else ""
                    )
                    dedupe_key = (
                        "url:" + normalized_url
                        if normalized_url
                        else _text_dedupe_key(effective_text)
                    )
                    sets.append("dedupe_key = ?")
                    values.append(dedupe_key)
                values.extend([job_id, tenant_id])
                try:
                    cursor = conn.execute(
                        f"UPDATE library_jobs SET {', '.join(sets)} "
                        "WHERE job_id = ? AND tenant_id = ?",
                        values,
                    )
                except sqlite3.IntegrityError as exc:
                    raise UserStoreError(
                        "Duplicate job already exists"
                    ) from exc
                if cursor.rowcount == 0:
                    return None
                self._maybe_write_application_snapshot(
                    conn,
                    tenant_id,
                    job_id,
                    fields,
                    append_only_snapshot,
                    snapshot_applied_at,
                )
        return self.get_job(tenant_id, job_id)

'''

start = TEXT.index(OLD_START)
end = TEXT.index(OLD_END)
new_text = TEXT[:start] + HELPERS + TEXT[end:]
SRC.write_text(new_text, encoding="utf-8")
print("rewrote update_job", start, end)
