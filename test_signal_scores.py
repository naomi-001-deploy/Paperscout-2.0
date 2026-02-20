import ast
import unittest
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover
    pd = None


def _load_scoring_functions():
    if pd is None:
        raise unittest.SkipTest("pandas ist nicht installiert")
    source_path = Path(__file__).resolve().parents[1] / "paperscoutV2.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))

    wanted = {"_safe_parse_date", "add_signal_scores"}
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=selected, type_ignores=[])

    namespace = {
        "pd": pd,
        "datetime": datetime,
        "Optional": Optional,
    }
    exec(compile(module, filename=str(source_path), mode="exec"), namespace)
    return namespace["add_signal_scores"]


@unittest.skipIf(pd is None, "pandas ist nicht installiert")
class AddSignalScoresRegressionTest(unittest.TestCase):
    def test_same_day_dates_do_not_raise_zero_division(self):
        add_signal_scores = _load_scoring_functions()
        df = pd.DataFrame(
            {
                "title": ["A", "B"],
                "issued": ["2026-02-13", "2026-02-13"],
                "relevance_score": [60.0, 80.0],
            }
        )

        out = add_signal_scores(df.copy())

        self.assertEqual(out["days_ago"].tolist(), [0, 0])
        self.assertEqual(out["signal_score"].tolist(), [76.0, 88.0])

    def test_same_day_dates_without_relevance_score_remain_valid(self):
        add_signal_scores = _load_scoring_functions()
        df = pd.DataFrame(
            {
                "title": ["A", "B"],
                "issued": ["2026-02-13", "2026-02-13"],
            }
        )

        out = add_signal_scores(df.copy())

        self.assertEqual(out["days_ago"].tolist(), [0, 0])
        self.assertEqual(out["signal_score"].tolist(), [100.0, 100.0])


if __name__ == "__main__":
    unittest.main()
