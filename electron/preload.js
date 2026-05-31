const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  selectVideo: () => ipcRenderer.invoke('select-video'),
});
