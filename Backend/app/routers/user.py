# Placeholder router — user management routes will be added here in a future step.
# Currently empty intentionally. The import in main.py is kept so this module is
# already wired up and ready to receive routes without touching main.py later.

from fastapi import APIRouter

router = APIRouter(
    prefix="/user",
    tags=["User"],
)
