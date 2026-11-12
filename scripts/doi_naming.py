"""DOI'den dosya adı üretme — tek kaynak.

PDF adı ile HTML'de gösterilen ad aynı olmalı; aksi hâlde kullanıcı listeden
kopyaladığı adı yapıştırdığında dosya eşleşmez. Kural bilinçli olarak basit:
yalnızca harf, rakam, nokta ve tire kalır.

    >>> doi_filename("10.4073/csr.2011.4")
    '10.4073csr.2011.4'

Eğik çizgi ve diğer özel karakterler tireye çevrilmez, **silinir**; böylece ad
DOI ile gözle eşleştirilebilir ve uzunluk artmaz.
"""

from __future__ import annotations

import re
import unicodedata

_ILLEGAL = re.compile(r"[^A-Za-z0-9.\-]+")


def doi_filename(doi: str, max_length: int = 150) -> str:
    """Return the filename stem for ``doi`` (no ``.pdf`` suffix)."""
    text = unicodedata.normalize("NFKD", str(doi or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = _ILLEGAL.sub("", text).strip(".-")
    return (text or "doi-yok")[:max_length]


def doi_pdf_filename(doi: str, max_length: int = 150) -> str:
    return f"{doi_filename(doi, max_length)}.pdf"
