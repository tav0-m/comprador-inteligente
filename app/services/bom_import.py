"""Importacion de listas de materiales (CSV o Excel) a lineas de canasta.

Acepta la planilla tal como sale de un presupuesto de obra: detecta la fila de
encabezados (material/descripcion, cantidad, unidad) en cualquier posicion,
interpreta numeros en formato chileno, fusiona materiales repetidos y avisa de
unidades ambiguas propias de presupuestos (ml = metro lineal, gl = global).
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field

from app.schemas import MAX_BASKET_LINES, BomImportLine, BomImportResponse
from app.services.product_guardrails import validate_query
from app.services.specs import canonical

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024  # defensa ante zip bombs en .xlsx
MAX_ROWS = 2000

# Alias por prioridad: "Descripcion" gana a "Item" (que suele ser la numeracion 1.1, 1.2).
# "Total" no es alias de cantidad: en presupuestos suele ser el monto en pesos.
_HEADER_ALIASES = {
    "query": ["material", "materiales", "descripcion", "producto", "insumo", "articulo",
              "detalle", "nombre", "partida", "item"],
    "quantity": ["cantidad", "cant", "cantidades", "qty"],
    "unit": ["unidad", "unid", "und", "un", "ud", "unit", "u"],
}
# Unidades de presupuesto de obra -> unidad de la canasta, con advertencia si aplica.
_UNIT_MAP = {
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg", "ton": "ton", "tn": "ton",
    "lt": "l", "lts": "l", "l": "l", "litro": "l", "litros": "l",
    "m2": "m2", "mt2": "m2", "mts2": "m2", "m²": "m2",
    "u": "unidades", "un": "unidades", "und": "unidades", "unid": "unidades", "ud": "unidades",
    "c/u": "unidades", "unidades": "unidades", "pza": "unidades", "piezas": "unidades",
    "saco": "saco", "sacos": "saco", "plancha": "plancha", "planchas": "plancha",
    "rollo": "rollo", "rollos": "rollo", "caja": "caja", "cajas": "caja", "galon": "galon", "tineta": "tineta",
}
_AMBIGUOUS_UNITS = {
    "ml": "metro lineal", "m": "metro lineal", "mt": "metro lineal", "mts": "metro lineal",
    "m3": "metro cubico", "gl": "global", "glb": "global",
}


class BomImportError(ValueError):
    pass


@dataclass
class _Accumulator:
    lines: dict[tuple[str, str], BomImportLine] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    rows_read: int = 0
    rows_skipped: int = 0


def parse_quantity(value) -> float | None:
    """'1.500' -> 1500, '2,5' -> 2.5, '1.234,5' -> 1234.5; numeros de Excel pasan tal cual."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    text = re.sub(r"[^\d.,-]", "", str(value).strip())
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    elif text.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", text):
        text = text.replace(".", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number > 0 else None


def _read_csv(content: bytes) -> list[list]:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    try:
        delimiter = csv.Sniffer().sniff(text[:4096], delimiters=";,\t|").delimiter
    except csv.Error:
        delimiter = ";" if text.count(";") > text.count(",") else ","
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)][:MAX_ROWS]


def _read_xlsx(content: bytes) -> list[list]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise BomImportError("El archivo no es un Excel (.xlsx) valido.") from exc
    if sum(info.file_size for info in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
        raise BomImportError("El Excel descomprimido es demasiado grande.")
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        rows = []
        for row in sheet.iter_rows(values_only=True):
            rows.append(list(row))
            if len(rows) >= MAX_ROWS:
                break
        return rows
    finally:
        workbook.close()


def _header_key(value) -> str:
    return re.sub(r"[^a-z0-9/]", "", canonical(str(value or "")))


def _find_columns(rows: list[list]) -> tuple[int, dict[str, int]]:
    """Fila de encabezados y columnas; sin encabezados: material, cantidad, unidad."""
    for index, row in enumerate(rows[:30]):
        best: dict[str, tuple[int, int]] = {}  # campo -> (prioridad del alias, columna)
        for position, cell in enumerate(row):
            key = _header_key(cell)
            for field_name, aliases in _HEADER_ALIASES.items():
                if key in aliases:
                    rank = aliases.index(key)
                    if field_name not in best or rank < best[field_name][0]:
                        best[field_name] = (rank, position)
        columns = {field_name: position for field_name, (_, position) in best.items()}
        if "query" in columns and "quantity" in columns:
            return index + 1, columns
    return 0, {"query": 0, "quantity": 1, "unit": 2}


def _normalize_unit(raw, row_number: int, acc: _Accumulator) -> str:
    key = canonical(str(raw or "")).replace(" ", "").rstrip(".")
    if not key:
        return "unidad"
    if key in _AMBIGUOUS_UNITS:
        acc.warnings.append(
            f"Fila {row_number}: unidad '{raw}' ({_AMBIGUOUS_UNITS[key]}) no se convierte a envases; "
            "revisa la cantidad (se tomara como numero de envases)."
        )
        return key
    return _UNIT_MAP.get(key, key[:40])


def parse_bom(filename: str, content: bytes) -> BomImportResponse:
    if not content:
        raise BomImportError("El archivo esta vacio.")
    if len(content) > MAX_FILE_BYTES:
        raise BomImportError("El archivo supera 2 MB.")
    name = (filename or "").lower()
    if name.endswith(".xlsx") or content[:2] == b"PK":
        rows = _read_xlsx(content)
    elif name.endswith((".csv", ".txt", ".tsv")) or not name:
        rows = _read_csv(content)
    else:
        raise BomImportError("Formato no soportado: usa .xlsx o .csv.")

    start, columns = _find_columns(rows)
    acc = _Accumulator()
    for offset, row in enumerate(rows[start:], start=start + 1):
        cells = list(row) + [None] * 3
        raw_query = cells[columns["query"]] if columns["query"] < len(cells) else None
        if raw_query is None or not str(raw_query).strip():
            continue  # fila vacia o separador
        acc.rows_read += 1
        try:
            query = validate_query(str(raw_query))
        except ValueError as exc:
            acc.rows_skipped += 1
            acc.warnings.append(f"Fila {offset}: '{str(raw_query)[:40]}' omitida ({exc})")
            continue
        quantity = parse_quantity(cells[columns["quantity"]] if columns["quantity"] < len(cells) else None)
        if quantity is None:
            acc.rows_skipped += 1
            acc.warnings.append(f"Fila {offset}: '{query[:40]}' sin cantidad valida; omitida.")
            continue
        unit_column = columns.get("unit")
        unit = _normalize_unit(cells[unit_column] if unit_column is not None else None, offset, acc)
        key = (canonical(query), unit)
        if key in acc.lines:
            acc.lines[key].quantity += quantity
        else:
            acc.lines[key] = BomImportLine(query=query, quantity=quantity, unit=unit, source_row=offset)

    lines = list(acc.lines.values())
    merged = acc.rows_read - acc.rows_skipped - len(lines)
    if merged > 0:
        acc.warnings.append(f"Se fusionaron {merged} filas repetidas (mismo material y unidad).")
    if len(lines) > MAX_BASKET_LINES:
        acc.warnings.append(
            f"La lista tiene {len(lines)} materiales; se importan los primeros {MAX_BASKET_LINES} "
            "(optimiza el resto en otra canasta)."
        )
        lines = lines[:MAX_BASKET_LINES]
    if not lines:
        raise BomImportError("No se encontraron materiales con cantidad valida en el archivo.")
    for line in lines:
        line.quantity = round(line.quantity, 3)
    return BomImportResponse(lines=lines, warnings=acc.warnings[:50], rows_read=acc.rows_read,
                             rows_skipped=acc.rows_skipped)
