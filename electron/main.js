const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const path = require("path");
const { spawn } = require("child_process");
const net = require("net");

let mainWindow = null;
let pythonProcess = null;
const BACKEND_PORT = 18919;
const BACKEND_HOST = "127.0.0.1";

function getResourcePath(...segments) {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "app", ...segments);
  }
  return path.join(__dirname, "..", ...segments);
}

function findPython() {
  const candidates = ["python3", "python"];
  const { execSync } = require("child_process");
  for (const cmd of candidates) {
    try {
      const result = execSync(`${cmd} --version`, { encoding: "utf-8", timeout: 5000 });
      if (result.includes("Python 3")) {
        return cmd;
      }
    } catch {}
  }
  return null;
}

function isPortInUse(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(true));
    server.once("listening", () => {
      server.close();
      resolve(false);
    });
    server.listen(port, BACKEND_HOST);
  });
}

async function waitForBackend(timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const inUse = await isPortInUse(BACKEND_PORT);
    if (inUse) return true;
    await new Promise((r) => setTimeout(r, 300));
  }
  return false;
}

function startBackend() {
  const python = findPython();
  if (!python) {
    dialog.showErrorBox(
      "Python Not Found",
      "AI Media Studio requires Python 3.10+ to be installed.\n\nPlease install Python from python.org and try again."
    );
    app.quit();
    return false;
  }

  const srcDir = getResourcePath("src");
  const env = {
    ...process.env,
    WEBAPP_HOST: BACKEND_HOST,
    WEBAPP_PORT: String(BACKEND_PORT),
    WEBAPP_DB_PATH: path.join(app.getPath("userData"), "webapp.sqlite"),
    PYTHONPATH: srcDir,
  };

  pythonProcess = spawn(python, ["-m", "ai_scraper_bot.webapp"], {
    cwd: srcDir,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });

  pythonProcess.stdout.on("data", (data) => {
    console.log(`[backend] ${data.toString().trim()}`);
  });

  pythonProcess.stderr.on("data", (data) => {
    console.error(`[backend] ${data.toString().trim()}`);
  });

  pythonProcess.on("error", (err) => {
    console.error("Failed to start backend:", err.message);
    dialog.showErrorBox(
      "Backend Error",
      `Failed to start the AI backend:\n${err.message}\n\nMake sure Python dependencies are installed:\npip install -r requirements.txt`
    );
  });

  pythonProcess.on("exit", (code) => {
    console.log(`Backend exited with code ${code}`);
    pythonProcess = null;
  });

  return true;
}

function stopBackend() {
  if (pythonProcess) {
    pythonProcess.kill("SIGTERM");
    setTimeout(() => {
      if (pythonProcess) {
        pythonProcess.kill("SIGKILL");
      }
    }, 3000);
    pythonProcess = null;
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 900,
    minHeight: 600,
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 16, y: 16 },
    icon: path.join(__dirname, "resources", "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
    },
    show: false,
    backgroundColor: "#0f0f14",
  });

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
  });

  mainWindow.loadURL(`http://${BACKEND_HOST}:${BACKEND_PORT}`);

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

ipcMain.handle("open-file-dialog", async (_, options) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ["openFile"],
    filters: options?.filters || [{ name: "All Files", extensions: ["*"] }],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle("get-app-version", () => app.getVersion());

app.whenReady().then(async () => {
  const portInUse = await isPortInUse(BACKEND_PORT);
  if (!portInUse) {
    const started = startBackend();
    if (!started) return;
  }

  const backendReady = await waitForBackend();
  if (!backendReady) {
    dialog.showErrorBox(
      "Startup Timeout",
      "The AI backend did not start in time.\n\nPlease ensure Python dependencies are installed:\npip install -r requirements.txt"
    );
    app.quit();
    return;
  }

  createWindow();
});

app.on("window-all-closed", () => {
  stopBackend();
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("activate", () => {
  if (mainWindow === null) {
    createWindow();
  }
});

app.on("before-quit", () => {
  stopBackend();
});
