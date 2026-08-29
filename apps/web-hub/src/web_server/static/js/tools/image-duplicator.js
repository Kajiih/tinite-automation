/**
 * ASIN Image Duplicator Tool Controller
 */

import { setupDropzone } from "../components/dropzone.js";
import { downloadZipArchive } from "../components/download.js";
import { getPyodide } from "../pyodide-bridge.js";

let templateImageFiles = [];
let targetAsinsList = [];
let imageManifest = [];

let showErrorCallback = null;
let hideErrorCallback = null;

const VALID_IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "tif", "tiff", "gif"];

export function initImageDuplicatorTool(showError, hideError) {
  showErrorCallback = showError;
  hideErrorCallback = hideError;

  const dropzoneTemplates = document.getElementById("dropzone-image-templates");
  const fileTemplatesInput = document.getElementById("file-image-templates");
  const badgeTemplates = document.getElementById("badge-image-templates");
  const labelTemplates = document.getElementById("label-image-templates");

  const dropzoneAsins = document.getElementById("dropzone-asins");
  const fileAsinsInput = document.getElementById("file-asins");
  const textareaAsins = document.getElementById("textarea-asins");
  const btnGenerate = document.getElementById("btn-generate-images");

  // Template Images Dropzone
  setupDropzone(dropzoneTemplates, fileTemplatesInput, (files) => {
    templateImageFiles = files;
    badgeTemplates.classList.remove("hidden");
    badgeTemplates.textContent = `✓ ${files.length} template images loaded`;
    labelTemplates.textContent = "Click or drop to replace";
    if (hideErrorCallback) hideErrorCallback();
    updateImageDuplicationPreview();
  }, VALID_IMAGE_EXTENSIONS);

  // ASIN File Dropzone (.txt, .csv, .xlsx)
  setupDropzone(dropzoneAsins, fileAsinsInput, async (files) => {
    if (files.length > 0) {
      await loadAsinsFromFile(files[0]);
    }
  }, ["txt", "csv", "xlsx"]);

  // Textarea ASIN input listener
  textareaAsins.addEventListener("input", () => {
    updateAsinsFromTextarea();
  });

  // Generate button
  btnGenerate.addEventListener("click", () => {
    executeImageDuplicationZip();
  });
}

async function loadAsinsFromFile(file) {
  const pyodide = getPyodide();
  if (!pyodide) {
    if (showErrorCallback) showErrorCallback("Engine Loading", "Please wait for WebAssembly to finish initializing.");
    return;
  }

  try {
    const ext = file.name.split(".").pop().toLowerCase();
    let parsedAsins = [];

    if (ext === "xlsx") {
      const buffer = await file.arrayBuffer();
      pyodide.FS.writeFile("/temp_asins.xlsx", new Uint8Array(buffer));
      const jsonRes = pyodide.runPython(`
from pathlib import Path
from image_renamer.engine import parse_asins
import json
json.dumps(parse_asins(Path("/temp_asins.xlsx")))
`);
      parsedAsins = JSON.parse(jsonRes);
    } else {
      const text = await file.text();
      const jsonRes = pyodide.runPython(`run_parse_asins(${JSON.stringify(text)})`);
      parsedAsins = JSON.parse(jsonRes);
    }

    if (parsedAsins.length === 0) {
      if (showErrorCallback) showErrorCallback("No ASINs Found", `Could not find valid ASINs in ${file.name}`);
      return;
    }

    const textarea = document.getElementById("textarea-asins");
    textarea.value = parsedAsins.join("\n");
    updateAsinsFromTextarea();
  } catch (err) {
    console.error("ASIN file load error:", err);
    if (showErrorCallback) showErrorCallback("ASIN Load Error", err.message, err.toString());
  }
}

function updateAsinsFromTextarea() {
  const pyodide = getPyodide();
  if (!pyodide) return;

  const textarea = document.getElementById("textarea-asins");
  const badgeAsinCount = document.getElementById("badge-asin-count");
  const text = textarea.value;

  if (!text.trim()) {
    targetAsinsList = [];
    badgeAsinCount.classList.add("hidden");
    updateImageDuplicationPreview();
    return;
  }

  try {
    const jsonRes = pyodide.runPython(`run_parse_asins(${JSON.stringify(text)})`);
    targetAsinsList = JSON.parse(jsonRes);

    badgeAsinCount.classList.remove("hidden");
    badgeAsinCount.textContent = `${targetAsinsList.length} ASINs`;
    updateImageDuplicationPreview();
  } catch (e) {
    console.error("ASIN parse error:", e);
  }
}

function updateImageDuplicationPreview() {
  const pyodide = getPyodide();
  if (!pyodide) return;

  const actionBar = document.getElementById("image-action-bar");
  const previewSection = document.getElementById("image-preview-section");
  const previewBody = document.getElementById("table-image-preview-body");
  const heading = document.getElementById("image-summary-heading");
  const subheading = document.getElementById("image-summary-subheading");
  const previewCount = document.getElementById("image-preview-count");

  if (templateImageFiles.length === 0 || targetAsinsList.length === 0) {
    actionBar.classList.add("hidden");
    previewSection.classList.add("hidden");
    return;
  }

  const imgNames = templateImageFiles.map((f) => f.name);
  const manifestJson = pyodide.runPython(`
run_generate_image_manifest(${JSON.stringify(JSON.stringify(imgNames))}, ${JSON.stringify(JSON.stringify(targetAsinsList))})
`);
  imageManifest = JSON.parse(manifestJson);

  actionBar.classList.remove("hidden");
  previewSection.classList.remove("hidden");

  heading.textContent = `Ready to Generate ${imageManifest.length.toLocaleString()} Images`;
  subheading.textContent = `${templateImageFiles.length} template images × ${targetAsinsList.length} ASINs = ${imageManifest.length} total files in ${targetAsinsList.length} folders`;
  previewCount.textContent = `Previewing ${Math.min(imageManifest.length, 50)} of ${imageManifest.length} files`;

  previewBody.innerHTML = imageManifest
    .slice(0, 50)
    .map(
      (item) => `
      <tr class="hover:bg-slate-50">
        <td class="px-5 py-2 font-bold text-blue-700">${item.asin}</td>
        <td class="px-5 py-2 text-slate-600">${item.source_filename}</td>
        <td class="px-5 py-2 font-mono text-emerald-700">${item.target_relative_path}</td>
      </tr>
    `
    )
    .join("");
}

async function executeImageDuplicationZip() {
  if (templateImageFiles.length === 0 || targetAsinsList.length === 0) {
    if (showErrorCallback) showErrorCallback("Missing Selection", "Please upload template images and provide target ASINs.");
    return;
  }

  const btn = document.getElementById("btn-generate-images");
  const originalText = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="animate-spin">⚙️</span><span>Building .zip archive...</span>`;

  try {
    const fileMap = new Map();
    const imageBuffers = new Map();

    // Read all template images into memory array buffers
    for (const file of templateImageFiles) {
      const buffer = await file.arrayBuffer();
      imageBuffers.set(file.name, buffer);
    }

    // Map duplicated files
    for (const item of imageManifest) {
      const buffer = imageBuffers.get(item.source_filename);
      if (buffer) {
        fileMap.set(item.target_relative_path, buffer);
      }
    }

    await downloadZipArchive(
      fileMap,
      `amazon_asin_images_${targetAsinsList.length}_asins.zip`,
      (percent) => {
        btn.innerHTML = `<span class="animate-spin">⚙️</span><span>Compressing ${percent.toFixed(0)}%...</span>`;
      }
    );
  } catch (err) {
    console.error("ZIP creation error:", err);
    if (showErrorCallback) showErrorCallback("ZIP Generation Error", err.message, err.toString());
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalText;
  }
}
