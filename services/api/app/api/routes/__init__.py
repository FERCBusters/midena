from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import admin, auth, diagrams, me, mfa, system

router = APIRouter()

router.include_router(system.router, tags=["system"])
router.include_router(auth.router, tags=["auth"])
router.include_router(mfa.router, tags=["auth"])
router.include_router(me.router, tags=["me"])
# Optional areas (public diagrams, AI generation, Google Drive export) are
# gated route by route in diagrams.py with require_feature.
router.include_router(diagrams.router, tags=["diagrams"])
router.include_router(admin.router, tags=["admin"])
