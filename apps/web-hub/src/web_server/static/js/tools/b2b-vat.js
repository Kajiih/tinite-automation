/**
 * B2B Intra-EU VAT Automation Tool Controller
 */

import { setupDropzone } from "../components/dropzone.js";
import { downloadBlob } from "../components/download.js";
import { getPyodide } from "../pyodide-bridge.js";

let selectedReportFile = null;
let currentB2BResult = null;
let currentDeparture = "FR";
let currentDestinationFilter = "ALL";
let currentSearchText = "";

let showErrorCallback = null;
let hideErrorCallback = null;

export function initB2bVatTool(showError, hideError) {
  showErrorCallback = showError;
  hideErrorCallback = hideError;

  const dropzoneB2B = document.getElementById("dropzone-b2b");
  const fileB2BInput = document.getElementById("file-b2b");
  const badgeB2B = document.getElementById("badge-b2b");
  const labelB2B = document.getElementById("label-b2b");

  // Setup single CSV dropzone
  setupDropzone(dropzoneB2B, fileB2BInput, (files) => {
    selectedReportFile = files[0];
    badgeB2B.classList.remove("hidden");
    badgeB2B.textContent = `✓ ${selectedReportFile.name}`;
    labelB2B.textContent = "Click or drop to replace";
    if (hideErrorCallback) hideErrorCallback();
    executeB2BProcessing();
  }, ["csv"]);

  // Departure country change -> re-process
  document.getElementById("filter-b2b-departure").addEventListener("change", (e) => {
    currentDeparture = e.target.value;
    if (selectedReportFile) {
      executeB2BProcessing();
    }
  });

  // Destination country filter change
  document.getElementById("filter-b2b-destination").addEventListener("change", (e) => {
    currentDestinationFilter = e.target.value;
    renderFilteredB2BTable();
  });

  // Search input filter
  document.getElementById("filter-b2b-search").addEventListener("input", (e) => {
    currentSearchText = e.target.value;
    renderFilteredB2BTable();
  });

  // Reset filters
  document.getElementById("btn-reset-b2b-filters").addEventListener("click", () => {
    currentDestinationFilter = "ALL";
    currentSearchText = "";
    document.getElementById("filter-b2b-destination").value = "ALL";
    document.getElementById("filter-b2b-search").value = "";
    renderFilteredB2BTable();
  });

  // Download buttons
  document.getElementById("btn-download-b2b-summary").addEventListener("click", () => {
    const pyodide = getPyodide();
    if (!pyodide) return;
    try {
      const content = pyodide.FS.readFile("/b2b_summary.csv");
      const baseName = selectedReportFile ? selectedReportFile.name.replace(/\.[^/.]+$/, "") : "b2b_vat";
      downloadBlob(content, `${baseName}_b2b_vat_summary.csv`, "text/csv;charset=utf-8");
    } catch (err) {
      if (showErrorCallback) showErrorCallback("Download Error", "Could not export VAT summary CSV.", err.message);
    }
  });

  document.getElementById("btn-download-b2b-transactions").addEventListener("click", () => {
    const pyodide = getPyodide();
    if (!pyodide) return;
    try {
      const content = pyodide.FS.readFile("/b2b_transactions.csv");
      const baseName = selectedReportFile ? selectedReportFile.name.replace(/\.[^/.]+$/, "") : "b2b_vat";
      downloadBlob(content, `${baseName}_b2b_filtered_transactions.csv`, "text/csv;charset=utf-8");
    } catch (err) {
      if (showErrorCallback) showErrorCallback("Download Error", "Could not export transactions CSV.", err.message);
    }
  });
}

async function executeB2BProcessing() {
  const pyodide = getPyodide();
  if (!pyodide) {
    if (showErrorCallback) showErrorCallback("Engine Not Ready", "WebAssembly is still loading. Please wait a moment.");
    return;
  }

  if (!selectedReportFile) return;

  const loader = document.getElementById("processing-loader-b2b");
  const resultsSection = document.getElementById("results-section-b2b");
  loader.classList.remove("hidden");
  resultsSection.classList.add("hidden");
  if (hideErrorCallback) hideErrorCallback();

  try {
    const reportBuffer = await selectedReportFile.arrayBuffer();
    pyodide.FS.writeFile("/b2b_input.csv", new Uint8Array(reportBuffer));

    const pyCode = `run_b2b_vat("/b2b_input.csv", "${currentDeparture}", "/b2b_summary.csv", "/b2b_transactions.csv")`;
    const resultJsonString = pyodide.runPython(pyCode);
    currentB2BResult = JSON.parse(resultJsonString);

    currentDestinationFilter = "ALL";
    currentSearchText = "";
    document.getElementById("filter-b2b-search").value = "";

    populateDestinationFilterOptions();
    renderB2BView();
  } catch (err) {
    console.error("B2B processing error:", err);
    if (showErrorCallback) showErrorCallback("B2B Processing Error", err.message, err.toString());
  } finally {
    loader.classList.add("hidden");
  }
}

function renderB2BView() {
  if (!currentB2BResult) return;

  document.getElementById("results-section-b2b").classList.remove("hidden");
  document.getElementById("metric-b2b-matched-rows").textContent = Number(currentB2BResult.matched_rows_count).toLocaleString();
  document.getElementById("metric-b2b-unique-vats").textContent = Number(currentB2BResult.unique_vats_count).toLocaleString();
  document.getElementById("metric-b2b-sales").textContent = `€${Number(currentB2BResult.grand_total_selling_price).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  document.getElementById("metric-b2b-promos").textContent = `€${Number(currentB2BResult.grand_total_promo_amount).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  document.getElementById("metric-b2b-diff").textContent = `€${Number(currentB2BResult.grand_total_net_difference).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;

  renderFilteredB2BTable();
}

function populateDestinationFilterOptions() {
  const destSelect = document.getElementById("filter-b2b-destination");
  if (!currentB2BResult) return;

  const destSet = new Set();
  currentB2BResult.vat_summaries.forEach((s) => {
    s.destination_countries.forEach((c) => destSet.add(c));
  });

  const uniqueDests = Array.from(destSet).sort();
  const prevVal = destSelect.value;

  destSelect.innerHTML = '<option value="ALL">All Destinations</option>';
  uniqueDests.forEach((dest) => {
    const opt = document.createElement("option");
    opt.value = dest;
    opt.textContent = dest;
    destSelect.appendChild(opt);
  });

  destSelect.value = uniqueDests.includes(prevVal) ? prevVal : "ALL";
  currentDestinationFilter = destSelect.value;
}

function renderFilteredB2BTable() {
  const tbody = document.getElementById("table-b2b-body");
  const tfoot = document.getElementById("table-b2b-foot");
  const countStatus = document.getElementById("filter-b2b-status-count");
  const btnReset = document.getElementById("btn-reset-b2b-filters");

  if (!currentB2BResult) return;

  const searchLower = currentSearchText.trim().toLowerCase();
  const isFiltering = currentDestinationFilter !== "ALL" || searchLower !== "";

  if (isFiltering) btnReset.classList.remove("hidden");
  else btnReset.classList.add("hidden");

  const filteredSummaries = currentB2BResult.vat_summaries.filter((s) => {
    if (currentDestinationFilter !== "ALL" && !s.destination_countries.includes(currentDestinationFilter)) {
      return false;
    }
    if (searchLower) {
      const matchVat = s.buyer_vat.toLowerCase().includes(searchLower);
      const matchDest = s.destination_countries.some((c) => c.toLowerCase().includes(searchLower));
      if (!matchVat && !matchDest) return false;
    }
    return true;
  });

  countStatus.textContent = isFiltering
    ? `Showing ${filteredSummaries.length} of ${currentB2BResult.vat_summaries.length} VAT numbers`
    : `${currentB2BResult.vat_summaries.length} VAT numbers total`;

  if (filteredSummaries.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="px-5 py-8 text-center text-slate-400 font-sans text-xs">
          No B2B transactions match the selected filters.
        </td>
      </tr>
    `;
    tfoot.innerHTML = "";
    return;
  }

  let grandTransfers = 0;
  let grandSales = 0;
  let grandPromos = 0;
  let grandDiff = 0;

  const rowsHtml = filteredSummaries
    .map((s) => {
      grandTransfers += s.transaction_count;
      grandSales += s.total_tax_exclusive_price;
      grandPromos += s.total_tax_inclusive_promo;
      grandDiff += s.total_net_difference;

      const destBadges = s.destination_countries
        .map((c) => `<span class="bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded text-[11px] font-semibold border border-slate-200">${c}</span>`)
        .join(" ");

      return `
        <tr class="hover:bg-slate-50 transition-colors">
          <td class="px-5 py-2.5 font-bold text-slate-800">${s.buyer_vat}</td>
          <td class="px-5 py-2.5 font-sans">${destBadges}</td>
          <td class="px-5 py-2.5 text-right font-mono text-slate-600">${s.transaction_count.toLocaleString()}</td>
          <td class="px-5 py-2.5 text-right font-mono text-slate-800">€${s.total_tax_exclusive_price.toFixed(2)}</td>
          <td class="px-5 py-2.5 text-right font-mono text-slate-600">€${s.total_tax_inclusive_promo.toFixed(2)}</td>
          <td class="px-5 py-2.5 text-right font-mono font-semibold ${s.total_net_difference >= 0 ? 'text-emerald-700' : 'text-amber-700'}">€${s.total_net_difference.toFixed(2)}</td>
        </tr>
      `;
    })
    .join("");

  tbody.innerHTML = rowsHtml;

  const totalLabel = isFiltering ? "FILTERED TOTAL" : "TOTAL";
  tfoot.innerHTML = `
    <tr>
      <td class="px-5 py-3 text-slate-900" colspan="2">${totalLabel}</td>
      <td class="px-5 py-3 text-right font-mono text-slate-900">${grandTransfers.toLocaleString()}</td>
      <td class="px-5 py-3 text-right font-mono text-slate-900">€${grandSales.toFixed(2)}</td>
      <td class="px-5 py-3 text-right font-mono text-slate-900">€${grandPromos.toFixed(2)}</td>
      <td class="px-5 py-3 text-right font-mono text-blue-600 text-sm">€${grandDiff.toFixed(2)}</td>
    </tr>
  `;
}
