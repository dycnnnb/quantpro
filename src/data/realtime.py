"""
实时行情数据源
基于 easyquotation 封装，提供 A 股实时报价
"""

from typing import Dict, List, Optional, Union

import pandas as pd


class RealtimeQuote:
    """easyquotation 实时行情封装"""

    def __init__(self, source: str = "tencent"):
        import easyquotation
        self._source = source
        self._q = easyquotation.use(source)
        self._fallback_sources = ["sina", "qq"] if source == "tencent" else ["tencent"]

    def get_quote(self, codes: Union[str, List[str]]) -> Dict[str, dict]:
        """获取实时行情（带自动降级）"""
        if isinstance(codes, str):
            codes = [codes]
        codes = [c.split(".")[-1] if "." in c else c for c in codes]

        for source in [self._source] + self._fallback_sources:
            try:
                if source != self._source:
                    import easyquotation
                    q = easyquotation.use(source)
                else:
                    q = self._q
                data = q.real(codes)
                if data:
                    return data
            except Exception:
                continue
        return {}

    def get_price(self, code: str) -> Optional[float]:
        """快速获取单只股票当前价

        Args:
            code: 6 位纯数字股票代码

        Returns:
            当前价格，获取失败返回 None
        """
        quote = self.get_quote(code)
        code = code.split(".")[-1] if "." in code else code
        if code in quote:
            return quote[code].get("now")
        return None

    def get_prices(self, codes: List[str]) -> Dict[str, float]:
        """批量获取当前价格

        Args:
            codes: 股票代码列表

        Returns:
            {code: price}，仅包含成功获取的股票
        """
        quotes = self.get_quote(codes)
        prices = {}
        for code in codes:
            bare = code.split(".")[-1] if "." in code else code
            if bare in quotes:
                price = quotes[bare].get("now")
                if price:
                    prices[bare] = price
        return prices

    def get_snapshot(self, codes: List[str]) -> pd.DataFrame:
        """返回 DataFrame 格式的实时快照

        Args:
            codes: 股票代码列表

        Returns:
            DataFrame，index=code，columns 包含 now/open/high/low/close/volume/amount 等
        """
        quotes = self.get_quote(codes)
        if not quotes:
            return pd.DataFrame()

        records = []
        for code, q in quotes.items():
            records.append({
                "code": code,
                "name": q.get("name", ""),
                "now": q.get("now", 0),
                "open": q.get("open", 0),
                "high": q.get("high", 0),
                "low": q.get("low", 0),
                "close": q.get("close", 0),
                "volume": q.get("volume", 0),
                "amount": q.get("成交额(元)", 0),
                "turnover": q.get("turnover", 0),
                "PE": q.get("PE", 0),
                "PB": q.get("PB", 0),
                "datetime": q.get("datetime"),
            })
        df = pd.DataFrame(records).set_index("code")
        return df
