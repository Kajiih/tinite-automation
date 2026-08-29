/**
 * Amazon Automation Tools Web Hub - Main Application Entry Point
 */

import { initPyodideEngine } from "./pyodide-bridge.js";
import { initVatReportTool } from "./tools/vat-report.js";
import { initImageDuplicatorTool } from "./tools/image-duplicator.js";

function showError(title, message, traceback) {
  const banner = document.getElementById("error-banner");
  const titleEl = document.getElementById("error-title");
  const summaryEl = document.getElementById("error-summary");
  const tracebackEl = document.getElementById("error-traceback");

  titleEl.textContent = title;
  summaryEl.textContent = message;
  tracebackEl.textContent = traceback || message;
  banner.classList.remove("hidden");
  banner.scrollIntoView({ behavior: "smooth" });
}

function hideError() {
  document.getElementById("error-banner").classList.add("hidden");
}

function switchToolTab(tab) {
  const sectionVat = document.getElementById("section-vat");
  const sectionImages = document.getElementById("section-images");
  const btnVat = document.getElementById("tab-btn-vat");
  const btnImages = document.getElementById("tab-btn-images");

  if (tab === "vat") {
    sectionVat.classList.remove("hidden");
    sectionImages.classList.add("hidden");
    btnVat.className = "px-3.5 py-1.5 rounded-lg bg-white text-blue-700 shadow-sm transition-all";
    btnImages.className = "px-3.5 py-1.5 rounded-lg text-slate-600 hover:text-slate-900 transition-all";
  } else {
    sectionVat.classList.add("hidden");
    sectionImages.classList.remove("hidden");
    btnImages.className = "px-3.5 py-1.5 rounded-lg bg-white text-blue-700 shadow-sm transition-all";
    btnVat.className = "px-3.5 py-1.5 rounded-lg text-slate-600 hover:text-slate-900 transition-all";
  }
}

// Global dismiss error listener
document.getElementById("btn-dismiss-error")?.addEventListener("click", hideError);

// Tab switch button listeners
document.getElementById("tab-btn-vat")?.addEventListener("click", () => switchToolTab("vat"));
document.getElementById("tab-btn-images")?.addEventListener("click", () => switchToolTab("images"));

// Bootstrap Application
async function bootApp() {
  const engineStatus = document.getElementById("engine-status");
  const engineStatusText = document.getElementById("engine-status-text");

  try {
    const pyodide = await initPyodideEngine(
      (status) => {
        if (status === "Ready") {
          engineStatus.className =
            "flex items-center space-x-2 text-xs bg-emerald-50 text-emerald-800 border border-emerald-200 px-3 py-1.5 rounded-full font-medium";
          engineStatus.innerHTML =
            '<span class="w-2 h-2 rounded-full bg-emerald-500"></span><span>v0.2.0 • WebAssembly Ready</span>';
        } else {
          engineStatusText.textContent = status;
        }
      },
      (err) => {
        engineStatus.className =
          "flex items-center space-x-2 text-xs bg-red-50 text-red-800 border border-red-200 px-3 py-1.5 rounded-full font-medium";
        engineStatus.innerHTML = `<span class="w-2 h-2 rounded-full bg-red-500"></span><span>Engine Error</span>`;
        showError("Initialization Error", err.message, err.stack || err.toString());
      }
    );

    // Initialize Tool Controllers
    initVatReportTool(showError, hideError);
    initImageDuplicatorTool(showError, hideError);
  } catch (err) {
    console.error("Boot failure:", err);
  }
}

window.addEventListener("DOMContentLoaded", bootApp);
