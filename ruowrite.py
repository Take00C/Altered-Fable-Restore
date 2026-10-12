"""Write a Photonmelodies .ruo file.

Engine facts (Muv-Luv_PM.exe FUN_005de150 / FUN_005de420):
 - the .ruo is mapped at virtual units (2^shift + 0x17FFFFFFF) >> shift  -> 6 GiB for shift 2;
 - parts are searched in order and the FIRST part whose [start, start+len] contains a position wins;
 - the base archive is 7,786,022,612 bytes, so positions < 7.79 GB resolve into photonmelodies11.rio.004.
=> objects must sit at ruo file offsets > 7,786,022,612 - 6 GiB = 1,343,571,668. We start at DATA_START and keep
   the leading region sparse (NTFS sparse file: no disk space used).
Table entries: (key enc_off, K + filepos>>2, enc_size(raw size)), then u32 count at the very end."""
import os, struct, ctypes, ctypes.wintypes as wt, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objio import enc_size, K, PM_RIO, parts

SHIFT = 2
RUO_VBASE = ((1 << SHIFT) + 0x17FFFFFFF) >> SHIFT << SHIFT        # 6 GiB


def base_total():
    return sum(os.path.getsize(p) for p in parts(PM_RIO))


def data_start():
    need = base_total() - RUO_VBASE + 1
    return (need + 0xFFFFF) & ~0xFFFFF          # round up to 1 MiB


def set_sparse(path):
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.CreateFileW.restype = wt.HANDLE
    k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
    k32.DeviceIoControl.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD,
                                    ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
    h = k32.CreateFileW(path, 0xC0000000, 0, None, 2, 0x80, None)   # CREATE_ALWAYS
    if h in (None, wt.HANDLE(-1).value):
        raise OSError(ctypes.get_last_error())
    ret = wt.DWORD()
    ok = k32.DeviceIoControl(h, 0x000900C4, None, 0, None, 0, ctypes.byref(ret), None)   # FSCTL_SET_SPARSE
    k32.CloseHandle(h)
    return bool(ok)


def write_ruo(path, objs):
    """objs: list of (key_enc_off, bytes). Returns (data_start, total_size)."""
    start = data_start()
    sparse = set_sparse(path)
    blob = bytearray(); table = []
    for key, data in objs:
        while len(blob) % 4: blob.append(0)
        pos = start + len(blob)
        table.append(struct.pack('<III', key, (K + (pos >> SHIFT)) & 0xFFFFFFFF, enc_size(len(data))))
        blob += data
    while len(blob) % 4: blob.append(0)
    with open(path, 'r+b') as f:
        f.seek(start)
        f.write(bytes(blob) + b''.join(table) + struct.pack('<I', len(table)))
    return start, os.path.getsize(path), sparse


if __name__ == '__main__':
    print('base total', base_total(), 'ruo vbase', RUO_VBASE, 'data start', hex(data_start()))
