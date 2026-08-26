from __future__ import annotations

import argparse
import logging
import os
import socket
import time
from collections.abc import Callable
from contextlib import closing

from sqlalchemy.orm import Session

from app import db as db_module
from app.webhook_worker import process_provider_webhook_batch

logger = logging.getLogger("moneybee.webhook_worker")


def resolve_session_factory() -> Callable[[], Session]:
    for name in ("SessionLocal", "SessionFactory", "session_factory"):
        factory = getattr(db_module, name, None)
        if callable(factory):
            return factory
    raise RuntimeError("MoneyBee database session factory is not available")


def run_once(*, worker_id: str, batch_size: int) -> int:
    session_factory = resolve_session_factory()
    with closing(session_factory()) as db:
        result = process_provider_webhook_batch(
            db,
            worker_id=worker_id,
            limit=batch_size,
        )
    logger.info(
        "provider webhook batch claimed=%s processed=%s retried=%s dead_lettered=%s",
        result.claimed,
        result.processed,
        result.retried,
        result.dead_lettered,
    )
    return result.claimed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Process authenticated MoneyBee provider webhook receipts."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one available batch and exit.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.getenv("WEBHOOK_WORKER_BATCH_SIZE", "50")),
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=float(os.getenv("WEBHOOK_WORKER_POLL_SECONDS", "5")),
    )
    parser.add_argument(
        "--worker-id",
        default=os.getenv(
            "WEBHOOK_WORKER_ID", f"{socket.gethostname()}-{os.getpid()}"
        ),
    )
    return parser


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = build_parser().parse_args()
    if args.batch_size < 1 or args.batch_size > 500:
        raise SystemExit("--batch-size must be between 1 and 500")
    if args.poll_seconds < 0.25:
        raise SystemExit("--poll-seconds must be at least 0.25")

    if args.once:
        run_once(worker_id=args.worker_id, batch_size=args.batch_size)
        return 0

    while True:
        claimed = run_once(worker_id=args.worker_id, batch_size=args.batch_size)
        if claimed == 0:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
