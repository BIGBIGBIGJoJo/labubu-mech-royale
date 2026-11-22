"""Optional exact move_clear acceleration for the immutable loaded arena.

The original ArenaMap and its geometry/cache signatures remain authoritative.
Only a complete native predicate result replaces a Python query. Unsupported
metadata, absent libraries and customized geometry methods use the original.
"""
import ctypes
import math
from pathlib import Path
import weakref

import arena_map

_base = arena_map.ArenaMap
_methods = ('ground_height', '_terrain_grade', '_terrain_cuts', '_grade_clear',
            '_candidates', '_solid', 'point_clear')
_original = tuple(getattr(_base, name) for name in _methods)
try:
    _library = ctypes.CDLL(str(Path(__file__).with_name('libterrain.so')))
    _library.movement_kernel_version.restype = ctypes.c_int
    if _library.movement_kernel_version() != 1:
        raise OSError('Unsupported movement kernel ABI')
    _create, _destroy, _clear = (_library.movement_create, _library.movement_destroy,
                                _library.movement_clear)
    _create.argtypes = [ctypes.POINTER(ctypes.c_int16), ctypes.c_int, ctypes.c_int,
                       ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double), ctypes.c_size_t]
    _create.restype = ctypes.c_void_p
    _destroy.argtypes, _destroy.restype = [ctypes.c_void_p], None
    _clear.argtypes, _clear.restype = [ctypes.c_void_p] + [ctypes.c_double]*9, ctypes.c_int
except (OSError, AttributeError):
    _library = _create = _destroy = _clear = None


def _metadata(arena):
    t, b = arena.terrain, arena.bounds
    return (t['minX'], t['minY'], t['step'], t.get('scale', .01),
            b['minX'], b['minY'], b['maxX'], b['maxY'], arena.step_up,
            arena.max_slope, arena.arena_margin, arena.CONTACT_EPS)


class ArenaMap(_base):
    def __init__(self, *args, **kwargs):
        self._movement_context = None
        self.movement_kernel_status = 'unavailable'
        super().__init__(*args, **kwargs)
        if not self.available or _create is None:
            return
        if self.samples.typecode != 'h' or self.samples.itemsize != 2 or len(self.samples) != self.nx*self.ny:
            return
        try:
            metadata = _metadata(self)
            flat = []
            for prism in self.prisms:
                rings = [prism['ring'], *prism.get('holes', [])]
                flat.extend((prism['base'], prism['top'], len(rings)))
                for ring in rings:
                    flat.extend((len(ring)//2, *ring))
            self._movement_samples = self.samples
            self._movement_view = (ctypes.c_int16*len(self.samples)).from_buffer(self.samples)
            context = _create(self._movement_view, self.nx, self.ny,
                              (ctypes.c_double*12)(*metadata),
                              (ctypes.c_double*len(flat))(*flat), len(flat))
            if not context:
                self.movement_kernel_status = 'unsupported metadata'
                return
            self._movement_context = context
            self._movement_finalizer = weakref.finalize(self, _destroy, context)
            self._movement_key = (self.nx, self.ny, id(self.prisms), len(self.prisms), id(self.bins), metadata)
            self.movement_kernel_status = 'loaded'
        except (ValueError, TypeError, KeyError, OverflowError, BufferError):
            self.movement_kernel_status = 'unsupported metadata'

    def move_clear(self, pos, end, radius=2.5, height=9.0):
        context = self._movement_context
        if context is not None and self.available:
            # Loaded world geometry is immutable. Guard replacement/configuration
            # changes and test/custom map overrides before using its native copy.
            key = (self.nx, self.ny, id(self.prisms), len(self.prisms), id(self.bins), _metadata(self))
            methods = tuple(getattr(getattr(self, name), '__func__', getattr(self, name)) for name in _methods)
            if (key == self._movement_key and self.samples is self._movement_samples
                    and len(self.samples) == self.nx*self.ny and methods == _original):
                # CPython's compensated hypot can differ by one ULP from libm.
                # Keep its exact distance for terrain grade and sample counts.
                distance = math.hypot(end[0]-pos[0], end[1]-pos[1])
                result = _clear(context, *pos, *end, radius, height, distance)
                if result in (0, 1):
                    return bool(result)
        return super().move_clear(pos, end, radius, height)
