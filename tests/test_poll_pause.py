import asyncio
import time

from app.main import _pause


def test_a_shortened_interval_ends_a_running_pause_within_seconds():
    interval = [3600.0]

    async def scenario():
        async def shorten():
            await asyncio.sleep(0.05)
            interval[0] = 0.1  # e.g. changed in the UI while the loop sleeps

        started = time.monotonic()
        await asyncio.gather(_pause(lambda: interval[0]), shorten())
        return time.monotonic() - started

    assert asyncio.run(asyncio.wait_for(scenario(), timeout=10)) < 5.5  # not the hour it started with


def test_a_zero_or_negative_interval_does_not_wait():
    asyncio.run(asyncio.wait_for(_pause(lambda: 0.0), timeout=1))
