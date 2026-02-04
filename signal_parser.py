import re
import hashlib
from typing import Any, Dict, Optional, List

NUM = r"([0-9]+(?:\.[0-9]+)?)"

# ============================================================
# AO TRADING FORMAT (with optional ** markdown bold)
# ============================================================
# Beispiel-Signal (echtes Format aus Discord):
# 🔴 **SHORT SIGNAL - ICNT/USDT**
# **Leverage:** 25x • **Trader:** haseeb1111
# 📊 Entry: `0.52100` ⏳ *Pending*
# 🎯 **TP1:** `0.51475` **→ NEXT**
# ⏳ **TP2:** `0.50850` *Pending*
# ⏳ **TP3:** `0.50016` *Pending*
# 🛡️ **Stop Loss:** `0.53000`
# ============================================================

# Symbol and Side: "🔴 **SHORT SIGNAL - ICNT/USDT**"
# Mit optionalen ** vor und nach dem Text
RE_SYMBOL_SIDE = re.compile(
    r"\*{0,2}(LONG|SHORT)\s+SIGNAL\s*[-–—]\s*([A-Z0-9]+)/([A-Z]+)\*{0,2}",
    re.I
)

# Entry: "📊 Entry: `0.52100`" (mit optionalen backticks und $)
RE_ENTRY = re.compile(
    r"Entry\s*:\s*`?\$?" + NUM + r"`?",
    re.I
)

# TP: verschiedene Formate mit optionalen ** und backticks:
# "🎯 **TP1:** `0.51475` **→ NEXT**"
# "⏳ **TP2:** `0.50850` *Pending*"
RE_TP = re.compile(
    r"\*{0,2}TP(\d+)\s*:\s*\*{0,2}\s*`?\$?" + NUM + r"`?",
    re.I
)

# DCA: "⏳ **DCA1:** `0.16590` *Pending*" (mit optionalen ** und backticks)
RE_DCA = re.compile(
    r"\*{0,2}DCA\s*#?\s*(\d+)\s*:\s*\*{0,2}\s*`?\$?" + NUM + r"`?",
    re.I
)

# Stop Loss: "🛡️ **Stop Loss:** `0.53000`" (mit optionalen ** und backticks)
RE_SL = re.compile(
    r"\*{0,2}Stop\s*Loss\s*:\s*\*{0,2}\s*`?\$?" + NUM + r"`?",
    re.I
)

# Leverage: "**Leverage:** 25x"
RE_LEVERAGE = re.compile(
    r"\*{0,2}Leverage\s*:\s*\*{0,2}\s*(\d+)x",
    re.I
)

# Trader/Caller: "**Trader:** haseeb1111"
RE_TRADER = re.compile(
    r"\*{0,2}(?:Trader|Caller)\s*:\s*\*{0,2}\s*(\w+)",
    re.I
)

# Status patterns to detect if trade is still valid for entry
RE_AWAITING = re.compile(r"AWAITING\s+ENTRY|Pending", re.I)
RE_CLOSED = re.compile(r"TRADE\s+CLOSED|CLOSED\s+AT\s+BREAKEVEN|TRADE\s+CANCELLED|STOPPED\s+OUT", re.I)

# TP HIT detection: "✅ TP1: 0.09796 HIT" or "✅ **TP1:** `0.09796` *HIT*"
RE_TP_HIT = re.compile(
    r"[✅☑️]\s*\*{0,2}TP(\d+)\s*:\s*\*{0,2}\s*`?\$?" + NUM + r"`?\s*(?:\*{0,2})?\s*HIT",
    re.I
)

# Entry triggered: "📊 Entry: 0.09875 ✅ Triggered"
RE_ENTRY_TRIGGERED = re.compile(
    r"Entry\s*:\s*`?\$?" + NUM + r"`?\s*[✅☑️]\s*Triggered",
    re.I
)


def parse_signal(text: str, quote: str = "USDT") -> Optional[Dict[str, Any]]:
    """
    Parse AO Trading signal format.

    Returns None if:
    - Not a NEW SIGNAL message
    - Trade is already CLOSED/CANCELLED
    - Cannot parse symbol/side or entry price
    """
    # We only want fresh "NEW SIGNAL" entries, not closed summaries
    if "NEW SIGNAL" not in text.upper():
        return None

    # Skip already closed/cancelled trades
    if RE_CLOSED.search(text):
        return None

    # Parse symbol and side
    ms = RE_SYMBOL_SIDE.search(text)
    if not ms:
        return None

    side_word = ms.group(1).upper()
    base = ms.group(2).upper()
    quote_from_signal = ms.group(3).upper()

    side = "sell" if side_word == "SHORT" else "buy"
    symbol = f"{base}{quote_from_signal}"

    # Parse entry/trigger price
    mtr = RE_ENTRY.search(text)
    if not mtr:
        return None
    trigger = float(mtr.group(1))

    # Parse TP prices
    tps: List[float] = []
    for m in RE_TP.finditer(text):
        idx = int(m.group(1))
        price = float(m.group(2))
        # Keep in order
        while len(tps) < idx:
            tps.append(0.0)
        tps[idx-1] = price
    tps = [p for p in tps if p > 0]

    # Parse DCA prices (only 1 or none in AO Trading)
    dcas: List[float] = []
    for m in RE_DCA.finditer(text):
        idx = int(m.group(1))
        price = float(m.group(2))
        while len(dcas) < idx:
            dcas.append(0.0)
        dcas[idx-1] = price
    dcas = [p for p in dcas if p > 0]

    # Parse Stop Loss
    sl = None
    msl = RE_SL.search(text)
    if msl:
        sl = float(msl.group(1))

    # Parse leverage (optional, for logging)
    leverage = None
    mlev = RE_LEVERAGE.search(text)
    if mlev:
        leverage = int(mlev.group(1))

    # Parse trader (optional, for logging)
    trader = None
    mtr2 = RE_TRADER.search(text)
    if mtr2:
        trader = mtr2.group(1)

    return {
        "base": base,
        "symbol": symbol,
        "side": side,          # buy / sell
        "trigger": trigger,
        "tp_prices": tps,
        "dca_prices": dcas,
        "sl_price": sl,
        "leverage": leverage,  # Optional: leverage from signal
        "trader": trader,      # Optional: trader name
        "raw": text,
    }


def parse_signal_update(text: str) -> Dict[str, Any]:
    """
    Parse signal for SL/TP/DCA updates.

    Unlike parse_signal(), this does NOT require "NEW SIGNAL" in text.
    Used for checking if an existing signal was updated with new SL/TP/DCA values.

    Returns dict with:
    - sl_price: float or None
    - tp_prices: list of TP prices
    - dca_prices: list of DCA prices
    - tps_hit: list of TP indices that are HIT (e.g., [1] means TP1 is HIT)
    - entry_triggered: bool - whether entry was triggered
    - is_closed: bool - whether trade is closed/stopped out
    """
    result = {
        "sl_price": None,
        "tp_prices": [],
        "dca_prices": [],
        "tps_hit": [],
        "entry_triggered": False,
        "is_closed": False,
    }

    # Check if trade is closed/stopped out
    if RE_CLOSED.search(text):
        result["is_closed"] = True

    # Check if entry was triggered
    if RE_ENTRY_TRIGGERED.search(text):
        result["entry_triggered"] = True

    # Parse Stop Loss
    msl = RE_SL.search(text)
    if msl:
        result["sl_price"] = float(msl.group(1))

    # Parse TP prices
    tps: List[float] = []
    for m in RE_TP.finditer(text):
        idx = int(m.group(1))
        price = float(m.group(2))
        while len(tps) < idx:
            tps.append(0.0)
        tps[idx-1] = price
    result["tp_prices"] = [p for p in tps if p > 0]

    # Parse which TPs are HIT
    tps_hit: List[int] = []
    for m in RE_TP_HIT.finditer(text):
        idx = int(m.group(1))
        if idx not in tps_hit:
            tps_hit.append(idx)
    result["tps_hit"] = sorted(tps_hit)

    # Parse DCA prices
    dcas: List[float] = []
    for m in RE_DCA.finditer(text):
        idx = int(m.group(1))
        price = float(m.group(2))
        while len(dcas) < idx:
            dcas.append(0.0)
        dcas[idx-1] = price
    result["dca_prices"] = [p for p in dcas if p > 0]

    return result


def signal_hash(sig: Dict[str, Any]) -> str:
    """Generate unique hash for signal deduplication."""
    core = f"{sig.get('symbol')}|{sig.get('side')}|{sig.get('trigger')}|{sig.get('tp_prices')}|{sig.get('dca_prices')}"
    return hashlib.md5(core.encode("utf-8")).hexdigest()
