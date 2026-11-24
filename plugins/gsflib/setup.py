"""Build only the optional plugin, using the user's reference GSF distribution."""
import os
import sys
from pathlib import Path

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext

source = os.environ.get("GSFLIB_SOURCE_DIR")
prefix = os.environ.get("GSFLIB_PREFIX")
if bool(source) == bool(prefix):
    raise RuntimeError("Set exactly one of GSFLIB_SOURCE_DIR or GSFLIB_PREFIX (GSF 3.11).")

sources = ["native/shim.c"]
reference_sources = []
options = {}
if source:
    directory = Path(source).resolve()
    names = ("gsf", "gsf_dec", "gsf_enc", "gsf_indx", "gsf_info", "gsf_geo", "gsf_compress")
    reference_sources = [str(directory / (name + ".c")) for name in names]
    options["include_dirs"] = [str(directory)]
else:
    directory = Path(prefix).resolve()
    options.update(include_dirs=[str(directory / "include")],
                   library_dirs=[str(directory / "lib")], libraries=["gsf"])
    if os.name != "nt":
        options["runtime_library_dirs"] = [str(directory / "lib")]
if os.name != "nt":
    options.setdefault("libraries", []).append("m")


class ReferenceBuild(build_ext):
    def build_extensions(self):
        self.force = True
        self.compiler.force = True
        # Compile user-owned sources separately. They must not enter the package
        # manifest or source distribution as absolute paths or vendored code.
        if reference_sources:
            extension = self.extensions[0]
            macros = [("_LARGEFILE64_SOURCE", "1"), ("_FILE_OFFSET_BITS", "64")]
            if sys.platform == "darwin":
                # macOS uses 64-bit off_t through the unsuffixed POSIX API.
                macros += [(name + "64", name) for name in ("stat", "fopen", "fseeko", "ftello")]
            objects = self.compiler.compile(reference_sources, output_dir=self.build_temp,
                                            include_dirs=extension.include_dirs, macros=macros)
            extension.extra_objects = list(extension.extra_objects or []) + objects
        super().build_extensions()


setup(ext_modules=[Extension("mbtoolkit_gsflib._native", sources, **options)],
      cmdclass={"build_ext": ReferenceBuild})
