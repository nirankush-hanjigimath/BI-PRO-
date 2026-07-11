"""
signal_engine/models.py
All dataclasses for the signal engine pipeline.
Immutable by convention — no stage mutates another stage's output.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Literal, Optional


@dataclass
class CandleData:
    symbol:        str
    timeframe:     str
    open:          float
    high:          float
    low:           float
    close:         float
    volume:        float
    close_time:    datetime
    candle_status: Literal["CLOSED", "FORMING"]


@dataclass
class RegimeState:
    timeframe:           str
    regime:              str   # TRENDING|RANGING|HIGH_VOLATILITY|LOW_VOL_SQUEEZE|UNDEFINED
    regime_age_candles:  int
    adx:                 float
    choppiness:          float
    bbwidth:             float
    bbwidth_percentile:  float
    confidence_modifier: int


@dataclass
class BTCMacro:
    classification:      str   # STRONGLY_BULLISH|BULLISH|NEUTRAL|BEARISH|STRONGLY_BEARISH
    ema50_slope:         float
    ema200_slope:        float
    rsi:                 float
    volume_zscore:       float
    confidence_modifier: int


@dataclass
class RelativeStrength:
    rs_pct:              float
    classification:      str   # LEADER|LAGGARD|NEUTRAL
    confidence_modifier: int
    correlation_cluster: Optional[str] = None


@dataclass
class FuturesData:
    blocked:                     bool
    oi_change_pct:               Optional[float] = None
    funding_rate:                Optional[float] = None
    ls_ratio:                    Optional[float] = None
    oi_signal:                   Optional[str]   = None
    funding_signal:              Optional[str]   = None
    ls_signal:                   Optional[str]   = None
    oi_confidence_modifier:      int = 0
    funding_confidence_modifier: int = 0


@dataclass
class SRLevels:
    resistance_levels:      List[float]
    support_levels:         List[float]
    nearest_resistance:     Optional[float]
    nearest_support:        Optional[float]
    room_to_resistance_pct: Optional[float]
    room_to_support_pct:    Optional[float]
    long_rejected:          bool = False
    short_rejected:         bool = False
    rejection_reason:       Optional[str] = None


@dataclass
class EntrySignal:
    pattern_name:       Optional[str]
    direction:          Optional[str]   # LONG|SHORT
    body_quality_score: float
    candle_status:      str             # CLOSED|FORMING
    is_valid:           bool
    rejection_reason:   Optional[str] = None
    is_doji:            bool = False
    is_spinning_top:    bool = False
    body_quality:       str = "NORMAL"


@dataclass
class ConfidenceScore:
    raw_score:                float
    modifiers_applied:        List[str]
    final_score:              float
    grade:                    str        # A+|A|B|C|REJECT
    position_size_multiplier: float
    layer_scores:             Dict[str, float]
    futures_blocked:          bool = False


@dataclass
class Signal:
    symbol:            str
    direction:         str       # LONG|SHORT
    timestamp:         datetime

    regime:            RegimeState
    btc_macro:         BTCMacro
    relative_strength: RelativeStrength
    futures:           FuturesData
    sr:                SRLevels
    entry:             EntrySignal
    confidence:        ConfidenceScore

    entry_price:       float
    stop_loss:         float
    target1:           float
    target2:           float
    rr_ratio:          float
    position_size_pct: float
    invalidation_price:float

    narrative:         str
    risks:             str

    tags: List[str] = field(default_factory=list)
