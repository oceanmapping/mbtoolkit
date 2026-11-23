"""
Decode GSF sensor-specific SWATH_BATHY subrecords (ID >= 102).

Layouts follow Leidos GSF 03.11 reference (gsf.h / gsf_dec.c). Unknown or
vendor extension IDs fall back to a generic hex/integer summary.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

SENSOR_SUBRECORD_MIN_ID = 102
KNOWN_SENSOR_SUBRECORD_MAX_ID = 157

SENSOR_SUBRECORD_NAMES: Dict[int, str] = {
    102: "SEABEAM_SPECIFIC",
    103: "EM12_SPECIFIC",
    104: "EM100_SPECIFIC",
    105: "EM950_SPECIFIC",
    106: "EM121A_SPECIFIC",
    107: "EM121_SPECIFIC",
    108: "SASS_SPECIFIC",
    109: "SEAMAP_SPECIFIC",
    110: "SEABAT_SPECIFIC",
    111: "EM1000_SPECIFIC",
    112: "TYPEIII_SEABEAM_SPECIFIC",
    113: "SB_AMP_SPECIFIC",
    114: "SEABAT_II_SPECIFIC",
    115: "SEABAT_8101_SPECIFIC",
    116: "SEABEAM_2112_SPECIFIC",
    117: "ELAC_MKII_SPECIFIC",
    118: "EM3000_SPECIFIC",
    119: "EM1002_SPECIFIC",
    120: "EM300_SPECIFIC",
    121: "CMP_SASS_SPECIFIC",
    122: "RESON_8101_SPECIFIC",
    123: "RESON_8111_SPECIFIC",
    124: "RESON_8124_SPECIFIC",
    125: "RESON_8125_SPECIFIC",
    126: "RESON_8150_SPECIFIC",
    127: "RESON_8160_SPECIFIC",
    128: "EM120_SPECIFIC",
    129: "EM3002_SPECIFIC",
    130: "EM3000D_SPECIFIC",
    131: "EM3002D_SPECIFIC",
    132: "EM121A_SIS_SPECIFIC",
    133: "EM710_SPECIFIC",
    134: "EM302_SPECIFIC",
    135: "EM122_SPECIFIC",
    136: "GEOSWATH_PLUS_SPECIFIC",
    137: "KLEIN_5410_BSS_SPECIFIC",
    138: "RESON_7125_SPECIFIC",
    139: "EM2000_SPECIFIC",
    140: "EM300_RAW_SPECIFIC",
    141: "EM1002_RAW_SPECIFIC",
    142: "EM2000_RAW_SPECIFIC",
    143: "EM3000_RAW_SPECIFIC",
    144: "EM120_RAW_SPECIFIC",
    145: "EM3002_RAW_SPECIFIC",
    146: "EM3000D_RAW_SPECIFIC",
    147: "EM3002D_RAW_SPECIFIC",
    148: "EM121A_SIS_RAW_SPECIFIC",
    149: "EM2040_SPECIFIC",
    150: "DELTA_T_SPECIFIC",
    151: "R2SONIC_2022_SPECIFIC",
    152: "R2SONIC_2024_SPECIFIC",
    153: "R2SONIC_2020_SPECIFIC",
    155: "RESON_TSERIES_SPECIFIC",
    156: "KMALL_SPECIFIC",
    157: "ME70BO_SPECIFIC",
}

_DEPTH_MODE = (
    "Very shallow", "Shallow", "Medium", "Deep", "Deeper",
    "Very deep", "Extra deep", "Extreme deep",
)
_BEAM_SPACING = ("Equidistance", "Equiangle", "High density")
_PULSE_FORM = ("CW", "Mix", "FM")


@dataclass
class SensorDecodeResult:
    subrecord_id: int
    decoder: str
    fields: List[Tuple[str, str]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    bytes_consumed: Optional[int] = None

    @property
    def name(self) -> str:
        return sensor_subrecord_name(self.subrecord_id)


def sensor_subrecord_name(sid: int) -> str:
    if sid in SENSOR_SUBRECORD_NAMES:
        return SENSOR_SUBRECORD_NAMES[sid]
    if sid >= SENSOR_SUBRECORD_MIN_ID:
        return f"VENDOR_{sid}"
    return f"UNKNOWN_{sid}"


def is_sensor_subrecord_id(sid: int) -> bool:
    return sid >= SENSOR_SUBRECORD_MIN_ID


def _need(payload: bytes, offset: int, size: int) -> None:
    if offset + size > len(payload):
        raise ValueError(
            f"payload truncated at offset {offset}: need {size} bytes, "
            f"have {len(payload) - offset}"
        )


def _u8(p: bytes, o: int) -> Tuple[int, int]:
    _need(p, o, 1)
    return p[o], o + 1


def _u16(p: bytes, o: int) -> Tuple[int, int]:
    _need(p, o, 2)
    return struct.unpack_from(">H", p, o)[0], o + 2


def _s16(p: bytes, o: int) -> Tuple[int, int]:
    _need(p, o, 2)
    return struct.unpack_from(">h", p, o)[0], o + 2


def _u32(p: bytes, o: int) -> Tuple[int, int]:
    _need(p, o, 4)
    return struct.unpack_from(">I", p, o)[0], o + 4


def _s32(p: bytes, o: int) -> Tuple[int, int]:
    _need(p, o, 4)
    return struct.unpack_from(">i", p, o)[0], o + 4


def _fixed_ascii(p: bytes, o: int, n: int) -> Tuple[str, int]:
    _need(p, o, n)
    return p[o:o + n].split(b"\x00", 1)[0].decode("ascii", "replace"), o + n


def _hex_preview(payload: bytes, limit: int = 32) -> str:
    chunk = payload[:limit]
    text = chunk.hex(" ")
    if len(payload) > limit:
        text += f" ... (+{len(payload) - limit} B)"
    return text


def _decode_generic(sid: int, payload: bytes) -> SensorDecodeResult:
    fields: List[Tuple[str, str]] = [("payload_length", f"{len(payload)} B")]
    warnings: List[str] = []
    if len(payload) == 0:
        warnings.append("empty payload")
        return SensorDecodeResult(sid, "generic", fields, warnings)

    if len(payload) <= 8:
        fields.append(("raw_hex", payload.hex(" ")))
        if sid > KNOWN_SENSOR_SUBRECORD_MAX_ID:
            warnings.append("vendor extension (not in GSF 03.11)")
        return SensorDecodeResult(sid, "generic", fields, warnings)

    u0, _ = _u16(payload, 0)
    fields.append(("first_u16_be", str(u0)))
    if len(payload) >= 4:
        u1, _ = _u32(payload, 0)
        fields.append(("first_u32_be", str(u1)))
    fields.append(("hex_preview", _hex_preview(payload)))
    if sid > KNOWN_SENSOR_SUBRECORD_MAX_ID:
        warnings.append("vendor extension (not in GSF 03.11)")
    else:
        warnings.append("no structured decoder for this GSF sensor id")
    return SensorDecodeResult(sid, "generic", fields, warnings)


def _skip_kmall_tx_sector(p: bytes, o: int, sector_bytes: int) -> int:
    _need(p, o, sector_bytes)
    return o + sector_bytes


def _decode_kmall(payload: bytes) -> SensorDecodeResult:
    sid = 156
    p = payload
    o = 0
    fields: List[Tuple[str, str]] = []

    ver, o = _u8(p, o)
    dgm_type, o = _u8(p, o)
    dgm_ver, o = _u8(p, o)
    system_id, o = _u8(p, o)
    es_id, o = _u16(p, o)
    o += 8  # spare1
    _, o = _u16(p, o)  # numBytesCmnPart
    ping_cnt, o = _u16(p, o)
    rx_fans, o = _u8(p, o)
    rx_fan_idx, o = _u8(p, o)
    swaths, o = _u8(p, o)
    swath_along, o = _u8(p, o)
    tx_idx, o = _u8(p, o)
    rx_idx, o = _u8(p, o)
    num_rx, o = _u8(p, o)
    o += 1  # algorithmType
    o += 16  # spare2
    num_bytes_info, o = _u16(p, o)  # numBytesInfoData
    ping_info_start = o
    ping_rate_raw, o = _u32(p, o)
    beam_sp, o = _u8(p, o)
    depth_mode, o = _u8(p, o)
    sub_depth, o = _u8(p, o)
    dist_swath, o = _u8(p, o)
    det_mode, o = _u8(p, o)
    pulse, o = _u8(p, o)
    freq_mode, o = _s32(p, o)
    flo_raw, o = _u32(p, o)
    fhi_raw, o = _u32(p, o)
    max_tx_len, o = _u32(p, o)
    max_eff_tx, o = _u32(p, o)
    max_bw, o = _u32(p, o)
    abs_coeff_raw, o = _u32(p, o)
    port_edge, o = _s16(p, o)
    stbd_edge, o = _s16(p, o)
    port_cov_deg, o = _s16(p, o)
    stbd_cov_deg, o = _s16(p, o)
    o += 4  # duplicate mean-coverage degrees (gsf_dec reads these twice)
    port_cov_m, o = _s16(p, o)
    stbd_cov_m, o = _s16(p, o)
    mode_stab, o = _u8(p, o)
    filt1, o = _u8(p, o)
    filt2, o = _u16(p, o)
    pipe, o = _u32(p, o)
    tx_arr, o = _u16(p, o)
    rx_arr, o = _u16(p, o)
    tx_pwr, o = _s16(p, o)
    o += 2  # SLrampUpTimeRemaining
    yaw_raw, o = _s32(p, o)
    num_tx_sectors, o = _u16(p, o)
    num_bytes_per_tx_sector, o = _u16(p, o)
    heading_raw, o = _s32(p, o)
    ss_raw, o = _u32(p, o)
    tx_depth_raw, o = _u32(p, o)
    waterline_raw, o = _u32(p, o)
    x_k2a, o = _u32(p, o)
    y_k2a, o = _u32(p, o)
    lat_info, o = _u8(p, o)
    pos_stat, o = _u8(p, o)
    att_stat, o = _u8(p, o)
    lat_raw, o = _s32(p, o)
    lon_raw, o = _s32(p, o)
    ellipsoid_raw, o = _s32(p, o)
    o += 32  # spare3
    o = ping_info_start + num_bytes_info

    sector_bytes = num_bytes_per_tx_sector if num_bytes_per_tx_sector > 0 else 57
    sectors_to_skip = min(num_tx_sectors, 9)
    for _ in range(sectors_to_skip):
        if o + sector_bytes > len(p):
            sectors_to_skip = _
            break
        o = _skip_kmall_tx_sector(p, o, sector_bytes)

    warnings: List[str] = []
    max_snd = valid_snd = num_rx_info = 0
    wc_int = wc_frac = si_int = si_frac = bs_norm = bs_obl = 0
    rx_start = o
    if o + 8 <= len(p):
        num_rx_info, o = _u16(p, o)
        max_snd, o = _u16(p, o)
        valid_snd, o = _u16(p, o)
        o += 2  # numBytesPerSounding
        rx_sane = (
            0 < max_snd <= 4096
            and 0 <= valid_snd <= max_snd
            and num_rx_info < 2048
        )
        if rx_sane and o + 32 <= len(p):
            wc_int, o = _s32(p, o)
            wc_frac, o = _u32(p, o)
            si_int, o = _s32(p, o)
            si_frac, o = _u32(p, o)
            bs_norm, o = _s32(p, o)
            bs_obl, o = _s32(p, o)
            o += 8  # extraDetectionAlarmFlag, numExtraDetections
            if o + 4 <= len(p):
                o += 4  # numExtraDetectionClasses, numBytesPerClass
                if o + 32 <= len(p):
                    o += 32  # spare4
                    o += 32  # spare5
        else:
            o = rx_start
            max_snd = valid_snd = num_rx_info = 0
            warnings.append("rxInfo not decoded (TX sector block size may differ from payload)")
    elif sectors_to_skip < num_tx_sectors:
        warnings.append(
            f"only {sectors_to_skip} of {num_tx_sectors} TX sector(s) present in payload"
        )

    dgm_name = "#MRZ" if dgm_type == 1 else f"type {dgm_type}"
    fields.extend([
        ("gsfKMALLVersion", str(ver)),
        ("dgmType", f"{dgm_type} ({dgm_name})"),
        ("dgmVersion", str(dgm_ver)),
        ("systemID", str(system_id)),
        ("echoSounderID", str(es_id)),
        ("pingCnt", str(ping_cnt)),
        ("rxFansPerPing", str(rx_fans)),
        ("rxFanIndex", str(rx_fan_idx)),
        ("swathsPerPing", str(swaths)),
        ("swathAlongPosition", str(swath_along)),
        ("txTransducerInd", str(tx_idx)),
        ("rxTransducerInd", str(rx_idx)),
        ("numRxTransducers", str(num_rx)),
        ("numBytesInfoData", str(num_bytes_info)),
        ("pingRate_Hz", f"{ping_rate_raw / 1e5:.5f}"),
        ("beamSpacing", _BEAM_SPACING[beam_sp] if beam_sp < 3 else str(beam_sp)),
        ("depthMode", _DEPTH_MODE[depth_mode] if depth_mode < 8 else str(depth_mode)),
        ("subDepthMode", str(sub_depth)),
        ("distanceBtwSwath_pct", str(dist_swath)),
        ("detectionMode", str(det_mode)),
        ("pulseForm", _PULSE_FORM[pulse] if pulse < 3 else str(pulse)),
        ("frequencyMode_Hz", str(freq_mode)),
        ("freqRange_Hz", f"{flo_raw / 1e3:.1f} – {fhi_raw / 1e3:.1f}"),
        ("maxTotalTxPulseLength_sec", f"{max_tx_len / 1e6:.6f}"),
        ("maxEffTxPulseLength_sec", f"{max_eff_tx / 1e6:.6f}"),
        ("maxEffTxBandWidth_Hz", f"{max_bw / 1e3:.1f}"),
        ("absCoeff_dBPerkm", f"{abs_coeff_raw / 1e3:.3f}"),
        ("portSectorEdge_deg", f"{port_edge / 100:.2f}"),
        ("starbSectorEdge_deg", f"{stbd_edge / 100:.2f}"),
        ("portMeanCov_deg", f"{port_cov_deg / 100:.2f}"),
        ("starbMeanCov_deg", f"{stbd_cov_deg / 100:.2f}"),
        ("portMeanCov_m", str(port_cov_m)),
        ("starbMeanCov_m", str(stbd_cov_m)),
        ("modeAndStabilisation", str(mode_stab)),
        ("runtimeFilter1", str(filt1)),
        ("runtimeFilter2", str(filt2)),
        ("transmitArraySizeUsed_deg", f"{tx_arr / 1000:.3f}"),
        ("receiveArraySizeUsed_deg", f"{rx_arr / 1000:.3f}"),
        ("transmitPower_dB", f"{tx_pwr / 100:.2f}"),
        ("yawAngle_deg", f"{yaw_raw / 1e6:.3f}"),
        ("numTxSectors", str(num_tx_sectors)),
        ("numBytesPerTxSector", str(num_bytes_per_tx_sector)),
        ("headingVessel_deg", f"{heading_raw / 1e6:.3f}"),
        ("soundSpeedAtTxDepth_mps", f"{ss_raw / 1e6:.3f}"),
        ("txTransducerDepth_m", f"{tx_depth_raw / 1e6:.3f}"),
        ("latitude_deg", f"{lat_raw / 1e7:.7f}"),
        ("longitude_deg", f"{lon_raw / 1e7:.7f}"),
        ("ellipsoidHeight_m", f"{ellipsoid_raw / 1e3:.3f}"),
    ])
    if max_snd > 0:
        fields.extend([
            ("numSoundingsMaxMain", str(max_snd)),
            ("numSoundingsValidMain", str(valid_snd)),
            ("WCSampleRate_Hz", f"{wc_int + wc_frac / 1e9:.3f}"),
            ("seabedImageSampleRate_Hz", f"{si_int + si_frac / 1e9:.3f}"),
            ("BSnormal_dB", f"{bs_norm / 1e6:.3f}"),
            ("BSoblique_dB", f"{bs_obl / 1e6:.3f}"),
            ("numBytesRxInfo", str(num_rx_info)),
        ])
    fields.extend([
        ("latLongInfo", str(lat_info)),
        ("posSensorStatus", str(pos_stat)),
        ("attitudeSensorStatus", str(att_stat)),
    ])
    return SensorDecodeResult(sid, "KMALL (#MRZ)", fields, warnings, bytes_consumed=o)


def _decode_em3(payload: bytes) -> SensorDecodeResult:
    sid = -1  # filled by caller
    p = payload
    o = 0
    model, o = _u16(p, o)
    ping_num, o = _u16(p, o)
    serial, o = _u16(p, o)
    ss, o = _u16(p, o)
    depth, o = _u16(p, o)
    valid, o = _u16(p, o)
    sample_rate, o = _u16(p, o)
    depth_diff, o = _s16(p, o)
    fields = [
        ("model_number", str(model)),
        ("ping_number", str(ping_num)),
        ("serial_number", str(serial)),
        ("surface_velocity_mps", f"{ss / 10:.1f}"),
        ("transducer_depth_m", f"{depth / 100:.2f}"),
        ("valid_beams", str(valid)),
        ("sample_rate_Hz", str(sample_rate)),
        ("depth_difference_m", f"{depth_diff / 100:.2f}"),
    ]
    if o + 4 <= len(p):
        rt_flags, o = _u32(p, o)
        fields.append(("run_time_flags", f"0x{rt_flags:08X}"))
        if rt_flags & 1:
            fields.append(("run_time", "present (not fully expanded)"))
    return SensorDecodeResult(0, "EM3 series", fields, bytes_consumed=o)


def _decode_em4(payload: bytes) -> SensorDecodeResult:
    p = payload
    o = 0
    model, o = _u16(p, o)
    ping_cnt, o = _u16(p, o)
    serial, o = _u16(p, o)
    ss, o = _u16(p, o)
    tx_depth_raw, o = _u32(p, o)
    valid_det, o = _u16(p, o)
    fs_int, o = _u32(p, o)
    fs_frac, o = _u32(p, o)
    fs = fs_int + fs_frac / 4e9
    fields = [
        ("model_number", str(model)),
        ("ping_counter", str(ping_cnt)),
        ("serial_number", str(serial)),
        ("surface_velocity_mps", f"{ss / 10:.1f}"),
        ("transducer_depth_m", f"{tx_depth_raw / 20000:.3f}"),
        ("valid_detections", str(valid_det)),
        ("sampling_frequency_Hz", f"{fs:.3f}"),
    ]
    if o + 24 <= len(p):
        o += 24  # doppler, vehicle depth, spare
        tx_sectors, o = _u16(p, o)
        fields.append(("transmit_sectors", str(tx_sectors)))
    return SensorDecodeResult(0, "EM4 series", fields, bytes_consumed=o)


def _decode_r2sonic(payload: bytes) -> SensorDecodeResult:
    p = payload
    o = 0
    model, o = _fixed_ascii(p, o, 12)
    serial, o = _fixed_ascii(p, o, 12)
    tv_sec, o = _u32(p, o)
    tv_nsec, o = _u32(p, o)
    ping_num, o = _u32(p, o)
    period_raw, o = _u32(p, o)
    ss_raw, o = _u32(p, o)
    freq_raw, o = _u32(p, o)
    fields = [
        ("model_number", model or "(empty)"),
        ("serial_number", serial or "(empty)"),
        ("ping_time_utc", f"{tv_sec}.{tv_nsec:09d}"),
        ("ping_number", str(ping_num)),
        ("ping_period_s", f"{period_raw / 1e6:.4f}"),
        ("sound_speed_mps", f"{ss_raw / 100:.2f}"),
        ("frequency_Hz", f"{freq_raw / 1000:.1f}"),
    ]
    return SensorDecodeResult(0, "R2Sonic", fields, bytes_consumed=o)


def _decode_seabat(payload: bytes) -> SensorDecodeResult:
    p = payload
    o = 0
    ping_num, o = _u16(p, o)
    ss, o = _u16(p, o)
    mode, o = _u8(p, o)
    sonar_range, o = _u8(p, o)
    tx_pwr, o = _u8(p, o)
    rx_gain, o = _u8(p, o)
    fields = [
        ("ping_number", str(ping_num)),
        ("surface_velocity_mps", f"{ss / 10:.1f}"),
        ("mode", str(mode)),
        ("sonar_range", str(sonar_range)),
        ("transmit_power", str(tx_pwr)),
        ("receive_gain", str(rx_gain)),
    ]
    return SensorDecodeResult(0, "SeaBat", fields, bytes_consumed=o)


def _decode_reson8100(payload: bytes) -> SensorDecodeResult:
    p = payload
    o = 0
    latency, o = _u16(p, o)
    ping_num, o = _u32(p, o)
    sonar_id, o = _u32(p, o)
    sonar_model, o = _u16(p, o)
    frequency, o = _u16(p, o)
    ss_raw, o = _u16(p, o)
    fields = [
        ("latency_ms", str(latency)),
        ("ping_number", str(ping_num)),
        ("sonar_id", str(sonar_id)),
        ("sonar_model", str(sonar_model)),
        ("frequency_kHz", str(frequency)),
        ("surface_velocity_mps", f"{ss_raw / 10:.1f}"),
    ]
    return SensorDecodeResult(0, "Reson 8100 series", fields, bytes_consumed=o)


def _decode_geoswath(payload: bytes) -> SensorDecodeResult:
    p = payload
    o = 0
    data_source, o = _u16(p, o)
    side, o = _u16(p, o)
    model, o = _u16(p, o)
    fields = [
        ("data_source", "CBF" if data_source == 0 else "RDF" if data_source == 1 else str(data_source)),
        ("side", "port" if side == 0 else "starboard" if side == 1 else str(side)),
        ("model_number", str(model)),
    ]
    return SensorDecodeResult(0, "GeoSwath+", fields, bytes_consumed=o)


EM3_IDS = {
    111, 118, 119, 120, 128, 129, 130, 131, 132, 139,
    140, 141, 142, 143, 144, 145, 146, 147, 148,
}
EM4_IDS = {133, 134, 135, 149, 157}
R2SONIC_IDS = {151, 152, 153}
RESON_8100_IDS = {122, 123, 124, 125, 126, 127}
SEABAT_IDS = {110, 114}

_DECODER_BY_ID: Dict[int, Callable[[bytes], SensorDecodeResult]] = {}


def _register(ids, fn, label: str) -> None:
    for i in ids:
        _DECODER_BY_ID[i] = fn


_register({156}, _decode_kmall, "KMALL")
_register(EM3_IDS, _decode_em3, "EM3")
_register(EM4_IDS, _decode_em4, "EM4")
_register(R2SONIC_IDS, _decode_r2sonic, "R2Sonic")
_register(RESON_8100_IDS, _decode_reson8100, "Reson8100")
_register(SEABAT_IDS, _decode_seabat, "SeaBat")
_register({136}, _decode_geoswath, "GeoSwath+")


def decode_sensor_subrecord(sid: int, payload: bytes) -> SensorDecodeResult:
    """Decode one sensor-specific subrecord payload."""
    decoder = _DECODER_BY_ID.get(sid)
    if decoder is None:
        result = _decode_generic(sid, payload)
        result.subrecord_id = sid
        return result
    try:
        result = decoder(payload)
        result.subrecord_id = sid
        if result.decoder == "EM3 series":
            result.decoder = f"EM3 series ({sensor_subrecord_name(sid)})"
        elif result.decoder == "EM4 series":
            result.decoder = f"EM4 series ({sensor_subrecord_name(sid)})"
        elif result.decoder == "R2Sonic":
            result.decoder = f"R2Sonic ({sensor_subrecord_name(sid)})"
        elif result.decoder == "SeaBat":
            result.decoder = f"SeaBat ({sensor_subrecord_name(sid)})"
        elif result.decoder == "Reson 8100 series":
            result.decoder = f"Reson 8100 ({sensor_subrecord_name(sid)})"
        elif result.decoder == "GeoSwath+":
            result.decoder = f"GeoSwath+ ({sensor_subrecord_name(sid)})"
        if result.bytes_consumed is not None and result.bytes_consumed < len(payload):
            tail = len(payload) - result.bytes_consumed
            if tail > 0:
                result.warnings.append(f"{tail} trailing byte(s) not decoded")
        return result
    except ValueError as exc:
        result = _decode_generic(sid, payload)
        result.subrecord_id = sid
        result.warnings.insert(0, f"structured decode failed: {exc}")
        return result


def format_sensor_decode(result: SensorDecodeResult, indent: str = "  ") -> List[str]:
    lines = [f"{indent}Decoder: {result.decoder}"]
    for key, value in result.fields:
        lines.append(f"{indent}{key:28}: {value}")
    for warn in result.warnings:
        lines.append(f"{indent}Note: {warn}")
    return lines


def print_sensor_specific_report(
    filename: str,
    counts: Dict[int, int],
    samples: Dict[int, Tuple[int, int, bytes]],
    total_pings: int,
) -> None:
    """Print decoded sensor-specific subrecords found in a file."""
    print("\n=== Sensor-Specific Subrecord Decode ===")
    print(f"File          : {filename}")
    print(f"Swath pings   : {total_pings:,}")

    if not counts:
        print("No sensor-specific subrecords (ID >= 102) found.")
        return

    for sid in sorted(counts):
        name = sensor_subrecord_name(sid)
        cnt = counts[sid]
        pct = 100.0 * cnt / total_pings if total_pings else 0.0
        print(f"\n--- ID {sid:3d} {name} ---")
        print(f"  Occurrences : {cnt:,} ({pct:.1f}% of pings)")

        if sid not in samples:
            print("  (no sample payload captured)")
            continue

        ping_index, file_offset, payload = samples[sid]
        print(f"  Sample ping : {ping_index} @0x{file_offset:X}")
        print(f"  Payload size: {len(payload)} B")

        result = decode_sensor_subrecord(sid, payload)
        for line in format_sensor_decode(result, indent="  "):
            print(line)
