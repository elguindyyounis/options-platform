"""The scan universe, grouped by sector, so the dashboard can draw a sector heat map and the lanes can stop one
sector from dominating. A fixed hand-picked list of liquid, optionable US names and funds, from mega-caps down
through mid-caps. It is deliberately not "the whole market": free data cannot scan every chain."""
from __future__ import annotations

SECTORS: dict[str, tuple[str, ...]] = {
    "Broad index funds": ("SPY", "QQQ", "IWM", "DIA", "EEM", "EFA"),
    "Rates and commodity funds": ("TLT", "HYG", "GLD", "SLV", "USO", "UNG"),
    "Sector funds": ("XLF", "XLE", "XLK", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XBI", "SMH", "KRE", "ARKK"),
    "Mega-cap tech": ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "NFLX", "ORCL"),
    "Semiconductors": ("AMD", "INTC", "QCOM", "MU", "ARM", "SMCI", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "MRVL", "ON", "TXN", "MPWR"),
    "Software and internet": ("CRM", "ADBE", "NOW", "INTU", "SHOP", "UBER", "SNOW", "CRWD", "PANW", "PLTR", "DDOG", "NET", "ZS", "MDB",
                              "TTD", "ABNB", "DASH", "PINS", "SNAP", "RBLX", "U", "ROKU", "TEAM", "WDAY", "FTNT", "OKTA"),
    "Fintech and crypto": ("COIN", "MSTR", "HOOD", "SOFI", "AFRM", "UPST", "PYPL", "MARA", "RIOT", "CLSK"),
    "Banks and finance": ("JPM", "BAC", "WFC", "GS", "MS", "C", "V", "MA", "SCHW", "BLK", "AXP", "USB"),
    "Healthcare": ("UNH", "LLY", "JNJ", "PFE", "MRK", "ABBV", "ISRG", "TMO", "ABT", "CVS", "HCA", "MDT"),
    "Biotech": ("MRNA", "BNTX", "VRTX", "REGN", "GILD", "AMGN", "BIIB", "ALNY", "CRSP", "NTLA", "BEAM", "SRPT", "IONS", "HIMS"),
    "Energy": ("XOM", "CVX", "COP", "OXY", "SLB", "HAL", "DVN", "EOG", "MPC", "VLO", "FANG"),
    "Industrials and defense": ("CAT", "GE", "BA", "DE", "HON", "LMT", "RTX", "UPS", "FDX", "UNP", "NOC", "GD"),
    "Materials and miners": ("FCX", "NEM", "ALB", "LIN", "NUE", "CLF"),
    "Consumer discretionary": ("HD", "NKE", "LOW", "TGT", "SBUX", "MCD", "LULU", "DECK", "CMG", "ETSY", "CVNA", "CELH", "RH", "DKNG"),
    "Consumer staples": ("WMT", "COST", "PG", "KO", "PEP", "MDLZ", "PM", "MO", "KR"),
    "Autos and EVs": ("F", "GM", "RIVN", "LCID", "NIO"),
    "Travel and leisure": ("DAL", "UAL", "AAL", "CCL", "RCL", "BKNG", "MAR", "DIS"),
    "Utilities and real estate": ("NEE", "DUK", "SO", "PLD", "AMT", "O"),
    "Telecom and media": ("T", "VZ", "TMUS", "CMCSA"),
}

UNIVERSE: tuple[str, ...] = tuple(s for names in SECTORS.values() for s in names)
SECTOR_OF: dict[str, str] = {s: sector for sector, names in SECTORS.items() for s in names}
