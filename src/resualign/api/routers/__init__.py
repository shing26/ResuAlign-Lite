from fastapi import APIRouter

from . import (
    analyze,
    applications,
    auth,
    health,
    jobs,
    kanban,
    resumes,
    settings,
    workspace,
)

router = APIRouter()
router.include_router(health.router)
router.include_router(analyze.router)
router.include_router(jobs.router)
router.include_router(kanban.router)
router.include_router(auth.router)
router.include_router(resumes.router)
router.include_router(applications.router)
router.include_router(settings.router)
router.include_router(workspace.router)
