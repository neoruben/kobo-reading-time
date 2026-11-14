#!/usr/bin/env python3
"""Windows app for the Kobo reading-time patch (no SSH needed).

1. Finds the Kobo connected over USB and reads .kobo/version.
2. Gets the original libnickel.so.1.0.0 from Kobo's official firmware update
   (downloaded from Kobo's servers once and cached), or from a file you choose.
3. Patches it with make_patch.patch() and writes .kobo/KoboRoot.tgz on the Kobo.
   "Undo" writes the original, unpatched libnickel the same way.

Run:   python kobo_gui.py            (or the packaged KoboReadingTime.exe)
Test:  python kobo_gui.py --kobo D:\\some\\folder   (folder that looks like a Kobo)
"""
import hashlib, io, os, queue, sys, tarfile, threading, urllib.request, zipfile
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import make_patch as mp

FW_VERSION = '4.46.23852'
ORIGINAL_MD5 = 'ff0d6f9cba0ff963a71cc98384089070'
FW_URL = 'https://ereaderfiles.kobo.com/firmwares/kobo12/Oct2026/kobo-update-4.46.23852.zip'
# Device IDs (last field of .kobo/version) whose 4.46.23852 update is the kobo12
# zip above, i.e. the same libnickel.  tested = seen working on a real device.
MODELS = {
    '00000000-0000-0000-0000-000000000391': ('Kobo Clara BW', True),
    '00000000-0000-0000-0000-000000000393': ('Kobo Clara Colour', False),
}
CACHE = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'KoboReadingTime')
CACHED_LIB = os.path.join(CACHE, f'libnickel-{FW_VERSION}.so.1.0.0')
SAMPLE = {'%0': '9', '%1': '39', '%n': '39'}

T = {
    'es': dict(
        title='Kobo: tiempo de lectura', kobo='Kobo:', refresh='Buscar de nuevo',
        none='No se encuentra ningún Kobo. Conéctalo por USB y pulsa «Buscar de nuevo».',
        text='Texto:', custom='Personalizado…', hm='Horas y minutos (%0 = h, %1 = min):',
        mins='Solo minutos (%n = min):', preview='Se verá así:',
        install='Instalar parche', undo='Quitar parche', own='Usar un libnickel propio…',
        ok_model='{model}, firmware {fw}: compatible.',
        untested='{model}, firmware {fw}: debería funcionar, pero nadie lo ha probado aún.',
        bad_fw='{model}, firmware {fw}: no compatible (solo {need}).',
        bad_model='Modelo {model}, firmware {fw}: no compatible (solo Kobo Clara BW / Clara Colour).',
        cached='Usando el libnickel original guardado en caché.',
        downloading='Descargando el firmware oficial de Kobo ({mb} MB, solo la primera vez)…',
        extracting='Extrayendo libnickel del firmware…', checking='Comprobando MD5…',
        bad_md5='El archivo no es el libnickel original de {fw} (MD5 {md5}). No se ha escrito nada.',
        patching='Aplicando el parche…', writing='Escribiendo {path}…',
        done_install='Listo. Expulsa el Kobo desde Windows, desconéctalo y espera: '
                     'Kobo instalará el parche y se reiniciará solo.',
        done_undo='Listo. Expulsa el Kobo, desconéctalo y espera: Kobo volverá al '
                  'texto original y se reiniciará solo.',
        exists='Ya hay un KoboRoot.tgz pendiente en el Kobo (quizá de una actualización). '
               '¿Reemplazarlo?',
        untested_q='Este modelo no se ha probado. Modificar archivos del sistema puede dejar '
                   'el Kobo sin arrancar. ¿Continuar?',
        error='Error', untested_tag=' (sin probar)'),
    'en': dict(
        title='Kobo reading time', kobo='Kobo:', refresh='Search again',
        none='No Kobo found. Connect it over USB and click "Search again".',
        text='Text:', custom='Custom…', hm='Hours and minutes (%0 = h, %1 = min):',
        mins='Minutes only (%n = min):', preview='It will look like:',
        install='Install patch', undo='Remove patch', own='Use my own libnickel…',
        ok_model='{model}, firmware {fw}: supported.',
        untested='{model}, firmware {fw}: should work, but nobody has tested it yet.',
        bad_fw='{model}, firmware {fw}: not supported (only {need}).',
        bad_model='Model {model}, firmware {fw}: not supported (only Kobo Clara BW / Clara Colour).',
        cached='Using the cached original libnickel.',
        downloading="Downloading Kobo's official firmware ({mb} MB, first time only)…",
        extracting='Extracting libnickel from the firmware…', checking='Checking MD5…',
        bad_md5='That file is not the original {fw} libnickel (MD5 {md5}). Nothing was written.',
        patching='Patching…', writing='Writing {path}…',
        done_install='Done. Eject the Kobo in Windows, unplug it and wait: Kobo will '
                     'install the patch and restart by itself.',
        done_undo='Done. Eject the Kobo, unplug it and wait: Kobo will go back to the '
                  'original text and restart by itself.',
        exists='There is already a pending KoboRoot.tgz on the Kobo (maybe an update). Replace it?',
        untested_q='This model has not been tested. Modifying system files can leave the Kobo '
                   'unable to boot. Continue?',
        error='Error', untested_tag=' (untested)'),
}


def ui_lang():
    try:
        import ctypes
        return 'es' if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3ff == 0x0a else 'en'
    except Exception:
        return 'en'


# ---------------------------------------------------------------- core logic

def read_version(root):
    """Return (device_id, firmware) from <root>/.kobo/version, or None."""
    try:
        with open(os.path.join(root, '.kobo', 'version'), encoding='ascii', errors='replace') as f:
            parts = f.read().strip().split(',')
    except OSError:
        return None
    # serial, kernel, firmware, ..., device id
    if len(parts) < 4:
        return None
    return parts[-1].strip(), parts[2].strip()


def find_kobos():
    roots = []
    if os.name == 'nt':
        import ctypes, string
        k = ctypes.windll.kernel32
        old = k.SetErrorMode(1)   # no "insert a disk" popups for empty card readers
        try:
            mask = k.GetLogicalDrives()
            roots = [f'{c}:\\' for i, c in enumerate(string.ascii_uppercase) if mask >> i & 1]
        finally:
            k.SetErrorMode(old)
    return [r for r in roots if read_version(r)]


def describe(root, t):
    """(message, ok, tested) for the Kobo at root."""
    dev, fw = read_version(root)
    model, tested = MODELS.get(dev, (None, False))
    if not model:
        return t['bad_model'].format(model=dev[-3:], fw=fw), False, False
    if fw != FW_VERSION:
        return t['bad_fw'].format(model=model, fw=fw, need=FW_VERSION), False, tested
    return t['ok_model' if tested else 'untested'].format(model=model, fw=fw), True, tested


def md5(b):
    return hashlib.md5(b).hexdigest()


def get_original(log, t, own_file=None):
    """Original libnickel bytes, verified by MD5.  Raises RuntimeError."""
    if own_file:
        data = open(own_file, 'rb').read()
    elif os.path.exists(CACHED_LIB) and md5(open(CACHED_LIB, 'rb').read()) == ORIGINAL_MD5:
        log(t['cached'])
        return open(CACHED_LIB, 'rb').read()
    else:
        os.makedirs(CACHE, exist_ok=True)
        zpath = os.path.join(CACHE, 'firmware.zip.part')
        req = urllib.request.Request(FW_URL, headers={'User-Agent': 'KoboReadingTime'})
        with urllib.request.urlopen(req, timeout=60) as r, open(zpath, 'wb') as f:
            total = int(r.headers.get('Content-Length') or 0)
            log(t['downloading'].format(mb=total // 1_000_000 or '?'))
            got = 0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                got += len(chunk)
                log(None, got / total if total else None)
        log(t['extracting'], None)
        data = None
        with zipfile.ZipFile(zpath) as z, z.open('KoboRoot.tgz') as tgz, \
                tarfile.open(fileobj=tgz, mode='r|gz') as tar:
            for m in tar:
                if m.name.lstrip('./') == mp.TAR_NAME:
                    data = tar.extractfile(m).read()
                    break
        os.remove(zpath)
        if data is None:
            raise RuntimeError('libnickel not found in the firmware zip')
    log(t['checking'])
    if md5(data) != ORIGINAL_MD5:
        raise RuntimeError(t['bad_md5'].format(fw=FW_VERSION, md5=md5(data)))
    if not own_file:
        with open(CACHED_LIB, 'wb') as f:
            f.write(data)
    return data


def texts(lang, custom=None):
    """(hm, mins, hours) as NUL-terminated bytes.  Raises ValueError."""
    def enc(s, need):
        for tok in need:
            if tok not in s:
                raise ValueError(f'"{s}" must contain {tok}')
        return s.encode('utf-8') + b'\0'
    if custom:
        hm, mins = enc(custom[0], ('%0', '%1')), enc(custom[1], ('%n',))
        return hm, mins, mins
    return (enc(mp.LANGS[lang][0], ('%0', '%1')), enc(mp.LANGS[lang][1], ('%n',)),
            enc(mp.HOURS_ONLY[lang], ('%n',)))


def write_tgz(root, data, log, t):
    dst = os.path.join(root, '.kobo', 'KoboRoot.tgz')
    tmp = dst + '.part'
    log(t['writing'].format(path=dst))
    mp.make_tgz(data, tmp)      # also reads it back and compares
    os.replace(tmp, dst)
    with tarfile.open(dst) as tar:
        assert tar.extractfile(mp.TAR_NAME).read() == data


def run(root, undo, lang, custom, log, t, own_file=None):
    orig = get_original(log, t, own_file)
    if undo:
        out = orig
    else:
        log(t['patching'])
        hm, mins, hours = texts(lang, custom)
        try:
            out = mp.patch(orig, hm, mins, hours, verbose=False)
        except SystemExit as e:     # make_patch reports some errors with sys.exit
            raise RuntimeError(str(e))
    write_tgz(root, out, log, t)


# ---------------------------------------------------------------- GUI

def preview(s):
    for k, v in SAMPLE.items():
        s = s.replace(k, v)
    return s


class App:
    def __init__(self, master, forced_root=None):
        self.t = t = T[ui_lang()]
        self.m, self.forced, self.q, self.busy = master, forced_root, queue.Queue(), False
        master.title(t['title'])
        master.resizable(False, False)
        f = ttk.Frame(master, padding=14)
        f.grid(sticky='nsew')
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text=t['kobo']).grid(row=0, column=0, sticky='w')
        self.kobo = ttk.Combobox(f, state='readonly', width=12)
        self.kobo.grid(row=0, column=1, sticky='w', padx=6)
        self.kobo.bind('<<ComboboxSelected>>', lambda e: self.update_state())
        ttk.Button(f, text=t['refresh'], command=self.scan).grid(row=0, column=2, sticky='e')
        self.status = ttk.Label(f, wraplength=430, justify='left')
        self.status.grid(row=1, column=0, columnspan=3, sticky='w', pady=(6, 12))

        ttk.Label(f, text=t['text']).grid(row=2, column=0, sticky='w')
        self.langs = sorted(mp.LANGS)
        names = [f'{l} — {preview(mp.LANGS[l][0])}' for l in self.langs] + [t['custom']]
        self.lang = ttk.Combobox(f, state='readonly', values=names, width=34)
        self.lang.current(self.langs.index(ui_lang()))
        self.lang.grid(row=2, column=1, columnspan=2, sticky='w', padx=6)
        self.lang.bind('<<ComboboxSelected>>', lambda e: self.update_state())

        self.cf = ttk.Frame(f)
        self.hm, self.mins = tk.StringVar(value=mp.LANGS['en'][0]), tk.StringVar(value=mp.LANGS['en'][1])
        ttk.Label(self.cf, text=t['hm']).grid(row=0, column=0, sticky='w')
        ttk.Entry(self.cf, textvariable=self.hm, width=30).grid(row=0, column=1, padx=6, pady=2)
        ttk.Label(self.cf, text=t['mins']).grid(row=1, column=0, sticky='w')
        ttk.Entry(self.cf, textvariable=self.mins, width=30).grid(row=1, column=1, padx=6, pady=2)
        for v in (self.hm, self.mins):
            v.trace_add('write', lambda *a: self.update_state())
        self.cf.grid(row=3, column=0, columnspan=3, sticky='w', pady=(6, 0))
        self.prev = ttk.Label(f, foreground='#555')
        self.prev.grid(row=4, column=0, columnspan=3, sticky='w', pady=(6, 12))

        b = ttk.Frame(f)
        b.grid(row=5, column=0, columnspan=3, sticky='ew')
        self.b_install = ttk.Button(b, text=t['install'], command=lambda: self.start(False))
        self.b_undo = ttk.Button(b, text=t['undo'], command=lambda: self.start(True))
        self.b_own = ttk.Button(b, text=t['own'], command=self.choose_own)
        self.b_install.pack(side='left')
        self.b_undo.pack(side='left', padx=6)
        self.b_own.pack(side='right')
        self.own_file = None

        self.bar = ttk.Progressbar(f, length=430, mode='determinate')
        self.bar.grid(row=6, column=0, columnspan=3, sticky='ew', pady=(12, 4))
        self.msg = ttk.Label(f, wraplength=430, justify='left')
        self.msg.grid(row=7, column=0, columnspan=3, sticky='w')
        self.scan()
        master.after(100, self.poll)

    # state ------------------------------------------------------------
    def scan(self):
        roots = [self.forced] if self.forced else find_kobos()
        self.kobo['values'] = roots
        if roots:
            self.kobo.current(0)
        else:
            self.kobo.set('')
        self.update_state()

    def custom(self):
        return self.lang.current() == len(self.langs)

    def update_state(self):
        t, root = self.t, self.kobo.get()
        if root:
            text, self.ok, self.tested = describe(root, t)
        else:
            text, self.ok, self.tested = t['none'], False, False
        self.status['text'] = text
        if self.custom():
            self.cf.grid()
            s = self.hm.get()
        else:
            self.cf.grid_remove()
            s = mp.LANGS[self.langs[self.lang.current()]][0]
        self.prev['text'] = f"{t['preview']}  {preview(s)}"
        st = 'normal' if self.ok and not self.busy else 'disabled'
        for w in (self.b_install, self.b_undo, self.b_own):
            w['state'] = st

    def choose_own(self):
        p = filedialog.askopenfilename(title='libnickel.so.1.0.0')
        if p:
            self.own_file = p
            self.msg['text'] = p

    # work -------------------------------------------------------------
    def start(self, undo):
        t, root = self.t, self.kobo.get()
        if not self.tested and not messagebox.askyesno(t['title'], t['untested_q'], icon='warning'):
            return
        if os.path.exists(os.path.join(root, '.kobo', 'KoboRoot.tgz')) and \
                not messagebox.askyesno(t['title'], t['exists'], icon='warning'):
            return
        custom = (self.hm.get(), self.mins.get()) if self.custom() else None
        lang = None if custom else self.langs[self.lang.current()]
        try:
            texts(lang, custom)
        except ValueError as e:
            messagebox.showerror(t['error'], str(e))
            return
        self.busy = True
        self.update_state()
        self.bar['value'] = 0

        def log(text, frac=None):
            self.q.put(('log', text, frac))

        def work():
            try:
                run(root, undo, lang, custom, log, t, self.own_file)
                self.q.put(('done', t['done_undo' if undo else 'done_install'], None))
            except Exception as e:
                self.q.put(('fail', f'{type(e).__name__}: {e}' if not isinstance(e, RuntimeError)
                            else str(e), None))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, text, frac = self.q.get_nowait()
                if text:
                    self.msg['text'] = text
                if kind == 'log':
                    self.bar['value'] = frac * 100 if frac is not None else self.bar['value']
                else:
                    self.busy = False
                    self.bar['value'] = 100 if kind == 'done' else 0
                    self.update_state()
                    (messagebox.showinfo if kind == 'done' else messagebox.showerror)(
                        self.t['title'] if kind == 'done' else self.t['error'], text)
        except queue.Empty:
            pass
        self.m.after(100, self.poll)


def main():
    forced = None
    if '--kobo' in sys.argv:
        forced = sys.argv[sys.argv.index('--kobo') + 1]
    root = tk.Tk()
    App(root, forced)
    root.mainloop()


if __name__ == '__main__':
    main()
