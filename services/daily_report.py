"""
Daily report state machine for operator-facing pipeline summaries.

This converts a single run summary dict into one mutually exclusive state so
"no alerts" is no longer the default fallback when the pipeline had no usable
input or when required stages failed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DailyReportState(str, Enum):
    ALERTS_FOUND = "alerts_found"
    NO_ALERTS_BUT_DATA_PROCESSED = "no_alerts_but_data_processed"
    NO_RECENT_DATA = "no_recent_data"
    PIPELINE_FAILURE = "pipeline_failure"
    PARTIAL_RUN_STALE_RESULTS = "partial_run_stale_results"


@dataclass
class DailyReport:
    state: DailyReportState
    title: str
    status_line: str
    summary_lines: list[str] = field(default_factory=list)
    failed_stages: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


def _required_source_failed(summary: dict[str, Any]) -> bool:
    required = summary.get("collection", {}).get("required_sources", {})
    return any(not source.get("success", False) for source in required.values())


def _optional_source_failed(summary: dict[str, Any]) -> bool:
    optional = summary.get("collection", {}).get("optional_sources", {})
    return any(not source.get("success", True) for source in optional.values())


def _failed_stages(summary: dict[str, Any]) -> list[str]:
    failed: list[str] = []

    collection = summary.get("collection", {})
    extraction = summary.get("extraction", {})
    scoring = summary.get("scoring", {})
    alerting = summary.get("alerting", {})

    if not collection.get("success", False):
        failed.append("Collection")
    for name, result in collection.get("required_sources", {}).items():
        if not result.get("success", False):
            failed.append(f"{name.title()} collection")

    if not extraction.get("success", False):
        failed.append("Extraction")
    if not scoring.get("success", False):
        failed.append("Scoring")
    if not alerting.get("success", True):
        failed.append("Alerting")

    # Preserve order while removing duplicates
    seen: set[str] = set()
    ordered: list[str] = []
    for item in failed:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _fresh_data_processed(summary: dict[str, Any]) -> bool:
    collection = summary.get("collection", {})
    extraction = summary.get("extraction", {})
    scoring = summary.get("scoring", {})

    scraped_messages = int(collection.get("scraped_messages_persisted", 0) or 0)
    messages_processed = int(extraction.get("messages_processed", scraped_messages) or 0)
    entities_extracted = int(extraction.get("entities_extracted", 0) or 0)

    return (
        scraped_messages > 0
        and not _required_source_failed(summary)
        and collection.get("success", False)
        and extraction.get("success", False)
        and scoring.get("success", False)
        and messages_processed > 0
        and entities_extracted > 0
    )


def determine_daily_report_state(
    summary: dict[str, Any],
    *,
    allow_partial_run_state: bool = False,
) -> DailyReportState:
    failed_required = _required_source_failed(summary)
    extraction_failed = not summary.get("extraction", {}).get("success", False)
    scoring_failed = not summary.get("scoring", {}).get("success", False)
    alerts_triggered = int(summary.get("scoring", {}).get("alerts_triggered", 0) or 0)
    alerts_sent = int(summary.get("alerting", {}).get("alerts_sent", 0) or 0)

    if failed_required or extraction_failed or scoring_failed:
        if allow_partial_run_state and failed_required and not extraction_failed and not scoring_failed:
            return DailyReportState.PARTIAL_RUN_STALE_RESULTS
        return DailyReportState.PIPELINE_FAILURE

    if alerts_triggered > 0 or alerts_sent > 0:
        return DailyReportState.ALERTS_FOUND

    if _fresh_data_processed(summary):
        return DailyReportState.NO_ALERTS_BUT_DATA_PROCESSED

    return DailyReportState.NO_RECENT_DATA


def build_daily_report(
    summary: dict[str, Any],
    *,
    report_date: str,
    allow_partial_run_state: bool = False,
) -> DailyReport:
    state = determine_daily_report_state(summary, allow_partial_run_state=allow_partial_run_state)
    failed = _failed_stages(summary)

    collection = summary.get("collection", {})
    extraction = summary.get("extraction", {})
    scoring = summary.get("scoring", {})
    alerting = summary.get("alerting", {})

    summary_lines = [
        f"• Raw messages persisted: {int(collection.get('scraped_messages_persisted', 0) or 0)}",
        f"• Messages extracted: {int(extraction.get('messages_processed', 0) or 0)}",
        f"• Entities extracted: {int(extraction.get('entities_extracted', 0) or 0)}",
        f"• Campaigns scored: {int(scoring.get('campaigns_scored', 0) or 0)}",
        f"• Alerts triggered: {int(scoring.get('alerts_triggered', 0) or 0)}",
        f"• Alerts sent: {int(alerting.get('alerts_sent', 0) or 0)}",
    ]

    if state == DailyReportState.ALERTS_FOUND:
        return DailyReport(
            state=state,
            title="📊 FraudMVP Daily Report",
            status_line=f"📅 Date: {report_date}\n✅ Status: Alert-level campaigns were detected",
            summary_lines=summary_lines,
        )

    if state == DailyReportState.NO_ALERTS_BUT_DATA_PROCESSED:
        return DailyReport(
            state=state,
            title="📊 FraudMVP Daily Report",
            status_line=(
                f"📅 Date: {report_date}\n"
                "✅ Status: Scan completed, no alert-level campaigns found"
            ),
            summary_lines=summary_lines,
        )

    if state == DailyReportState.PIPELINE_FAILURE:
        return DailyReport(
            state=state,
            title="📊 FraudMVP Daily Report",
            status_line=(
                f"📅 Date: {report_date}\n"
                "❌ Status: Pipeline failure"
            ),
            summary_lines=summary_lines,
            failed_stages=failed,
            recommendations=[
                "Inspect pipeline logs.",
                "Rerun failed stages after fixing the issue.",
            ],
        )

    if state == DailyReportState.PARTIAL_RUN_STALE_RESULTS:
        return DailyReport(
            state=state,
            title="📊 FraudMVP Daily Report",
            status_line=(
                f"📅 Date: {report_date}\n"
                "⚠️ Status: Partial run completed"
            ),
            summary_lines=summary_lines,
            failed_stages=failed,
            recommendations=[
                "Check required collector health.",
                "Results may under-report active campaigns.",
            ],
        )

    enabled_collectors = ", ".join(
        [name.title() for name in collection.get("required_sources", {}).keys()]
        + [name.title() for name in collection.get("optional_sources", {}).keys() if collection["optional_sources"][name].get("enabled", True)]
    )
    return DailyReport(
        state=DailyReportState.NO_RECENT_DATA,
        title="📊 FraudMVP Daily Report",
        status_line=(
            f"📅 Date: {report_date}\n"
            "⚠️ Status: No recent source data"
        ),
        summary_lines=summary_lines + [f"• Enabled collectors: {enabled_collectors or 'unknown'}"],
        recommendations=[
            "Check collector health and source connectivity.",
        ],
    )


def format_daily_report(report: DailyReport) -> str:
    lines = [
        report.title,
        "",
        report.status_line,
        "",
    ]

    if report.state == DailyReportState.NO_ALERTS_BUT_DATA_PROCESSED:
        lines.extend(
            [
                "Sources were collected and processed successfully.",
                "No campaigns crossed the configured alert threshold in this run.",
                "",
            ]
        )
    elif report.state == DailyReportState.NO_RECENT_DATA:
        lines.extend(
            [
                "The pipeline ran, but no fresh source messages were collected",
                "in the expected time window.",
                'This is not the same as "no scams detected".',
                "",
            ]
        )
    elif report.state == DailyReportState.PIPELINE_FAILURE:
        lines.extend(
            [
                "The pipeline did not complete successfully. Detection results",
                "may be incomplete or stale.",
                "",
            ]
        )
    elif report.state == DailyReportState.PARTIAL_RUN_STALE_RESULTS:
        lines.extend(
            [
                "Scoring completed, but one or more required sources were unavailable.",
                "Results may under-report active campaigns.",
                "",
            ]
        )

    if report.failed_stages:
        lines.append("Failed stages:")
        lines.extend(report.failed_stages)
        lines.append("")

    lines.append("Summary:")
    lines.extend(report.summary_lines)

    if report.recommendations:
        lines.append("")
        lines.append("Recommendation:")
        lines.extend(report.recommendations)

    return "\n".join(lines)
