from __future__ import annotations

from mosp.api.routing import Router

from app.api.routes import admin, diagrams, me, system

router = Router()

router.include_router(system.router, tags=["system"])
router.include_router(me.router, tags=["me"])
# Optional areas (public diagrams, AI generation, Google Drive export) are
# gated route by route in diagrams.py with require_feature.
router.include_router(diagrams.router, tags=["diagrams"])
router.include_router(admin.router, tags=["admin"])
