from ctypes import *
from ctypes.wintypes import *
import time, sys, subprocess, threading
import psutil

WM_DESTROY = 0x02
WNDPROCTYPE = WINFUNCTYPE(c_longlong, HWND, c_uint, WPARAM, LPARAM)
class WNDCLASSEX(Structure):
    _fields_ = [("cbSize", c_uint), ("style", c_uint), ("lpfnWndProc", WNDPROCTYPE), ("cbClsExtra", c_int),
                ("cbWndExtra", c_int), ("hInstance", HANDLE), ("hIcon", HANDLE), ("hCursor", HANDLE),
                ("hBrush", HANDLE), ("lpszMenuName", LPCWSTR), ("lpszClassName", LPCWSTR), ("hIconSm", HANDLE)]

def WndProc(hWnd, msg, wParam, lParam):
    if msg not in (1, 36, 129, 131): # i.e. ones I've checked that we don't care about logging
        print('WndProc', msg, wParam, lParam)
    if msg == WM_DESTROY:
        windll.user32.PostQuitMessage(0)
    else:
        return windll.user32.DefWindowProcA(hWnd, msg, WPARAM(wParam), LPARAM(lParam))
    return 0

class FSForceRunner:
    '''creates a dummy window that FSForce can send messages to, then spawns FSForce in the background,
    pumping messages in the dummy window until Stop() is called
    '''
    def __init__(self):
        self.running = False
        self.keepRunning = False

    def Start(self):
        assert not self.running
        self.keepRunning = True
        self.thread = threading.Thread(target=self._Thread)
        self.thread.daemon = 1
        self.thread.start()

    def Stop(self, maxWait = 0.5):
        if self.running:
            self.keepRunning = False
            waitUntil = time.time() + maxWait
            while self.running and time.time() < waitUntil:
                time.sleep(0.1)
            if self.running:
                print('WARNING: message thread is still running')

    def _Thread(self):
        self.running = True
        try:
            # get hInst - since we're starting as a console app, we don't get it via a WinMain
            self.hInst = windll.kernel32.GetModuleHandleW(None)
            assert self.hInst

            # Register our custom window class and create message only window
            className = 'FS89MAIN' # TODO: once we no longer need the proxy, use FS98MAIN (instead of 89) and unpatched FSForce
            wc = WNDCLASSEX()
            wc.cbSize = sizeof(WNDCLASSEX)
            wc.lpfnWndProc = WNDPROCTYPE(WndProc)
            wc.style = wc.cbClsExtra = wc.cbWndExtra = wc.hIcon = wc.hBrush = wc.hCursor = wc.lpszMenuName = wc.hIconSm = 0
            wc.hInstance = self.hInst
            wc.lpszClassName = className
            if not windll.user32.RegisterClassExW(byref(wc)):
                raise Exception('Failed to register class')

            HWND_MESSAGE = -3 # message only window
            hWnd = windll.user32.CreateWindowExW(0, className, "shim", 0, 0, 0, 0, 0, HWND_MESSAGE, 0, 0, 0)
            if not hWnd:
                raise Exception('Failed to create window')

            # Load the FSForce DLL
            fsDLL = windll.LoadLibrary('d:\\Program Files (x86)\\FSForce 2\\FSForce_x64.dll')
            if not fsDLL:
                raise Exception('Failed to load FSForce_x64.dll')
            print('Starting DLL', fsDLL.DLLStart())

            # Kill any prior versions of the FSForce executable, then relaunch
            for p in psutil.process_iter(attrs=['name']):
                if p.info['name'] == 'FSForce.exe':
                    p.kill()
                    print('killed one old instance')
            fsEXE = subprocess.Popen(['d:\\Program Files (x86)\\FSForce 2\\FSForce.exe', '/FS'])

            try:
                # Pump messages til done
                #print('Pumping messages')
                msg = MSG()
                pMsg = pointer(msg)
                while self.keepRunning:
                    if windll.user32.PeekMessageW(pMsg, 0, 0, 0, 1):
                        windll.user32.TranslateMessage(pMsg)
                        windll.user32.DispatchMessageW(pMsg)
                    else:
                        time.sleep(0.05)
            finally:
                print('killing fsEXE')
                fsEXE.kill()
        finally:
            self.running = False

if __name__ == '__main__':
    print('sleeping') ; time.sleep(2) ; print('going')
    runner = FSForceRunner()
    runner.Start()
    try:
        while 1:
            time.sleep(0.25)
    except KeyboardInterrupt:
        runner.Stop()

