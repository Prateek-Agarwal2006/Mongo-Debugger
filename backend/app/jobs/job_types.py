from __future__ import annotations

JOB_TYPE_MONGO_FTDC = "mongo_ftdc"
JOB_TYPE_HATCHET = "hatchet"
DEFAULT_JOB_TYPE = JOB_TYPE_MONGO_FTDC


def normalize_job_type(value: str | None) -> str:
    if value in {JOB_TYPE_MONGO_FTDC, JOB_TYPE_HATCHET}:
        return value
    return DEFAULT_JOB_TYPE
