"""BigQuery execution helpers for the All of Us Researcher Workbench.

The workbench injects ``WORKSPACE_CDR`` (the versioned CDR BigQuery dataset) and
ambient GCP credentials. Nothing here runs outside that environment.
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

try:  # google-cloud-bigquery is only present inside the workbench
    from google.cloud import bigquery
except Exception:  # pragma: no cover - import guard for local linting/editing
    bigquery = None  # type: ignore


class Runner:
    """Thin wrapper over a ``bigquery.Client`` bound to the CDR dataset.

    Parameters
    ----------
    dataset:
        Fully-qualified CDR dataset (``project.dataset``). Defaults to the
        ``WORKSPACE_CDR`` environment variable set by the workbench.
    client:
        An existing ``bigquery.Client``. One is created if omitted.
    """

    def __init__(self, dataset: str | None = None, client: Any | None = None):
        self.dataset = dataset or os.environ["WORKSPACE_CDR"]
        if client is not None:
            self.client = client
        else:
            if bigquery is None:
                raise RuntimeError(
                    "google-cloud-bigquery is unavailable; a Runner can only "
                    "execute inside the All of Us Researcher Workbench."
                )
            self.client = bigquery.Client()

    def df(self, sql: str) -> pd.DataFrame:
        """Execute ``sql`` and return the result as a DataFrame."""
        return self.client.query(sql).to_dataframe()

    def scalar(self, sql: str):
        """Return the first column of the first row of ``sql``'s result."""
        value = self.df(sql).iloc[0].iloc[0]
        return value.item() if hasattr(value, "item") else value

    def run(self, sql: str) -> None:
        """Execute ``sql`` for its side effects (DDL), discarding results."""
        self.client.query(sql).result()
