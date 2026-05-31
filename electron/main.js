const { app, BrowserWindow, dialog, ipcMain, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');

let mainWindow = null;
let pythonProcess = null;
let backendOwned = false;
let backendStopping = false;
const BACKEND_URL = 'http://127.0.0.1:18090';
const STARTUP_TIMEOUT = 30000;

function getPythonCmd() {
  return process.platform === 'win32' ? 'python' : 'python3';
}

function getAppPath() {
  const base = app.isPackaged ? process.resourcesPath : path.join(__dirname, '..');
  return path.join(base, 'app', 'main.py');
}

function startBackend() {
  const cmd = getPythonCmd();
  const appPath = getAppPath();
  const cwd = app.isPackaged ? process.resourcesPath : path.join(__dirname, '..');
  const runtimeDataDir = path.join(app.getPath('userData'), 'data');
  const env = { ...process.env, AI_SUB_PRO_DATA_DIR: runtimeDataDir };

  pythonProcess = spawn(cmd, [appPath, '--headless'], { cwd, env, stdio: ['pipe', 'pipe', 'pipe'] });
  backendOwned = true;
  backendStopping = false;
  pythonProcess.stdout.on('data', d => console.log('[Py]', d.toString().trim()));
  pythonProcess.stderr.on('data', d => console.error('[Py]', d.toString().trim()));
  pythonProcess.on('error', err => {
    dialog.showErrorBox('启动失败', `Python 后端启动失败:\n${err.message}`);
    app.quit();
  });
  pythonProcess.on('exit', code => {
    pythonProcess = null;
    if (backendStopping || !backendOwned) {
      backendStopping = false;
      backendOwned = false;
      return;
    }
    if (mainWindow && !mainWindow.isDestroyed()) {
      dialog.showErrorBox('后端退出', `Python 进程意外退出 (code ${code})`);
      app.quit();
    }
  });
}

async function backendReady() {
  return new Promise(resolve => {
    const req = http.get(`${BACKEND_URL}/api/settings`, res => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.setTimeout(2000, () => {
      req.destroy();
      resolve(false);
    });
  });
}

function waitForBackend() {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    async function poll() {
      if (!pythonProcess) return reject(new Error('Python not running'));
      if (await backendReady()) return resolve();
      if (Date.now() - start > STARTUP_TIMEOUT) return reject(new Error('Backend timeout'));
      setTimeout(poll, 500);
    }
    poll();
  });
}

function killBackend() {
  if (!backendOwned || !pythonProcess) return;
  backendStopping = true;
  try {
    if (process.platform === 'win32') spawn('taskkill', ['/pid', String(pythonProcess.pid), '/f', '/t']);
    else pythonProcess.kill('SIGTERM');
  } catch(_) {}
  pythonProcess = null;
  backendOwned = false;
}

function isBackendUrl(url) {
  try {
    return new URL(url).origin === new URL(BACKEND_URL).origin;
  } catch(_) {
    return false;
  }
}

function openExternalUrl(url) {
  try {
    const protocol = new URL(url).protocol;
    if (protocol === 'http:' || protocol === 'https:') shell.openExternal(url);
  } catch(_) {}
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400, height: 900, minWidth: 1100, minHeight: 700,
    title: 'AI Sub Pro',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    backgroundColor: '#f8fafc',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false,
    },
    show: false,
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    openExternalUrl(url);
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (isBackendUrl(url)) return;
    event.preventDefault();
    openExternalUrl(url);
  });

  mainWindow.loadURL(BACKEND_URL);
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.on('closed', () => { mainWindow = null; });
}

async function ensureWindow() {
  if (mainWindow) return;
  if (!(await backendReady())) {
    if (!pythonProcess) startBackend();
    await waitForBackend();
  }
  createWindow();
}

function showStartupFailure(error) {
  killBackend();
  dialog.showErrorBox('启动失败', error.message);
  app.quit();
}

ipcMain.handle('select-video', async () => {
  const r = await dialog.showOpenDialog(mainWindow, {
    title: '选择视频文件',
    properties: ['openFile'],
    filters: [{ name: 'Video', extensions: ['mp4','mkv','mov','avi','wmv','flv','ts'] }],
  });
  return r.canceled ? null : r.filePaths[0];
});

app.whenReady().then(async () => {
  if (await backendReady()) {
    console.log('[Py] Reusing existing AI Sub Pro backend');
  } else {
    startBackend();
  }
  try {
    await ensureWindow();
  } catch (error) {
    showStartupFailure(error);
    return;
  }
  app.on('activate', () => { ensureWindow().catch(showStartupFailure); });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    killBackend();
    app.quit();
  }
});
app.on('before-quit', killBackend);
process.on('exit', killBackend);
