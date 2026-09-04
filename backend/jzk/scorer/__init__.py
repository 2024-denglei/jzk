"""Versioned, database-free donor scoring service."""

from .app import app, create_app

__all__ = ["app", "create_app"]
