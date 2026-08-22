from fastapi import APIRouter

from . import (
    analyze,
    applications,
    auth,
    blockers,
    fetch,
    health,
    jobs,
    kanban,
    nodes,
    optimize,
    refresh,
    reminders,
    resumes,
    rules,
    settings,
    workspace,
)

router = APIRouter()
router.include_router(health.router)
router.include_router(analyze.router)
router.include_router(jobs.router)
router.include_router(fetch.router)
router.include_router(rules.router)
router.include_router(blockers.router)
router.include_router(kanban.router)
router.include_router(auth.router)
router.include_router(resumes.router)
router.include_router(applications.router)
router.include_router(settings.router)
router.include_router(nodes.router)
router.include_router(optimize.router)
router.include_router(refresh.router)
router.include_router(reminders.router)
router.include_router(workspace.router)
