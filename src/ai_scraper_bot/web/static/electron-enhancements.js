(function () {
  const isElectron = window.electronAPI && window.electronAPI.isElectron;

  if (isElectron) {
    const spacer = document.createElement("div");
    spacer.className = "electron-titlebar-spacer";
    document.body.prepend(spacer);

    const appShell = document.querySelector(".app-shell");
    if (appShell) {
      appShell.style.paddingTop = "54px";
    }
  }

  const dropOverlay = document.getElementById("drop-overlay");
  let dragCounter = 0;

  document.addEventListener("dragenter", (e) => {
    e.preventDefault();
    dragCounter++;
    if (dragCounter === 1 && hasFiles(e)) {
      dropOverlay.classList.add("drop-overlay--active");
    }
  });

  document.addEventListener("dragleave", (e) => {
    e.preventDefault();
    dragCounter--;
    if (dragCounter <= 0) {
      dragCounter = 0;
      dropOverlay.classList.remove("drop-overlay--active");
    }
  });

  document.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  });

  document.addEventListener("drop", (e) => {
    e.preventDefault();
    dragCounter = 0;
    dropOverlay.classList.remove("drop-overlay--active");

    const files = e.dataTransfer?.files;
    if (!files || files.length === 0) return;

    const file = files[0];
    const fileInputEl = document.getElementById("file-input");
    const attachmentChipEl = document.getElementById("attachment-chip");
    const attachmentNameEl = document.getElementById("attachment-name");

    if (fileInputEl && attachmentChipEl && attachmentNameEl) {
      const dt = new DataTransfer();
      dt.items.add(file);
      fileInputEl.files = dt.files;
      fileInputEl.dispatchEvent(new Event("change", { bubbles: true }));
    }
  });

  function hasFiles(e) {
    if (e.dataTransfer?.types) {
      for (const type of e.dataTransfer.types) {
        if (type === "Files") return true;
      }
    }
    return false;
  }
})();
