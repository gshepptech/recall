import logging
import math
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DECAY_DAYS       = max(1, int(float(os.getenv('RECALL_DECAY_DAYS', '30'))))
FREQUENCY_WEIGHT = float(os.getenv('RECALL_FREQUENCY_WEIGHT', '0.1'))


def clamp_confidence(value) -> 'float | None':
    """Normalize a caller-supplied confidence to [0, 1]. Returns None when absent or
    unparseable so the write path can COALESCE to the column default / existing value."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, v))


def _confidence(mem: dict) -> float:
    """Stored confidence, treating only a missing value as full confidence (0 is a real score)."""
    value = mem.get("confidence_score")
    return 1.0 if value is None else float(value)


def _age_days(mem: dict) -> int:
    """Whole days since created_at; 0 (no decay) when the timestamp is missing or malformed."""
    raw = mem.get("created_at")
    if raw is None:
        return 0
    try:
        created = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        logger.warning(f'Failed to parse created_at timestamp {raw!r}')
        return 0
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - created).days)


def compute_score(mem: dict) -> float:
    """
    Absolute memory health score (0–1), independent of search query.
    Used for the UI decay gauge.
    """
    age_days = _age_days(mem)
    decay = max(0.05, math.exp(-0.693 * age_days / DECAY_DAYS))
    freq  = 1.0 + FREQUENCY_WEIGHT * math.log1p(mem.get("access_count") or 0)
    conf  = _confidence(mem)
    pin   = 1.5 if mem.get("pinned") else 1.0
    return min(1.0, decay * freq * conf * pin)


def score(raw: float, mem: dict) -> float:
    """
    Re-ranks search results using decay, frequency, and confidence.
    Applied post-search on top-K candidates only, not a full table scan.
    """
    age_days = _age_days(mem)
    decay = max(0.05, math.exp(-0.693 * age_days / DECAY_DAYS))
    freq  = 1.0 + FREQUENCY_WEIGHT * math.log1p(mem.get("access_count") or 0)
    conf  = _confidence(mem)
    return raw * decay * freq * conf
