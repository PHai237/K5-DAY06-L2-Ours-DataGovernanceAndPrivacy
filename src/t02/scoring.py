"""TEAM MEMBER 3 OWNS THIS FILE: T02 model / scoring.

Contract
--------
score_images(ctx, images) -> pandas.DataFrame containing EXACTLY ONE row for
EACH image in images.csv, including eval (without reading any GT).
Required: image_id (str), score (finite float, larger means more suspicious).
Recommended: pred_defect_type, pred_action (KEEP/RECAPTURE), reason.

Never train/tune on the eval split. The Leader owns src/pipeline.py;
please implement this file rather than editing src/pipeline.py.
"""
from __future__ import annotations

import pandas as pd

from ..common.context import RunContext


def score_images(ctx: RunContext, images: pd.DataFrame) -> pd.DataFrame:
    raise NotImplementedError(
        "T02 scoring belongs to member 3: implement src/t02/scoring.py::score_images(ctx, images). "
        "The review/override/decision module can already be tested independently."
    )
