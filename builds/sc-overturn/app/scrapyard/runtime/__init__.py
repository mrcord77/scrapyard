"""Application runtime: settings, database init, lifecycle, and bootstrap.

These modules turn generated model+route code into a self-contained app that
boots with `uvicorn main:app` and no manual wiring. Not catalog parts — this is
runtime infrastructure the generated main.py imports.
"""
