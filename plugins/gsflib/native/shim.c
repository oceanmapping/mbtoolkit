/* Match the selected gsf.h at compile time; never mirror SDK structs in Python.
 * All SDK calls retain CPython's GIL: gsflib has process-global state/buffers.
 * Each session owns a decoder file table; record views alias its cached arrays.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>
#include <limits.h>
#include <string.h>
#include "gsf.h"
#include "gsf_dec.h"

#ifdef Py_GIL_DISABLED
#error "The reference GSF backend requires a CPython build with the GIL"
#endif

typedef struct {
    int handle;
    gsfRecords records;
    GSF_FILE_TABLE table;
} Session;

static const char *capsule_name = "mbtoolkit_gsflib.Session";

static PyObject *sdk_error(void) {
    PyErr_Format(PyExc_RuntimeError, "GSF error %d: %s", gsfIntError(), gsfStringError());
    return NULL;
}

static void destroy(PyObject *capsule) {
    Session *session = PyCapsule_GetPointer(capsule, capsule_name);
    if (session) {
        if (session->handle) gsfClose(session->handle);
        gsfFree(&session->table.rec);
        PyMem_Free(session);
    }
}

static PyObject *open_session(PyObject *self, PyObject *args) {
    const char *path;
    int major, minor;
    Session *session;
    PyObject *capsule;
    if (!PyArg_ParseTuple(args, "yii", &path, &major, &minor)) return NULL;
    session = PyMem_Calloc(1, sizeof(*session));
    if (!session) return PyErr_NoMemory();
    if (gsfOpen(path, GSF_READONLY, &session->handle) < 0) {
        PyMem_Free(session);
        return sdk_error();
    }
    session->table.major_version_number = major;
    session->table.minor_version_number = minor;
    capsule = PyCapsule_New(session, capsule_name, destroy);
    if (!capsule) {
        gsfClose(session->handle);
        PyMem_Free(session);
    }
    return capsule;
}

static PyObject *close_session(PyObject *self, PyObject *capsule) {
    Session *session = PyCapsule_GetPointer(capsule, capsule_name);
    int handle;
    if (!session) return NULL;
    handle = session->handle;
    session->handle = 0;
    gsfFree(&session->table.rec);
    if (handle && gsfClose(handle) < 0) return sdk_error();
    Py_RETURN_NONE;
}

/* Consume a new reference even on failure. */
static int put(PyObject *dict, const char *key, PyObject *value) {
    int result;
    if (!value) return -1;
    result = PyDict_SetItemString(dict, key, value);
    Py_DECREF(value);
    return result;
}

static int array(PyObject *dict, int sid, const void *data, int count,
                 size_t width, const char *dtype) {
    PyObject *key, *value;
    int result;
    if (!data) return 0;
    key = PyLong_FromLong(sid);
    value = Py_BuildValue("(sy#)", dtype, data, (Py_ssize_t)count * width);
    if (!key || !value) { Py_XDECREF(key); Py_XDECREF(value); return -1; }
    result = PyDict_SetItem(dict, key, value);
    Py_DECREF(key);
    Py_DECREF(value);
    return result;
}

static int64_t epoch_ns(struct timespec time) {
    return (int64_t)time.tv_sec * INT64_C(1000000000) + time.tv_nsec;
}

static uint32_t wire_u32(const unsigned char *p) {
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}

static PyObject *read_record(PyObject *self, PyObject *args) {
    PyObject *capsule, *fields = NULL, *arrays = NULL, *samples = NULL, *result = NULL;
    const char *expected;
    unsigned char *raw;
    Py_ssize_t size;
    int rid, beams, include_arrays, status;
    Session *session;
    gsfSwathBathyPing *p;
    if (!PyArg_ParseTuple(args, "Oiy#p", &capsule, &rid, &expected, &size, &include_arrays)) return NULL;
    session = PyCapsule_GetPointer(capsule, capsule_name);
    if (!session) return NULL;
    if (!session->handle) { PyErr_SetString(PyExc_RuntimeError, "Closed GSF session"); return NULL; }
    if (size > GSF_MAX_RECORD_SIZE || size > INT_MAX) {
        PyErr_SetString(PyExc_ValueError, "Record exceeds the reference library size limit"); return NULL;
    }
    /* Match the reference reader's working-buffer capacity, with zeroed
     * lookahead for its subrecord width detection at the end of a ping. */
    raw = PyMem_Calloc(1, GSF_MAX_RECORD_SIZE + 16);
    if (!raw) return PyErr_NoMemory();
    memcpy(raw, expected, size);
    /* Use the toolkit's physical frames. gsfRead rejects unknown IDs even
     * while skipping records, which would break raw-record retention. A real
     * read-only SDK handle reserves a distinct slot in the decoder's global
     * array-size tables; all per-pass buffers and scale factors live here. */
    if (rid == GSF_RECORD_HEADER) {
        status = gsfDecodeHeader(&session->records.header, raw);
    } else if (rid == GSF_RECORD_SWATH_BATHYMETRY_PING) {
        status = gsfDecodeSwathBathymetryPing(&session->records.mb_ping, raw,
                                            &session->table, session->handle, (int)size);
    } else if (rid == GSF_RECORD_ATTITUDE) {
        status = gsfDecodeAttitude(&session->records.attitude, &session->table, raw);
    } else {
        PyMem_Free(raw);
        PyErr_SetString(PyExc_ValueError, "No normalized projection for record type"); return NULL;
    }
    PyMem_Free(raw);
    if (status < 0) return sdk_error();
    fields = PyDict_New(); arrays = PyDict_New(); samples = Py_None; Py_INCREF(samples);
    if (!fields || !arrays) goto done;
#define I(key, value) if (put(fields, key, PyLong_FromLongLong(value)) < 0) goto done
#define D(key, value) if (put(fields, key, PyFloat_FromDouble(value)) < 0) goto done
    if (rid == GSF_RECORD_HEADER) {
        if (put(fields, "version", PyUnicode_FromString(session->records.header.version)) < 0) goto done;
    } else if (rid == GSF_RECORD_SWATH_BATHYMETRY_PING) {
        p = &session->records.mb_ping;
        I("timestamp_ns", epoch_ns(p->ping_time));
        I("num_beams", p->number_beams); I("centre_beam", p->center_beam);
        I("ping_flags", p->ping_flags); I("reserved", p->reserved);
        D("longitude", p->longitude); D("latitude", p->latitude);
        D("tide_corrector", p->tide_corrector); D("depth_corrector", p->depth_corrector);
        D("heading", p->heading); D("pitch", p->pitch); D("roll", p->roll);
        D("heave", p->heave); D("course", p->course); D("speed", p->speed);
        D("height", p->height); D("separation", p->sep); D("gps_tide_corrector", p->gps_tide_corrector);
        beams = p->number_beams;
#define A(sid, member) if (array(arrays, sid, p->member, beams, sizeof(double), "=f8") < 0) goto done
#define U(sid, member, type, dtype) if (array(arrays, sid, p->member, beams, sizeof(type), dtype) < 0) goto done
        if (include_arrays) {
            A(1, depth); A(2, across_track); A(3, along_track); A(4, travel_time);
            A(5, beam_angle); A(6, mc_amplitude); A(7, mr_amplitude); A(8, echo_width);
            A(9, quality_factor); A(10, receive_heave); A(11, depth_error);
            A(12, across_track_error); A(13, along_track_error); A(14, nominal_depth);
            U(15, quality_flags, unsigned char, "u1"); U(16, beam_flags, unsigned char, "u1");
            A(17, signal_to_noise); A(18, beam_angle_forward); A(19, vertical_error); A(20, horizontal_error);
            U(22, sector_number, unsigned short, "=u2"); U(23, detection_info, unsigned short, "=u2");
            A(24, incident_beam_adj); U(25, system_cleaning, unsigned short, "=u2");
            A(26, doppler_corr); A(27, sonar_vert_uncert); A(28, sonar_horz_uncert);
            A(29, detection_window); A(30, mean_abs_coeff); A(31, TVG_dB);
        }
    } else if (rid == GSF_RECORD_ATTITUDE) {
        gsfAttitude *a = &session->records.attitude;
        const unsigned char *wire = (const unsigned char *)expected;
        int64_t base = (int64_t)wire_u32(wire) * INT64_C(1000000000) + wire_u32(wire + 4);
        PyObject *times = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)a->num_measurements * sizeof(int64_t));
        Py_ssize_t bytes = (Py_ssize_t)a->num_measurements * sizeof(double);
        if (!times) goto done;
        for (int i = 0; i < a->num_measurements; i++) {
            /* LocalAddTimes uses floating-point seconds in GSF 3.11 and can
             * lose one ns. Preserve the wire's exact unsigned millisecond offset. */
            const unsigned char *offset = wire + 10 + i * 10;
            int64_t ns = base + ((uint32_t)offset[0] << 8 | offset[1]) * INT64_C(1000000);
            memcpy(PyBytes_AS_STRING(times) + i * sizeof(ns), &ns, sizeof(ns));
        }
        Py_DECREF(samples);
        samples = Py_BuildValue("(Ny#y#y#y#)", times,
                               a->roll, bytes, a->pitch, bytes, a->heave, bytes, a->heading, bytes);
        if (!samples) goto done;
    } else {
        PyErr_SetString(PyExc_ValueError, "No normalized projection for record type"); goto done;
    }
    result = Py_BuildValue("(OOO)", fields, arrays, samples);
done:
    Py_XDECREF(fields); Py_XDECREF(arrays); Py_XDECREF(samples);
    return result;
}

static PyMethodDef methods[] = {
    {"open", open_session, METH_VARARGS, "Open a read-only sequential GSF session."},
    {"read", read_record, METH_VARARGS, "Decode a physical payload and copy its projection."},
    {"close", close_session, METH_O, "Close a session, idempotently."},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "_native", NULL, -1, methods};
PyMODINIT_FUNC PyInit__native(void) {
    PyObject *result = PyModule_Create(&module);
    if (result && PyModule_AddStringConstant(result, "version", GSF_VERSION) < 0) {
        Py_DECREF(result); return NULL;
    }
    return result;
}
