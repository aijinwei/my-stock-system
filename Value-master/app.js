const API_BASE_URL = "http://127.0.0.1:8000/api";

const metricMeta = {
    pe: {
        label: "市盈率 TTM",
        suffix: "x",
        description: "盈利稳定指数常用指标，越低越便宜",
    },
    pb: {
        label: "市净率 LF",
        suffix: "x",
        description: "适合周期或重资产指数，越低越便宜",
    },
    ps: {
        label: "市销率",
        suffix: "x",
        description: "衡量营收相对估值，越低越便宜",
    },
    pcf: {
        label: "市现率",
        suffix: "x",
        description: "现金流敏感行业参考指标，越低越安全",
    },
    riskPremium: {
        label: "风险溢价",
        suffix: "%",
        description: "收益率与无风险利率差值，越高越安全边际",
    },
    dividend: {
        label: "股息率",
        suffix: "%",
        description: "高分红指数锚，越高越便宜",
    },
};

const state = {
    selectedIndex: "SH000300",
    range: 10,
    metric: "pe",
};

const dom = {
    chart: document.getElementById("valuationChart"),
    chartCard: document.querySelector(".chart-card"),
    chartTitle: document.getElementById("chartTitle"),
    chartSubtitle: document.getElementById("chartSubtitle"),
    heroName: document.getElementById("heroIndexName"),
    heroMetric: document.getElementById("heroMetric"),
    heroRange: document.getElementById("heroRange"),
    stats: {
        current: document.getElementById("statCurrent"),
        percentile: document.getElementById("statPercentile"),
        opportunity: document.getElementById("statOpportunity"),
        median: document.getElementById("statMedian"),
        danger: document.getElementById("statDanger"),
        indexClose: document.getElementById("statIndexClose"),
        range: document.getElementById("statRange"),
        avgStd: document.getElementById("statAvgStd"),
        stdBand: document.getElementById("statStdBand"),
        zScore: document.getElementById("statZScore"),
    },
    searchInput: document.getElementById("indexSearch"),
    clearSearch: document.getElementById("clearSearch"),
    searchButton: document.getElementById("searchButton"),
    searchStatus: document.getElementById("searchStatus"),
    rangeSelector: document.getElementById("rangeSelector"),
    metricSelector: document.getElementById("metricSelector"),
};

let indexUniverse = {};
let searchIndexCache = [];
let cachedHistory = [];
let useLiveApi = false;

init().catch((error) => {
    console.error("初始化失败", error);
    setChartStatus("初始化失败，请刷新重试", "error");
});

async function init() {
    attachEventListeners();
    await bootstrapData();
}

async function bootstrapData() {
    try {
        await loadIndexUniverseFromApi();
        useLiveApi = true;
    } catch (error) {
        console.warn("实时接口不可用，回退到示例数据", error);
        indexUniverse = buildMockIndexUniverse();
        searchIndexCache = Object.values(indexUniverse);
        useLiveApi = false;
    }

    if (!Object.keys(indexUniverse).length) {
        setChartStatus("暂无指数数据", "error");
        return;
    }

    if (!indexUniverse[state.selectedIndex]) {
        state.selectedIndex = Object.keys(indexUniverse)[0];
    }

    await updateDashboard();
}

async function loadIndexUniverseFromApi() {
    const response = await fetch(`${API_BASE_URL}/indices`, {
        headers: { Accept: "application/json" },
    });
    if (!response.ok) {
        throw new Error(`索引列表请求失败 ${response.status}`);
    }
    const payload = await response.json();
    if (!Array.isArray(payload)) {
        throw new Error("索引列表返回结构不正确");
    }
    indexUniverse = payload.reduce((map, item) => {
        if (!item.id) return map;
        map[item.id] = item;
        return map;
    }, {});
    searchIndexCache = payload;
}

function attachEventListeners() {
    const requestDashboardRefresh = () => {
        updateDashboard().catch((error) => {
            console.error("刷新仪表盘失败", error);
            setChartStatus("数据刷新失败", "error");
        });
    };

    dom.rangeSelector.addEventListener("click", (event) => {
        const btn = event.target.closest(".chip");
        if (!btn) return;
        const value = btn.dataset.range;
        state.range = value === "max" ? "max" : Number(value);
        updateActiveChips(dom.rangeSelector, btn);
        requestDashboardRefresh();
    });

    dom.metricSelector.addEventListener("click", (event) => {
        const btn = event.target.closest(".chip");
        if (!btn) return;
        const metric = btn.dataset.metric;
        if (!metricMeta[metric]) return;
        state.metric = metric;
        updateActiveChips(dom.metricSelector, btn);
        requestDashboardRefresh();
    });

    dom.clearSearch.addEventListener("click", () => {
        dom.searchInput.value = "";
        setSearchStatus("");
    });

    dom.searchButton.addEventListener("click", () => {
        handleManualSearch();
    });

    dom.searchInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            handleManualSearch();
        }
    });

    window.addEventListener("resize", () => {
        if (cachedHistory.length) {
            drawChart(cachedHistory);
        }
    });
}

function updateActiveChips(container, activeButton) {
    container.querySelectorAll(".chip").forEach((chip) => {
        chip.classList.toggle("chip--active", chip === activeButton);
    });
}

function selectIndex(id) {
    if (!indexUniverse[id]) return;
    state.selectedIndex = id;
    dom.searchInput.value = "";
    updateDashboard().catch((error) => {
        console.error("切换指数失败", error);
        setChartStatus("数据刷新失败", "error");
    });
}

async function updateDashboard() {
    const dataset = indexUniverse[state.selectedIndex];
    if (!dataset) {
        setChartStatus("未找到对应指数", "error");
        return;
    }

    setChartStatus("数据拉取中...", "loading");

    try {
        const { history, datasetMeta } = await resolveHistoryDataset(dataset);
        if (!history.length) {
            throw new Error("历史数据为空");
        }
        cachedHistory = history;
        const metricSeries = history
            .map((point) => point.metrics[state.metric])
            .filter((value) => typeof value === "number" && !Number.isNaN(value));
        if (!metricSeries.length) {
            throw new Error("缺少可用的估值序列");
        }
        const stats = computeStats(metricSeries);
        stats.indexClose = history[history.length - 1].indexValue;
        stats.samples = history.length;
        stats.startDate = history[0].date;
        stats.endDate = history[history.length - 1].date;

        renderStats(stats);
        renderHeaders(datasetMeta || dataset, stats);
        drawChart(history, stats);
        setChartStatus("");
    } catch (error) {
        console.error("更新仪表盘失败", error);
        setChartStatus("实时数据加载失败，请稍后重试", "error");
    }
}

async function resolveHistoryDataset(dataset) {
    if (useLiveApi) {
        const { history, meta } = await fetchHistoryFromApi(
            state.selectedIndex,
            state.metric,
            state.range,
        );
        const normalized = normalizeHistoryPoints(history);
        return {
            history: normalized,
            datasetMeta: meta || dataset,
        };
    }

    const maxMonths = dataset.data.length;
    const monthsToTake =
        state.range === "max" ? maxMonths : Math.min(state.range * 12, maxMonths);
    const history = dataset.data.slice(maxMonths - monthsToTake);
    return { history, datasetMeta: dataset };
}

async function fetchHistoryFromApi(indexId, metric, range) {
    const params = new URLSearchParams({
        metric,
        range: range === "max" ? "max" : String(range),
    });
    const response = await fetch(
        `${API_BASE_URL}/indices/${encodeURIComponent(indexId)}/history?${params}`, { headers: { Accept: "application/json" } },
    );
    if (!response.ok) {
        throw new Error(`历史数据请求失败 ${response.status}`);
    }
    const payload = await response.json();
    const rawPoints = Array.isArray(payload) ?
        payload :
        Array.isArray(payload.points) ?
        payload.points :
        Array.isArray(payload.history) ?
        payload.history : [];

    return {
        history: rawPoints,
        meta: payload.meta || payload.index || payload.summary,
    };
}

function normalizeHistoryPoints(rawPoints) {
    if (!Array.isArray(rawPoints)) return [];
    return rawPoints
        .map((point) => {
            if (!point) return null;
            const date = point.date || point.period || point.time;
            const indexValue = Number(
                point.indexValue ?? point.close ?? point.price ?? NaN,
            );
            const metrics =
                point.metrics && typeof point.metrics === "object"
                    ? point.metrics
                    : {
                          [state.metric]: point.metricValue ?? point.value,
                      };
            const metricValue = Number(metrics[state.metric]);
            if (!date || Number.isNaN(indexValue) || Number.isNaN(metricValue)) {
                return null;
            }
            return {
                date,
                indexValue,
                metrics: {
                    ...metrics,
                    [state.metric]: metricValue,
                },
            };
        })
        .filter(Boolean);
}

function computeStats(series) {
    if (!series.length) {
        return {
            current: 0,
            percentileRank: 0,
            opportunity: 0,
            median: 0,
            danger: 0,
            max: 0,
            min: 0,
            avg: 0,
            stdDev: 0,
            stdUpper: 0,
            stdLower: 0,
            zScore: 0,
        };
    }

  const invertedMetrics = new Set(["riskPremium", "dividend"]);
  const isInverted = invertedMetrics.has(state.metric);
  const sorted = [...series]
    .sort((a, b) => (isInverted ? b - a : a - b));
    const min = sorted[0];
    const max = sorted[sorted.length - 1];
    const current = series[series.length - 1];
    const sum = series.reduce((total, value) => total + value, 0);
    const avg = sum / series.length;
    const variance =
        series.reduce((total, value) => total + (value - avg) ** 2, 0) /
        Math.max(series.length, 1);
    const stdDev = Math.sqrt(variance);

    const opportunity = percentile(sorted, 0.2);
    const median = percentile(sorted, 0.5);
    const danger = percentile(sorted, 0.8);
  const percentileRank = getPercentileRank(sorted, current, isInverted);

    return {
        current,
        percentileRank,
        opportunity,
        median,
        danger,
        max,
        min,
        avg,
        stdDev,
        stdUpper: avg + stdDev,
        stdLower: avg - stdDev,
        zScore: stdDev ? (current - avg) / stdDev : 0,
    };
}

function percentile(sortedSeries, ratio) {
    if (!sortedSeries.length) return 0;
    const position = (sortedSeries.length - 1) * ratio;
    const lowerIndex = Math.floor(position);
    const upperIndex = Math.ceil(position);
    if (lowerIndex === upperIndex) {
        return sortedSeries[lowerIndex];
    }
    const interpolation = position - lowerIndex;
    return (
        sortedSeries[lowerIndex] +
        interpolation * (sortedSeries[upperIndex] - sortedSeries[lowerIndex])
    );
}

function getPercentileRank(sortedSeries, value, inverted = false) {
    if (!sortedSeries.length) return 0;
    let count = 0;
    for (const item of sortedSeries) {
        if (inverted) {
            if (item >= value) count += 1;
        } else if (item <= value) {
            count += 1;
        }
    }
    return count / sortedSeries.length;
}

function renderStats(stats) {
    const meta = metricMeta[state.metric];
    dom.stats.current.textContent = formatValue(stats.current, meta);
    dom.stats.percentile.textContent = `${(stats.percentileRank * 100).toFixed(
    2,
  )}%`;
    dom.stats.opportunity.textContent = formatValue(stats.opportunity, meta);
    dom.stats.median.textContent = formatValue(stats.median, meta);
    dom.stats.danger.textContent = formatValue(stats.danger, meta);
    dom.stats.indexClose.textContent = formatNumber(stats.indexClose);
    dom.stats.range.textContent = `${formatValue(stats.max, meta)} / ${formatValue(
    stats.min,
    meta,
  )}`;
    dom.stats.avgStd.textContent = `${formatValue(stats.avg, meta)} / ${
    stats.stdDev ? formatValue(stats.stdDev, meta) : "--"
  }`;
    dom.stats.stdBand.textContent = `${formatValue(stats.stdUpper, meta)} / ${formatValue(
    stats.stdLower,
    meta,
  )}`;
    dom.stats.zScore.textContent = stats.zScore ? stats.zScore.toFixed(2) : "--";
}

function renderHeaders(dataset, stats) {
    const meta = metricMeta[state.metric];
    dom.chartTitle.textContent = `${dataset.name ?? "未知指数"} · ${meta.label}`;
    const rangeText =
        state.range === "max" ? "成立以来" : `近 ${state.range} 年`;
    dom.chartSubtitle.textContent = `统计区间：${formatDate(
    stats.startDate,
  )} ~ ${formatDate(stats.endDate)} · 样本 ${
    stats.samples
  } 期 · ${meta.description} · ${useLiveApi ? "实时数据" : "示例数据"}`;

    dom.heroName.textContent = dataset.name ?? "--";
    dom.heroMetric.textContent = meta.label;
    dom.heroRange.textContent = rangeText;
}


function setChartStatus(message, mode) {
  if (!dom.chartCard) return;
  if (!message) {
    dom.chartCard.removeAttribute("data-status");
    dom.chartCard.classList.remove("is-loading", "is-error");
    return;
  }
  dom.chartCard.dataset.status = message;
  dom.chartCard.classList.toggle("is-loading", mode === "loading");
  dom.chartCard.classList.toggle("is-error", mode === "error");
  if (mode !== "loading" && mode !== "error") {
    dom.chartCard.classList.remove("is-loading", "is-error");
  }
}

function formatValue(value, meta) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return "--";
  }
  if (!meta) return value.toFixed(2);
  if (meta.suffix === "%") {
    return `${value.toFixed(2)}%`;
  }
  return `${value.toFixed(2)}${meta.suffix}`;
}

function formatNumber(value) {
  if (!value && value !== 0) return "--";
  return Number(value).toLocaleString("zh-CN", {
    maximumFractionDigits: 0,
  });
}

function formatDate(dateString) {
  if (!dateString) return "--";
  return dateString.slice(0, 7);
}

function buildMockIndexUniverse() {
    const configs = [
        {
            id: "SH000300",
            name: "沪深300",
            ticker: "000300.SH",
            alias: ["沪深300", "HS300", "沪300", "沪深300指数"],
            startYear: 2009,
            baseIndex: 3200,
            trend: 35,
            indexVol: 0.22,
            basePE: 12,
            basePB: 1.5,
            basePS: 1.2,
            basePCF: 8,
            baseDividend: 2.3,
            peStretch: 0.35,
            pbStretch: 0.22,
            psStretch: 0.2,
            pcfStretch: 0.25,
            dividendStretch: 0.3,
            peMin: 8,
            peMax: 25,
            pbMax: 3.2,
            psMax: 2.8,
            pcfMax: 15,
            riskFreeRate: 3,
        },
        {
            id: "NDX100",
            name: "纳斯达克100",
            ticker: "NDX.GI",
            alias: ["纳指100", "纳斯达克", "NDX", "QQQ"],
            startYear: 2010,
            baseIndex: 6000,
            trend: 85,
            indexVol: 0.32,
            basePE: 25,
            basePB: 4.8,
            basePS: 3.5,
            basePCF: 18,
            baseDividend: 0.9,
            peStretch: 0.5,
            pbStretch: 0.4,
            psStretch: 0.4,
            pcfStretch: 0.45,
            dividendStretch: 0.2,
            peMin: 12,
            peMax: 45,
            pbMax: 9,
            psMax: 6.5,
            pcfMax: 28,
            riskFreeRate: 2.5,
        },
        {
            id: "CSI-DIV",
            name: "中证红利",
            ticker: "000922.CSI",
            alias: ["中证红利", "红利指数", "CSI DIV"],
            startYear: 2008,
            baseIndex: 2800,
            trend: 18,
            indexVol: 0.16,
            basePE: 9,
            basePB: 1.2,
            basePS: 0.8,
            basePCF: 5.5,
            baseDividend: 4.2,
            peStretch: 0.22,
            pbStretch: 0.18,
            psStretch: 0.18,
            pcfStretch: 0.2,
            dividendStretch: 0.35,
            peMin: 5,
            peMax: 16,
            pbMax: 2.3,
            psMax: 1.5,
            pcfMax: 9,
            riskFreeRate: 3.2,
        },
        {
            id: "CSI-SEM",
            name: "中证半导体",
            ticker: "000939.CSI",
            alias: ["半导体指数", "芯片指数", "CSI Semi"],
            startYear: 2012,
            baseIndex: 1600,
            trend: 30,
            indexVol: 0.38,
            basePE: 35,
            basePB: 4,
            basePS: 5.2,
            basePCF: 22,
            baseDividend: 0.6,
            peStretch: 0.6,
            pbStretch: 0.45,
            psStretch: 0.5,
            pcfStretch: 0.55,
            dividendStretch: 0.18,
            peMin: 15,
            peMax: 70,
            pbMax: 7,
            psMax: 8.5,
            pcfMax: 40,
            riskFreeRate: 2.8,
        },
    ];

  return configs.reduce((acc, cfg) => {
    acc[cfg.id] = {
      ...cfg,
      data: generateHistoricalData(cfg),
    };
    return acc;
  }, {});
}

function generateHistoricalData(cfg) {
  const now = new Date();
  const durationYears = now.getUTCFullYear() - cfg.startYear + 1;
  const months = durationYears * 12;
  const startDate = new Date(Date.UTC(cfg.startYear, 0, 1));
  const result = [];

  for (let i = 0; i < months; i += 1) {
    const timestamp = new Date(startDate);
    timestamp.setMonth(startDate.getMonth() + i);
    const cycle = Math.sin(i / 7) * 0.8 + Math.cos(i / 17) * 0.4;
    const noise = (Math.random() - 0.5) * 0.5;
    const composite = cycle + noise;
    const indexValue = Math.max(
      200,
      Math.round(
        (cfg.baseIndex + i * cfg.trend) * (1 + composite * cfg.indexVol),
      ),
    );
    const pe = clamp(
      cfg.basePE * (1 + composite * cfg.peStretch) + Math.random(),
      cfg.peMin,
      cfg.peMax,
    );
    const pb = clamp(
      cfg.basePB * (1 + composite * cfg.pbStretch) +
        (Math.random() - 0.5) * 0.3,
      0.6,
      cfg.pbMax,
    );
    const ps = clamp(
      cfg.basePS * (1 + composite * cfg.psStretch) +
        (Math.random() - 0.5) * 0.2,
      0.4,
      cfg.psMax,
    );
    const pcf = clamp(
      cfg.basePCF * (1 + composite * cfg.pcfStretch) +
        (Math.random() - 0.5) * 1.5,
      1,
      cfg.pcfMax,
    );
    const dividend = clamp(
      cfg.baseDividend *
        (1 - composite * cfg.dividendStretch) +
        (Math.random() - 0.5) * 0.4,
      0.4,
      8,
    );
    const earningsYield = pe ? 100 / pe : null;
    const riskPremium =
      earningsYield !== null && earningsYield !== undefined
        ? earningsYield - (cfg.riskFreeRate ?? 3)
        : null;

    result.push({
      date: timestamp.toISOString().slice(0, 10),
      indexValue,
      metrics: {
        pe: round(pe, 2),
        pb: round(pb, 2),
        ps: round(ps, 2),
        pcf: round(pcf, 2),
        dividend: round(dividend, 2),
        riskPremium: riskPremium !== null ? round(riskPremium, 2) : null,
      },
    });
  }
  return result;
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function round(value, decimals = 2) {
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}

function drawChart(history, stats) {
  const canvas = dom.chart;
  const context = canvas.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth * ratio;
  const height = canvas.clientHeight * ratio;

  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }

  context.clearRect(0, 0, width, height);

  const margin = {
    top: 40 * ratio,
    right: 80 * ratio,
    bottom: 40 * ratio,
    left: 80 * ratio,
  };
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;
  if (!history.length) return;

  const sanitizedMetrics = [];
  let lastValidMetric =
    typeof stats.current === "number" && !Number.isNaN(stats.current)
      ? stats.current
      : 0;
  history.forEach((point) => {
    const value = point.metrics[state.metric];
    if (typeof value === "number" && !Number.isNaN(value)) {
      lastValidMetric = value;
    }
    sanitizedMetrics.push(lastValidMetric);
  });
  const metricSeries = sanitizedMetrics;
  const metricMin = Math.min(
    stats.opportunity,
    stats.median,
    stats.danger,
    ...metricSeries,
  );
  const metricMax = Math.max(
    stats.opportunity,
    stats.median,
    stats.danger,
    ...metricSeries,
  );
  const metricPadding = (metricMax - metricMin || 1) * 0.15;
  const axisMin = metricMin - metricPadding;
  const axisMax = metricMax + metricPadding;
  const axisRange = axisMax - axisMin || 1;

  const indexSeries = history.map((point) => point.indexValue);
  const idxMin = Math.min(...indexSeries);
  const idxMax = Math.max(...indexSeries);

  const mapX = (idx) => {
    if (history.length === 1) return margin.left + chartWidth / 2;
    return margin.left + (idx / (history.length - 1)) * chartWidth;
  };
  const mapMetric = (value) =>
    margin.top +
    chartHeight -
    ((value - axisMin) / (axisMax - axisMin || 1)) * chartHeight;
  const mapIndex = (value) =>
    margin.top +
    chartHeight -
    ((value - idxMin) / (idxMax - idxMin || 1)) * chartHeight;

  context.beginPath();
  context.moveTo(mapX(0), margin.top + chartHeight);
  history.forEach((point, idx) => {
    const x = mapX(idx);
    const y = mapMetric(metricSeries[idx]);
    context.lineTo(x, y);
  });
  context.lineTo(mapX(history.length - 1), margin.top + chartHeight);
  context.closePath();
  const areaGradient = context.createLinearGradient(
    0,
    margin.top,
    0,
    margin.top + chartHeight,
  );
  areaGradient.addColorStop(0, "rgba(59,130,246,0.55)");
  areaGradient.addColorStop(1, "rgba(59,130,246,0.05)");
  context.fillStyle = areaGradient;
  context.fill();

  context.beginPath();
  history.forEach((point, idx) => {
    const x = mapX(idx);
    const y = mapMetric(metricSeries[idx]);
    if (idx === 0) {
      context.moveTo(x, y);
    } else {
      context.lineTo(x, y);
    }
  });
  context.lineWidth = 2 * ratio;
  context.strokeStyle = "rgba(15, 76, 129, 0.8)";
  context.stroke();

  const lines = [
    { value: stats.opportunity, color: "#10b981", label: "20%" },
    { value: stats.median, color: "#94a3b8", label: "50%" },
    { value: stats.danger, color: "#ef4444", label: "80%" },
  ];

  lines.forEach((line) => {
    const y = mapMetric(line.value);
    context.save();
    context.setLineDash([6 * ratio, 6 * ratio]);
    context.beginPath();
    context.moveTo(margin.left, y);
    context.lineTo(width - margin.right, y);
    context.strokeStyle = line.color;
    context.lineWidth = 1.3 * ratio;
    context.stroke();
    context.restore();

    context.fillStyle = line.color;
    context.font = `${12 * ratio}px "Segoe UI", sans-serif`;
    context.fillText(line.label, width - margin.right + 8 * ratio, y + 4 * ratio);
  });

  context.beginPath();
  history.forEach((point, idx) => {
    const x = mapX(idx);
    const y = mapIndex(point.indexValue);
    if (idx === 0) {
      context.moveTo(x, y);
    } else {
      context.lineTo(x, y);
    }
  });
  context.strokeStyle = "#8b5cf6";
  context.lineWidth = 2.6 * ratio;
  context.stroke();

  const ticks = [0, Math.floor(history.length / 2), history.length - 1].filter(
    (idx, pos, arr) => history[idx] && arr.indexOf(idx) === pos,
  );
  context.fillStyle = "#475467";
  context.font = `${12 * ratio}px "Segoe UI", sans-serif`;
  ticks.forEach((idx) => {
    const x = mapX(idx);
    const dateLabel = formatDate(history[idx].date);
    context.fillText(dateLabel, x - 20 * ratio, height - 10 * ratio);
  });

  const meta = metricMeta[state.metric];
  const metricTicks = [
    axisMin,
    axisMin + axisRange * 0.25,
    axisMin + axisRange * 0.5,
    axisMin + axisRange * 0.75,
    axisMax,
  ];
  context.font = `${11 * ratio}px "Segoe UI", sans-serif`;
  context.fillStyle = "#94a3b8";
  context.textAlign = "right";
  metricTicks.forEach((value) => {
    const y = mapMetric(value);
    context.fillText(formatValue(value, meta), margin.left - 10 * ratio, y + 4 * ratio);
  });

  const indexTicks = [idxMin, idxMin + (idxMax - idxMin) * 0.25, idxMin + (idxMax - idxMin) * 0.5, idxMin + (idxMax - idxMin) * 0.75, idxMax];
  context.textAlign = "left";
  indexTicks.forEach((value) => {
    const y = mapIndex(value);
    context.fillText(formatNumber(value), width - margin.right + 10 * ratio, y + 4 * ratio);
  });

  context.save();
  context.translate(18 * ratio, height / 2);
  context.rotate(-Math.PI / 2);
  context.textAlign = "center";
  context.fillStyle = "#475467";
  context.fillText(meta.label, 0, 0);
  context.restore();

  context.save();
  context.translate(width - 18 * ratio, height / 2);
  context.rotate(Math.PI / 2);
  context.textAlign = "center";
  context.fillStyle = "#475467";
  context.fillText("指数点位", 0, 0);
  context.restore();
}
function handleManualSearch() {
  const query = dom.searchInput.value.trim();
  const resultsEl = ensureSearchResultsContainer();
  resultsEl.classList.remove("active");
  resultsEl.innerHTML = "";
  if (!query) {
    setSearchStatus("请输入股票 / 指数 / ETF 名称或代码", true);
    return;
  }
  const matches = findCandidates(query);
  if (!matches.length) {
    setSearchStatus("当前数据源暂未覆盖该标的", true);
    return;
  }
  renderSearchResults(matches);
}

function findCandidates(query) {
  const normalized = query.toLowerCase();
  const dataset =
    searchIndexCache.length
      ? searchIndexCache
      : Object.values(indexUniverse);
  const sanitize = (value) =>
    value?.toString().toLowerCase().replace(/\.sh|\.sz|\.gi|\.hk|\.si/g, "");
  return dataset.filter((item) => {
    const rawTokens = [
      item.name,
      item.ticker,
      item.ts_code,
      item.id,
      ...(item.alias || []),
    ].filter(Boolean);
    const lowered = rawTokens.map((token) =>
      token.toString().toLowerCase(),
    );
    const expanded = [...lowered];
    lowered.forEach((token) => {
      const cleaned = sanitize(token);
      if (cleaned && cleaned !== token) {
        expanded.push(cleaned);
      }
    });
    return expanded.some(
      (token) => token && token.includes(normalized),
    );
  });
}

function renderSearchResults(list) {
  const resultsEl = ensureSearchResultsContainer();
  resultsEl.onclick = null;
  if (!list || !list.length) {
    resultsEl.classList.remove("active");
    resultsEl.innerHTML = "";
    return;
  }
  resultsEl.classList.add("active");
  resultsEl.innerHTML = list
    .slice(0, 8)
    .map((item) => {
      const tokens = [
        item.ticker,
        item.ts_code && item.ts_code !== item.ticker ? item.ts_code : null,
        item.kind ? `(${item.kind.toUpperCase()})` : null,
      ]
        .filter(Boolean)
        .join(" ");
      return `
        <div class="search-result-item" data-id="${item.id}" data-name="${item.name ?? item.id}">
          <strong>${item.name ?? item.id}</strong>
          <span>${tokens || "—"}</span>
        </div>
      `;
    })
    .join("");
  resultsEl.onclick = (event) => {
    const card = event.target.closest(".search-result-item");
    if (!card) return;
    const id = card.dataset.id;
    selectIndex(id);
    resultsEl.classList.remove("active");
    resultsEl.innerHTML = "";
    dom.searchInput.value = card.dataset.name || id;
    setSearchStatus(`已切换至 ${card.dataset.name || id}`, false);
  };
}

function ensureSearchResultsContainer() {
  if (dom.searchResults) return dom.searchResults;
  const wrapper = document.querySelector(".search-group");
  const fallback = document.createElement("div");
  fallback.id = "searchResults";
  fallback.className = "search-results";
  wrapper?.insertBefore(fallback, dom.searchStatus);
  dom.searchResults = fallback;
  return fallback;
}

function setSearchStatus(message, isError = false) {
  dom.searchStatus.textContent = message || "";
  dom.searchStatus.classList.toggle(
    "search-status--error",
    Boolean(isError && message),
  );
  dom.searchStatus.classList.toggle(
    "search-status--success",
    Boolean(!isError && message),
  );
  if (!message) {
    dom.searchStatus.classList.remove(
      "search-status--error",
      "search-status--success",
    );
  }
}
