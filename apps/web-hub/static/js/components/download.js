/**
 * File & ZIP Download Utilities
 */

export function downloadBlob(data, filename, mimeType = "application/octet-stream") {
  const blob = data instanceof Blob ? data : new Blob([data], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function downloadZipArchive(filesMap, zipFilename = "archive.zip", onProgress = null) {
  if (typeof JSZip === "undefined") {
    throw new Error("JSZip library is not loaded.");
  }

  const zip = new JSZip();
  for (const [relativePath, content] of filesMap.entries()) {
    zip.file(relativePath, content);
  }

  const zipBlob = await zip.generateAsync({ type: "blob" }, (metadata) => {
    if (onProgress) {
      onProgress(metadata.percent);
    }
  });

  downloadBlob(zipBlob, zipFilename, "application/zip");
}
