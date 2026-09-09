#!/usr/bin/env python3
"""Certificate generation utilities.

Uses the `cryptography` library for cross-platform self-signed certificate
generation, avoiding dependency on the `openssl` command-line tool.
"""
from pathlib import Path
from typing import Dict, Optional
import datetime

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False


def _generate_selfsigned_cryptography(cert_path: Path, key_path: Path,
                                      common_name: str = "moq-testbed.local",
                                      days: int = 365) -> None:
    """Generate self-signed cert using cryptography library."""
    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    
    # Write private key
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path.write_bytes(key_pem)
    
    # Create self-signed certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(common_name)]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )
    
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    cert_path.write_bytes(cert_pem)


def _generate_selfsigned_openssl(cert_path: Path, key_path: Path,
                                 common_name: str = "moq-testbed.local",
                                 days: int = 365,
                                 check: bool = False,
                                 timeout: Optional[int] = None) -> None:
    """Fallback to openssl command if available."""
    import subprocess
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(key_path),
            "-out", str(cert_path),
            "-days", str(days), "-nodes",
            "-subj", f"/CN={common_name}",
        ],
        capture_output=True,
        check=check,
        timeout=timeout,
    )


def generate_selfsigned(cert_path: Path, key_path: Path,
                        common_name: str = "moq-testbed.local",
                        days: int = 365,
                        check: bool = False,
                        timeout: Optional[int] = None) -> None:
    """Generate a self-signed certificate and private key.
    
    Prefers the cryptography library for cross-platform support,
    falls back to openssl command if available.
    """
    if CRYPTOGRAPHY_AVAILABLE:
        _generate_selfsigned_cryptography(cert_path, key_path, common_name, days)
    else:
        _generate_selfsigned_openssl(cert_path, key_path, common_name, days, check, timeout)


def ensure_cert_set(cert_dir: Path, aliases: Dict[str, str],
                    common_name: str = "moq-testbed.local",
                    days: int = 365,
                    check: bool = False,
                    timeout: Optional[int] = None) -> None:
    """Generate a self-signed cert pair and any per-implementation aliases.

    ``aliases`` maps the filename an implementation expects to the source file
    it is a copy of, e.g. ``{"priv.key": "key.pem"}``. Idempotent: existing
    files are never regenerated or overwritten.
    """
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / "cert.pem"
    key_path = cert_dir / "key.pem"
    if not cert_path.exists():
        generate_selfsigned(cert_path, key_path,
                            common_name=common_name, days=days,
                            check=check, timeout=timeout)
    for alias, source in aliases.items():
        alias_path = cert_dir / alias
        if not alias_path.exists():
            source_path = cert_dir / source
            alias_path.write_bytes(source_path.read_bytes())
