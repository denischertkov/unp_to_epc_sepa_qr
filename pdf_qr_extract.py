# -*- coding: utf-8 -*-
"""
Извлечение и декодирование QR-кодов со страниц PDF.
Используется для чтения UNP/UPN QR из платёжных поручений.
"""
import io
from typing import List, Optional

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from PIL import Image
except ImportError:
    Image = None

# pyzbar требует системную библиотеку libzbar (brew install zbar)
_pyzbar_decode = None
try:
    from pyzbar.pyzbar import decode as _pyzbar_decode_func
    from pyzbar.pyzbar import ZBarSymbol
    def _pyzbar_decode(img: "Image.Image"):
        return _pyzbar_decode_func(img, symbols=[ZBarSymbol.QRCODE])
    _pyzbar_decode = _pyzbar_decode
except Exception:
    pass

# Запасной декодер: OpenCV (pip install opencv-python-headless)
# Используем detect + decodeBytes, чтобы получить сырые байты и декодировать сами
# (detectAndDecode внутри OpenCV делает UTF-8 decode и падает на Latin-2/ECI).
_cv2_decode = None
try:
    import cv2
    import numpy as np
    # Подавить предупреждения "ECI is not supported properly" при декодировании QR
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
    except Exception:
        pass
    _cv2_detector = cv2.QRCodeDetector()

    def _cv2_decode(img: "Image.Image") -> List[str]:
        arr = np.array(img)
        if len(arr.shape) == 3 and arr.shape[2] == 3:
            arr_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        else:
            arr_bgr = arr
        # Try grayscale first (often more reliable for QR on rendered PDFs)
        if len(arr_bgr.shape) == 3:
            arr_gray = cv2.cvtColor(arr_bgr, cv2.COLOR_BGR2GRAY)
        else:
            arr_gray = arr_bgr
        for im in (arr_gray, arr_bgr):
            retval, points = _cv2_detector.detect(im)
            if not retval or points is None or (hasattr(points, "size") and points.size == 0):
                continue
            result: List[str] = []
            try:
                data_bytes, _ = _cv2_detector.decodeBytes(im, points)
            except Exception:
                data_bytes = None
            if data_bytes is not None and len(data_bytes) > 0:
                s = _normalize_qr_content_to_str(data_bytes)
                if s.strip():
                    result.append(s)
            if not result:
                try:
                    data, _, _ = _cv2_detector.detectAndDecode(im)
                    if data and isinstance(data, str) and data.strip():
                        result = [_normalize_qr_content_to_str(data)]
                except Exception:
                    pass
            if result:
                return result
        return []
    _cv2_decode = _cv2_decode
except Exception:
    pass


def _normalize_qr_content_to_str(raw: "str | bytes") -> str:
    """
    Приводит содержимое QR к строке Unicode для дальнейшей работы.
    UPN QR в Словении часто в кодировке Latin-2 (ISO-8859-2) или Windows-1250 (č, š, ž).
    """
    if raw is None:
        return ""
    if not isinstance(raw, (str, bytes, bytearray)):
        raw = bytes(raw) if hasattr(raw, "tobytes") else str(raw)
    if isinstance(raw, str):
        try:
            raw.encode("utf-8")
            return raw
        except UnicodeEncodeError:
            raw = raw.encode("latin-1")
    if isinstance(raw, (bytes, bytearray)):
        for enc in ("utf-8", "iso-8859-2", "cp1250", "latin-1"):
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _page_to_pil_image(doc: "fitz.Document", page_no: int, dpi: int = 200) -> Optional["Image.Image"]:
    """Рендер одной страницы PDF в PIL Image."""
    if fitz is None or Image is None:
        return None
    page = doc[page_no]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def _decode_qr_from_image(img: "Image.Image") -> List[str]:
    """Decode all QR codes on the image. Run both pyzbar and OpenCV and merge results
    so we don't miss UPN QR when another QR (e.g. numeric ID) is also present."""
    seen: set = set()
    result: List[str] = []

    def add(s: str) -> None:
        if s and s.strip() and s.strip() not in seen:
            seen.add(s.strip())
            result.append(s)

    if _pyzbar_decode is not None:
        for obj in _pyzbar_decode(img):
            data = _normalize_qr_content_to_str(obj.data)
            add(data)
    if _cv2_decode is not None:
        for s in _cv2_decode(img):
            add(s)
    return result


def _decode_qr_from_pil(pil_img: "Image.Image") -> List[str]:
    """Декодирует QR из PIL Image; конвертирует в RGB если нужно."""
    if pil_img.mode != "RGB":
        pil_img = pil_img.convert("RGB")
    return _decode_qr_from_image(pil_img)


def _extract_embedded_images(doc: "fitz.Document") -> List["Image.Image"]:
    """
    Extract all embedded images from PDF as PIL Image:
    1) images by xref (page.get_images() + doc.extract_image);
    2) inline images from page stream (get_text("dict"), type==1);
    3) any image xref in the document (in case get_images() misses some).
    """
    if fitz is None or Image is None:
        return []
    out: List["Image.Image"] = []
    seen_xrefs: set = set()

    def add_pil(blob: bytes) -> None:
        try:
            pil = Image.open(io.BytesIO(blob))
            out.append(pil)
        except Exception:
            pass

    for page_no in range(len(doc)):
        page = doc[page_no]
        for item in page.get_images():
            xref = item[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                base = doc.extract_image(xref)
                if base:
                    blob = base.get("image") or base.get("data")
                    if blob:
                        add_pil(blob)
            except Exception:
                continue
        try:
            d = page.get_text("dict")
            for block in d.get("blocks") or []:
                if block.get("type") != 1:
                    continue
                blob = block.get("image")
                if blob:
                    add_pil(blob)
        except Exception:
            continue

    # Some PDFs store images so they are not listed in get_images(); try all xrefs
    try:
        for xref in range(1, doc.xref_length()):
            if xref in seen_xrefs:
                continue
            try:
                base = doc.extract_image(xref)
                if base:
                    seen_xrefs.add(xref)
                    blob = base.get("image") or base.get("data")
                    if blob:
                        add_pil(blob)
            except Exception:
                continue
    except Exception:
        pass

    return out


def extract_qr_strings_from_pdf(pdf_path: str, dpi: int = 300, verbose: bool = False) -> List[str]:
    """
    Extract all QR codes from PDF pages; return list of decoded strings.
    Uses: (1) embedded images, (2) page render at several DPIs.
    """
    import sys
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) required. Install: pip install pymupdf")
    if _pyzbar_decode is None and _cv2_decode is None:
        raise RuntimeError("QR decoder required: pip install pyzbar (and zbar) or opencv-python-headless")

    result: List[str] = []
    doc = fitz.open(pdf_path)
    n_pages = len(doc)
    if verbose:
        print(f"PDF: {n_pages} page(s)", file=sys.stderr)

    try:
        # 1) Embedded images
        embedded = _extract_embedded_images(doc)
        if verbose:
            print(f"Embedded images: {len(embedded)}", file=sys.stderr)
        for pil in embedded:
            result.extend(_decode_qr_from_pil(pil))
        if verbose and result:
            print(f"QR from embedded: {len(result)}", file=sys.stderr)

        # 2) Always render each page too (UPN QR may be vector, only visible on render; embedded may be other QR)
        for try_dpi in (dpi, 400, 600):
            for page_no in range(n_pages):
                img = _page_to_pil_image(doc, page_no, dpi=try_dpi)
                if img is not None:
                    if verbose and page_no == 0 and try_dpi == dpi:
                        try:
                            debug_path = pdf_path + ".page0_%ddpi.png" % try_dpi
                            img.save(debug_path)
                            print(f"Debug: saved first page render to {debug_path}", file=sys.stderr)
                        except Exception:
                            pass
                    n_before = len(result)
                    result.extend(_decode_qr_from_image(img))
                    if img.width * img.height < 4000 * 4000 and _cv2_decode is not None:
                        try:
                            from PIL import Image as PILImage
                            w, h = img.size
                            img2 = img.resize((w * 2, h * 2), PILImage.Resampling.LANCZOS)
                            result.extend(_decode_qr_from_image(img2))
                        except Exception:
                            pass
                    if verbose and len(result) > n_before:
                        print(f"QR from render page {page_no + 1} @ {try_dpi} DPI: +{len(result) - n_before}", file=sys.stderr)
            if any(s.strip().startswith("UPNQR") for s in result):
                break
    finally:
        doc.close()
    return result
