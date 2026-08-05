
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

import resualign.api as api_module

from ...config import clear_runtime_llm, set_runtime_llm
from ...settings_store import default_settings
from ..deps import get_current_user
from ..schemas import SettingsUpdateRequest

router = APIRouter()

@router.get('/api/settings')
def get_settings(user: dict[str, Any]=Depends(get_current_user)):
    """Return the current user's editable workbench settings."""
    return api_module._settings_store.get_settings(user['user_id'])

@router.put('/api/settings')
def update_settings(req: SettingsUpdateRequest, user: dict[str, Any]=Depends(get_current_user)):
    """Persist validated settings updates for the current user."""
    updates = {
        key: value
        for key, value in req.model_dump().items()
        if value is not None or key in ("llm_provider", "llm_model")
    }
    try:
        saved = api_module._settings_store.update_settings(
            user['user_id'], updates
        )
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if "llm_provider" in updates or "llm_model" in updates:
        set_runtime_llm(
            provider=saved.get("llm_provider"),
            model=saved.get("llm_model"),
        )
    return saved


@router.get('/api/settings/status')
def settings_status(user: dict[str, Any] = Depends(get_current_user)):
    """Return runtime status so the settings page is not just raw forms."""
    config = api_module.build_config()
    return {
        "api_key_configured": bool(config.api_key),
        "provider": config.provider,
        "model": config.model,
        "personal_mode": api_module._PERSONAL_MODE,
        "resume_count": len(
            api_module._resumes.list_master_resumes(user["user_id"])
        ),
        "job_count": len(
            api_module._jobs.list_jobs(user["user_id"], limit=500)
        ),
        "application_count": len(
            api_module._applications.list_applications(user["user_id"])
        ),
    }


@router.post('/api/settings/reset')
def reset_settings(user: dict[str, Any] = Depends(get_current_user)):
    """Restore the built-in weights, vocabulary, and salary reference."""
    api_module._settings_store.update_settings(user["user_id"], default_settings())
    clear_runtime_llm()
    return api_module._settings_store.get_settings(user["user_id"])

