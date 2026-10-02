"""Relative timing: assert how cost scales or compares, never how many seconds it takes.

An absolute bound ("under 1.5 s") fails on a slow or coverage-traced machine and passes on a
fast one whatever the code does. A ratio of two timings taken in the same process, back to back,
survives both. Each helper times the fastest of several runs, so a busy moment slows one run and
rarely all of them.
"""

import gc
import time
from collections.abc import Callable
from typing import Any

# Seconds added to every allowance so a sub-millisecond baseline cannot fail on timer noise.
FLOOR = 0.02


def best_of(fn: Callable[[], Any], runs: int = 5) -> float:
    """Fastest of `runs` calls: load only ever adds time, so the minimum is the least-disturbed run.

    Timed in per-thread CPU time, which a busy neighbour cannot inflate by descheduling the
    thread (wall time can be).
    """
    best = float("inf")
    # A cyclic-GC pass scans every live container, so it would charge the bigger input for its
    # own size and not for the code under test.
    gc.collect()
    gc.disable()
    try:
        for _ in range(runs):
            started = time.thread_time()
            fn()
            best = min(best, time.thread_time() - started)
    finally:
        gc.enable()
    return best


def assert_grows_at_most(
    make: Callable[[int], Any],
    run: Callable[[Any], Any],
    n: int,
    ratio: float,
    *,
    scale: int = 2,
    runs: int = 5,
    floor: float = FLOOR,
) -> None:
    """`run(make(scale * n))` may cost at most `ratio` times `run(make(n))` plus FLOOR.

    Linear work gives about `scale`, quadratic about `scale ** 2`, work capped by a budget about
    1. Pick `ratio` between the shape that must pass and the shape that must fail, and `n` large
    enough that a capped test is already past its cap.
    """
    small, large = make(n), make(scale * n)  # built outside the timed calls
    t_small = best_of(lambda: run(small), runs)
    t_large = best_of(lambda: run(large), runs)
    assert t_large <= ratio * t_small + floor, (
        f"{scale}N took {t_large:.3f}s against {t_small:.3f}s for N: "
        f"x{t_large / max(t_small, 1e-9):.1f}, allowed x{ratio}"
    )


def assert_relative(
    run: Callable[[], Any], control: Callable[[], Any], factor: float, *, runs: int = 10
) -> None:
    """`run` may cost at most `factor` times `control`, a same-size call that takes the cheap path.

    For work whose cost per character is the constant under test, so doubling the input cannot
    show a regression. Both calls slow down together on a loaded or traced machine.

    The allowance is `max(factor * control, FLOOR)`, not their sum: FLOOR only rescues a control
    too fast to time (under FLOOR / factor), and never loosens the factor itself.
    """
    t_run, t_control = best_of(run, runs), best_of(control, runs)
    assert t_run <= max(factor * t_control, FLOOR), (
        f"x{t_run / max(t_control, 1e-9):.0f}, allowed x{factor}"
    )
