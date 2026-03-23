"""
Vercel serverless entry point for the Pecan API.
Wraps the FastAPI ASGI app via Mangum (AWS Lambda / Vercel adapter).
"""
import os
import sys

# Make project root importable from within the api/ subdirectory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Initialise DB and seed demo alumni on cold start
try:
    from tools.database import init_database
    init_database()
    from tools.seed_data import generate_alumni
    generate_alumni(250)
except Exception:
    pass

import importlib.util as _ilu

_spec = _ilu.spec_from_file_location(
    "pecan_api",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api.py"),
)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
app = _mod.app  # noqa: E402
from mangum import Mangum  # noqa: E402

handler = Mangum(app, lifespan="off")
