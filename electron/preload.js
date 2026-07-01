const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  selectVideo: () => ipcRenderer.invoke('select-video'),
  getPathForFile: (file) => {
    try {
      return webUtils.getPathForFile(file) || '';
    } catch (_) {
      return '';
    }
  },
});
