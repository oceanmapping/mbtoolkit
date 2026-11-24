"""Backend-neutral GSF API. Parser libraries are imported only when selected."""
import argparse
import importlib
import importlib.util
import os

from .backend import Decoder, Reader
from .model import (
    ATTITUDE, COMMENT, HEADER, HISTORY, HV_NAVIGATION_ERROR, NAVIGATION_ERROR,
    PROCESSING_PARAMETERS, SENSOR_PARAMETERS, SINGLE_BEAM_SOUNDING,
    SOUND_VELOCITY_PROFILE, SWATH_BATHYMETRY, SWATH_BATHY_SUMMARY,
    AttitudeData, BackendError, BackendInfo, BackendUnavailableError,
    DecodeRequest, FormatError, Record, RecordData, UnsupportedFeatureError,
)

ENTRY_POINT_GROUP = "mbtoolkit.gsf_backends"
DEFAULT_BACKEND = "pygsf"


def _plugins():
    try:
        from importlib.metadata import entry_points
    except ImportError:
        from importlib_metadata import entry_points
    points = entry_points()
    entries = points.select(group=ENTRY_POINT_GROUP) if hasattr(points, "select") else points.get(ENTRY_POINT_GROUP, ())
    result = {}
    for entry in entries:
        if entry.name in {"pygsf", "gsfu"} or entry.name in result:
            raise BackendError("Duplicate or reserved backend name: " + entry.name)
        result[entry.name] = entry
    return result


def available_backends():
    """Inspect installed backend names without loading third-party plugin code."""
    entries = {
        "pygsf": "bundled",
        "gsfu": "installed" if importlib.util.find_spec("GSFU") else 'not installed; pip install ".[gsfu]"',
    }
    plugins = _plugins()
    entries.update({name: "installed plugin" for name in plugins})
    if "gsflib" not in plugins:
        entries["gsflib"] = "not installed; build plugins/gsflib with GSF 3.11 (see plugins/gsflib/README.md)"
    return entries


def open_reader(path, backend=None):
    """Select explicit backend, then MBTOOLKIT_GSF_BACKEND, then bundled pygsf.

    Selection is deterministic. Missing dependencies, unsupported features,
    and decode failures never trigger fallback to a different parser.
    """
    name = backend if backend is not None else os.environ.get("MBTOOLKIT_GSF_BACKEND", DEFAULT_BACKEND)
    if name in {"pygsf", "gsfu"}:
        module = importlib.import_module(".backends." + name, __name__)
        decoder = getattr(module, "PygsfDecoder" if name == "pygsf" else "GsfuDecoder")()
    else:
        plugins = _plugins()
        if name not in plugins:
            raise BackendUnavailableError("Backend {!r} is unavailable. Known backends: {}. "
                                          "Native adapters register entry points in {}.".format(
                                              name, ", ".join(available_backends()), ENTRY_POINT_GROUP))
        try:
            decoder = plugins[name].load()()
        except BackendError:
            raise
        except (ImportError, OSError) as exc:
            raise BackendUnavailableError("Backend {!r} dependencies are unavailable: {}".format(
                name, exc)) from exc
        except Exception as exc:
            raise BackendError("Cannot load backend {!r}: {}".format(name, exc)) from exc
        if not isinstance(decoder, Decoder):
            raise BackendError("Backend plugins must implement readers.Decoder")
        if not isinstance(decoder.info, BackendInfo) or decoder.info.api_version != 1:
            raise BackendError("Backend plugins must use backend API version 1")
        if decoder.info.name != name:
            raise BackendError("Backend plugin name differs from its advertised BackendInfo")
    return Reader(path, decoder)


class _ListBackends(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        for name, status in available_backends().items():
            print("{}: {}".format(name, status))
        parser.exit()


def add_backend_arguments(parser):
    parser.add_argument("--backend", metavar="NAME", help=(
        "GSF parser backend (explicit option > MBTOOLKIT_GSF_BACKEND > pygsf)"))
    parser.add_argument("--list-backends", nargs=0, action=_ListBackends,
                        help="List installed and optional parser backends and exit")
