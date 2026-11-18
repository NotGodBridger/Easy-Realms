"""Console-free Windows bootstrap; uses only Python's standard library."""
from pathlib import Path
import ctypes
from datetime import datetime, timezone
import importlib.util
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('EASY_REALMS_DATA', ROOT/'data'))
LOG_DIR = DATA_DIR / 'logs'
LOG = LOG_DIR / ('startup-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+'.log')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def command(args, log, timeout):
    result = subprocess.run(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=NO_WINDOW, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Setup could not complete. Open the startup log for details, then retry.')


def probe(python, log, mode='--dependencies-only'):
    return subprocess.run([str(python), str(ROOT/'dependency_check.py'), mode],
                          cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                          creationflags=NO_WINDOW, timeout=45).returncode == 0


def prepare(send):
    """Install only missing dependencies, then wait for the real UI-ready signal."""
    log_dir=LOG.parent;log_dir.mkdir(parents=True, exist_ok=True)
    old_logs=sorted(log_dir.glob('startup-*.log'),key=lambda path:path.stat().st_mtime,reverse=True)
    for old_log in old_logs[9:]:
        try:old_log.unlink()
        except OSError:pass
    with LOG.open('w', encoding='utf-8') as log:
        log.write('Easy Realms startup\n');log.flush()
        send('Checking your Python environment…')
        python = ROOT / '.venv' / 'Scripts' / 'python.exe' if os.name == 'nt' else ROOT / '.venv' / 'bin' / 'python'
        if not python.exists():
            send('Preparing Easy Realms for its first launch…')
            command([sys.executable, '-m', 'venv', str(ROOT / '.venv')], log, 180)
        send('Checking required components…')
        if not probe(python, log):
            send('Installing required components… First launch may take a few minutes.')
            pip_probe = subprocess.run([str(python), '-m', 'pip', '--version'], cwd=ROOT,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=NO_WINDOW, timeout=30)
            if pip_probe.returncode:
                command([str(python), '-m', 'ensurepip', '--upgrade'], log, 180)
            command([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                     '--no-input', '--upgrade', '--only-binary=:all:',
                     '-r', str(ROOT/'requirements.txt')], log, 600)
            send('Verifying installed components…')
            if not probe(python, log):
                raise RuntimeError('Required components were installed but did not pass verification. Open the startup log for details.')
        if not probe(python, log, '--files-only'):
            raise RuntimeError('Easy Realms application files are incomplete. Download and extract a fresh copy, then retry.')
        send('Opening your server dashboard…')
        fd, marker = tempfile.mkstemp(prefix='easyservers-ready-', suffix='.flag')
        os.close(fd);Path(marker).unlink()
        env = dict(os.environ, EASY_SERVERS_READY_FILE=marker)
        child = None
        try:
            child = subprocess.Popen([str(python), str(ROOT/'app.py')], cwd=ROOT, env=env,
                                     stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
            deadline = time.monotonic()+90
            while not Path(marker).exists():
                if child.poll() is not None:
                    raise RuntimeError('The dashboard could not open. The startup log contains the error.')
                if time.monotonic()>deadline:
                    child.terminate();child.wait(timeout=10)
                    raise RuntimeError('The dashboard took too long to open. Check the startup log and retry.')
                time.sleep(.1)
        finally:
            Path(marker).unlink(missing_ok=True)


class LoadingScreen:
    def __init__(self):
        self.events=queue.Queue();self.root=tk.Tk();self.root.title('Starting Easy Realms')
        if os.name=='nt':self.root.iconbitmap(str(ROOT/'assets'/'app-icon.ico'))
        self.root.configure(bg='#242424');self.root.resizable(False,False)
        width,height=560,420
        self.root.geometry(f'{width}x{height}+{(self.root.winfo_screenwidth()-width)//2}+{(self.root.winfo_screenheight()-height)//2}')
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        if os.name=='nt':
            try:
                for name in ('MinecraftTen-VGORe.ttf','Minecraft-Seven_v2.ttf'):
                    ctypes.windll.gdi32.AddFontResourceExW(str(ROOT/'assets'/name),0x10,0)
            except Exception:pass
        tk.Frame(self.root,bg='#70c45c',height=5).pack(fill='x')
        original=tk.PhotoImage(file=str(ROOT/'assets'/'logo.png'))
        cropped=tk.PhotoImage(width=2048,height=917)
        self.root.tk.call(str(cropped),'copy',str(original),'-from',0,565,2048,1482,'-to',0,0)
        self.logo=cropped.subsample(5,5)
        tk.Label(self.root,image=self.logo,bg='#242424').pack(pady=(20,8))
        tk.Label(self.root,text='Your next world starts here.',font=('Minecraft Seven v2',11),fg='#aaa',bg='#242424').pack()
        self.message=tk.StringVar(value='Getting things ready…')
        tk.Label(self.root,textvariable=self.message,font=('Minecraft Seven v2',11),fg='#ededed',bg='#242424',wraplength=480,height=3).pack(pady=(16,4))
        style=ttk.Style();style.theme_use('clam');style.configure('ES.Horizontal.TProgressbar',troughcolor='#161616',background='#79ca63',bordercolor='#161616',lightcolor='#79ca63',darkcolor='#79ca63')
        self.progress=ttk.Progressbar(self.root,style='ES.Horizontal.TProgressbar',mode='indeterminate',length=470);self.progress.pack(pady=8);self.progress.start(12)
        self.actions=tk.Frame(self.root,bg='#242424');self.actions.pack(pady=7)
        self.retry=tk.Button(self.actions,text='Retry',command=self.start,bg='#3f8543',fg='white',relief='flat',padx=18,font=('Minecraft Seven v2',11))
        self.logs=tk.Button(self.actions,text='Open startup log',command=self.open_log,bg='#383838',fg='white',relief='flat',padx=14,font=('Minecraft Seven v2',11))
        self.running=False;self.start();self.root.after(80,self.poll)
    def start(self):
        if self.running:return
        self.running=True;self.retry.pack_forget();self.logs.pack_forget();self.progress.start(12)
        def work():
            try:prepare(lambda msg:self.events.put(('status',msg)));self.events.put(('ready',''))
            except Exception as exc:
                try:
                    with LOG.open('a',encoding='utf-8') as f:
                        import traceback;traceback.print_exc(file=f)
                except OSError:pass
                self.events.put(('error',str(exc)))
        threading.Thread(target=work,daemon=True).start()
    def poll(self):
        try:
            while True:
                kind,message=self.events.get_nowait()
                if kind=='ready':self.running=False;self.root.destroy();return
                if kind=='error':
                    self.running=False;self.progress.stop();self.message.set(message)
                    self.retry.pack(side='left',padx=5);self.logs.pack(side='left',padx=5)
                else:self.message.set(message)
        except queue.Empty:pass
        self.root.after(80,self.poll)
    def open_log(self):
        if os.name=='nt':os.startfile(str(LOG))
        else:subprocess.Popen(['xdg-open',str(LOG)])
    def close(self):
        if self.running:self.message.set('Setup is still running. This window will close when the dashboard opens.')
        else:self.root.destroy()
    def run(self):self.root.mainloop()

if __name__=='__main__':LoadingScreen().run()
