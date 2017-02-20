from __future__ import print_function
from builtins import object
print("Detected windows, creating rsvg.")
#some workarounds for windows

from ctypes import *

l=CDLL('librsvg-2-2.dll')
g=CDLL('libgobject-2.0-0.dll')
g.g_type_init()

class rsvgHandle(object):
    class RsvgDimensionData(Structure):
        _fields_ = [("width", c_int),
                    ("height", c_int),
                    ("em",c_double),
                    ("ex",c_double)]

    class PycairoContext(Structure):
        _fields_ = [("PyObject_HEAD", c_byte * object.__basicsize__),
                    ("ctx", c_void_p),
                    ("base", c_void_p)]

    def __init__(self, path):
        self.path = path
        error = ''
        self.handle = l.rsvg_handle_new_from_file(self.path,error)


    def get_dimension_data(self):
        svgDim = self.RsvgDimensionData()
        l.rsvg_handle_get_dimensions(self.handle,byref(svgDim))
        return (svgDim.width,svgDim.height)

    def render_cairo(self, ctx):
        ctx.save()
        z = self.PycairoContext.from_address(id(ctx))
        l.rsvg_handle_render_cairo(self.handle, z.ctx)
        ctx.restore()



class rsvgClass(object):
    def Handle(self,file):
        return rsvgHandle(file)

rsvg = rsvgClass()