const dom = {
  statusBanner: document.querySelector("#status-banner"),
  generatedAt: document.querySelector("#generated-at"),
  operationsCards: document.querySelector("#operations-cards"),
  freshnessPill: document.querySelector("#freshness-pill"),
  freshnessDetails: document.querySelector("#freshness-details"),
  queueHealth: document.querySelector("#queue-health"),
  topCampaigns: document.querySelector("#top-campaigns"),
  riskDistribution: document.querySelector("#risk-distribution"),
  campaignTrend: document.querySelector("#campaign-trend"),
  scamTypes: document.querySelector("#scam-types"),
  campaignList: document.querySelector("#campaign-list"),
  campaignDetail: document.querySelector("#campaign-detail"),
  campaignDetailPill: document.querySelector("#campaign-detail-pill"),
  alertList: document.querySelector("#alert-list"),
  evidenceCards: document.querySelector("#evidence-cards"),
  crossReferenceSources: document.querySelector("#cross-reference-sources"),
  victimSignalBreakdown: document.querySelector("#victim-signal-breakdown"),
  alertReasons: document.querySelector("#alert-reasons"),
  topEntities: document.querySelector("#top-entities"),
  activeChannels: document.querySelector("#active-channels"),
  activePlatforms: document.querySelector("#active-platforms"),
  emptyTemplate: document.querySelector("#empty-template"),
};

let selectedCampaignId = null;

loadDashboard();

async function loadDashboard() {
  setLoadingState();
  try {
    const summary = await fetchJson("/dashboard_api/summary");
    renderDashboard(summary);
    showBanner("Dashboard loaded from live API data.", false);
    const firstCampaignId = summary.recent_campaigns?.[0]?.id;
    if (firstCampaignId) {
      await loadCampaignDetail(firstCampaignId);
    } else {
      renderEmpty(dom.campaignDetail, "No campaigns available yet.");
      dom.campaignDetailPill.textContent = "No campaigns";
      dom.campaignDetailPill.className = "pill neutral";
    }
  } catch (error) {
    showBanner(error.message, true);
    clearDashboard();
  }
}

async function loadCampaignDetail(campaignId) {
  selectedCampaignId = campaignId;
  syncSelectedCampaign();
  dom.campaignDetail.innerHTML = '<div class="empty-state">Loading campaign detail...</div>';
  try {
    const detail = await fetchJson(`/dashboard_api/campaigns/${campaignId}`);
    renderCampaignDetail(detail);
  } catch (error) {
    dom.campaignDetailPill.textContent = "Load failed";
    dom.campaignDetailPill.className = "pill failed";
    renderEmpty(dom.campaignDetail, error.message);
  }
}

async function fetchJson(path) {
  const response = await fetch(path);
  if (!response.ok) {
    const detail = await safeJson(response);
    const reason = detail?.detail || `${response.status} ${response.statusText}`;
    throw new Error(`Request failed for ${path}: ${reason}`);
  }
  return response.json();
}

async function safeJson(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function renderDashboard(summary) {
  dom.generatedAt.textContent = `Generated ${formatDateTime(summary.generated_at)}`;

  renderOperationCards(summary.operations);
  renderFreshness(summary.operations);
  renderStackList(dom.topCampaigns, summary.intelligence.top_active_campaigns, renderTopCampaignCard);
  renderBars(dom.riskDistribution, summary.intelligence.risk_distribution, "value");
  renderTrend(dom.campaignTrend, summary.intelligence.campaign_trend);
  renderBars(dom.scamTypes, summary.intelligence.scam_type_distribution, "value");
  renderCampaignList(summary.recent_campaigns);
  renderAlertList(summary.recent_alerts);
  renderEvidenceCards(summary.evidence);
  renderBars(dom.crossReferenceSources, summary.evidence.cross_reference_sources, "value");
  renderBars(dom.victimSignalBreakdown, summary.evidence.victim_signal_breakdown, "value");
  renderBars(dom.alertReasons, summary.evidence.alert_reason_breakdown, "value");
  renderStackList(dom.topEntities, summary.intelligence.top_reused_entities, renderEntityCard);
  renderStackList(dom.activeChannels, summary.intelligence.active_channels, renderChannelCard);
  renderPlatforms(summary.intelligence.active_platforms);
}

function renderOperationCards(operations) {
  const cards = [
    {
      label: "Last successful run",
      value: formatDateTime(operations.last_successful_pipeline_run_at),
      footnote: operations.next_scheduled_run_label,
    },
    {
      label: "Messages ingested (24h)",
      value: formatNumber(operations.messages_ingested_24h),
      footnote: "Recent collection throughput",
    },
    {
      label: "Entities extracted (24h)",
      value: formatNumber(operations.entities_extracted_24h),
      footnote: "Recent extraction throughput",
    },
    {
      label: "Campaigns / alerts (24h)",
      value: `${formatNumber(operations.campaigns_formed_24h)} / ${formatNumber(operations.alerts_sent_24h)}`,
      footnote: "Detections and sent alerts",
    },
  ];
  dom.operationsCards.innerHTML = cards.map(renderMetricCard).join("");
}

function renderEvidenceCards(evidence) {
  const cards = [
    {
      label: "Cross-reference matches",
      value: formatNumber(evidence.cross_reference_matches),
      footnote: "Confirmed against external or internal sources",
    },
    {
      label: "Victim signal detections",
      value: formatNumber(evidence.victim_signal_detections),
      footnote: "Signals from complaint text and extracted evidence",
    },
    {
      label: "Entity relationships",
      value: formatNumber(evidence.entity_relationship_count),
      footnote: `Average campaign depth ${evidence.linked_entity_depth_avg}`,
    },
    {
      label: "Campaigns with evidence",
      value: `${evidence.campaigns_with_supporting_evidence_pct}%`,
      footnote: "Campaigns backed by cross-reference, victim signal, or graph evidence",
    },
  ];
  dom.evidenceCards.innerHTML = cards.map(renderMetricCard).join("");
}

function renderFreshness(operations) {
  const freshness = operations.fresh_data_status;
  dom.freshnessPill.textContent = freshness.label;
  dom.freshnessPill.className = `pill ${freshness.status}`;

  const freshnessItems = [
    ["Recent messages", freshness.checks.messages],
    ["Recent entities", freshness.checks.entities],
    ["Recent campaigns", freshness.checks.campaigns],
    ["Recent alerts", freshness.checks.alerts],
  ];
  dom.freshnessDetails.innerHTML = freshnessItems.map(([label, active]) => `
    <div class="metric-row">
      <span>${label}</span>
      <span class="pill ${active ? "fresh" : "stale"}">${active ? "Yes" : "No"}</span>
    </div>
  `).join("");

  const queue = operations.queue_depth || {};
  const queueBackend = operations.queue_backend || {};
  dom.queueHealth.innerHTML = [
    queueItem("Raw messages", queue.raw_messages ?? 0),
    queueItem("Extracted entities", queue.extracted_entities ?? 0),
    queueItem("Alerts", queue.alerts ?? 0),
    `
      <div class="stack-item">
        <div class="item-head">
          <div class="item-title">Queue backend</div>
          <span class="pill ${queueBackend.available ? "fresh" : "degraded"}">${queueBackend.mode || "unknown"}</span>
        </div>
        <div class="item-subtitle">${queueBackend.error || "Redis reachable or queue running in expected mode."}</div>
      </div>
    `,
  ].join("");
}

function renderCampaignList(campaigns) {
  if (!campaigns?.length) {
    renderEmpty(dom.campaignList, "No recent campaigns available.");
    return;
  }
  dom.campaignList.innerHTML = campaigns.map((campaign) => `
    <button type="button" class="stack-item interactive ${campaign.id === selectedCampaignId ? "is-selected" : ""}" data-campaign-id="${campaign.id}">
      <div class="item-head">
        <div>
          <div class="item-title">#${campaign.id} · ${humanize(campaign.campaign_type)}</div>
          <div class="item-subtitle">${campaign.reason_summary}</div>
        </div>
        <span class="pill ${campaign.risk_level}">${campaign.risk_level}</span>
      </div>
      <div class="tag-row">
        <span class="tag">Score ${campaign.score}</span>
        <span class="tag">${campaign.entity_count} entities</span>
        <span class="tag">${campaign.channel_count} channels</span>
        <span class="tag ${campaign.alert_sent ? "alert" : ""}">${campaign.alert_sent ? "Alerted" : "Not alerted"}</span>
      </div>
    </button>
  `).join("");

  dom.campaignList.querySelectorAll("[data-campaign-id]").forEach((button) => {
    button.addEventListener("click", () => loadCampaignDetail(Number(button.dataset.campaignId)));
  });
}

function renderCampaignDetail(detail) {
  dom.campaignDetailPill.textContent = detail.risk_level;
  dom.campaignDetailPill.className = `pill ${detail.risk_level}`;
  dom.campaignDetail.innerHTML = `
    <div class="detail-group">
      <div class="detail-heading">
        <div>
          <div class="detail-title">Campaign #${detail.id} · ${humanize(detail.campaign_type)}</div>
          <div class="detail-copy">${detail.reason}</div>
        </div>
        <div class="detail-tags">
          <span class="tag">Score ${detail.score}</span>
          <span class="tag">${detail.metrics.entity_count} entities</span>
          <span class="tag">${detail.metrics.channel_count} channels</span>
          <span class="tag ${detail.alert_sent ? "alert" : ""}">${detail.alert_sent ? "Alert sent" : "Alert not sent"}</span>
        </div>
      </div>
    </div>
    <div class="detail-inline">
      <span>First seen</span>
      <strong>${formatDateTime(detail.first_seen)}</strong>
    </div>
    <div class="detail-inline">
      <span>Last seen</span>
      <strong>${formatDateTime(detail.last_seen)}</strong>
    </div>
    <div class="detail-group">
      <h4>Evidence markers</h4>
      <div class="detail-list">
        ${detailStat("Cross references", detail.metrics.cross_references)}
        ${detailStat("Victim signals", detail.metrics.victim_signals)}
        ${detailStat("Entity relationships", detail.metrics.relationships)}
      </div>
    </div>
    <div class="detail-group">
      <h4>Top entities</h4>
      <div class="detail-list">${detail.entities.slice(0, 12).map((entity) => `
        <div class="detail-inline">
          <span>${entity.value} <span class="dim">(${entity.type})</span></span>
          <strong>${entity.count}</strong>
        </div>
      `).join("") || '<div class="dim">No linked entities.</div>'}</div>
    </div>
    <div class="detail-group">
      <h4>Cross-reference support</h4>
      <div class="detail-list">${detail.cross_references.slice(0, 8).map((item) => `
        <div class="detail-inline">
          <span>${item.value} <span class="dim">(${item.source_db})</span></span>
          <strong>${item.status}</strong>
        </div>
      `).join("") || '<div class="dim">No cross-reference rows linked to this campaign.</div>'}</div>
    </div>
    <div class="detail-group">
      <h4>Victim signals</h4>
      <div class="detail-list">${detail.victim_signals.slice(0, 8).map((item) => `
        <div class="detail-inline">
          <span>${humanize(item.signal_type)} <span class="dim">${item.value}</span></span>
          <strong>${item.extracted_amount ? formatCurrency(item.extracted_amount) : "Observed"}</strong>
        </div>
      `).join("") || '<div class="dim">No victim-signal rows linked to this campaign.</div>'}</div>
    </div>
    <div class="detail-group">
      <h4>Recent alert</h4>
      ${detail.recent_alert ? `
        <div class="detail-inline">
          <span>${detail.recent_alert.alert_level} · ${detail.recent_alert.status}</span>
          <strong>${formatDateTime(detail.recent_alert.sent_at)}</strong>
        </div>
        <div class="detail-copy">${detail.recent_alert.message || ""}</div>
      ` : '<div class="dim">No alert logged for this campaign.</div>'}
    </div>
  `;
}

function renderAlertList(alerts) {
  if (!alerts?.length) {
    renderEmpty(dom.alertList, "No alerts have been logged yet.");
    return;
  }
  dom.alertList.innerHTML = alerts.map((alert) => `
    <article class="alert-item">
      <div class="item-head">
        <div>
          <div class="item-title">Campaign #${alert.campaign_id ?? "N/A"} · ${humanize(alert.campaign_type || "unknown")}</div>
          <div class="item-subtitle">${alert.message_preview || "No alert preview available."}</div>
        </div>
        <span class="pill ${alert.alert_level || alert.risk_level || "neutral"}">${alert.alert_level || alert.risk_level || "unknown"}</span>
      </div>
      <div class="tag-row">
        <span class="tag">${alert.status}</span>
        <span class="tag">Sent ${formatDateTime(alert.sent_at)}</span>
        ${alert.score != null ? `<span class="tag">Score ${alert.score}</span>` : ""}
      </div>
    </article>
  `).join("");
}

function renderPlatforms(platforms) {
  if (!platforms?.length) {
    renderEmpty(dom.activePlatforms, "No platform activity available.");
    return;
  }
  dom.activePlatforms.innerHTML = platforms.map((platform) => `
    <div class="platform-item">
      <div class="item-head">
        <div class="item-title">${humanize(platform.platform)}</div>
        <strong>${formatNumber(platform.messages)}</strong>
      </div>
      <div class="item-subtitle">${platform.channels} active channels in the last 30 days</div>
    </div>
  `).join("");
}

function renderStackList(target, items, renderer) {
  if (!items?.length) {
    renderEmpty(target, "No data available.");
    return;
  }
  target.innerHTML = items.map(renderer).join("");
}

function renderBars(target, items, valueKey) {
  if (!items?.length) {
    renderEmpty(target, "No data available.");
    return;
  }
  const maxValue = Math.max(...items.map((item) => Number(item[valueKey] || 0)), 1);
  target.innerHTML = items.map((item) => `
    <div class="bar-row">
      <div class="bar-meta">
        <span>${humanize(item.label || item.platform || item.channel)}</span>
        <strong>${formatNumber(item[valueKey])}</strong>
      </div>
      <div class="bar-track">
        <div class="bar-fill" style="width:${Math.max((Number(item[valueKey]) / maxValue) * 100, 6)}%"></div>
      </div>
    </div>
  `).join("");
}

function renderTrend(target, items) {
  if (!items?.length) {
    renderEmpty(target, "No campaign trend available.");
    return;
  }
  const maxValue = Math.max(...items.map((item) => Number(item.campaigns || 0)), 1);
  target.innerHTML = items.map((item) => `
    <div class="spark-row">
      <div class="spark-meta">
        <span>${item.date}</span>
        <strong>${formatNumber(item.campaigns)}</strong>
      </div>
      <div class="spark-track">
        <div class="spark-fill" style="width:${Math.max((Number(item.campaigns) / maxValue) * 100, 6)}%"></div>
      </div>
    </div>
  `).join("");
}

function renderMetricCard({ label, value, footnote }) {
  return `
    <article class="metric-card">
      <div class="metric-label">${label}</div>
      <div class="metric-value">${value}</div>
      <div class="metric-footnote">${footnote}</div>
    </article>
  `;
}

function renderTopCampaignCard(campaign) {
  return `
    <div class="stack-item">
      <div class="item-head">
        <div>
          <div class="item-title">#${campaign.id} · ${humanize(campaign.campaign_type)}</div>
          <div class="item-subtitle">${campaign.reason_summary}</div>
        </div>
        <span class="pill ${campaign.risk_level}">${campaign.risk_level}</span>
      </div>
      <div class="tag-row">
        <span class="tag">Score ${campaign.score}</span>
        <span class="tag">${campaign.entity_count} entities</span>
        <span class="tag">${campaign.evidence.cross_references} cross refs</span>
      </div>
    </div>
  `;
}

function renderEntityCard(entity) {
  return `
    <div class="stack-item">
      <div class="item-head">
        <div>
          <div class="item-title">${entity.value}</div>
          <div class="item-subtitle">${humanize(entity.type)}</div>
        </div>
        <strong>${formatNumber(entity.count)}</strong>
      </div>
      <div class="item-subtitle">Last seen ${formatDateTime(entity.last_seen)}</div>
    </div>
  `;
}

function renderChannelCard(channel) {
  return `
    <div class="stack-item">
      <div class="item-head">
        <div>
          <div class="item-title">${channel.channel}</div>
          <div class="item-subtitle">${humanize(channel.platform)}</div>
        </div>
        <strong>${formatNumber(channel.messages)}</strong>
      </div>
    </div>
  `;
}

function detailStat(label, value) {
  return `
    <div class="detail-inline">
      <span>${label}</span>
      <strong>${formatNumber(value)}</strong>
    </div>
  `;
}

function queueItem(label, value) {
  return `
    <div class="metric-row">
      <span>${label}</span>
      <strong>${formatNumber(value)}</strong>
    </div>
  `;
}

function renderEmpty(target, message) {
  target.innerHTML = `<div class="empty-state">${message}</div>`;
}

function showBanner(message, isError) {
  dom.statusBanner.textContent = message;
  dom.statusBanner.classList.remove("hidden", "error");
  if (isError) {
    dom.statusBanner.classList.add("error");
  }
}

function clearDashboard() {
  [
    dom.operationsCards,
    dom.freshnessDetails,
    dom.queueHealth,
    dom.topCampaigns,
    dom.riskDistribution,
    dom.campaignTrend,
    dom.scamTypes,
    dom.campaignList,
    dom.alertList,
    dom.evidenceCards,
    dom.crossReferenceSources,
    dom.victimSignalBreakdown,
    dom.alertReasons,
    dom.topEntities,
    dom.activeChannels,
    dom.activePlatforms,
  ].forEach((target) => renderEmpty(target, "No data loaded."));
  renderEmpty(dom.campaignDetail, "No campaign selected.");
}

function setLoadingState() {
  dom.generatedAt.textContent = "Loading live data";
}

function syncSelectedCampaign() {
  dom.campaignList.querySelectorAll("[data-campaign-id]").forEach((button) => {
    button.classList.toggle("is-selected", Number(button.dataset.campaignId) === selectedCampaignId);
  });
}

function humanize(value) {
  if (!value) {
    return "Unknown";
  }
  return String(value).replaceAll("_", " ").replace(/\b\w/g, (match) => match.toUpperCase());
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(Number(value || 0));
}

function formatCurrency(value) {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "MYR",
    maximumFractionDigits: 0,
  }).format(Number(value || 0));
}

function formatDateTime(value) {
  if (!value) {
    return "Unavailable";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
