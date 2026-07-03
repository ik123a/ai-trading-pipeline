#!/usr/bin/env python3
"""Launcher script for Dashboard API - runs from correct directory"""
import os, sys
from pathlib import Path

# Ensure we run from the project root
project_dir = Path(__file__).resolve().parent.parent
os.chdir(project_dir)

# Import and run
from dashboard.dashboard_api import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
