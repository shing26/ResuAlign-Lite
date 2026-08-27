"""Automation rule endpoints for the Sprint 3 fetch pipeline."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

import resualign.api as api_module

from ..deps import get_current_user
from ..schemas import AutomationRuleCreateRequest, AutomationRuleUpdateRequest

router = APIRouter()


@router.get("/api/automation/rules")
def list_automation_rules(
    user: dict[str, Any] = Depends(get_current_user),
):
    """Return the tenant's automation rules in creation order."""
    return api_module._fetcher.list_rules(user["user_id"])


@router.post("/api/automation/rules", status_code=201)
def create_automation_rule(
    req: AutomationRuleCreateRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Create one automation rule for the fetch pipeline."""
    try:
        return api_module._fetcher.create_rule(
            user["user_id"],
            req.rule_type,
            req.value,
            label=req.label,
            enabled=req.enabled,
        )
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/api/automation/rules/{rule_id}")
def update_automation_rule(
    rule_id: str,
    req: AutomationRuleUpdateRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Partially update one automation rule."""
    try:
        rule = api_module._fetcher.update_rule(
            user["user_id"],
            rule_id,
            value=req.value,
            label=req.label,
            enabled=req.enabled,
        )
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.delete("/api/automation/rules/{rule_id}", status_code=204)
def delete_automation_rule(
    rule_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Delete one automation rule."""
    if not api_module._fetcher.delete_rule(user["user_id"], rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    return None
