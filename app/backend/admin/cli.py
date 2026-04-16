"""Admin CLI — operator commands that sit alongside the server.

Currently supports:
- `clean-drafts` — remove drafts older than N days (retention policy).

Invoke with:  python -m app.backend.admin.cli <subcommand> [--flags]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone

from app.backend.core.config import get_settings
from app.backend.core.logging import configure_logging, get_logger
from app.backend.persistence.database import get_session_factory, init_db
from app.backend.persistence.repositories import DraftRepository

log = get_logger("admin.cli")


async def clean_drafts(*, days: int, dry_run: bool = False) -> dict:
    """Async entry point — returns a summary dict. Used by CLI and tests."""
    if not days or days <= 0:
        return {
            "deleted": 0,
            "reason": "DRAFT_RETENTION_DAYS is not set (0 disables cleanup).",
        }
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    await init_db()
    factory = get_session_factory()
    async with factory() as session:
        repo = DraftRepository(session)
        if dry_run:
            from sqlalchemy import func, select

            from app.backend.persistence.models import Draft

            stmt = select(func.count()).where(Draft.created_at < cutoff)
            count = int((await session.execute(stmt)).scalar_one())
            return {
                "dry_run": True,
                "would_delete": count,
                "cutoff": cutoff.isoformat(),
            }
        removed = await repo.delete_older_than(cutoff)
    log.info("admin.clean_drafts.done", removed=removed, cutoff=cutoff.isoformat())
    return {"deleted": removed, "cutoff": cutoff.isoformat()}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="admin", description="MailCraft admin")
    sub = parser.add_subparsers(dest="cmd", required=True)

    clean = sub.add_parser(
        "clean-drafts",
        help="Delete drafts older than --days (default: DRAFT_RETENTION_DAYS from settings)",
    )
    clean.add_argument("--days", type=int, default=None)
    clean.add_argument("--dry-run", action="store_true")

    return parser


async def _cmd_clean_drafts(args: argparse.Namespace) -> int:
    settings = get_settings()
    days = args.days if args.days is not None else settings.draft_retention_days
    result = await clean_drafts(days=days, dry_run=args.dry_run)
    print(json.dumps(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "clean-drafts":
        return asyncio.run(_cmd_clean_drafts(args))
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
