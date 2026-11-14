#!/usr/bin/env python3
"""Reading-time patch for Kobo libnickel.so.1.0.0 (firmware 4.46.23852, Clara BW).

On the home-screen book card and in the library list, Kobo shows the time LEFT
to finish a book ("8 hours to go"). This patch makes it show the time you have
ALREADY spent reading it ("9 h 39 min read"), which Kobo already stores per book.

Changes (all in libnickel.so.1.0.0):
  1. SingleBookHomeWidget / DragonListWidget::setContent read
     Volume TimeSpentReading (d+0x16c) instead of RestOfBookEstimate (d+0x170).
  2. readingTimeLeft() always takes the "hours + minutes" branch that Kobo
     otherwise only uses for audiobooks.
  3. New texts are written into the unused padding at the end of the first
     PT_LOAD segment, and ONLY readingTimeLeft() is pointed at them, so the
     original strings used by other screens (stats, in-book footer) are untouched.

Translations are bypassed (Qt shows the text as written), so you choose the
language when applying the patch:  --lang es|en|fr|de|it|pt|nl  or  --text ...

Requirements: Python 3.8+, `pip install capstone pyelftools`.

Usage:
  python make_patch.py libnickel.so.1.0.0 --lang en --tgz KoboRoot.tgz
  python make_patch.py libnickel.so.1.0.0 --text "%0h %1m read" "%n min read"
"""
import argparse, hashlib, io, re, struct, sys, tarfile, time

SUPPORTED_MD5 = {
    'ff0d6f9cba0ff963a71cc98384089070': '4.46.23852 (Kobo Clara BW, kobo12)',
}

# (hours+minutes, minutes only).  %0 = hours, %1 = minutes, %n = minutes.
LANGS = {
    'es': ('Llevas %0 h %1 min', 'Llevas %n min'),
    'en': ('%0h %1m read', '%n min read'),
    'fr': ('%0 h %1 min de lecture', '%n min de lecture'),
    'de': ('%0 Std. %1 Min. gelesen', '%n Min. gelesen'),
    'it': ('%0 h %1 min di lettura', '%n min di lettura'),
    'pt': ('%0 h %1 min de leitura', '%n min de leitura'),
    'nl': ('%0 u %1 min gelezen', '%n min gelezen'),
}
# Unused after change 2 (ebook "hours only" branch), kept consistent anyway.
HOURS_ONLY = {'es': 'Llevas %n h', 'en': '%n h read', 'fr': '%n h de lecture',
              'de': '%n Std. gelesen', 'it': '%n h di lettura',
              'pt': '%n h de leitura', 'nl': '%n u gelezen'}

# Addresses for 4.46.23852 (virtual address == file offset in segment 1).
SETCONTENT = ((0xda7516, 'SingleBookHomeWidget::setContent'),
              (0xeb15ca, 'DragonListWidget::setContent'))
TIMELEFT = ((0xda6318, 0xda63d8, 'SingleBookHomeWidget::readingTimeLeft'),
            (0xeaee3c, 0xeaeefc, 'DragonListWidget::readingTimeLeft'))
LDR_170 = bytes.fromhex('d3f87021')   # ldr.w r2, [r3, #0x170]
LDR_16C = bytes.fromhex('d3f86c21')   # ldr.w r2, [r3, #0x16c]
TAR_NAME = 'usr/local/Kobo/libnickel.so.1.0.0'


def check_text(s, need):
    for tok in need:
        if tok not in s:
            sys.exit(f'Text "{s}" must contain {tok}')
    if not s.isascii():
        print(f'WARNING: "{s}" has non-ASCII characters; written as UTF-8 (not tested on device).')
    return s.encode('utf-8') + b'\0'


def patch(data, hm, mins, hours, verbose=True):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    from elftools.elf.elffile import ELFFile
    data = bytearray(data)
    elf = ELFFile(io.BytesIO(bytes(data)))
    loads = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
    seg1, seg2 = loads[0], loads[1]
    assert seg1['p_offset'] == 0 and seg1['p_vaddr'] == 0 and seg1['p_filesz'] == seg1['p_memsz']
    changes = []

    def put(off, new, label):
        changes.append((off, bytes(data[off:off + len(new)]), bytes(new), label))
        data[off:off + len(new)] = new

    for va, label in SETCONTENT:
        assert bytes(data[va:va + 4]) == LDR_170, label
        put(va, LDR_16C, f'{label}: TimeSpentReading instead of RestOfBookEstimate')
    for _, va, label in TIMELEFT:
        b = bytes(data[va:va + 2])
        assert b[1] in (0xb1, 0xb3) and (b[0] & 7) == 0, label      # cbz r0, ...
        put(va, bytes.fromhex('00bf'), f'{label}: always hours+minutes format')

    # new strings in segment-1 padding
    end1 = seg1['p_filesz']
    base = cur = (end1 + 15) & ~15
    blob = hours + mins + hm
    if base + len(blob) > seg2['p_offset'] or any(data[base:base + len(blob)]):
        sys.exit('Not enough free padding for these texts (make them shorter).')
    at = {}
    for s in (hours, mins, hm):
        put(cur, s, f'new text "{s[:-1].decode()}"')
        at[s] = cur
        cur += len(s)
    ph = elf['e_phoff'] + elf['e_phentsize'] * next(
        i for i, s in enumerate(elf.iter_segments()) if s['p_type'] == 'PT_LOAD')
    assert struct.unpack_from('<II', data, ph + 16) == (end1, end1)
    put(ph + 16, struct.pack('<II', cur, cur), 'segment 1: filesz/memsz extended')

    targets = {b'%n hour(s) to go': at[hours], b'%n min(s) to go': at[mins],
               b'%nm left': at[mins], b'%0h %1m left': at[hm]}
    old_addr = {}
    for s in targets:
        i = data.find(b'\0' + s + b'\0') + 1
        assert i > 0, s
        old_addr[i] = s

    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB); md.skipdata = True
    for fva, _, fn in TIMELEFT:
        lits, done = {}, 0
        for ins in md.disasm(bytes(data[fva:fva + 700]), fva):
            m = re.match(r'(\w+), \[pc, #(0x[0-9a-f]+|\d+)\]', ins.op_str)
            if ins.mnemonic in ('ldr', 'ldr.w') and m:
                lits[m.group(1)] = ((ins.address + 4) & ~3) + int(m.group(2), 0)
                continue
            m = re.match(r'(\w+), pc$', ins.op_str)
            if ins.mnemonic == 'add' and m and m.group(1) in lits:
                lit = lits.pop(m.group(1))
                w = struct.unpack_from('<I', data, lit)[0]
                tgt = (w + ins.address + 4) & 0xffffffff
                if tgt in old_addr:
                    s = old_addr[tgt]
                    nw = (targets[s] - (ins.address + 4)) & 0xffffffff
                    put(lit, struct.pack('<I', nw), f'{fn}: "{s.decode()}" -> new text')
                    done += 1
        assert done == 4, (fn, done)

    if verbose:
        for off, old, new, label in changes:
            print(f'  {off:#09x}  {old.hex():>28} -> {new.hex():28}  {label}')
    return bytes(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('libnickel', help='original libnickel.so.1.0.0 copied from the Kobo')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--lang', choices=sorted(LANGS), default='es', help='language of the texts (default: es)')
    g.add_argument('--text', nargs=2, metavar=('HOURS_MINUTES', 'MINUTES'),
                   help='custom texts, e.g. "%%0h %%1m read" "%%n min read"')
    ap.add_argument('-o', '--out', help='write patched libnickel here')
    ap.add_argument('--tgz', help='write a KoboRoot.tgz ready to copy to .kobo/')
    ap.add_argument('--restore', action='store_true',
                    help='do not patch: package the ORIGINAL libnickel into --tgz (to undo the patch)')
    ap.add_argument('--force', action='store_true', help='skip the firmware MD5 check (dangerous)')
    a = ap.parse_args()
    if not (a.out or a.tgz):
        ap.error('give --out and/or --tgz')

    src = open(a.libnickel, 'rb').read()
    md5 = hashlib.md5(src).hexdigest()
    print('Input MD5:', md5)
    if md5 not in SUPPORTED_MD5 and not a.force:
        sys.exit('This libnickel is not a supported version; nothing was written.')
    print('Firmware:', SUPPORTED_MD5.get(md5, 'UNKNOWN (--force)'))

    if a.restore:
        if not a.tgz:
            ap.error('--restore needs --tgz')
        out = src
        print('Restore mode: packaging the original, unpatched libnickel.')
    else:
        if a.text:
            hm = check_text(a.text[0], ('%0', '%1'))
            mins = check_text(a.text[1], ('%n',))
            hours = mins   # "hours only" branch is never reached after the patch
        else:
            hm = check_text(LANGS[a.lang][0], ('%0', '%1'))
            mins = check_text(LANGS[a.lang][1], ('%n',))
            hours = check_text(HOURS_ONLY[a.lang], ('%n',))
        print(f'Texts: "{hm[:-1].decode()}" / "{mins[:-1].decode()}"')
        out = patch(src, hm, mins, hours)
        print('Patched MD5:', hashlib.md5(out).hexdigest())
    if a.out:
        open(a.out, 'wb').write(out)
        print('Wrote', a.out)
    if a.tgz:
        ti = tarfile.TarInfo(TAR_NAME)
        ti.size, ti.mode, ti.uid, ti.gid, ti.uname, ti.gname = len(out), 0o775, 0, 0, 'root', 'root'
        ti.mtime = int(time.time())
        with tarfile.open(a.tgz, 'w:gz', format=tarfile.GNU_FORMAT) as t:
            t.addfile(ti, io.BytesIO(out))
        with tarfile.open(a.tgz) as t:
            assert t.extractfile(TAR_NAME).read() == out
        print('Wrote', a.tgz, '(copy it to .kobo/KoboRoot.tgz on the Kobo and reboot)')


if __name__ == '__main__':
    main()
