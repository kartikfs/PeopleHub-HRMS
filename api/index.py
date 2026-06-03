"""
Vercel serverless entry point.
Adds /backend to sys.path so all relative imports in server.py work,
then exports the FastAPI app wrapped with Mangum for ASGI→Lambda.
"""
import sys
import os

# Make backend modules importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from server import app
from mangum import Mangum

# Vercel invokes this as a Lambda — Mangum bridges ASGI to Lambda's handler interface
handler = Mangum(app, lifespan="off")
