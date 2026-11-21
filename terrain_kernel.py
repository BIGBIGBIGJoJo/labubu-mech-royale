"""Optional compiled terrain-ray loop; unchanged Python geometry is fallback."""
import ctypes
from pathlib import Path

try:
    _library=ctypes.CDLL(str(Path(__file__).with_name('libterrain.so')))
    _library.terrain_kernel_version.restype=ctypes.c_int
    if _library.terrain_kernel_version()!=1:
        raise OSError('Unsupported terrain kernel ABI')
    _line=_library.terrain_line_clear
    _line.argtypes=[ctypes.POINTER(ctypes.c_int16),ctypes.c_int,ctypes.c_int]+[ctypes.c_double]*10
    _line.restype=ctypes.c_int
except (OSError,AttributeError):
    _library=None
    _line=None


class TerrainKernel:
    def __init__(self, samples, nx, ny, terrain):
        self.samples=samples
        self.key=(nx,ny,terrain['minX'],terrain['minY'],terrain['step'],terrain.get('scale',.01))
        self.view=(ctypes.c_int16*len(samples)).from_buffer(samples)

    def line_clear(self, arena, start, end):
        t=arena.terrain
        key=(arena.nx,arena.ny,t['minX'],t['minY'],t['step'],t.get('scale',.01))
        if self.samples is not arena.samples or key!=self.key or len(self.samples)!=arena.nx*arena.ny:
            return None
        result=_line(self.view,*key,*start,*end)
        return bool(result) if result in (0,1) else None


def make_kernel(arena):
    if _line is None or arena.samples.typecode!='h' or arena.samples.itemsize!=2:
        return None
    if arena.nx<2 or arena.ny<2 or len(arena.samples)!=arena.nx*arena.ny:
        return None
    return TerrainKernel(arena.samples,arena.nx,arena.ny,arena.terrain)
