"""Bounded acquisition scheduling and safe, structured stage timings."""

import logging
from concurrent.futures import FIRST_COMPLETED, wait
from contextlib import contextmanager
from time import perf_counter

from sports_analyst.analysis.research.state import ContextPool as ThreadPoolExecutor

logger = logging.getLogger(__name__)


@contextmanager
def timed_stage(stage, **scope):
    started = perf_counter()
    status = "failed"
    try:
        yield
        status = "complete"
    finally:
        logger.info("dataset_stage stage=%s status=%s duration_ms=%d scope=%s",
                    stage, status, round((perf_counter() - started) * 1000), scope)


def bounded_results(function, items, workers):
    """Yield (item, future), keeping at most workers tasks outstanding.

    Refill before yielding so normalization/storage does not idle network workers.
    Callers inspect futures individually to retain partial successes on failure.
    """
    iterator = iter(items)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dataset-fetch") as pool:
        pending = {}

        def submit_next():
            try:
                item = next(iterator)
            except StopIteration:
                return
            pending[pool.submit(function, item)] = item

        for _ in range(workers):
            submit_next()
        try:
            while pending:
                finished, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in finished:
                    item = pending.pop(future)
                    submit_next()
                    yield item, future
        finally:
            for future in pending:
                future.cancel()
