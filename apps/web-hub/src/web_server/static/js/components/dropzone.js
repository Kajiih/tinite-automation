/**
 * HTML5 Dropzone Helper with Recursive Directory Traversal
 */

export async function extractFilesFromDataTransfer(dataTransfer, validExtensions = null) {
  const extractedFiles = [];
  const items = dataTransfer.items;

  const isAllowed = (filename) => {
    if (!validExtensions) return true;
    const ext = filename.split(".").pop().toLowerCase();
    return validExtensions.includes(ext);
  };

  if (!items || items.length === 0) {
    for (const file of dataTransfer.files) {
      if (isAllowed(file.name)) extractedFiles.push(file);
    }
    return extractedFiles;
  }

  async function scanEntry(entry) {
    if (!entry) return;
    if (entry.isFile) {
      await new Promise((resolve) => {
        entry.file((file) => {
          if (isAllowed(file.name)) extractedFiles.push(file);
          resolve();
        }, () => resolve());
      });
    } else if (entry.isDirectory) {
      const dirReader = entry.createReader();
      const readAllEntries = async () => {
        const batch = await new Promise((resolve) => dirReader.readEntries(resolve, () => resolve([])));
        if (batch && batch.length > 0) {
          for (const child of batch) await scanEntry(child);
          await readAllEntries();
        }
      };
      await readAllEntries();
    }
  }

  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    if (item.webkitGetAsEntry) {
      const entry = item.webkitGetAsEntry();
      if (entry) await scanEntry(entry);
    } else if (item.kind === "file") {
      const file = item.getAsFile();
      if (file && isAllowed(file.name)) extractedFiles.push(file);
    }
  }

  return extractedFiles;
}

export function setupDropzone(dropzoneEl, fileInputEl, onFilesSelected, validExtensions = null) {
  if (!dropzoneEl) return;

  if (fileInputEl) {
    dropzoneEl.addEventListener("click", () => fileInputEl.click());
    fileInputEl.addEventListener("change", (e) => {
      const files = Array.from(e.target.files).filter(f => {
        if (!validExtensions) return true;
        const ext = f.name.split(".").pop().toLowerCase();
        return validExtensions.includes(ext);
      });
      if (files.length > 0) {
        onFilesSelected(files);
      }
    });
  }

  ["dragenter", "dragover"].forEach((ev) => {
    dropzoneEl.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzoneEl.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach((ev) => {
    dropzoneEl.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzoneEl.classList.remove("dragover");
    });
  });

  dropzoneEl.addEventListener("drop", async (e) => {
    const files = await extractFilesFromDataTransfer(e.dataTransfer, validExtensions);
    if (files.length > 0) {
      onFilesSelected(files);
    }
  });
}
