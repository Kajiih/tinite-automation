import { setupDropzone } from "../components/dropzone.js";
import { downloadBlob, downloadZipArchive } from "../components/download.js";
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
  setupDropzone(
    dropzoneB2B,
    fileB2BInput,
    (files) => {
      selectedReportFile = files[0];
      badgeB2B.classList.remove("hidden");
      badgeB2B.textContent = `✓ ${selectedReportFile.name}`;
      labelB2B.textContent = "Click or drop to replace";
      if (hideErrorCallback) hideErrorCallback();
      executeB2BProcessing();
    },
    ["csv"],
    (rejectedFiles, allowedExts) => {
      const names = rejectedFiles.map((f) => `'${f.name}'`).join(", ");
      const expected = allowedExts.map((e) => `.${e}`).join(", ");
      if (showErrorCallback) {
        showErrorCallback(
          "Invalid File Type",
          `Unsupported file format: ${names}. Expected CSV file (${expected}) for Amazon VAT reports.`
        );
      }
    }
  );

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

  // Download All button
  document.getElementById("btn-download-all-b2b").addEventListener("click", () => {
    downloadAllB2bArtifacts();
  });

  // Download Invoices button -> opens interactive invoices modal
  document.getElementById("btn-download-invoices-b2b").addEventListener("click", () => {
    openInvoicesModal();
  });

  // Modal event listeners
  document.getElementById("btn-close-invoices-modal").addEventListener("click", closeInvoicesModal);
  document.getElementById("btn-modal-close-footer").addEventListener("click", closeInvoicesModal);
  document.getElementById("modal-b2b-invoices").addEventListener("click", (e) => {
    if (e.target.id === "modal-b2b-invoices") closeInvoicesModal();
  });

  document.getElementById("btn-modal-open-all-invoices").addEventListener("click", () => {
    openAllInvoicesInTabs();
  });

  document.getElementById("btn-modal-download-launcher").addEventListener("click", () => {
    if (!currentB2BResult || !currentB2BResult.transactions) return;
    const baseName = selectedReportFile ? selectedReportFile.name.replace(/\.[^/.]+$/, "") : "b2b_vat";
    const launcherHtml = generateInvoicesHtmlLauncher(currentB2BResult.transactions, selectedReportFile ? selectedReportFile.name : "VAT Report");
    downloadBlob(launcherHtml, `${baseName}_invoices_launcher.html`, "text/html;charset=utf-8");
  });

  // Download individual CSV buttons
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

function generateInvoicesHtmlLauncher(transactions, reportName) {
  const invoiceRows = transactions.filter((t) => t.invoice_url && t.invoice_url.trim() !== "");
  const rowsHtml = invoiceRows
    .map(
      (t, idx) => `
    <tr>
      <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; font-family: monospace;">${idx + 1}</td>
      <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; font-family: monospace; font-weight: bold;">${t.order_id}</td>
      <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; font-family: monospace;">${t.buyer_vat}</td>
      <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; font-family: monospace;">${t.invoice_number || "-"}</td>
      <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">${t.ship_from_country} &rarr; ${t.ship_to_country}</td>
      <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; font-family: monospace; text-align: right;">&euro;${t.net_difference.toFixed(2)}</td>
      <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: center;">
        <a href="${t.invoice_url}" target="_blank" class="btn" style="background:#2563eb; color:#fff; padding:6px 12px; border-radius:6px; text-decoration:none; font-size:12px; display:inline-block;">&darr; Download Invoice</a>
      </td>
    </tr>
  `
    )
    .join("");

  const urlsJson = JSON.stringify(invoiceRows.map((t) => t.invoice_url));

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Amazon B2B Invoices - ${reportName}</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8fafc; color: #1e293b; margin: 0; padding: 30px; }
    .container { max-width: 1050px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 16px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }
    h1 { font-size: 20px; margin-top: 0; display: flex; align-items: center; gap: 8px; color: #0f172a; }
    .btn { cursor: pointer; border: none; font-weight: 600; transition: opacity 0.2s; }
    .btn:hover { opacity: 0.9; }
    .btn-main { background: #059669; color: white; padding: 10px 20px; border-radius: 8px; font-size: 14px; }
    table { width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 13px; }
    th { text-align: left; padding: 10px; background: #f1f5f9; color: #475569; font-size: 11px; text-transform: uppercase; }
  </style>
</head>
<body>
  <div class="container">
    <h1>🧾 Amazon B2B Invoices (${invoiceRows.length} documents)</h1>
    <p style="color: #64748b; font-size: 13px;">Report: <strong>${reportName}</strong>. Make sure you are logged into your Amazon Seller Central account in this browser.</p>
    <div style="margin: 20px 0;">
      <button class="btn btn-main" onclick="openAllInvoices()">🚀 Open / Download All Invoices in Tabs</button>
    </div>
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Order ID</th>
          <th>Buyer VAT</th>
          <th>Invoice #</th>
          <th>Route</th>
          <th style="text-align: right;">Net Amount</th>
          <th style="text-align: center;">Action</th>
        </tr>
      </thead>
      <tbody>
        ${rowsHtml}
      </tbody>
    </table>
  </div>
  <script>
    const urls = ${urlsJson};
    function openAllInvoices() {
      urls.forEach((url, i) => {
        setTimeout(() => {
          window.open(url, '_blank');
        }, i * 350);
      });
    }
  </script>
</body>
</html>`;
}

function openInvoicesModal() {
  if (!currentB2BResult || !currentB2BResult.transactions || currentB2BResult.transactions.length === 0) {
    if (showErrorCallback) {
      showErrorCallback("No Transactions", "No matching B2B transactions found to download invoices for.");
    }
    return;
  }

  const validInvoices = currentB2BResult.transactions.filter(
    (t) => t.invoice_url && t.invoice_url.trim() !== ""
  );

  if (validInvoices.length === 0) {
    if (showErrorCallback) {
      showErrorCallback("No Invoice URLs", "No invoice download URLs found in the matched transactions.");
    }
    return;
  }

  const modal = document.getElementById("modal-b2b-invoices");
  const title = document.getElementById("modal-invoices-title");
  const subtitle = document.getElementById("modal-invoices-subtitle");
  const tbody = document.getElementById("modal-invoices-tbody");

  title.textContent = `B2B Cross-Border Invoices (${validInvoices.length} documents)`;
  subtitle.textContent = `Amazon VAT report: ${selectedReportFile ? selectedReportFile.name : "Active Report"}`;

  tbody.innerHTML = validInvoices
    .map(
      (tx) => `
    <tr class="hover:bg-slate-50 transition-colors">
      <td class="px-4 py-2.5 font-bold text-slate-800">${tx.order_id}</td>
      <td class="px-4 py-2.5 font-sans">${tx.buyer_vat}</td>
      <td class="px-4 py-2.5 text-slate-700">${tx.invoice_number || "-"}</td>
      <td class="px-4 py-2.5 text-right font-mono font-semibold ${tx.net_difference >= 0 ? "text-emerald-700" : "text-amber-700"}">€${tx.net_difference.toFixed(2)}</td>
      <td class="px-4 py-2.5 text-center font-sans">
        <a href="${tx.invoice_url}" target="_blank" rel="noopener noreferrer" class="bg-blue-600 hover:bg-blue-700 text-white text-[11px] font-semibold px-2.5 py-1 rounded shadow-sm inline-flex items-center space-x-1">
          <span>⬇</span>
          <span>Download PDF</span>
        </a>
      </td>
    </tr>
  `
    )
    .join("");

  modal.classList.remove("hidden");
}

function closeInvoicesModal() {
  const modal = document.getElementById("modal-b2b-invoices");
  modal.classList.add("hidden");
}

function openAllInvoicesInTabs() {
  if (!currentB2BResult || !currentB2BResult.transactions) return;
  const validInvoices = currentB2BResult.transactions.filter(
    (t) => t.invoice_url && t.invoice_url.trim() !== ""
  );

  validInvoices.forEach((tx, idx) => {
    setTimeout(() => {
      window.open(tx.invoice_url, "_blank");
    }, idx * 350);
  });
}

async function downloadAllB2bArtifacts() {
  const pyodide = getPyodide();
  if (!pyodide || !selectedReportFile) return;

  const baseName = selectedReportFile.name.replace(/\.[^/.]+$/, "");
  const btnAll = document.getElementById("btn-download-all-b2b");
  const originalHtml = btnAll.innerHTML;
  btnAll.disabled = true;
  btnAll.innerHTML = `<span>⏳</span><span>Packaging ZIP...</span>`;

  try {
    const filesMap = new Map();

    // 1. Summary CSV
    try {
      const summaryContent = pyodide.FS.readFile("/b2b_summary.csv");
      filesMap.set(`${baseName}_b2b_vat_summary.csv`, summaryContent);
    } catch (err) {
      console.warn("Could not read summary CSV:", err);
    }

    // 2. Transactions CSV
    try {
      const txContent = pyodide.FS.readFile("/b2b_transactions.csv");
      filesMap.set(`${baseName}_b2b_filtered_transactions.csv`, txContent);
    } catch (err) {
      console.warn("Could not read transactions CSV:", err);
    }

    // 3. Invoices Launcher HTML
    if (currentB2BResult && currentB2BResult.transactions) {
      const launcherHtml = generateInvoicesHtmlLauncher(currentB2BResult.transactions, selectedReportFile.name);
      filesMap.set("invoices_launcher.html", launcherHtml);
    }

    btnAll.innerHTML = `<span>⏳</span><span>Generating ZIP...</span>`;
    await downloadZipArchive(filesMap, `${baseName}_all_b2b_artifacts.zip`);

    // 4. Also open the invoices modal for immediate access
    openInvoicesModal();

    btnAll.innerHTML = `<span>✓</span><span>ZIP Saved!</span>`;
    setTimeout(() => {
      btnAll.innerHTML = originalHtml;
      btnAll.disabled = false;
    }, 2500);
  } catch (err) {
    console.error("Download All error:", err);
    if (showErrorCallback) showErrorCallback("Download All Error", err.message);
    btnAll.disabled = false;
    btnAll.innerHTML = originalHtml;
  }
}
