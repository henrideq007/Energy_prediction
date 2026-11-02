"""Time-series splits — never shuffle, always train on the past and test on the future."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import pandas as pd


@dataclass
class Fold:
    name: str
    train_idx: pd.DatetimeIndex
    test_idx: pd.DatetimeIndex


def train_val_test(index: pd.DatetimeIndex, val_start: str, test_start: str) -> dict[str, pd.DatetimeIndex]:
    vs, ts = pd.Timestamp(val_start, tz="UTC"), pd.Timestamp(test_start, tz="UTC")
    return {
        "train": index[index < vs],
        "val": index[(index >= vs) & (index < ts)],
        "test": index[index >= ts],
    }


def walk_forward(index: pd.DatetimeIndex, first_test_month: str, n_folds: int, tz: str = "Europe/Brussels",
                 gap_hours: int = 0) -> Iterator[Fold]:
    """Expanding-window monthly folds: train on everything before month m, test on month m.

    Months are defined in local time so a fold = whole delivery days.
    """
    loc = index.tz_convert(tz)
    start = pd.Period(first_test_month, freq="M")
    for k in range(n_folds):
        m = start + k
        m_start = pd.Timestamp(m.start_time).tz_localize(tz)
        m_end = pd.Timestamp((m + 1).start_time).tz_localize(tz)
        test_mask = (loc >= m_start) & (loc < m_end)
        if not test_mask.any():
            break
        train_mask = loc < (m_start - pd.Timedelta(hours=gap_hours))
        yield Fold(name=str(m), train_idx=index[train_mask], test_idx=index[test_mask])
