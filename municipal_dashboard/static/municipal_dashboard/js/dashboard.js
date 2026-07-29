(function () {
  "use strict";

  const root = document.getElementById("municipal-dashboard-root");
  if (!root) {
    return;
  }

  const SVG_NS = "http://www.w3.org/2000/svg";
  const SEARCH_DELAY_MS = 320;
  const FRESHNESS_INTERVAL_MS = 60000;
  const VALID_VIEWS = new Set(["cards", "table"]);
  const VALID_STATUS_FILTERS = new Set([
    "",
    "target_met",
    "improving",
    "stable",
    "attention",
    "no_data",
  ]);
  const STATUS_TONES = new Set(["positive", "negative", "warning", "info", "neutral"]);
  const TREND_GROUPS = [
    {
      key: "positive",
      label: "Em boa direção",
      color: "#237246",
      matches: new Set(["target_met", "improving"]),
    },
    {
      key: "stable",
      label: "Estáveis ou sem referência",
      color: "#2d728f",
      matches: new Set(["stable", "no_reference", "changed"]),
    },
    {
      key: "attention",
      label: "Em atenção",
      color: "#b65a49",
      matches: new Set(["worsening", "target_not_met"]),
    },
    {
      key: "no_data",
      label: "Sem dados",
      color: "#87979e",
      matches: new Set(["no_data"]),
    },
  ];

  const elements = {
    loadingState: byId("loadingState"),
    errorState: byId("errorState"),
    errorMessage: byId("errorMessage"),
    retryButton: byId("retryButton"),
    dashboardContent: byId("dashboardContent"),
    filtersForm: byId("dashboardFilters"),
    filterBar: document.querySelector(".filter-bar"),
    toggleFiltersButton: byId("toggleFiltersButton"),
    mobileFilterCount: byId("mobileFilterCount"),
    yearFilter: byId("yearFilter"),
    dimensionFilter: byId("dimensionFilter"),
    axisFilter: byId("axisFilter"),
    searchFilter: byId("searchFilter"),
    statusFilter: byId("statusFilter"),
    clearFiltersButton: byId("clearFiltersButton"),
    emptyClearButton: byId("emptyClearButton"),
    appliedFiltersText: byId("appliedFiltersText"),
    refreshButton: byId("refreshButton"),
    copyLinkButton: byId("copyLinkButton"),
    exportButton: byId("exportButton"),
    connectionStatus: byId("connectionStatus"),
    connectionStatusText: byId("connectionStatusText"),
    lastFreshnessText: byId("lastFreshnessText"),
    coveragePercentage: byId("coveragePercentage"),
    coverageBar: byId("coverageBar"),
    coverageDescription: byId("coverageDescription"),
    coverageRingValue: byId("coverageRingValue"),
    coverageRingDescription: byId("coverageRingDescription"),
    dimensionCount: byId("dimensionCount"),
    axisCount: byId("axisCount"),
    indicatorCount: byId("indicatorCount"),
    measurementCount: byId("measurementCount"),
    dimensionsGrid: byId("dimensionsGrid"),
    dimensionCardTemplate: byId("dimensionCardTemplate"),
    showAllDimensionsButton: byId("showAllDimensionsButton"),
    trendSvg: byId("trendSvg"),
    trendChartDescription: byId("trendChartDescription"),
    trendLegend: byId("trendLegend"),
    trendSummary: byId("trendSummary"),
    indicatorCards: byId("indicatorCards"),
    indicatorCardTemplate: byId("indicatorCardTemplate"),
    indicatorTablePanel: byId("indicatorTablePanel"),
    indicatorTableBody: byId("indicatorTableBody"),
    indicatorRowTemplate: byId("indicatorRowTemplate"),
    indicatorResultCount: byId("indicatorResultCount"),
    emptyState: byId("emptyState"),
    generatedAtText: byId("generatedAtText"),
    detailBackdrop: byId("detailBackdrop"),
    detailDrawer: byId("detailDrawer"),
    detailLoading: byId("detailLoading"),
    detailError: byId("detailError"),
    detailContent: byId("detailContent"),
    closeDetailButton: byId("closeDetailButton"),
    retryDetailButton: byId("retryDetailButton"),
    shareDetailButton: byId("shareDetailButton"),
    detailUpsertButton: byId("detailUpsertButton"),
    detailDimension: byId("detailDimension"),
    detailTitle: byId("detailTitle"),
    detailAxis: byId("detailAxis"),
    detailFrequency: byId("detailFrequency"),
    detailPolarity: byId("detailPolarity"),
    detailKind: byId("detailKind"),
    detailDescription: byId("detailDescription"),
    detailCurrentValue: byId("detailCurrentValue"),
    detailCurrentPeriod: byId("detailCurrentPeriod"),
    detailTargetValue: byId("detailTargetValue"),
    detailTargetDeadline: byId("detailTargetDeadline"),
    detailStatus: byId("detailStatus"),
    detailDelta: byId("detailDelta"),
    detailSeriesCount: byId("detailSeriesCount"),
    detailChartWrap: byId("detailChartWrap"),
    detailSeriesSvg: byId("detailSeriesSvg"),
    detailChartDescription: byId("detailChartDescription"),
    detailNoSeries: byId("detailNoSeries"),
    detailSeriesTableBody: byId("detailSeriesTableBody"),
    detailMethodology: byId("detailMethodology"),
    detailSourceLink: byId("detailSourceLink"),
    detailSourceText: byId("detailSourceText"),
    detailUpdatedAt: byId("detailUpdatedAt"),
    openUpsertButton: byId("openUpsertButton"),
    upsertDialog: byId("upsertDialog"),
    upsertForm: byId("upsertForm"),
    closeUpsertButton: byId("closeUpsertButton"),
    cancelUpsertButton: byId("cancelUpsertButton"),
    submitUpsertButton: byId("submitUpsertButton"),
    upsertFormError: byId("upsertFormError"),
    measurementIndicator: byId("measurementIndicator"),
    measurementPeriodStart: byId("measurementPeriodStart"),
    measurementPeriodEnd: byId("measurementPeriodEnd"),
    measurementValue: byId("measurementValue"),
    measurementTarget: byId("measurementTarget"),
    measurementQuality: byId("measurementQuality"),
    measurementSourceName: byId("measurementSourceName"),
    measurementSourceUrl: byId("measurementSourceUrl"),
    measurementNote: byId("measurementNote"),
    toast: byId("toast"),
    announcements: byId("screenReaderAnnouncements"),
  };

  const state = {
    overview: null,
    freshness: null,
    detail: null,
    visibleIndicators: [],
    filters: readFiltersFromUrl(),
    view: readViewFromUrl(),
    activeSlug: "",
    pendingIndicatorSlug: readIndicatorFromUrl(),
    overviewController: null,
    detailController: null,
    freshnessController: null,
    searchTimer: null,
    toastTimer: null,
    freshnessTimer: null,
    lastFreshnessRequestAt: 0,
    detailReturnFocus: null,
    upsertReturnFocus: null,
    firstLoad: true,
    popstateInProgress: false,
    initialYearPending: !new URLSearchParams(window.location.search).has("year"),
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function readFiltersFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const status = params.get("status") || "";
    const rawYear = params.get("year") || "";
    return {
      year: rawYear.toLowerCase() === "all" || rawYear.toLowerCase() === "todos" ? "" : rawYear,
      dimension: params.get("dimension") || "",
      axis: params.get("axis") || "",
      q: params.get("q") || "",
      status: VALID_STATUS_FILTERS.has(status) ? status : "",
    };
  }

  function readViewFromUrl() {
    const value = new URLSearchParams(window.location.search).get("view") || "cards";
    return VALID_VIEWS.has(value) ? value : "cards";
  }

  function readIndicatorFromUrl() {
    return new URLSearchParams(window.location.search).get("indicator") || "";
  }

  function setText(element, value, fallback) {
    if (!element) {
      return;
    }
    const resolved = value === null || value === undefined || value === "" ? fallback : value;
    element.textContent = resolved === null || resolved === undefined ? "" : String(resolved);
  }

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function safeAccent(value) {
    return /^#[0-9a-f]{6}$/i.test(String(value || "")) ? String(value) : "#1d6284";
  }

  function safeExternalUrl(value) {
    if (!value) {
      return "";
    }
    try {
      const url = new URL(String(value), window.location.origin);
      return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
    } catch (error) {
      return "";
    }
  }

  function clamp(value, minimum, maximum) {
    return Math.min(Math.max(Number(value) || 0, minimum), maximum);
  }

  function parseIsoDate(value) {
    if (!value) {
      return null;
    }
    const date = new Date(String(value).slice(0, 10) + "T00:00:00Z");
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function parseIsoDateTime(value) {
    if (!value) {
      return null;
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatDate(value, options) {
    const date = parseIsoDate(value);
    if (!date) {
      return "Data não informada";
    }
    return new Intl.DateTimeFormat(
      "pt-BR",
      options || { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" },
    ).format(date);
  }

  function formatDateTime(value) {
    const date = parseIsoDateTime(value);
    if (!date) {
      return "Atualização não informada";
    }
    return new Intl.DateTimeFormat("pt-BR", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  }

  function formatShortPeriod(value) {
    const date = parseIsoDate(value);
    if (!date) {
      return "—";
    }
    return new Intl.DateTimeFormat("pt-BR", {
      month: "short",
      year: "2-digit",
      timeZone: "UTC",
    }).format(date);
  }

  function formatPeriod(measurement) {
    if (!measurement) {
      return "Sem período";
    }
    const start = measurement.period_start;
    const end = measurement.period_end;
    if (!start && !end) {
      return "Sem período";
    }
    if (!start || start === end) {
      return formatDate(end || start);
    }
    const startDate = parseIsoDate(start);
    const endDate = parseIsoDate(end);
    if (startDate && endDate && startDate.getUTCFullYear() === endDate.getUTCFullYear()) {
      const first = formatDate(start, { day: "2-digit", month: "short", timeZone: "UTC" });
      const last = formatDate(end, { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
      return first + " a " + last;
    }
    return formatDate(start) + " a " + formatDate(end);
  }

  function formatNumber(value, maximumFractionDigits) {
    if (value === null || value === undefined || value === "") {
      return "—";
    }
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return "—";
    }
    const absolute = Math.abs(number);
    const digits =
      maximumFractionDigits !== undefined
        ? maximumFractionDigits
        : absolute > 0 && absolute < 1
          ? 4
          : 2;
    return new Intl.NumberFormat("pt-BR", {
      maximumFractionDigits: digits,
      minimumFractionDigits: 0,
    }).format(number);
  }

  function formatValue(value, unit) {
    if (value === null || value === undefined || value === "") {
      return "—";
    }
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return "—";
    }
    const normalizedUnit = String(unit || "").trim();
    if (/^(r\$|real|reais)$/i.test(normalizedUnit)) {
      return new Intl.NumberFormat("pt-BR", {
        style: "currency",
        currency: "BRL",
        maximumFractionDigits: 2,
      }).format(number);
    }
    if (normalizedUnit === "%") {
      return formatNumber(number) + "%";
    }
    return normalizedUnit ? formatNumber(number) + " " + normalizedUnit : formatNumber(number);
  }

  function formatDelta(indicator) {
    const rawPercentage =
      indicator && indicator.status ? indicator.status.delta_percentage : null;
    const percentage =
      rawPercentage === null || rawPercentage === undefined || rawPercentage === ""
        ? NaN
        : Number(rawPercentage);
    if (!Number.isFinite(percentage)) {
      return {
        text: "Sem comparação",
        className: "",
      };
    }
    const prefix = percentage > 0 ? "+" : "";
    const tone = indicator.status.tone;
    return {
      text: prefix + formatNumber(percentage, 1) + "% ante o anterior",
      className: tone === "positive" ? "is-positive" : tone === "negative" ? "is-negative" : "",
    };
  }

  function pluralize(count, singular, plural) {
    return Number(count) === 1 ? singular : plural;
  }

  function makeSvgElement(name, attributes, textValue) {
    const element = document.createElementNS(SVG_NS, name);
    Object.entries(attributes || {}).forEach(function (entry) {
      element.setAttribute(entry[0], String(entry[1]));
    });
    if (textValue !== undefined && textValue !== null) {
      element.textContent = String(textValue);
    }
    return element;
  }

  function fetchErrorMessage(payload, response) {
    if (payload && typeof payload.error === "string" && payload.error.trim()) {
      return payload.error;
    }
    return "A consulta falhou com o código " + response.status + ".";
  }

  async function fetchJson(url, options) {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(options && options.headers ? options.headers : {}),
      },
      ...options,
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }
    if (!response.ok) {
      throw new Error(fetchErrorMessage(payload, response));
    }
    return payload;
  }

  function buildApiUrl(baseUrl, filters) {
    const url = new URL(baseUrl, window.location.href);
    const selected = filters || state.filters;
    ["year", "dimension", "axis"].forEach(function (key) {
      if (selected[key]) {
        url.searchParams.set(key, selected[key]);
      }
    });
    if (selected.q) {
      url.searchParams.set("q", selected.q);
    }
    return url;
  }

  function detailUrlForSlug(slug) {
    const template = root.dataset.detailUrlTemplate || "";
    const path = template.replace("__slug__", encodeURIComponent(slug));
    const url = new URL(path, window.location.href);
    if (state.filters.year) {
      url.searchParams.set("year", state.filters.year);
    }
    return url;
  }

  function setBusy(isBusy) {
    root.setAttribute("aria-busy", isBusy ? "true" : "false");
    if (elements.refreshButton) {
      elements.refreshButton.disabled = isBusy;
      elements.refreshButton.classList.toggle("is-loading", isBusy);
    }
  }

  function showMainError(message) {
    elements.loadingState.hidden = true;
    elements.dashboardContent.hidden = true;
    setText(elements.errorMessage, message, "Tente novamente em instantes.");
    elements.errorState.hidden = false;
  }

  function showToast(message, isError) {
    if (!elements.toast) {
      return;
    }
    window.clearTimeout(state.toastTimer);
    elements.toast.classList.toggle("is-error", Boolean(isError));
    setText(elements.toast, message);
    elements.toast.hidden = false;
    state.toastTimer = window.setTimeout(function () {
      elements.toast.hidden = true;
    }, 4200);
  }

  function announce(message) {
    if (!elements.announcements) {
      return;
    }
    elements.announcements.textContent = "";
    window.setTimeout(function () {
      elements.announcements.textContent = message;
    }, 30);
  }

  function updateUrl(options) {
    const settings = options || {};
    const url = new URL(window.location.href);
    if (state.filters.year) {
      url.searchParams.set("year", state.filters.year);
    } else if (!state.initialYearPending) {
      url.searchParams.set("year", "all");
    } else {
      url.searchParams.delete("year");
    }
    const mappings = {
      dimension: state.filters.dimension,
      axis: state.filters.axis,
      q: state.filters.q,
      status: state.filters.status,
    };
    Object.entries(mappings).forEach(function (entry) {
      const key = entry[0];
      const value = entry[1];
      if (value) {
        url.searchParams.set(key, value);
      } else {
        url.searchParams.delete(key);
      }
    });
    if (state.view === "table") {
      url.searchParams.set("view", "table");
    } else {
      url.searchParams.delete("view");
    }
    if (state.activeSlug) {
      url.searchParams.set("indicator", state.activeSlug);
    } else {
      url.searchParams.delete("indicator");
    }
    const method = settings.push ? "pushState" : "replaceState";
    window.history[method]({ municipalDashboard: true }, "", url);
  }

  function syncStaticFilterControls() {
    elements.searchFilter.value = state.filters.q;
    elements.statusFilter.value = state.filters.status;
  }

  function appendOption(select, value, label) {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = String(label);
    select.appendChild(option);
    return option;
  }

  function rebuildSelect(select, placeholder, items, selectedValue, getValue, getLabel) {
    select.replaceChildren();
    appendOption(select, "", placeholder);
    items.forEach(function (item) {
      appendOption(select, getValue(item), getLabel(item));
    });
    select.value = selectedValue || "";
  }

  function populateFilterControls(payload) {
    const dimensions = asArray(payload.dimensions);
    const axes = asArray(payload.axes);
    const years = asArray(payload.years);

    rebuildSelect(
      elements.yearFilter,
      "Todos os anos",
      years,
      state.filters.year,
      function (year) {
        return year;
      },
      function (year) {
        return year;
      },
    );
    rebuildSelect(
      elements.dimensionFilter,
      "Todas as dimensões",
      dimensions,
      state.filters.dimension,
      function (dimension) {
        return dimension.slug;
      },
      function (dimension) {
        return dimension.name;
      },
    );
    rebuildSelect(
      elements.axisFilter,
      "Todos os eixos",
      axes,
      state.filters.axis,
      function (axis) {
        return axis.slug;
      },
      function (axis) {
        return axis.name;
      },
    );

    elements.yearFilter.value = state.filters.year;
    elements.dimensionFilter.value = state.filters.dimension;
    elements.axisFilter.value = state.filters.axis;
    syncStaticFilterControls();
    updateFilterSummary();
  }

  function filterLabel(select, value) {
    if (!value) {
      return "";
    }
    const option = Array.from(select.options).find(function (candidate) {
      return candidate.value === value;
    });
    return option ? option.textContent : value;
  }

  function activeFilterEntries() {
    const entries = [];
    if (state.filters.year) {
      entries.push("Ano: " + state.filters.year);
    }
    if (state.filters.dimension) {
      entries.push("Dimensão: " + filterLabel(elements.dimensionFilter, state.filters.dimension));
    }
    if (state.filters.axis) {
      entries.push("Eixo: " + filterLabel(elements.axisFilter, state.filters.axis));
    }
    if (state.filters.q) {
      entries.push('Busca: "' + state.filters.q + '"');
    }
    if (state.filters.status) {
      entries.push("Situação: " + filterLabel(elements.statusFilter, state.filters.status));
    }
    return entries;
  }

  function updateFilterSummary() {
    const entries = activeFilterEntries();
    const count = entries.length;
    setText(
      elements.appliedFiltersText,
      count ? entries.join(" • ") : "Nenhum filtro aplicado.",
    );
    elements.clearFiltersButton.disabled = count === 0;
    elements.mobileFilterCount.hidden = count === 0;
    setText(elements.mobileFilterCount, count);
  }

  function renderCoverage(payload) {
    const coverage = payload.coverage || {};
    const percentage = clamp(coverage.percentage, 0, 100);
    const display = formatNumber(percentage, percentage % 1 === 0 ? 0 : 1);
    setText(elements.coveragePercentage, display);
    elements.coverageBar.style.width = percentage + "%";
    elements.coverageRingValue.setAttribute(
      "stroke-dasharray",
      percentage + " " + Math.max(0, 100 - percentage),
    );
    const withData = Number(coverage.with_data) || 0;
    const total = Number(coverage.total) || 0;
    const description =
      withData +
      " de " +
      total +
      " " +
      pluralize(total, "indicador possui", "indicadores possuem") +
      " resultado publicado.";
    setText(elements.coverageDescription, description);
    setText(elements.coverageRingDescription, display + "% de cobertura. " + description);
  }

  function renderCounts(payload) {
    const counts = payload.counts || {};
    setText(elements.dimensionCount, formatNumber(counts.dimensions, 0));
    setText(elements.axisCount, formatNumber(counts.axes, 0));
    setText(elements.indicatorCount, formatNumber(counts.indicators, 0));
    setText(elements.measurementCount, formatNumber(counts.measurements, 0));
  }

  function renderMetadata(payload) {
    if (payload.latest_update) {
      setText(elements.lastFreshnessText, "Dados atualizados em " + formatDateTime(payload.latest_update));
    } else {
      setText(elements.lastFreshnessText, "Nenhuma atualização registrada");
    }
    if (payload.generated_at) {
      setText(elements.generatedAtText, "Painel gerado em " + formatDateTime(payload.generated_at));
    }
  }

  function renderDimensions(dimensions) {
    elements.dimensionsGrid.replaceChildren();
    const selected = state.filters.dimension;
    asArray(dimensions).forEach(function (dimension, index) {
      const fragment = elements.dimensionCardTemplate.content.cloneNode(true);
      const card = fragment.querySelector(".dimension-card");
      const button = fragment.querySelector(".dimension-card__button");
      const accent = safeAccent(dimension.accent_color);
      card.style.setProperty("--accent", accent);
      card.dataset.dimension = dimension.slug;
      card.classList.toggle("is-selected", dimension.slug === selected);
      button.setAttribute("aria-pressed", dimension.slug === selected ? "true" : "false");
      button.setAttribute(
        "aria-label",
        (dimension.slug === selected ? "Remover filtro da dimensão " : "Filtrar pela dimensão ") +
          dimension.name,
      );
      setText(fragment.querySelector(".dimension-card__number"), String(index + 1).padStart(2, "0"));
      setText(fragment.querySelector(".dimension-card__name"), dimension.name, "Dimensão");
      setText(
        fragment.querySelector(".dimension-card__description"),
        dimension.description,
        "Explore os eixos e resultados desta dimensão.",
      );
      const axisCount = Number(dimension.axis_count) || 0;
      const indicatorCount = Number(dimension.indicator_count) || 0;
      setText(
        fragment.querySelector(".dimension-card__axes"),
        axisCount + " " + pluralize(axisCount, "eixo", "eixos"),
      );
      setText(
        fragment.querySelector(".dimension-card__indicators"),
        indicatorCount + " " + pluralize(indicatorCount, "indicador", "indicadores"),
      );
      button.addEventListener("click", function () {
        selectDimension(dimension.slug);
      });
      elements.dimensionsGrid.appendChild(fragment);
    });
    elements.showAllDimensionsButton.hidden = !selected;
  }

  function statusMatches(indicator, filter) {
    if (!filter) {
      return true;
    }
    const code = indicator && indicator.status ? indicator.status.code : "no_data";
    if (filter === "attention") {
      return code === "worsening" || code === "target_not_met";
    }
    return code === filter;
  }

  function applyClientFilters() {
    const allIndicators = state.overview ? asArray(state.overview.indicators) : [];
    state.visibleIndicators = allIndicators.filter(function (indicator) {
      return statusMatches(indicator, state.filters.status);
    });
    renderIndicators();
    renderTrend(state.visibleIndicators);
    updateFilterSummary();
    updateUrl();
  }

  function statusTone(indicator) {
    const tone = indicator && indicator.status ? indicator.status.tone : "neutral";
    return STATUS_TONES.has(tone) ? tone : "neutral";
  }

  function applyStatusBadge(element, indicator) {
    const tone = statusTone(indicator);
    element.className = element.className
      .split(/\s+/)
      .filter(function (name) {
        return name && !name.startsWith("status-badge--");
      })
      .join(" ");
    element.classList.add("status-badge--" + tone);
    setText(element, indicator && indicator.status ? indicator.status.label : "Sem dados");
  }

  function applyKindBadge(element, indicator) {
    if (!element) {
      return;
    }
    const kind = indicator && indicator.kind ? indicator.kind : null;
    if (!kind || !kind.code) {
      element.hidden = true;
      element.classList.remove("kind-badge--mandatory", "kind-badge--contextual");
      setText(element, "");
      return;
    }
    element.hidden = false;
    element.classList.toggle("kind-badge--mandatory", kind.code === "mandatory");
    element.classList.toggle("kind-badge--contextual", kind.code === "supplemental");
    setText(element, kind.label, kind.code === "technical_proposal" ? "Proposta técnica" : "Classificação");
  }

  function dimensionColorFor(indicator) {
    const dimensions = state.overview ? asArray(state.overview.dimensions) : [];
    const slug = indicator && indicator.dimension ? indicator.dimension.slug : "";
    const match = dimensions.find(function (dimension) {
      return dimension.slug === slug;
    });
    return safeAccent(match ? match.accent_color : "");
  }

  function currentValueFor(indicator) {
    const measurement = indicator.current_measurement;
    return formatValue(measurement ? measurement.value : null, indicator.unit);
  }

  function targetValueFor(indicator) {
    const target = indicator.target || {};
    return formatValue(target.effective_value, indicator.unit);
  }

  function renderIndicatorCards(indicators) {
    elements.indicatorCards.replaceChildren();
    indicators.forEach(function (indicator) {
      const fragment = elements.indicatorCardTemplate.content.cloneNode(true);
      const card = fragment.querySelector(".indicator-card");
      const accent = dimensionColorFor(indicator);
      card.style.setProperty("--accent", accent);
      card.dataset.slug = indicator.slug;
      setText(fragment.querySelector(".indicator-card__dimension"), indicator.dimension.name);
      applyKindBadge(fragment.querySelector(".indicator-card__kind"), indicator);
      applyStatusBadge(fragment.querySelector(".indicator-card__status"), indicator);
      setText(fragment.querySelector(".indicator-card__name"), indicator.name);
      setText(fragment.querySelector(".indicator-card__axis"), "Eixo: " + indicator.axis.name);
      setText(fragment.querySelector(".indicator-card__value"), currentValueFor(indicator));
      const delta = formatDelta(indicator);
      const deltaElement = fragment.querySelector(".indicator-card__delta");
      setText(deltaElement, delta.text);
      if (delta.className) {
        deltaElement.classList.add(delta.className);
      }
      setText(fragment.querySelector(".indicator-card__target strong"), targetValueFor(indicator));
      setText(
        fragment.querySelector(".indicator-card__period"),
        formatPeriod(indicator.current_measurement),
      );
      const detailsButton = fragment.querySelector(".indicator-card__details");
      detailsButton.setAttribute("aria-label", "Ver detalhes de " + indicator.name);
      detailsButton.addEventListener("click", function (event) {
        openDetail(indicator.slug, { trigger: event.currentTarget, updateUrl: true });
      });
      elements.indicatorCards.appendChild(fragment);
    });
  }

  function renderIndicatorRows(indicators) {
    elements.indicatorTableBody.replaceChildren();
    indicators.forEach(function (indicator) {
      const fragment = elements.indicatorRowTemplate.content.cloneNode(true);
      const row = fragment.querySelector("tr");
      row.dataset.slug = indicator.slug;
      const nameButton = fragment.querySelector(".table-indicator-button");
      setText(nameButton, indicator.name);
      applyKindBadge(fragment.querySelector(".table-kind"), indicator);
      nameButton.setAttribute("aria-label", "Ver detalhes de " + indicator.name);
      nameButton.addEventListener("click", function (event) {
        openDetail(indicator.slug, { trigger: event.currentTarget, updateUrl: true });
      });
      setText(fragment.querySelector(".table-dimension"), indicator.dimension.name);
      setText(fragment.querySelector(".table-axis"), indicator.axis.name);
      setText(fragment.querySelector(".table-current"), currentValueFor(indicator));
      setText(fragment.querySelector(".table-target"), targetValueFor(indicator));
      applyStatusBadge(fragment.querySelector(".table-status"), indicator);
      setText(fragment.querySelector(".table-period"), formatPeriod(indicator.current_measurement));
      const detailButton = fragment.querySelector(".table-details");
      detailButton.setAttribute("aria-label", "Ver detalhes de " + indicator.name);
      detailButton.addEventListener("click", function (event) {
        openDetail(indicator.slug, { trigger: event.currentTarget, updateUrl: true });
      });
      elements.indicatorTableBody.appendChild(fragment);
    });
  }

  function renderIndicators() {
    const indicators = state.visibleIndicators;
    renderIndicatorCards(indicators);
    renderIndicatorRows(indicators);
    const totalBeforeStatus = state.overview ? asArray(state.overview.indicators).length : 0;
    const count = indicators.length;
    let resultText =
      count + " " + pluralize(count, "indicador encontrado", "indicadores encontrados");
    if (state.filters.status && count !== totalBeforeStatus) {
      resultText += " após filtrar a situação";
    }
    setText(elements.indicatorResultCount, resultText + ".");
    elements.emptyState.hidden = count !== 0;
    elements.indicatorCards.hidden = count === 0 || state.view !== "cards";
    elements.indicatorTablePanel.hidden = count === 0 || state.view !== "table";
    elements.exportButton.disabled = count === 0;
  }

  function groupTrendIndicators(indicators) {
    return TREND_GROUPS.map(function (group) {
      const count = indicators.filter(function (indicator) {
        const code = indicator && indicator.status ? indicator.status.code : "no_data";
        return group.matches.has(code);
      }).length;
      return { ...group, count: count };
    });
  }

  function renderTrendLegend(groups) {
    elements.trendLegend.replaceChildren();
    groups.forEach(function (group) {
      const item = document.createElement("span");
      item.className = "trend-legend__item";
      const swatch = document.createElement("span");
      swatch.className = "trend-legend__swatch";
      swatch.style.setProperty("--legend-color", group.color);
      swatch.setAttribute("aria-hidden", "true");
      const label = document.createElement("span");
      label.textContent = group.label + ": " + group.count;
      item.append(swatch, label);
      elements.trendLegend.appendChild(item);
    });
  }

  function renderTrend(indicators) {
    const groups = groupTrendIndicators(indicators);
    renderTrendLegend(groups);
    elements.trendSvg.replaceChildren();
    const total = indicators.length;
    const dataTotal = total - (groups.find(function (group) { return group.key === "no_data"; }) || { count: 0 }).count;
    const positiveCount = (groups.find(function (group) { return group.key === "positive"; }) || { count: 0 }).count;
    const positivePercentage = dataTotal ? Math.round((positiveCount / dataTotal) * 100) : 0;
    setText(
      elements.trendSummary,
      total
        ? positivePercentage +
            "% dos indicadores com dados estão em boa direção no recorte selecionado."
        : "Não há indicadores neste recorte para calcular a evolução.",
    );

    const title = makeSvgElement("title", { id: "trendChartTitle" }, "Distribuição da situação dos indicadores");
    const descriptionText = groups
      .map(function (group) {
        return group.label + ": " + group.count;
      })
      .join("; ");
    const description = makeSvgElement(
      "desc",
      { id: "trendChartDescription" },
      total ? descriptionText + "." : "Nenhum indicador encontrado.",
    );
    elements.trendSvg.append(title, description);
    setText(elements.trendChartDescription, descriptionText);

    const chartLeft = 220;
    const chartRight = 900;
    const chartTop = 16;
    const rowHeight = 45;
    const barHeight = 24;
    const maxCount = Math.max(
      1,
      ...groups.map(function (group) {
        return group.count;
      }),
    );

    for (let tick = 0; tick <= 4; tick += 1) {
      const x = chartLeft + ((chartRight - chartLeft) * tick) / 4;
      elements.trendSvg.appendChild(
        makeSvgElement("line", {
          x1: x,
          y1: chartTop,
          x2: x,
          y2: chartTop + rowHeight * groups.length - 8,
          class: "chart-grid",
        }),
      );
      elements.trendSvg.appendChild(
        makeSvgElement(
          "text",
          {
            x: x,
            y: chartTop + rowHeight * groups.length + 11,
            "text-anchor": "middle",
          },
          Math.round((maxCount * tick) / 4),
        ),
      );
    }

    groups.forEach(function (group, index) {
      const y = chartTop + index * rowHeight + 5;
      const width = ((chartRight - chartLeft) * group.count) / maxCount;
      elements.trendSvg.appendChild(
        makeSvgElement(
          "text",
          {
            x: chartLeft - 14,
            y: y + barHeight / 2 + 4,
            "text-anchor": "end",
          },
          group.label,
        ),
      );
      const bar = makeSvgElement("rect", {
        x: chartLeft,
        y: y,
        width: Math.max(group.count ? 4 : 0, width),
        height: barHeight,
        rx: 6,
        fill: group.color,
        class: "trend-bar",
      });
      const barTitle = makeSvgElement("title", {}, group.label + ": " + group.count);
      bar.appendChild(barTitle);
      elements.trendSvg.appendChild(bar);
      elements.trendSvg.appendChild(
        makeSvgElement(
          "text",
          {
            x: Math.min(chartRight - 2, chartLeft + width + 10),
            y: y + barHeight / 2 + 4,
            "font-weight": "700",
          },
          group.count,
        ),
      );
    });
  }

  function setView(view, updateAddress) {
    state.view = VALID_VIEWS.has(view) ? view : "cards";
    document.querySelectorAll("[data-view]").forEach(function (button) {
      const selected = button.dataset.view === state.view;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", selected ? "true" : "false");
    });
    renderIndicators();
    if (updateAddress !== false) {
      updateUrl();
    }
  }

  function populateMeasurementIndicators() {
    if (!elements.measurementIndicator || !state.overview) {
      return;
    }
    const currentValue = elements.measurementIndicator.value;
    elements.measurementIndicator.replaceChildren();
    appendOption(elements.measurementIndicator, "", "Selecione um indicador");

    const indicators = asArray(state.overview.indicators);
    const groups = new Map();
    indicators.forEach(function (indicator) {
      const key = indicator.dimension.name + " — " + indicator.axis.name;
      if (!groups.has(key)) {
        groups.set(key, []);
      }
      groups.get(key).push(indicator);
    });
    groups.forEach(function (items, label) {
      const optgroup = document.createElement("optgroup");
      optgroup.label = label;
      items.forEach(function (indicator) {
        const option = document.createElement("option");
        option.value = indicator.slug;
        option.textContent = indicator.name;
        optgroup.appendChild(option);
      });
      elements.measurementIndicator.appendChild(optgroup);
    });
    elements.measurementIndicator.value = currentValue;
  }

  function resolveInitialYear(payload) {
    if (!state.initialYearPending) {
      return false;
    }
    const years = asArray(payload.years).map(function (year) {
      return String(year);
    });
    const desiredYear = years.includes("2024") ? "2024" : years.length ? years[0] : "";
    const changed = state.filters.year !== desiredYear;
    state.filters.year = desiredYear;
    state.initialYearPending = false;
    updateUrl();
    return changed;
  }

  async function loadOverview(options) {
    const settings = options || {};
    if (state.overviewController) {
      state.overviewController.abort();
    }
    const controller = new AbortController();
    state.overviewController = controller;
    setBusy(true);
    if (state.firstLoad) {
      elements.loadingState.hidden = false;
      elements.dashboardContent.hidden = true;
    }
    elements.errorState.hidden = true;

    try {
      const payload = await fetchJson(buildApiUrl(root.dataset.overviewUrl), {
        method: "GET",
        signal: controller.signal,
      });
      if (controller !== state.overviewController) {
        return;
      }
      if (resolveInitialYear(payload || {})) {
        await loadOverview(settings);
        return;
      }
      state.overview = payload || {};
      populateFilterControls(state.overview);
      renderCoverage(state.overview);
      renderCounts(state.overview);
      renderMetadata(state.overview);
      renderDimensions(state.overview.dimensions);
      populateMeasurementIndicators();
      applyClientFilters();
      elements.loadingState.hidden = true;
      elements.errorState.hidden = true;
      elements.dashboardContent.hidden = false;
      state.firstLoad = false;
      if (settings.announce) {
        announce("Painel atualizado. " + state.visibleIndicators.length + " indicadores exibidos.");
      }
      if (state.pendingIndicatorSlug && !state.activeSlug) {
        const pendingSlug = state.pendingIndicatorSlug;
        state.pendingIndicatorSlug = "";
        openDetail(pendingSlug, { updateUrl: false });
      } else if (settings.refreshDetail && state.activeSlug) {
        loadDetail(state.activeSlug);
      }
      loadFreshness({ announce: false });
    } catch (error) {
      if (error.name === "AbortError") {
        return;
      }
      showMainError(error.message);
      updateFreshnessChip("error", "Falha na consulta");
    } finally {
      if (controller === state.overviewController) {
        state.overviewController = null;
        setBusy(false);
      }
    }
  }

  function updateFreshnessChip(mode, text) {
    elements.connectionStatus.classList.remove(
      "freshness-chip--loading",
      "freshness-chip--fresh",
      "freshness-chip--stale",
      "freshness-chip--error",
    );
    elements.connectionStatus.classList.add("freshness-chip--" + mode);
    setText(elements.connectionStatusText, text);
  }

  function renderFreshness(payload) {
    const counts = payload.counts || {};
    const stale = Number(counts.stale) || 0;
    const fresh = Number(counts.fresh) || 0;
    const noData = Number(counts.no_data) || 0;
    const indicators = Number(counts.indicators) || 0;
    if (!indicators) {
      updateFreshnessChip("stale", "Sem indicadores");
    } else if (stale > 0) {
      updateFreshnessChip(
        "stale",
        stale + " " + pluralize(stale, "dado desatualizado", "dados desatualizados"),
      );
    } else if (fresh > 0) {
      updateFreshnessChip("fresh", "Dados verificados");
    } else if (noData === indicators) {
      updateFreshnessChip("stale", "Aguardando dados");
    } else {
      updateFreshnessChip("fresh", "Atualização verificada");
    }
    if (payload.latest_update) {
      setText(elements.lastFreshnessText, "Dados atualizados em " + formatDateTime(payload.latest_update));
    }
  }

  async function loadFreshness(options) {
    const settings = options || {};
    if (state.freshnessController) {
      state.freshnessController.abort();
    }
    const controller = new AbortController();
    state.freshnessController = controller;
    state.lastFreshnessRequestAt = Date.now();
    if (!state.freshness) {
      updateFreshnessChip("loading", "Verificando dados");
    }
    try {
      const payload = await fetchJson(buildApiUrl(root.dataset.freshnessUrl), {
        method: "GET",
        signal: controller.signal,
      });
      if (controller !== state.freshnessController) {
        return;
      }
      state.freshness = payload || {};
      renderFreshness(state.freshness);
      if (settings.announce) {
        announce("Situação de atualização dos dados verificada.");
      }
    } catch (error) {
      if (error.name === "AbortError") {
        return;
      }
      updateFreshnessChip("error", "Freshness indisponível");
    } finally {
      if (controller === state.freshnessController) {
        state.freshnessController = null;
      }
    }
  }

  function selectDimension(slug) {
    state.filters.dimension = state.filters.dimension === slug ? "" : slug;
    state.filters.axis = "";
    updateUrl();
    loadOverview({ announce: true });
  }

  function updateFiltersFromControls() {
    state.filters.year = elements.yearFilter.value;
    state.filters.dimension = elements.dimensionFilter.value;
    state.filters.axis = elements.axisFilter.value;
    state.filters.q = elements.searchFilter.value.trim();
    state.filters.status = VALID_STATUS_FILTERS.has(elements.statusFilter.value)
      ? elements.statusFilter.value
      : "";
  }

  function onServerFilterChange(event) {
    if (event && event.target === elements.dimensionFilter) {
      elements.axisFilter.value = "";
    }
    updateFiltersFromControls();
    updateUrl();
    loadOverview({ announce: true });
  }

  function onStatusChange() {
    state.filters.status = VALID_STATUS_FILTERS.has(elements.statusFilter.value)
      ? elements.statusFilter.value
      : "";
    applyClientFilters();
    announce(state.visibleIndicators.length + " indicadores após filtrar a situação.");
  }

  function onSearchInput() {
    window.clearTimeout(state.searchTimer);
    state.searchTimer = window.setTimeout(function () {
      state.filters.q = elements.searchFilter.value.trim();
      updateUrl();
      loadOverview({ announce: true });
    }, SEARCH_DELAY_MS);
  }

  function clearFilters() {
    window.clearTimeout(state.searchTimer);
    state.filters = { year: "", dimension: "", axis: "", q: "", status: "" };
    syncStaticFilterControls();
    updateUrl();
    loadOverview({ announce: true });
  }

  function setFiltersOpen(isOpen) {
    if (!elements.filterBar || !elements.toggleFiltersButton) {
      return;
    }
    elements.filterBar.classList.toggle("is-open", isOpen);
    elements.toggleFiltersButton.setAttribute("aria-expanded", isOpen ? "true" : "false");
  }

  function getFocusable(container) {
    return Array.from(
      container.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ).filter(function (element) {
      return !element.hidden && element.getAttribute("aria-hidden") !== "true";
    });
  }

  function trapFocus(event, container) {
    if (event.key !== "Tab") {
      return;
    }
    const focusable = getFocusable(container);
    if (!focusable.length) {
      event.preventDefault();
      container.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function showDrawer() {
    elements.detailBackdrop.hidden = false;
    elements.detailDrawer.setAttribute("aria-hidden", "false");
    document.body.classList.add("has-open-dialog");
    window.requestAnimationFrame(function () {
      elements.detailBackdrop.classList.add("is-open");
      elements.detailDrawer.classList.add("is-open");
    });
  }

  function closeDetail(options) {
    const settings = options || {};
    if (!state.activeSlug && elements.detailDrawer.getAttribute("aria-hidden") === "true") {
      return;
    }
    if (state.detailController) {
      state.detailController.abort();
      state.detailController = null;
    }
    elements.detailDrawer.classList.remove("is-open");
    elements.detailBackdrop.classList.remove("is-open");
    elements.detailDrawer.setAttribute("aria-hidden", "true");
    window.setTimeout(function () {
      elements.detailBackdrop.hidden = true;
    }, 290);
    if (!elements.upsertDialog || !elements.upsertDialog.open) {
      document.body.classList.remove("has-open-dialog");
    }
    state.activeSlug = "";
    state.detail = null;
    if (settings.updateUrl !== false) {
      updateUrl();
    }
    if (settings.restoreFocus !== false && state.detailReturnFocus) {
      state.detailReturnFocus.focus();
    }
    state.detailReturnFocus = null;
  }

  function openDetail(slug, options) {
    if (!slug) {
      return;
    }
    const settings = options || {};
    state.detailReturnFocus = settings.trigger || document.activeElement;
    state.activeSlug = slug;
    if (settings.updateUrl !== false) {
      updateUrl({ push: true });
    }
    showDrawer();
    elements.detailLoading.hidden = false;
    elements.detailError.hidden = true;
    elements.detailContent.hidden = true;
    setText(elements.detailTitle, "Carregando indicador…");
    window.setTimeout(function () {
      elements.closeDetailButton.focus();
    }, 30);
    loadDetail(slug);
  }

  async function loadDetail(slug) {
    if (state.detailController) {
      state.detailController.abort();
    }
    const controller = new AbortController();
    state.detailController = controller;
    elements.detailLoading.hidden = false;
    elements.detailError.hidden = true;
    elements.detailContent.hidden = true;
    try {
      const payload = await fetchJson(detailUrlForSlug(slug), {
        method: "GET",
        signal: controller.signal,
      });
      if (controller !== state.detailController || state.activeSlug !== slug) {
        return;
      }
      state.detail = payload || {};
      renderDetail(state.detail);
      elements.detailLoading.hidden = true;
      elements.detailContent.hidden = false;
      setText(elements.detailTitle, state.detail.indicator ? state.detail.indicator.name : "Indicador");
    } catch (error) {
      if (error.name === "AbortError") {
        return;
      }
      elements.detailLoading.hidden = true;
      elements.detailContent.hidden = true;
      elements.detailError.hidden = false;
      const strong = elements.detailError.querySelector("strong");
      setText(strong, error.message, "Não foi possível abrir este indicador.");
    } finally {
      if (controller === state.detailController) {
        state.detailController = null;
      }
    }
  }

  function renderDetail(payload) {
    const indicator = payload.indicator || {};
    const current = indicator.current_measurement;
    const target = indicator.target || {};
    setText(elements.detailDimension, indicator.dimension ? indicator.dimension.name : "Indicador");
    setText(elements.detailTitle, indicator.name, "Detalhes do indicador");
    setText(elements.detailAxis, "Eixo: " + (indicator.axis ? indicator.axis.name : "não informado"));
    setText(
      elements.detailFrequency,
      indicator.frequency ? indicator.frequency.label : "Periodicidade não informada",
    );
    setText(
      elements.detailPolarity,
      indicator.polarity ? indicator.polarity.label : "Polaridade não informada",
    );
    applyKindBadge(elements.detailKind, indicator);
    setText(
      elements.detailDescription,
      indicator.description,
      "Descrição ainda não informada para este indicador.",
    );
    setText(elements.detailCurrentValue, formatValue(current ? current.value : null, indicator.unit));
    setText(elements.detailCurrentPeriod, formatPeriod(current));
    setText(elements.detailTargetValue, formatValue(target.effective_value, indicator.unit));
    setText(
      elements.detailTargetDeadline,
      target.deadline ? "Prazo: " + formatDate(target.deadline) : "Sem prazo definido",
    );
    applyStatusBadge(elements.detailStatus, indicator);
    setText(elements.detailDelta, formatDelta(indicator).text);
    setText(
      elements.detailMethodology,
      indicator.methodology,
      "Metodologia não informada.",
    );
    renderDetailSource(indicator, current);
    renderDetailSeries(asArray(payload.measurements), indicator);
  }

  function renderDetailSource(indicator, current) {
    const source = current && current.source ? current.source : indicator.source || {};
    const name = source.name || (indicator.source ? indicator.source.name : "") || "";
    const url = safeExternalUrl(source.url || (indicator.source ? indicator.source.url : ""));
    if (url) {
      elements.detailSourceLink.href = url;
      setText(elements.detailSourceLink, name || "Abrir fonte original");
      elements.detailSourceLink.hidden = false;
      elements.detailSourceText.hidden = true;
    } else {
      elements.detailSourceLink.hidden = true;
      elements.detailSourceLink.removeAttribute("href");
      elements.detailSourceText.hidden = false;
      setText(elements.detailSourceText, name, "Fonte não informada.");
    }
    const updated = current ? current.updated_at || current.observed_at : null;
    setText(
      elements.detailUpdatedAt,
      updated ? "Última atualização: " + formatDateTime(updated) : "Data de atualização não informada.",
    );
  }

  function numericMeasurements(measurements) {
    return measurements.filter(function (measurement) {
      return Number.isFinite(Number(measurement.value));
    });
  }

  function renderDetailSeries(measurements, indicator) {
    const selected = numericMeasurements(measurements);
    const count = selected.length;
    setText(
      elements.detailSeriesCount,
      count + " " + pluralize(count, "resultado", "resultados"),
    );
    elements.detailNoSeries.hidden = count !== 0;
    elements.detailChartWrap.hidden = count === 0;
    renderSeriesTable(selected, indicator);
    renderSeriesSvg(selected, indicator);
  }

  function renderSeriesTable(measurements, indicator) {
    elements.detailSeriesTableBody.replaceChildren();
    measurements.forEach(function (measurement) {
      const row = document.createElement("tr");
      const period = document.createElement("td");
      const value = document.createElement("td");
      const target = document.createElement("td");
      const quality = document.createElement("td");
      period.textContent = formatPeriod(measurement);
      value.textContent = formatValue(measurement.value, indicator.unit);
      target.textContent = formatValue(
        measurement.effective_target_value !== null &&
          measurement.effective_target_value !== undefined
          ? measurement.effective_target_value
          : measurement.target_value,
        indicator.unit,
      );
      quality.textContent =
        measurement.quality && measurement.quality.label
          ? measurement.quality.label
          : "Não informada";
      row.append(period, value, target, quality);
      elements.detailSeriesTableBody.appendChild(row);
    });
  }

  function linePath(points) {
    return points
      .map(function (point, index) {
        return (index ? "L" : "M") + point.x.toFixed(2) + " " + point.y.toFixed(2);
      })
      .join(" ");
  }

  function renderSeriesSvg(measurements, indicator) {
    elements.detailSeriesSvg.replaceChildren();
    const title = makeSvgElement(
      "title",
      { id: "detailChartTitle" },
      "Série histórica de " + (indicator.name || "indicador"),
    );
    const description = makeSvgElement(
      "desc",
      { id: "detailChartDescription" },
      measurements.length
        ? measurements.length + " resultados publicados, do mais antigo ao mais recente."
        : "Nenhum resultado publicado para este período.",
    );
    elements.detailSeriesSvg.append(title, description);
    setText(elements.detailChartDescription, description.textContent);
    if (!measurements.length) {
      return;
    }

    const width = 720;
    const height = 300;
    const margin = { top: 20, right: 24, bottom: 52, left: 72 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const values = measurements.map(function (measurement) {
      return Number(measurement.value);
    });
    const targets = measurements
      .map(function (measurement) {
        const value = measurement.effective_target_value;
        return value === null || value === undefined || value === "" ? NaN : Number(value);
      })
      .filter(Number.isFinite);
    let minimum = Math.min(...values, ...targets);
    let maximum = Math.max(...values, ...targets);
    if (minimum === maximum) {
      const padding = Math.abs(minimum || 1) * 0.1 || 1;
      minimum -= padding;
      maximum += padding;
    } else {
      const padding = (maximum - minimum) * 0.12;
      minimum -= padding;
      maximum += padding;
    }
    const scaleY = function (value) {
      return margin.top + ((maximum - value) / (maximum - minimum)) * plotHeight;
    };
    const scaleX = function (index) {
      if (measurements.length === 1) {
        return margin.left + plotWidth / 2;
      }
      return margin.left + (index / (measurements.length - 1)) * plotWidth;
    };

    for (let tick = 0; tick <= 4; tick += 1) {
      const y = margin.top + (plotHeight * tick) / 4;
      const value = maximum - ((maximum - minimum) * tick) / 4;
      elements.detailSeriesSvg.appendChild(
        makeSvgElement("line", {
          x1: margin.left,
          y1: y,
          x2: margin.left + plotWidth,
          y2: y,
          class: "chart-grid",
        }),
      );
      elements.detailSeriesSvg.appendChild(
        makeSvgElement(
          "text",
          {
            x: margin.left - 10,
            y: y + 4,
            "text-anchor": "end",
          },
          formatNumber(value),
        ),
      );
    }

    const points = measurements.map(function (measurement, index) {
      return {
        x: scaleX(index),
        y: scaleY(Number(measurement.value)),
        measurement: measurement,
      };
    });
    const areaPath =
      linePath(points) +
      " L" +
      points[points.length - 1].x.toFixed(2) +
      " " +
      (margin.top + plotHeight) +
      " L" +
      points[0].x.toFixed(2) +
      " " +
      (margin.top + plotHeight) +
      " Z";
    elements.detailSeriesSvg.appendChild(
      makeSvgElement("path", { d: areaPath, class: "series-area" }),
    );
    elements.detailSeriesSvg.appendChild(
      makeSvgElement("path", { d: linePath(points), class: "series-line" }),
    );

    const targetPoints = measurements
      .map(function (measurement, index) {
        const rawValue = measurement.effective_target_value;
        const value =
          rawValue === null || rawValue === undefined || rawValue === ""
            ? NaN
            : Number(rawValue);
        return Number.isFinite(value)
          ? { x: scaleX(index), y: scaleY(value), measurement: measurement }
          : null;
      })
      .filter(Boolean);
    if (targetPoints.length > 1) {
      elements.detailSeriesSvg.appendChild(
        makeSvgElement("path", { d: linePath(targetPoints), class: "target-line" }),
      );
    }

    const labelIndexes = new Set([
      0,
      measurements.length - 1,
      Math.floor((measurements.length - 1) / 2),
    ]);
    points.forEach(function (point, index) {
      const circle = makeSvgElement("circle", {
        cx: point.x,
        cy: point.y,
        r: 5,
        class: "series-point",
        tabindex: "0",
        role: "img",
        "aria-label":
          formatPeriod(point.measurement) +
          ": " +
          formatValue(point.measurement.value, indicator.unit),
      });
      circle.appendChild(
        makeSvgElement(
          "title",
          {},
          formatPeriod(point.measurement) +
            " — " +
            formatValue(point.measurement.value, indicator.unit),
        ),
      );
      elements.detailSeriesSvg.appendChild(circle);
      if (labelIndexes.has(index)) {
        elements.detailSeriesSvg.appendChild(
          makeSvgElement(
            "text",
            {
              x: point.x,
              y: margin.top + plotHeight + 28,
              "text-anchor": "middle",
            },
            formatShortPeriod(point.measurement.period_end),
          ),
        );
      }
    });
  }

  async function copyText(value, successMessage) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
      } else {
        const input = document.createElement("textarea");
        input.value = value;
        input.setAttribute("readonly", "");
        input.style.position = "fixed";
        input.style.opacity = "0";
        document.body.appendChild(input);
        input.select();
        const copied = document.execCommand("copy");
        input.remove();
        if (!copied) {
          throw new Error("Cópia indisponível");
        }
      }
      showToast(successMessage || "Link copiado.");
    } catch (error) {
      showToast("Não foi possível copiar automaticamente. Use a barra de endereço.", true);
    }
  }

  function csvCell(value) {
    const text = value === null || value === undefined ? "" : String(value);
    return '"' + text.replace(/"/g, '""') + '"';
  }

  function exportCsv() {
    if (!state.visibleIndicators.length) {
      showToast("Não há indicadores para exportar.", true);
      return;
    }
    const headers = [
      "Dimensão",
      "Eixo",
      "Indicador",
      "Classificação",
      "Unidade",
      "Resultado",
      "Início do período",
      "Fim do período",
      "Meta",
      "Situação",
      "Variação percentual",
      "Frequência",
      "Fonte",
      "Atualizado em",
    ];
    const rows = state.visibleIndicators.map(function (indicator) {
      const current = indicator.current_measurement || {};
      const target = indicator.target || {};
      return [
        indicator.dimension ? indicator.dimension.name : "",
        indicator.axis ? indicator.axis.name : "",
        indicator.name || "",
        indicator.kind ? indicator.kind.label : "",
        indicator.unit || "",
        current.value_exact || current.value || "",
        current.period_start || "",
        current.period_end || "",
        target.effective_value_exact || target.effective_value || "",
        indicator.status ? indicator.status.label : "",
        indicator.status && indicator.status.delta_percentage !== null
          ? indicator.status.delta_percentage
          : "",
        indicator.frequency ? indicator.frequency.label : "",
        current.source && current.source.name
          ? current.source.name
          : indicator.source
            ? indicator.source.name
            : "",
        current.updated_at || "",
      ];
    });
    const csv = [headers, ...rows]
      .map(function (row) {
        return row.map(csvCell).join(";");
      })
      .join("\r\n");
    const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const suffix = [state.filters.year, state.filters.dimension].filter(Boolean).join("-");
    link.href = url;
    link.download = "indicadores-rio-preto" + (suffix ? "-" + suffix : "") + ".csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 0);
    showToast(state.visibleIndicators.length + " indicadores exportados.");
  }

  function indicatorBySlug(slug) {
    if (!state.overview) {
      return null;
    }
    return (
      asArray(state.overview.indicators).find(function (indicator) {
        return indicator.slug === slug;
      }) || null
    );
  }

  function isoDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return year + "-" + month + "-" + day;
  }

  function suggestedPeriod(indicator) {
    const now = new Date();
    const selectedYear = Number(state.filters.year);
    const year = Number.isInteger(selectedYear) && selectedYear > 1900 ? selectedYear : now.getFullYear();
    const frequency = indicator && indicator.frequency ? indicator.frequency.code : "annual";
    let start = new Date(year, 0, 1);
    let end = new Date(year, 11, 31);
    if (frequency === "daily" || frequency === "real_time") {
      start = new Date(now);
      end = new Date(now);
    } else if (frequency === "weekly") {
      const day = now.getDay() || 7;
      start = new Date(now);
      start.setDate(now.getDate() - day + 1);
      end = new Date(start);
      end.setDate(start.getDate() + 6);
    } else if (frequency === "monthly") {
      const month = selectedYear ? 0 : now.getMonth();
      start = new Date(year, month, 1);
      end = new Date(year, month + 1, 0);
    } else if (frequency === "quarterly") {
      const quarterStart = selectedYear ? 0 : Math.floor(now.getMonth() / 3) * 3;
      start = new Date(year, quarterStart, 1);
      end = new Date(year, quarterStart + 3, 0);
    } else if (frequency === "semiannual") {
      const semesterStart = selectedYear ? 0 : now.getMonth() < 6 ? 0 : 6;
      start = new Date(year, semesterStart, 1);
      end = new Date(year, semesterStart + 6, 0);
    }
    return { start: isoDate(start), end: isoDate(end) };
  }

  function openUpsert(slug, trigger) {
    if (!elements.upsertDialog || !elements.upsertForm) {
      return;
    }
    state.upsertReturnFocus = trigger || document.activeElement;
    elements.upsertForm.reset();
    elements.upsertFormError.hidden = true;
    populateMeasurementIndicators();
    const indicator = indicatorBySlug(slug) || (state.detail ? state.detail.indicator : null);
    if (indicator && indicator.slug) {
      if (!Array.from(elements.measurementIndicator.options).some(function (option) {
        return option.value === indicator.slug;
      })) {
        appendOption(elements.measurementIndicator, indicator.slug, indicator.name || indicator.slug);
      }
      elements.measurementIndicator.value = indicator.slug;
      const period = suggestedPeriod(indicator);
      elements.measurementPeriodStart.value = period.start;
      elements.measurementPeriodEnd.value = period.end;
      const source = indicator.source || {};
      elements.measurementSourceName.value = source.name || "";
      elements.measurementSourceUrl.value = safeExternalUrl(source.url) || "";
    } else {
      const period = suggestedPeriod(null);
      elements.measurementPeriodStart.value = period.start;
      elements.measurementPeriodEnd.value = period.end;
    }
    document.body.classList.add("has-open-dialog");
    elements.upsertDialog.showModal();
    window.setTimeout(function () {
      elements.measurementIndicator.focus();
    }, 20);
  }

  function closeUpsert() {
    if (!elements.upsertDialog || !elements.upsertDialog.open) {
      return;
    }
    elements.upsertDialog.close();
  }

  function normalizedDecimal(value) {
    const text = String(value || "").trim();
    if (!text) {
      return "";
    }
    if (text.includes(",") && text.includes(".")) {
      return text.replace(/\./g, "").replace(",", ".");
    }
    return text.replace(",", ".");
  }

  function upsertPayload() {
    const payload = {
      indicator_slug: elements.measurementIndicator.value,
      period_start: elements.measurementPeriodStart.value,
      period_end: elements.measurementPeriodEnd.value,
      value: normalizedDecimal(elements.measurementValue.value),
      quality: elements.measurementQuality.value,
    };
    const optional = {
      target_value: normalizedDecimal(elements.measurementTarget.value),
      source_name: elements.measurementSourceName.value.trim(),
      source_url: elements.measurementSourceUrl.value.trim(),
      note: elements.measurementNote.value.trim(),
    };
    Object.entries(optional).forEach(function (entry) {
      if (entry[1] !== "") {
        payload[entry[0]] = entry[1];
      }
    });
    return payload;
  }

  function validateUpsertPayload(payload) {
    if (!payload.indicator_slug) {
      return "Selecione um indicador.";
    }
    if (!payload.period_start || !payload.period_end) {
      return "Informe o início e o fim do período.";
    }
    if (payload.period_end < payload.period_start) {
      return "O fim do período não pode ser anterior ao início.";
    }
    if (!payload.value || !Number.isFinite(Number(payload.value))) {
      return "Informe um resultado numérico válido.";
    }
    if (payload.target_value !== undefined && !Number.isFinite(Number(payload.target_value))) {
      return "Informe uma meta numérica válida.";
    }
    return "";
  }

  function csrfToken() {
    const input = elements.upsertForm
      ? elements.upsertForm.querySelector('input[name="csrfmiddlewaretoken"]')
      : null;
    return input ? input.value : "";
  }

  async function submitUpsert(event) {
    event.preventDefault();
    const payload = upsertPayload();
    const validationMessage = validateUpsertPayload(payload);
    if (validationMessage) {
      setText(elements.upsertFormError, validationMessage);
      elements.upsertFormError.hidden = false;
      return;
    }
    elements.upsertFormError.hidden = true;
    elements.submitUpsertButton.disabled = true;
    setText(elements.submitUpsertButton, "Salvando…");
    try {
      const result = await fetchJson(root.dataset.measurementsUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
        },
        body: JSON.stringify(payload),
      });
      const created = Number(result.created) || 0;
      const updated = Number(result.updated) || 0;
      const unchanged = Number(result.unchanged) || 0;
      let message = "Resultado salvo.";
      if (created) {
        message = "Novo resultado publicado.";
      } else if (updated) {
        message = "Resultado atualizado.";
      } else if (unchanged) {
        message = "O resultado já estava atualizado.";
      }
      closeUpsert();
      showToast(message);
      await loadOverview({ announce: true, refreshDetail: Boolean(state.activeSlug) });
    } catch (error) {
      setText(elements.upsertFormError, error.message);
      elements.upsertFormError.hidden = false;
    } finally {
      elements.submitUpsertButton.disabled = false;
      setText(elements.submitUpsertButton, "Salvar resultado");
    }
  }

  function handlePopState() {
    state.popstateInProgress = true;
    const nextFilters = readFiltersFromUrl();
    const hasYearParameter = new URLSearchParams(window.location.search).has("year");
    state.initialYearPending = !hasYearParameter;
    if (state.initialYearPending) {
      nextFilters.year = "2024";
    }
    const nextView = readViewFromUrl();
    const nextIndicator = readIndicatorFromUrl();
    const previousServerSignature = [
      state.filters.year,
      state.filters.dimension,
      state.filters.axis,
      state.filters.q,
    ].join("|");
    const nextServerSignature = [
      nextFilters.year,
      nextFilters.dimension,
      nextFilters.axis,
      nextFilters.q,
    ].join("|");
    state.filters = nextFilters;
    state.view = nextView;
    syncStaticFilterControls();
    setView(nextView, false);
    if (previousServerSignature !== nextServerSignature || !state.overview) {
      state.pendingIndicatorSlug = nextIndicator;
      if (state.activeSlug) {
        closeDetail({ updateUrl: false, restoreFocus: false });
      }
      loadOverview({ announce: false });
    } else {
      populateFilterControls(state.overview);
      applyClientFilters();
      if (nextIndicator && nextIndicator !== state.activeSlug) {
        openDetail(nextIndicator, { updateUrl: false });
      } else if (!nextIndicator && state.activeSlug) {
        closeDetail({ updateUrl: false, restoreFocus: false });
      }
    }
    state.popstateInProgress = false;
  }

  function bindEvents() {
    elements.filtersForm.addEventListener("submit", function (event) {
      event.preventDefault();
      window.clearTimeout(state.searchTimer);
      updateFiltersFromControls();
      updateUrl();
      loadOverview({ announce: true });
    });
    elements.yearFilter.addEventListener("change", onServerFilterChange);
    elements.dimensionFilter.addEventListener("change", onServerFilterChange);
    elements.axisFilter.addEventListener("change", onServerFilterChange);
    elements.statusFilter.addEventListener("change", onStatusChange);
    elements.searchFilter.addEventListener("input", onSearchInput);
    elements.clearFiltersButton.addEventListener("click", clearFilters);
    elements.emptyClearButton.addEventListener("click", clearFilters);
    elements.showAllDimensionsButton.addEventListener("click", function () {
      selectDimension(state.filters.dimension);
    });
    elements.toggleFiltersButton.addEventListener("click", function () {
      const expanded = elements.toggleFiltersButton.getAttribute("aria-expanded") === "true";
      setFiltersOpen(!expanded);
    });
    elements.refreshButton.addEventListener("click", function () {
      loadOverview({ announce: true, refreshDetail: Boolean(state.activeSlug) });
    });
    elements.retryButton.addEventListener("click", function () {
      loadOverview({ announce: true });
    });
    elements.copyLinkButton.addEventListener("click", function () {
      copyText(window.location.href, "Link desta visão copiado.");
    });
    elements.exportButton.addEventListener("click", exportCsv);
    document.querySelectorAll("[data-view]").forEach(function (button) {
      button.addEventListener("click", function () {
        setView(button.dataset.view, true);
      });
    });

    elements.closeDetailButton.addEventListener("click", function () {
      closeDetail();
    });
    elements.detailBackdrop.addEventListener("click", function () {
      closeDetail();
    });
    elements.retryDetailButton.addEventListener("click", function () {
      if (state.activeSlug) {
        loadDetail(state.activeSlug);
      }
    });
    elements.shareDetailButton.addEventListener("click", function () {
      copyText(window.location.href, "Link do indicador copiado.");
    });
    elements.detailDrawer.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && (!elements.upsertDialog || !elements.upsertDialog.open)) {
        event.preventDefault();
        closeDetail();
        return;
      }
      trapFocus(event, elements.detailDrawer);
    });

    if (elements.openUpsertButton) {
      elements.openUpsertButton.addEventListener("click", function (event) {
        openUpsert("", event.currentTarget);
      });
    }
    if (elements.detailUpsertButton) {
      elements.detailUpsertButton.addEventListener("click", function (event) {
        openUpsert(state.activeSlug, event.currentTarget);
      });
    }
    if (elements.upsertForm) {
      elements.upsertForm.addEventListener("submit", submitUpsert);
      elements.closeUpsertButton.addEventListener("click", closeUpsert);
      elements.cancelUpsertButton.addEventListener("click", closeUpsert);
      elements.upsertDialog.addEventListener("close", function () {
        if (!elements.detailDrawer.classList.contains("is-open")) {
          document.body.classList.remove("has-open-dialog");
        }
        if (state.upsertReturnFocus) {
          state.upsertReturnFocus.focus();
          state.upsertReturnFocus = null;
        }
      });
      elements.upsertDialog.addEventListener("cancel", function () {
        elements.upsertFormError.hidden = true;
      });
    }

    window.addEventListener("popstate", handlePopState);
    document.addEventListener("visibilitychange", function () {
      if (
        document.visibilityState === "visible" &&
        Date.now() - state.lastFreshnessRequestAt >= FRESHNESS_INTERVAL_MS
      ) {
        loadFreshness({ announce: false });
      }
    });
  }

  function startFreshnessPolling() {
    window.clearInterval(state.freshnessTimer);
    state.freshnessTimer = window.setInterval(function () {
      if (document.visibilityState === "visible") {
        loadFreshness({ announce: false });
      }
    }, FRESHNESS_INTERVAL_MS);
  }

  function initialize() {
    if (state.initialYearPending) {
      state.filters.year = "2024";
    }
    syncStaticFilterControls();
    bindEvents();
    setView(state.view, false);
    updateFilterSummary();
    loadOverview({ announce: false });
    startFreshnessPolling();
  }

  initialize();
})();
