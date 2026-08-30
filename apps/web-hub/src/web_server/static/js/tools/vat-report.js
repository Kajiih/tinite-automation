/**
 * VAT Report Automation Tool Controller
 */

import { setupDropzone } from "../components/dropzone.js";
import { downloadBlob, downloadZipArchive } from "../components/download.js";
import { getPyodide } from "../pyodide-bridge.js";

let selectedReportFiles = [];
let selectedCatalogFile = null;
let currentProcessingResult = null;
let activeFileIndex = "all";
let currentDepartureFilter = "ALL";
let currentArrivalFilter = "ALL";
let currentSearchText = "";

let showErrorCallback = null;
let hideErrorCallback = null;

export function initVatReportTool(showError, hideError) {
  showErrorCallback = showError;
  hideErrorCallback = hideError;

  const dropzoneReport = document.getElementById("dropzone-report");
  const dropzoneCatalog = document.getElementById("dropzone-catalog");
  const fileReportInput = document.getElementById("file-report");
  const fileCatalogInput = document.getElementById("file-catalog");
  const badgeReport = document.getElementById("badge-report");
  const badgeCatalog = document.getElementById("badge-catalog");
  const labelReport = document.getElementById("label-report");
  const labelCatalog = document.getElementById("label-catalog");

  // VAT Report Dropzone
  setupDropzone(
    dropzoneReport,
    fileReportInput,
    (files) => {
      selectedReportFiles = files;
      badgeReport.classList.remove("hidden");
      badgeReport.textContent =
        files.length === 1 ? `✓ ${files[0].name}` : `✓ ${files.length} CSV files loaded`;
      labelReport.textContent = "Click or drop to replace";
      if (hideErrorCallback) hideErrorCallback();
      checkAndTriggerProcessing();
    },
    ["csv"],
    (rejectedFiles, allowedExts) => {
      const names = rejectedFiles.map((f) => `'${f.name}'`).join(", ");
      const expected = allowedExts.map((e) => `.${e}`).join(", ");
      if (showErrorCallback) {
        showErrorCallback(
          "Invalid File Type",
          `Unsupported report format: ${names}. Expected CSV file (${expected}) for Amazon VAT reports.`
        );
      }
    }
  );

  // Catalog Dropzone
  setupDropzone(
    dropzoneCatalog,
    fileCatalogInput,
    (files) => {
      selectedCatalogFile = files[0];
      badgeCatalog.classList.remove("hidden");
      badgeCatalog.textContent = `✓ ${selectedCatalogFile.name}`;
      labelCatalog.textContent = "Click or drop to replace";
      if (hideErrorCallback) hideErrorCallback();
      checkAndTriggerProcessing();
    },
    ["xlsx"],
    (rejectedFiles, allowedExts) => {
      const names = rejectedFiles.map((f) => `'${f.name}'`).join(", ");
      const expected = allowedExts.map((e) => `.${e}`).join(", ");
      if (showErrorCallback) {
        showErrorCallback(
          "Invalid File Type",
          `Unsupported price catalog format: ${names}. Expected Excel file (${expected}) for the price catalog.`
        );
      }
    }
  );

  // Filter Event Listeners
  document.getElementById("filter-departure").addEventListener("change", (e) => {
    currentDepartureFilter = e.target.value;
    const data = getActiveVatDataset();
    if (data) renderFilteredTable(data.routes);
  });

  document.getElementById("filter-arrival").addEventListener("change", (e) => {
    currentArrivalFilter = e.target.value;
    const data = getActiveVatDataset();
    if (data) renderFilteredTable(data.routes);
  });

  document.getElementById("filter-search").addEventListener("input", (e) => {
    currentSearchText = e.target.value;
    const data = getActiveVatDataset();
    if (data) renderFilteredTable(data.routes);
  });

  document.getElementById("btn-reset-filters").addEventListener("click", () => {
    currentDepartureFilter = "ALL";
    currentArrivalFilter = "ALL";
    currentSearchText = "";
    document.getElementById("filter-departure").value = "ALL";
    document.getElementById("filter-arrival").value = "ALL";
    document.getElementById("filter-search").value = "";
    const data = getActiveVatDataset();
    if (data) renderFilteredTable(data.routes);
  });
}

async function checkAndTriggerProcessing() {
  if (selectedReportFiles.length > 0 && selectedCatalogFile) {
    await executeVatProcessing();
  }
}

async function executeVatProcessing() {
  const pyodide = getPyodide();
  if (!pyodide) {
    if (showErrorCallback) showErrorCallback("Engine Not Ready", "WebAssembly is still loading. Please wait a moment.");
    return;
  }

  const loader = document.getElementById("processing-loader-vat");
  const resultsSection = document.getElementById("results-section-vat");
  loader.classList.remove("hidden");
  resultsSection.classList.add("hidden");
  if (hideErrorCallback) hideErrorCallback();

  try {
    const catalogBuffer = await selectedCatalogFile.arrayBuffer();
    pyodide.FS.writeFile("/catalog.xlsx", new Uint8Array(catalogBuffer));

    let summaryJsonString = "";
    const isBatch = selectedReportFiles.length > 1;

    if (!isBatch) {
      const reportFile = selectedReportFiles[0];
      const reportBuffer = await reportFile.arrayBuffer();
      pyodide.FS.writeFile("/input.csv", new Uint8Array(reportBuffer));
      summaryJsonString = pyodide.runPython(`run_vat_single("/input.csv", "/catalog.xlsx")`);
    } else {
      try { pyodide.FS.mkdir("/batch_input"); } catch (e) {}
      try { pyodide.FS.mkdir("/batch_input/processed"); } catch (e) {}

      for (const file of selectedReportFiles) {
        const buffer = await file.arrayBuffer();
        pyodide.FS.writeFile(`/batch_input/${file.name}`, new Uint8Array(buffer));
      }
      summaryJsonString = pyodide.runPython(`run_vat_batch("/batch_input", "/catalog.xlsx")`);
    }

    currentProcessingResult = JSON.parse(summaryJsonString);
    activeFileIndex = "all";
    currentDepartureFilter = "ALL";
    currentArrivalFilter = "ALL";
    currentSearchText = "";

    setupFileSwitcher(currentProcessingResult);
    renderActiveVatView();
  } catch (err) {
    console.error("VAT processing error:", err);
    if (showErrorCallback) showErrorCallback("VAT Processing Error", err.message, err.toString());
  } finally {
    loader.classList.add("hidden");
  }
}

function setupFileSwitcher(result) {
  const switcherContainer = document.getElementById("file-switcher-container");
  const fileSelect = document.getElementById("select-file-view");

  if (result.mode !== "batch" || !result.files || result.files.length <= 1) {
    switcherContainer.classList.add("hidden");
    return;
  }

  switcherContainer.classList.remove("hidden");
  fileSelect.innerHTML = "";

  const allOption = document.createElement("option");
  allOption.value = "all";
  allOption.textContent = `📂 All Files (Consolidated - ${result.files.length} reports, €${result.total_value_added.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})})`;
  fileSelect.appendChild(allOption);

  result.files.forEach((fileData, index) => {
    const opt = document.createElement("option");
    opt.value = String(index);
    opt.textContent = `📄 ${fileData.filename} (${fileData.fc_transfer_updated} transfers, €${fileData.total_value_added.toFixed(2)})`;
    fileSelect.appendChild(opt);
  });

  fileSelect.value = "all";
  fileSelect.onchange = (e) => {
    activeFileIndex = e.target.value;
    currentDepartureFilter = "ALL";
    currentArrivalFilter = "ALL";
    currentSearchText = "";
    document.getElementById("filter-search").value = "";
    renderActiveVatView();
  };
}

function getActiveVatDataset() {
  if (!currentProcessingResult) return null;
  if (currentProcessingResult.mode !== "batch" || activeFileIndex === "all") {
    return {
      title: currentProcessingResult.mode === "batch" ? "Consolidated All Files" : selectedReportFiles[0].name,
      isBatch: currentProcessingResult.mode === "batch",
      total_rows: currentProcessingResult.total_rows,
      fc_transfer_updated: currentProcessingResult.fc_transfer_updated,
      total_value_added: currentProcessingResult.total_value_added,
      missing_asins: currentProcessingResult.missing_asins,
      routes: currentProcessingResult.routes,
      filename: currentProcessingResult.mode === "batch" ? null : selectedReportFiles[0].name,
    };
  }

  const fileData = currentProcessingResult.files[parseInt(activeFileIndex, 10)];
  return {
    title: fileData.filename,
    isBatch: false,
    total_rows: fileData.total_rows,
    fc_transfer_updated: fileData.fc_transfer_updated,
    total_value_added: fileData.total_value_added,
    missing_asins: fileData.missing_asins,
    routes: fileData.routes,
    filename: fileData.filename,
  };
}

function renderActiveVatView() {
  const data = getActiveVatDataset();
  if (!data) return;

  document.getElementById("results-section-vat").classList.remove("hidden");
  document.getElementById("metric-total-rows").textContent = Number(data.total_rows).toLocaleString();
  document.getElementById("metric-fc-rows").textContent = Number(data.fc_transfer_updated).toLocaleString();
  document.getElementById("metric-value-added").textContent = `€${Number(data.total_value_added).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  document.getElementById("metric-missing-asins").textContent = data.missing_asins.length;

  const titleEl = document.getElementById("route-table-title");
  const subtitleEl = document.getElementById("route-table-subtitle");
  if (currentProcessingResult.mode === "batch") {
    if (activeFileIndex === "all") {
      titleEl.textContent = `Consolidated Summary (${currentProcessingResult.files_count} Reports)`;
      subtitleEl.textContent = "Aggregated Departure Country × Arrival Country routes across all uploaded reports";
    } else {
      titleEl.textContent = `File Summary: ${data.title}`;
      subtitleEl.textContent = `Departure Country × Arrival Country routes for ${data.title}`;
    }
  } else {
    titleEl.textContent = `Departure Country × Arrival Country Summary`;
    subtitleEl.textContent = `Cross-border transfer aggregation for FC_TRANSFER transactions`;
  }

  const warningBox = document.getElementById("warning-missing-asins");
  const listMissing = document.getElementById("list-missing-asins");
  if (data.missing_asins && data.missing_asins.length > 0) {
    warningBox.classList.remove("hidden");
    listMissing.innerHTML = data.missing_asins.map((asin) => `<li>${asin}</li>`).join("");
  } else {
    warningBox.classList.add("hidden");
  }

  populateCountryFilterOptions(data.routes);
  renderFilteredTable(data.routes);
  renderVatDownloadButtons();
}

function populateCountryFilterOptions(routes) {
  const depSelect = document.getElementById("filter-departure");
  const arrSelect = document.getElementById("filter-arrival");

  const uniqueDeps = Array.from(new Set(routes.map((r) => r.departure))).sort();
  const uniqueArrs = Array.from(new Set(routes.map((r) => r.arrival))).sort();

  const prevDep = depSelect.value;
  const prevArr = arrSelect.value;

  depSelect.innerHTML = '<option value="ALL">All Departures</option>';
  uniqueDeps.forEach((dep) => {
    const opt = document.createElement("option");
    opt.value = dep;
    opt.textContent = dep;
    depSelect.appendChild(opt);
  });
  depSelect.value = uniqueDeps.includes(prevDep) ? prevDep : "ALL";
  currentDepartureFilter = depSelect.value;

  arrSelect.innerHTML = '<option value="ALL">All Arrivals</option>';
  uniqueArrs.forEach((arr) => {
    const opt = document.createElement("option");
    opt.value = arr;
    opt.textContent = arr;
    arrSelect.appendChild(opt);
  });
  arrSelect.value = uniqueArrs.includes(prevArr) ? prevArr : "ALL";
  currentArrivalFilter = arrSelect.value;
}

function renderFilteredTable(routes) {
  const tbody = document.getElementById("table-routes-body");
  const tfoot = document.getElementById("table-routes-foot");
  const countStatus = document.getElementById("filter-status-count");
  const btnReset = document.getElementById("btn-reset-filters");

  const searchLower = currentSearchText.trim().toLowerCase();
  const isFiltering = currentDepartureFilter !== "ALL" || currentArrivalFilter !== "ALL" || searchLower !== "";

  if (isFiltering) btnReset.classList.remove("hidden");
  else btnReset.classList.add("hidden");

  const filteredRoutes = routes.filter((r) => {
    if (currentDepartureFilter !== "ALL" && r.departure !== currentDepartureFilter) return false;
    if (currentArrivalFilter !== "ALL" && r.arrival !== currentArrivalFilter) return false;
    if (searchLower) {
      const matchDep = r.departure.toLowerCase().includes(searchLower);
      const matchArr = r.arrival.toLowerCase().includes(searchLower);
      const matchRoute = `${r.departure} -> ${r.arrival}`.toLowerCase().includes(searchLower);
      if (!matchDep && !matchArr && !matchRoute) return false;
    }
    return true;
  });

  countStatus.textContent = isFiltering
    ? `Showing ${filteredRoutes.length} of ${routes.length} routes`
    : `${routes.length} routes total`;

  if (filteredRoutes.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="5" class="px-5 py-8 text-center text-slate-400 font-sans text-xs">
          No routes match the selected country filter (${currentDepartureFilter} → ${currentArrivalFilter}).
        </td>
      </tr>
    `;
    tfoot.innerHTML = "";
    return;
  }

  let grandTransfers = 0;
  let grandQty = 0;
  let grandAmount = 0;

  const rowsHtml = filteredRoutes
    .map((r) => {
      grandTransfers += r.transfers;
      grandQty += r.quantity;
      grandAmount += r.amount;

      const qtyFormatted = Number.isInteger(r.quantity) ? r.quantity : r.quantity.toFixed(2);
      return `
        <tr class="hover:bg-slate-50 transition-colors">
          <td class="px-5 py-2.5 font-bold text-slate-800">${r.departure}</td>
          <td class="px-5 py-2.5 font-bold text-slate-800">${r.arrival}</td>
          <td class="px-5 py-2.5 text-right font-mono text-slate-600">${r.transfers.toLocaleString()}</td>
          <td class="px-5 py-2.5 text-right font-mono text-slate-600">${qtyFormatted}</td>
          <td class="px-5 py-2.5 text-right font-mono font-semibold text-slate-900">€${r.amount.toFixed(2)}</td>
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
      <td class="px-5 py-3 text-right font-mono text-slate-900">${Number.isInteger(grandQty) ? grandQty : grandQty.toFixed(2)}</td>
      <td class="px-5 py-3 text-right font-mono text-blue-600 text-sm">€${grandAmount.toFixed(2)}</td>
    </tr>
  `;
}

function renderVatDownloadButtons() {
  const container = document.getElementById("download-buttons-container");
  container.innerHTML = "";
  if (!currentProcessingResult) return;

  const pyodide = getPyodide();
  const isBatch = currentProcessingResult.mode === "batch";

  if (!isBatch) {
    const btnDownloadAll = document.createElement("button");
    btnDownloadAll.className =
      "bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm transition flex items-center space-x-1.5";
    btnDownloadAll.innerHTML = "<span>📦</span><span>Download All</span>";
    btnDownloadAll.onclick = () => {
      const processedContent = pyodide.FS.readFile("/output.csv");
      downloadBlob(processedContent, "vat_report_processed.csv", "text/csv;charset=utf-8");
      setTimeout(() => {
        const summaryContent = pyodide.FS.readFile("/output_country_summary.csv");
        downloadBlob(summaryContent, "country_summary.csv", "text/csv;charset=utf-8");
      }, 250);
    };

    const btnProcessed = document.createElement("button");
    btnProcessed.className =
      "bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm transition";
    btnProcessed.textContent = "⬇ Download Processed CSV";
    btnProcessed.onclick = () => {
      const content = pyodide.FS.readFile("/output.csv");
      downloadBlob(content, "vat_report_processed.csv", "text/csv;charset=utf-8");
    };

    const btnSummary = document.createElement("button");
    btnSummary.className =
      "bg-slate-800 hover:bg-slate-900 text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm transition";
    btnSummary.textContent = "⬇ Download Country Summary CSV";
    btnSummary.onclick = () => {
      const content = pyodide.FS.readFile("/output_country_summary.csv");
      downloadBlob(content, "country_summary.csv", "text/csv;charset=utf-8");
    };

    container.appendChild(btnDownloadAll);
    container.appendChild(btnProcessed);
    container.appendChild(btnSummary);
  } else {
    if (activeFileIndex === "all") {
      const btnZip = document.createElement("button");
      btnZip.className = "bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold px-4 py-2 rounded-lg shadow-sm transition";
      btnZip.textContent = `⬇ Download Batch Archive (${currentProcessingResult.files_count} CSVs in .zip)`;
      btnZip.onclick = () => downloadVatBatchZip();

      const btnBatchSummary = document.createElement("button");
      btnBatchSummary.className = "bg-slate-800 hover:bg-slate-900 text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm transition";
      btnBatchSummary.textContent = "⬇ Download Consolidated Summary CSV";
      btnBatchSummary.onclick = () => {
        const content = pyodide.FS.readFile("/batch_input/processed/batch_country_summary.csv");
        downloadBlob(content, "batch_country_summary.csv", "text/csv;charset=utf-8");
      };

      container.appendChild(btnZip);
      container.appendChild(btnBatchSummary);
    } else {
      const fileData = currentProcessingResult.files[parseInt(activeFileIndex, 10)];
      const baseName = fileData.filename.replace(/\.[^/.]+$/, "");

      const btnProcessedFile = document.createElement("button");
      btnProcessedFile.className = "bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm transition";
      btnProcessedFile.textContent = `⬇ Download ${fileData.filename}`;
      btnProcessedFile.onclick = () => {
        const content = pyodide.FS.readFile(`/batch_input/processed/${fileData.filename}`);
        downloadBlob(content, `processed_${fileData.filename}`, "text/csv;charset=utf-8");
      };

      const btnSummaryFile = document.createElement("button");
      btnSummaryFile.className = "bg-slate-800 hover:bg-slate-900 text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm transition";
      btnSummaryFile.textContent = `⬇ Download ${baseName} Summary`;
      btnSummaryFile.onclick = () => {
        const content = pyodide.FS.readFile(`/batch_input/processed/${baseName}_country_summary.csv`);
        downloadBlob(content, `${baseName}_country_summary.csv`, "text/csv;charset=utf-8");
      };

      const btnZip = document.createElement("button");
      btnZip.className = "bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold px-3.5 py-2 rounded-lg transition border border-slate-300";
      btnZip.textContent = "📦 Download All (.zip)";
      btnZip.onclick = () => downloadVatBatchZip();

      container.appendChild(btnProcessedFile);
      container.appendChild(btnSummaryFile);
      container.appendChild(btnZip);
    }
  }
}

async function downloadVatBatchZip() {
  const pyodide = getPyodide();
  const fileMap = new Map();

  for (const file of selectedReportFiles) {
    try {
      const processedContent = pyodide.FS.readFile(`/batch_input/processed/${file.name}`);
      fileMap.set(`processed_${file.name}`, processedContent);
    } catch (e) {}
    try {
      const baseName = file.name.replace(/\.[^/.]+$/, "");
      const summaryContent = pyodide.FS.readFile(`/batch_input/processed/${baseName}_country_summary.csv`);
      fileMap.set(`${baseName}_country_summary.csv`, summaryContent);
    } catch (e) {}
  }
  try {
    const batchSummaryContent = pyodide.FS.readFile("/batch_input/processed/batch_country_summary.csv");
    fileMap.set("batch_country_summary.csv", batchSummaryContent);
  } catch (e) {}

  await downloadZipArchive(fileMap, "batch_processed_reports.zip");
}
