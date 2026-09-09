"""Wire-level ALPN extraction for moq-rs probes.

moq-rs (draft-16/18) negotiates the MoQ draft exclusively via ALPN, and the
client picks a draft-specific ALPN literal ("moqt-16" / "moqt-18") when it
connects with a ``moqt://`` URL scheme (draft-14 uses "moq-00"). That ALPN is
inside the encrypted TLS ClientHello, so it cannot be grep'd from a pcap —
this module decrypts QUIC v1 Initial packets (RFC 9000/9001: keys derived from
the Initial DCID, header protection removed, payload GCM-decrypted), parses the
TLS ClientHello, and returns the offered ALPN list.

Validated end-to-end against the RFC 9000/9001 A.1+A.2 sample vector (keys,
header unmasking, and the decrypted CRYPTO plaintext), and against live moq-rs
16/18/14 captures (observed ALPNs: moqt-16 / moqt-18 / moq-00).
"""

import hmac
import hashlib
import struct
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

QUIC_V1_SALT = bytes.fromhex("38762cf7f55934b34d179ae6a4c80cadccbb7f0a")

# moq-rs ALPN literal -> MoQ draft. ALPN is the ONLY version negotiation
# mechanism at draft-16/18 (moq-transport/src/setup/*: "version negotiation is
# performed via ALPN only"); draft-14 uses the legacy "moq-00" ALPN.
MOQ_ALPN_TO_DRAFT = {"moq-00": "14", "moqt-16": "16", "moqt-18": "18"}


def _hkdf_extract(salt, ikm):
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def _hkdf_expand(prk, info, length):
    out, t, ctr = b"", b"", 1
    while len(out) < length:
        t = hmac.new(prk, t + info + bytes([ctr]), hashlib.sha256).digest()
        out += t
        ctr += 1
    return out[:length]


def _hkdf_expand_label(secret, label, length):
    full = b"tls13 " + label.encode()
    info = struct.pack(">H", length) + bytes([len(full)]) + full + b"\x00"
    return _hkdf_expand(secret, info, length)


def _initial_keys(dcid):
    secret = _hkdf_extract(QUIC_V1_SALT, dcid)
    cs = _hkdf_expand_label(secret, "client in", 32)
    return {
        "key": _hkdf_expand_label(cs, "quic key", 16),
        "iv": _hkdf_expand_label(cs, "quic iv", 12),
        "hp": _hkdf_expand_label(cs, "quic hp", 16),
    }


def _read_varint(b, off):
    first = b[off]
    n = 1 << (first >> 6)
    val = first & 0x3F
    for i in range(1, n):
        val = (val << 8) | b[off + i]
    return val, off + n


def _parse_long_pkt(pkt):
    p = 1 + 4
    dcil = pkt[p]; p += 1
    dcid = pkt[p:p + dcil]; p += dcil
    scidl = pkt[p]; p += 1
    scid = pkt[p:p + scidl]; p += scidl
    toklen, p = _read_varint(pkt, p)
    token = pkt[p:p + toklen]; p += toklen
    _, p = _read_varint(pkt, p)  # Length field (RFC 9000 17.2.2)
    return {"dcid": dcid, "scid": scid, "pn_offset": p}


def _decrypt_initial(dcid, pkt):
    keys = _initial_keys(dcid)
    meta = _parse_long_pkt(pkt)
    po = meta["pn_offset"]
    if po + 4 + 16 > len(pkt):
        return None
    # RFC 9001 5.4.2: sample at pn_offset + 4 (independent of PN length).
    sample = pkt[po + 4:po + 20]
    if len(sample) < 16:
        return None
    enc = Cipher(algorithms.AES(keys["hp"]), modes.ECB()).encryptor()
    mask = enc.update(sample) + enc.finalize()
    hp = bytearray(pkt)
    hp[0] ^= mask[0] & 0x0F
    pn_len = (hp[0] & 0x03) + 1  # long header: PN length in low 2 bits
    for i in range(pn_len):
        hp[po + i] ^= mask[1 + i]
    pn = int.from_bytes(bytes(hp[po:po + pn_len]), "big")
    aad = bytes(hp[:po + pn_len])
    iv = bytearray(keys["iv"])
    iv[4:12] = bytes(a ^ b for a, b in zip(iv[4:12], pn.to_bytes(8, "big")))
    payload = pkt[po + pn_len:]
    if len(payload) < 16:
        return None
    try:
        c = Cipher(algorithms.AES(keys["key"]), modes.GCM(bytes(iv), payload[-16:])).decryptor()
        c.authenticate_additional_data(aad)
        return c.update(payload[:-16]) + c.finalize()
    except Exception:
        return None


def _crypto_frames(data):
    chunks, off = [], 0
    while off < len(data):
        ft = data[off]
        if ft == 0x06:
            p = off + 1
            o, p = _read_varint(data, p)
            ln, p = _read_varint(data, p)
            chunks.append((o, data[p:p + ln]))
            off = p + ln
        else:
            off += 1
    return chunks


def _client_hello(chunks):
    stream = b""
    for o, raw in sorted(chunks):
        stream = stream[:o] + raw + stream[o + len(raw):]
    if not stream or stream[0] != 0x01 or len(stream) < 4:
        return None
    p = 4  # handshake type(1) + length(3)
    p += 2 + 32  # legacy_version + random
    n = stream[p] + 1
    p += n
    n = int.from_bytes(stream[p:p + 2], "big") + 2
    p += n
    n = stream[p] + 1
    p += n
    ext_len = int.from_bytes(stream[p:p + 2], "big")
    p += 2
    return stream[p:p + ext_len]


def _parse_extensions(exts):
    alpn, q = [], 0
    while q + 4 <= len(exts):
        etype = int.from_bytes(exts[q:q + 2], "big")
        elen = int.from_bytes(exts[q + 2:q + 4], "big")
        body = exts[q + 4:q + 4 + elen]
        q += 4 + elen
        if etype != 16:
            continue
        r = 2  # skip 2-byte ProtocolNameList length
        while r < len(body):
            plen = body[r]
            r += 1
            alpn.append(body[r:r + plen].decode("latin1", "replace"))
            r += plen
    return alpn


def _quic_alpn_from_datagram(dgram):
    p = 0
    while p < len(dgram):
        first = dgram[p]
        if not (first & 0x80):
            return None
        ver = dgram[p + 1:p + 5]
        if not (first & 0x40) or ver == b"\x00\x00\x00\x00" or len(ver) < 4:
            return None
        ptype = (first >> 4) & 0x03
        i = p + 5
        if len(dgram) <= i + 1:
            return None
        dcil = dgram[i]; i += 1
        if len(dgram) < i + dcil + 1:
            return None
        dcid = dgram[i:i + dcil]; i += dcil
        scidl = dgram[i]; i += 1
        if len(dgram) < i + scidl:
            return None
        i += scidl
        try:
            toklen, i = _read_varint(dgram, i)
            i += toklen
            length, i = _read_varint(dgram, i)
        except Exception:
            return None
        end = i + length
        if end > len(dgram):
            return None
        if ptype == 0 and ver == b"\x00\x00\x00\x01":
            plain = _decrypt_initial(dcid, dgram[p:end])
            if plain is not None:
                exts = _client_hello(_crypto_frames(plain))
                if exts is not None:
                    alpn = _parse_extensions(exts)
                    if alpn:
                        return alpn
        p = end
    return None


def _read_pcap(path):
    with open(path, "rb") as f:
        gh = f.read(24)
        if len(gh) < 24:
            return []
        magic = gh[:4]
        endian = "<" if magic == b"\xd4\xc3\xb2\xa1" else ">"
        if magic not in (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4"):
            return []
        linktype = struct.unpack(endian + "I", gh[20:24])[0]
        pkts = []
        while True:
            rec = f.read(16)
            if len(rec) < 16:
                break
            _, _, caplen, _ = struct.unpack(endian + "IIII", rec)
            data = f.read(caplen)
            if len(data) == caplen:
                pkts.append((linktype, data))
    return pkts


def extract_alpn_from_pcap(path, dport=4443):
    """Return the list of ALPN names offered by the client in the first
    successfully-decrypted QUIC Initial to *dport*, or [] if none."""
    found = []
    for linktype, data in _read_pcap(path):
        # Linux cooked v1/v2, Ethernet, or raw IP link layers.
        if linktype in (113, 276):
            eth = data[16 if linktype == 113 else 20:]
        elif linktype == 1:
            eth = data[14:]
        else:
            eth = data
        if len(eth) < 20 or eth[9] != 17:  # UDP
            continue
        ihl = (eth[0] & 0x0F) * 4
        udp = eth[ihl:]
        if len(udp) < 8:
            continue
        sport, dport_hdr = struct.unpack(">HH", udp[0:4])
        if dport_hdr != dport:
            continue
        alpn = _quic_alpn_from_datagram(udp[8:])
        if alpn:
            found.append((sport, alpn))
    return [a for _, a in found] or []