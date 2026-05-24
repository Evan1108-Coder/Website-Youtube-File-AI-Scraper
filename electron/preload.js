const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  openFileDialog: (options) => ipcRenderer.invoke("open-file-dialog", options),
  getAppVersion: () => ipcRenderer.invoke("get-app-version"),
  isElectron: true,
});
