/**
 * Pyodide WebAssembly Engine Lifecycle & Bridge Manager
 */

let pyodideInstance = null;

export async function initPyodideEngine(onStatusUpdate = null, onError = null) {
  if (pyodideInstance) return pyodideInstance;

  const update = (msg) => {
    if (onStatusUpdate) onStatusUpdate(msg);
  };

  try {
    update("Loading WebAssembly Core...");
    pyodideInstance = await loadPyodide({
      indexURL: "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/",
    });

    update("Loading micropip...");
    await pyodideInstance.loadPackage("micropip");
    const micropip = pyodideInstance.pyimport("micropip");

    update("Installing openpyxl...");
    await micropip.install("openpyxl");

    update("Mounting Python engines...");
    const [vatRes, imageRes, bridgeRes] = await Promise.all([
      fetch("/vat_report/engine.py"),
      fetch("/image_renamer/engine.py"),
      fetch("/py/bridge.py"),
    ]);

    if (!vatRes.ok) throw new Error("Failed to load /vat_report/engine.py");
    if (!imageRes.ok) throw new Error("Failed to load /image_renamer/engine.py");
    if (!bridgeRes.ok) throw new Error("Failed to load /py/bridge.py");

    const vatCode = await vatRes.text();
    const imageCode = await imageRes.text();
    const bridgeCode = await bridgeRes.text();

    // Mount vat_report package
    pyodideInstance.FS.mkdirTree("/lib/python3.12/site-packages/vat_report");
    pyodideInstance.FS.writeFile(
      "/lib/python3.12/site-packages/vat_report/__init__.py",
      "from .engine import *"
    );
    pyodideInstance.FS.writeFile(
      "/lib/python3.12/site-packages/vat_report/engine.py",
      vatCode
    );

    // Mount image_renamer package
    pyodideInstance.FS.mkdirTree("/lib/python3.12/site-packages/image_renamer");
    pyodideInstance.FS.writeFile(
      "/lib/python3.12/site-packages/image_renamer/__init__.py",
      "from .engine import *"
    );
    pyodideInstance.FS.writeFile(
      "/lib/python3.12/site-packages/image_renamer/engine.py",
      imageCode
    );

    // Execute bridge functions into global Python scope
    pyodideInstance.runPython(bridgeCode);

    update("Ready");
    return pyodideInstance;
  } catch (err) {
    console.error("Pyodide Engine Init Error:", err);
    if (onError) onError(err);
    throw err;
  }
}

export function getPyodide() {
  return pyodideInstance;
}
