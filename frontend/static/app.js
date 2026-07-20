// Stock Analyzer - simple frontend logic
// All prices/history come from the backend, which fetches them live from
// Yahoo Finance via yfinance. The live price is refreshed every few seconds
// by polling /api/quote/{symbol} (a real network call, not a simulation).

const QUOTE_POLL_MS = 10000; // how often to re-fetch the live price

let currentSymbol = null;
let currentPeriod = "1y";
let quotePollTimer = null;
let searchDebounceTimer = null;

let displayCurrency = "NATIVE";
let nativeCurrency = "USD";
let exchangeRates = {};
let rawQuote = null;
let rawHistoryData = null;

const el = (id) => document.getElementById(id);
const setText = (id, value) => { const node = el(id); if (node) node.textContent = value; };

function fmtMoney(value, currencyCode) {
    if (value === null || value === undefined || isNaN(value)) return "--";
    try {
        return new Intl.NumberFormat(undefined, {
            style: 'currency',
            currency: currencyCode || 'USD',
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(value);
    } catch (e) {
        return (currencyCode || '$') + ' ' + Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
}

function fmtNumber(value) {
    if (value === null || value === undefined || isNaN(value)) return "--";
    return Number(value).toLocaleString();
}

function fmtCompact(value, currencyCode) {
    if (value === null || value === undefined || isNaN(value)) return "--";
    try {
        return new Intl.NumberFormat(undefined, {
            style: 'currency',
            currency: currencyCode || 'USD',
            notation: 'compact',
            maximumFractionDigits: 2
        }).format(value);
    } catch (e) {
        return (currencyCode || '$') + ' ' + Number(value).toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 2 });
    }
}

// ---------- Popular stocks ----------

async function loadPopularStocks() {
    const container = el("popular-list");
    try {
        const res = await fetch("/api/stocks");
        const stocks = await res.json();
        container.innerHTML = "";
        stocks.slice(0, 10).forEach((s) => {
            const btn = document.createElement("button");
            btn.className = "popular-chip";
            btn.textContent = s.symbol;
            btn.title = s.name;
            btn.addEventListener("click", () => loadStock(s.symbol));
            container.appendChild(btn);
        });
    } catch (e) {
        container.innerHTML = '<span class="loading-text">Could not load popular stocks.</span>';
    }
}

// ---------- Search ----------

function setupSearch() {
    const input = el("ticker-search");
    const suggestions = el("search-suggestions");

    input.addEventListener("input", () => {
        clearTimeout(searchDebounceTimer);
        const q = input.value.trim();
        if (!q) {
            suggestions.classList.add("hidden");
            return;
        }
        searchDebounceTimer = setTimeout(() => runSearch(q), 250);
    });

    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            const q = input.value.trim();
            if (q) loadStock(q.toUpperCase());
            suggestions.classList.add("hidden");
        }
    });

    el("search-btn").addEventListener("click", () => {
        const q = input.value.trim();
        if (q) loadStock(q.toUpperCase());
        suggestions.classList.add("hidden");
    });

    document.addEventListener("click", (e) => {
        if (!e.target.closest(".search-wrapper")) {
            suggestions.classList.add("hidden");
        }
    });
}

async function runSearch(query) {
    const suggestions = el("search-suggestions");
    try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
        const results = await res.json();
        if (!results.length) {
            suggestions.classList.add("hidden");
            return;
        }
        suggestions.innerHTML = "";
        results.forEach((r) => {
            const li = document.createElement("li");
            li.innerHTML = `<span class="s-symbol">${r.symbol}</span><span class="s-name">${r.name}</span>`;
            li.addEventListener("click", () => {
                el("ticker-search").value = "";
                suggestions.classList.add("hidden");
                loadStock(r.symbol);
            });
            suggestions.appendChild(li);
        });
        suggestions.classList.remove("hidden");
    } catch (e) {
        suggestions.classList.add("hidden");
    }
}

// ---------- Period buttons ----------

function setupPeriodButtons() {
    document.querySelectorAll(".period-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            if (!currentSymbol) return;
            document.querySelectorAll(".period-btn").forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            currentPeriod = btn.dataset.period;
            loadHistory(currentSymbol);
        });
    });
}

// ---------- Loading a stock ----------

async function loadStock(symbol) {
    currentSymbol = symbol.toUpperCase();
    stopQuotePolling();

    el("empty-state").classList.add("hidden");
    el("error-state").classList.add("hidden");
    el("stock-view").classList.remove("hidden");
    el("loader").classList.remove("hidden");

    setText("stock-symbol", currentSymbol);

    // Reset cached data
    rawQuote = null;
    rawHistoryData = null;

    await Promise.all([loadHistory(currentSymbol), fetchQuoteOnce(currentSymbol)]);

    el("loader").classList.add("hidden");
    startQuotePolling(currentSymbol);
}

async function loadHistory(symbol) {
    try {
        const res = await fetch(`/api/history/${encodeURIComponent(symbol)}?period=${currentPeriod}&interval=1d`);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `Could not load history for ${symbol}`);
        }
        rawHistoryData = await res.json();
        if (rawHistoryData.currency && !rawQuote) {
            // Best-effort currency guess until/unless the live quote (more
            // authoritative) succeeds and overrides this.
            nativeCurrency = rawHistoryData.currency;
            const select = el("currency-select");
            if (select && select.options[0]) {
                select.options[0].textContent = `Default (Native: ${nativeCurrency})`;
            }
        }
        renderStockHeader(rawHistoryData);
        await updateDisplay();
    } catch (e) {
        showError(e.message || "Something went wrong while loading this stock.");
    }
}

function renderStockHeader(data) {
    setText("stock-name", data.name || data.symbol);
    setText("stock-symbol", data.symbol);
}

async function updateDisplay() {
    if (!rawHistoryData) return;

    const targetCurrency = displayCurrency === "NATIVE" ? nativeCurrency : displayCurrency;

    let rate = 1.0;
    if (targetCurrency !== nativeCurrency) {
        rate = await getExchangeRate(nativeCurrency, targetCurrency);
    }

    // Chart and forecast only depend on history data, so render them as
    // soon as history is available - don't block on the live quote, which
    // can legitimately fail for some symbols (e.g. mutual funds, where
    // Yahoo's fast_info endpoint has no real-time price).
    renderChart(rawHistoryData, rate, targetCurrency);
    renderForecast(rawHistoryData, rate, targetCurrency);

    if (rawQuote) {
        renderQuote(rawQuote, rate, targetCurrency);
    }
}

async function getExchangeRate(base, target) {
    if (base === target) return 1.0;
    
    // Check cache
    if (exchangeRates[base] && exchangeRates[base][target]) {
        return exchangeRates[base][target];
    }
    
    try {
        const res = await fetch(`https://open.er-api.com/v6/latest/${base}`);
        if (!res.ok) throw new Error("Could not fetch exchange rates");
        const data = await res.json();
        if (data.rates) {
            exchangeRates[base] = data.rates;
            return data.rates[target] || 1.0;
        }
    } catch (e) {
        console.error("Exchange rate fetch failed:", e);
    }
    return 1.0; // fallback
}

function renderChart(data, rate = 1.0, targetCurrency) {
    const dates = data.history.map((h) => h.date);
    const closes = data.history.map((h) => h.close * rate);
    const sma20 = data.history.map((h) => h.sma20 ? h.sma20 * rate : null);
    const sma50 = data.history.map((h) => h.sma50 ? h.sma50 * rate : null);
    const currency = targetCurrency || "USD";

    const traces = [
        {
            x: dates,
            y: closes,
            type: "scatter",
            mode: "lines",
            name: "Close price",
            line: { color: "#a35d46", width: 2.5 },
        },
        {
            x: dates,
            y: sma20,
            type: "scatter",
            mode: "lines",
            name: "20-day average",
            line: { color: "#d15647", width: 1.5, dash: "dot" },
        },
        {
            x: dates,
            y: sma50,
            type: "scatter",
            mode: "lines",
            name: "50-day average",
            line: { color: "#3d7e52", width: 1.5, dash: "dot" },
        },
    ];

    const currencySymbols = {
        USD: "$", EUR: "€", GBP: "£", INR: "₹", JPY: "¥", CAD: "CA$", AUD: "A$"
    };
    const prefix = currencySymbols[currency] || (currency + " ");

    const layout = {
        margin: { l: 55, r: 20, t: 15, b: 40 },
        font: { family: "Inter, sans-serif", color: "#704f4b", size: 12 },
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        xaxis: { 
            gridcolor: "rgba(141, 79, 59, 0.08)", 
            showline: true, 
            linecolor: "rgba(141, 79, 59, 0.15)",
            zeroline: false
        },
        yaxis: { 
            gridcolor: "rgba(141, 79, 59, 0.08)", 
            tickprefix: prefix, 
            showline: true, 
            linecolor: "rgba(141, 79, 59, 0.15)",
            zeroline: false
        },
        legend: { 
            orientation: "h", 
            y: 1.08, 
            x: 0,
            font: { color: "#704f4b" }
        },
        hovermode: "x unified",
        hoverlabel: {
            bgcolor: "#3d2321",
            bordercolor: "rgba(141, 79, 59, 0.15)",
            font: { color: "#ffffff", family: "Inter, sans-serif" }
        }
    };

    Plotly.newPlot("price-chart", traces, layout, { displayModeBar: false, responsive: true });
}

function fmtForecastDate(dateStr) {
    try {
        const d = new Date(dateStr + "T00:00:00");
        return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
    } catch (e) {
        return dateStr;
    }
}

function renderForecast(data, rate = 1.0, targetCurrency) {
    const metrics = data.metrics || {};
    const currency = targetCurrency || "USD";

    if (metrics.directional_accuracy != null) {
        setText("forecast-accuracy", metrics.directional_accuracy.toFixed(1) + "%");
    } else {
        setText("forecast-accuracy", "--");
    }

    const listEl = el("forecast-7day-list");
    if (!listEl) return;
    listEl.innerHTML = "";

    const days = data.forecast_7day || [];
    days.forEach((day) => {
        const row = document.createElement("div");
        row.className = "forecast-day-row";

        const info = document.createElement("div");
        info.className = "forecast-day-info";

        const dateSpan = document.createElement("span");
        dateSpan.className = "forecast-day-date";
        dateSpan.textContent = fmtForecastDate(day.date);

        const priceSpan = document.createElement("span");
        priceSpan.className = "forecast-day-price";
        priceSpan.textContent = fmtMoney(day.predicted_close * rate, currency);

        info.appendChild(dateSpan);
        info.appendChild(priceSpan);

        const changeSpan = document.createElement("span");
        const pct = day.change_percent;
        const sign = pct > 0 ? "+" : "";
        changeSpan.textContent = `${sign}${pct.toFixed(2)}%`;
        changeSpan.className = "forecast-day-change " + (pct > 0 ? "positive" : pct < 0 ? "negative" : "neutral");

        row.appendChild(info);
        row.appendChild(changeSpan);
        listEl.appendChild(row);
    });
}

// ---------- Live quote polling (real fetch from Yahoo Finance) ----------

async function fetchQuoteOnce(symbol) {
    try {
        const res = await fetch(`/api/quote/${encodeURIComponent(symbol)}`);
        if (!res.ok) throw new Error("quote unavailable");
        rawQuote = await res.json();
        nativeCurrency = rawQuote.currency || "USD";
        
        const select = el("currency-select");
        if (select && select.options[0]) {
            select.options[0].textContent = `Default (Native: ${nativeCurrency})`;
        }
        
        await updateDisplay();
    } catch (e) {
        const liveStatus = el("live-status");
        if (liveStatus) liveStatus.className = "live-dot off";
        setText("updated-text", "Live price unavailable right now");
    }
}

function renderQuote(q, rate = 1.0, targetCurrency) {
    const currency = targetCurrency || q.currency || "USD";
    setText("stock-price", fmtMoney(q.price * rate, currency));

    const changeEl = el("stock-change");
    const convertedChange = q.change * rate;
    const sign = q.change > 0 ? "+" : "";
    if (changeEl) {
        changeEl.textContent = `${sign}${convertedChange.toFixed(2)} (${sign}${q.change_percent.toFixed(2)}%)`;
        changeEl.className = "change " + (q.change > 0 ? "positive" : q.change < 0 ? "negative" : "neutral");
    }

    setText("stat-open", fmtMoney(q.open * rate, currency));
    setText("stat-prev-close", fmtMoney(q.previous_close * rate, currency));
    setText("stat-high", fmtMoney(q.day_high * rate, currency));
    setText("stat-low", fmtMoney(q.day_low * rate, currency));
    setText("stat-volume", fmtNumber(q.volume));
    setText("stat-market-cap", q.market_cap ? fmtCompact(q.market_cap * rate, currency) : "--");

    const liveStatus = el("live-status");
    if (liveStatus) liveStatus.className = "live-dot on";
    const tzLabel = q.timezone || "IST";
    setText("updated-text", `Live price as of ${q.timestamp} ${tzLabel} (India)`);
}

function startQuotePolling(symbol) {
    stopQuotePolling();
    quotePollTimer = setInterval(() => fetchQuoteOnce(symbol), QUOTE_POLL_MS);
}

function stopQuotePolling() {
    if (quotePollTimer) {
        clearInterval(quotePollTimer);
        quotePollTimer = null;
    }
}

// ---------- Errors ----------

function showError(message) {
    el("stock-view").classList.add("hidden");
    el("error-state").classList.remove("hidden");
    setText("error-text", message);
}

function setupCurrencySelector() {
    const select = el("currency-select");
    if (select) {
        select.addEventListener("change", () => {
            displayCurrency = select.value;
            updateDisplay();
        });
    }
}

// ---------- Init ----------

document.addEventListener("DOMContentLoaded", () => {
    loadPopularStocks();
    setupSearch();
    setupPeriodButtons();
    setupCurrencySelector();
});
