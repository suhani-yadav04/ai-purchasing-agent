"""Ensures tests never touch the same SQLite file as the running dev server.
Must set the env var before anything imports app.db.database.
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_buyer_agent.db"
