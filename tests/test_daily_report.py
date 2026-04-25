from __future__ import annotations

from services.daily_report import (
    DailyReportState,
    build_daily_report,
    determine_daily_report_state,
    format_daily_report,
)


def test_daily_report_no_alerts_but_data_processed_state():
    summary = {
        "collection": {
            "success": True,
            "required_sources": {
                "telegram": {"success": True, "messages": 72},
                "rss": {"success": True, "messages": 41},
            },
            "optional_sources": {},
            "scraped_messages_persisted": 148,
        },
        "extraction": {
            "success": True,
            "messages_processed": 132,
            "entities_extracted": 417,
        },
        "scoring": {
            "success": True,
            "campaigns_scored": 6,
            "alerts_triggered": 0,
        },
        "alerting": {
            "success": True,
            "alerts_sent": 0,
        },
    }

    report = build_daily_report(summary, report_date="15/04/2026")

    assert report.state == DailyReportState.NO_ALERTS_BUT_DATA_PROCESSED
    assert "Scan completed, no alert-level campaigns found" in format_daily_report(report)


def test_daily_report_no_recent_data_state():
    summary = {
        "collection": {
            "success": True,
            "required_sources": {
                "telegram": {"success": True, "messages": 0},
                "rss": {"success": True, "messages": 0},
            },
            "optional_sources": {},
            "scraped_messages_persisted": 0,
        },
        "extraction": {
            "success": True,
            "messages_processed": 0,
            "entities_extracted": 0,
        },
        "scoring": {
            "success": True,
            "campaigns_scored": 0,
            "alerts_triggered": 0,
        },
        "alerting": {
            "success": True,
            "alerts_sent": 0,
        },
    }

    state = determine_daily_report_state(summary)

    assert state == DailyReportState.NO_RECENT_DATA


def test_daily_report_pipeline_failure_takes_priority_over_no_alerts():
    summary = {
        "collection": {
            "success": True,
            "required_sources": {
                "telegram": {"success": False, "messages": 0},
                "rss": {"success": True, "messages": 10},
            },
            "optional_sources": {},
            "scraped_messages_persisted": 10,
        },
        "extraction": {
            "success": True,
            "messages_processed": 10,
            "entities_extracted": 20,
        },
        "scoring": {
            "success": True,
            "campaigns_scored": 1,
            "alerts_triggered": 0,
        },
        "alerting": {
            "success": True,
            "alerts_sent": 0,
        },
    }

    report = build_daily_report(summary, report_date="15/04/2026")
    text = format_daily_report(report)

    assert report.state == DailyReportState.PIPELINE_FAILURE
    assert "Pipeline failure" in text
    assert "Telegram collection" in text
