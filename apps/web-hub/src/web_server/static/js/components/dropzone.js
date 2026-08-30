/**
 * HTML5 Dropzone Helper with Recursive Directory Traversal and File Type Validation
 */

export async function extractFilesFromDataTransfer(dataTransfer, validExtensions = null) {
  const validFiles = [];
  const rejectedFiles = [];
  const items = dataTransfer.items;

  const isAllowed = (filename) => {
    if (!validExtensions) return true;
    const parts = filename.split(".");
    if (parts.length < 2) return false;
    const ext = parts.pop().toLowerCase();
    return validExtensions.map(e => e.toLowerCase()).includes(ext);
  };

  const processFile = (file) => {
    if (!file) return;
    if (isAllowed(file.name)) {
      validFiles.push(file);
    } else {
      rejectedFiles.push(file);
    }
  };

  if (!items || items.length === 0) {
    for (const file of dataTransfer.files) {
      processFile(file);
    }
    return { validFiles, rejectedFiles };
  }

  async function scanEntry(entry) {
    if (!entry) return;
    if (entry.isFile) {
      await new Promise((resolve) => {
        entry.file((file) => {
          processFile(file);
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
      if (file) processFile(file);
    }
  }

  return { validFiles, rejectedFiles };
}

export function setupDropzone(dropzoneEl, fileInputEl, onFilesSelected, validExtensions = null, onInvalidFiles = null) {
  if (!dropzoneEl) return;

  const isAllowed = (filename) => {
    if (!validExtensions) return true;
    const parts = filename.split(".");
    if (parts.length < 2) return false;
    const ext = parts.pop().toLowerCase();
    return validExtensions.map(e => e.toLowerCase()).includes(ext);
  };

  if (fileInputEl) {
    dropzoneEl.addEventListener("click", () => fileInputEl.click());
    fileInputEl.addEventListener("change", (e) => {
      const allFiles = Array.from(e.target.files);
      const validFiles = allFiles.filter(f => isAllowed(f.name));
      const rejectedFiles = allFiles.filter(f => !isAllowed(f.name));

      if (rejectedFiles.length > 0 && onInvalidFiles) {
        onInvalidFiles(rejectedFiles, validExtensions);
      }
      if (validFiles.length > 0) {
        onFilesSelected(validFiles);
      }
      // Reset input value so re-selecting the same file fires change event
      fileInputEl.value = "";
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
    const { validFiles, rejectedFiles } = await extractFilesFromDataTransfer(e.dataTransfer, validExtensions);
    if (rejectedFiles.length > 0 && onInvalidFiles) {
      onInvalidFiles(rejectedFiles, validExtensions);
    }
    if (validFiles.length > 0) {
      onFilesSelected(validFiles);
    }
  });
}
