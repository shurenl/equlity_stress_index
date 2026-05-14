from __future__ import annotations

import ast
import os

import pandas as pd

from src.fetchers.base import BaseFetcher, Ticker


class FREDFetcher(BaseFetcher):
    """FRED data fetcher using the FRED_API_KEY environment variable."""

    source = "fred"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("FRED_API_KEY")
        if not self.api_key:
            raise RuntimeError("FRED_API_KEY is required for FRED data. Set it as an environment variable.")

        from fredapi import Fred

        self.client = Fred(api_key=self.api_key)

    def fetch(self, ticker: Ticker, start: str, end: str) -> pd.DataFrame:
        if isinstance(ticker, list):
            frames = [self._fetch_one(item, start, end) for item in ticker]
            data = pd.concat(frames, axis=1)
        elif self._is_compute_expression(ticker):
            data = self._fetch_compute(ticker, start, end)
        else:
            data = self._fetch_one(ticker, start, end)

        return self.to_business_frame(data, start, end)

    def _fetch_one(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        series = self.client.get_series(ticker, observation_start=start, observation_end=end)
        series.name = ticker
        return series.to_frame()

    @staticmethod
    def _is_compute_expression(ticker: str) -> bool:
        return any(operator in ticker for operator in [" + ", " - ", " * ", " / ", "(", ")"])

    def _fetch_compute(self, expression: str, start: str, end: str) -> pd.DataFrame:
        tickers = sorted(self._expression_tickers(expression))
        if not tickers:
            raise ValueError(f"No FRED tickers found in compute expression: {expression}")

        series_map = {ticker: self._fetch_one(ticker, start, end).iloc[:, 0] for ticker in tickers}
        computed = self._eval_expression(expression, series_map)
        computed.name = expression
        return computed.to_frame()

    @classmethod
    def _expression_tickers(cls, expression: str) -> set[str]:
        tree = ast.parse(expression, mode="eval")
        cls._validate_expression_node(tree)
        return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}

    @classmethod
    def _validate_expression_node(cls, node: ast.AST) -> None:
        allowed_binary_ops = (ast.Add, ast.Sub, ast.Mult, ast.Div)
        allowed_nodes = (ast.Expression, ast.BinOp, ast.Name, ast.Load, ast.Constant)
        for child in ast.walk(node):
            if isinstance(child, ast.BinOp) and not isinstance(child.op, allowed_binary_ops):
                raise ValueError(f"Unsupported operator in FRED compute expression: {ast.dump(child.op)}")
            if not isinstance(child, (*allowed_nodes, *allowed_binary_ops)):
                raise ValueError(f"Unsupported syntax in FRED compute expression: {ast.dump(child)}")
            if isinstance(child, ast.Constant) and not isinstance(child.value, (int, float)):
                raise ValueError("Only numeric constants are allowed in FRED compute expressions")

    @classmethod
    def _eval_expression(cls, expression: str, series_map: dict[str, pd.Series]) -> pd.Series:
        tree = ast.parse(expression, mode="eval")
        cls._validate_expression_node(tree)
        return cls._eval_node(tree.body, series_map)

    @classmethod
    def _eval_node(cls, node: ast.AST, series_map: dict[str, pd.Series]) -> pd.Series | float:
        if isinstance(node, ast.Name):
            if node.id not in series_map:
                raise ValueError(f"Unknown FRED ticker in compute expression: {node.id}")
            return series_map[node.id]
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp):
            left = cls._eval_node(node.left, series_map)
            right = cls._eval_node(node.right, series_map)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
        raise ValueError(f"Unsupported FRED compute expression node: {ast.dump(node)}")
