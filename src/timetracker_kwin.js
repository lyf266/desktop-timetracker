// KDE Plasma 6 Wayland TimeTracker KWin Script
// Watches active window changes and ticks periodically

function getWindowData(w) {
    if (!w) return null;
    return {
        caption: w.caption || "",
        desktopFile: w.desktopFile || "",
        resourceClass: w.resourceClass || "",
        resourceName: w.resourceName || "",
        pid: w.pid || 0
    };
}

function notifyActiveWindow() {
    try {
        var w = workspace.activeWindow;
        var data = getWindowData(w);
        if (data) {
            console.info("TIMETRACKER_TICK:" + JSON.stringify(data));
        } else {
            console.info("TIMETRACKER_TICK:null");
        }
    } catch (e) {
        console.info("TIMETRACKER_ERR:" + e);
    }
}

// 1. Trigger immediately on window activation
workspace.windowActivated.connect(notifyActiveWindow);

// 2. Periodic timer (every 5 seconds) to ensure continuous tracking
var timer = new QTimer();
timer.interval = 5000;
timer.timeout.connect(notifyActiveWindow);
timer.start();

// Initial tick
notifyActiveWindow();
