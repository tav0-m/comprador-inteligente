"""Importacion de listas de materiales desde CSV y Excel."""
import io

import pytest
from fastapi.testclient import TestClient

from app.services.bom_import import BomImportError, parse_bom, parse_quantity


class TestQuantities:
    @pytest.mark.parametrize("raw, expected", [
        ("1.500", 1500), ("2,5", 2.5), ("1.234,5", 1234.5), ("12", 12), (7, 7), (0.5, 0.5),
        ("20 sacos", 20), ("", None), ("-3", None), (None, None),
    ])
    def test_formato_chileno(self, raw, expected):
        assert parse_quantity(raw) == expected


class TestCsv:
    CSV = (
        "Presupuesto Obra Los Alerces;;;\n"
        ";;;\n"
        "Item;Descripción;Unidad;Cantidad;Total\n"
        "1.1;Cemento 25 kg;kg;1.500;7.635.000\n"
        "1.2;Plancha OSB 15 mm;plancha;24;537.360\n"
        "1.3;Cemento 25 kg;kg;500;0\n"
        "1.4;Soleras de pino;ml;120;0\n"
        "1.5;Tornillo volcanita;;sin dato;0\n"
        "1.6;Pistola de calor;u;1;0\n"
    ).encode("cp1252")

    def test_detecta_encabezados_y_fusiona(self):
        result = parse_bom("presupuesto.csv", self.CSV)
        lines = {line.query: line for line in result.lines}
        # "Descripcion" gana a "Item"; "Total" (monto) no se usa como cantidad.
        assert lines["Cemento 25 kg"].quantity == 2000 and lines["Cemento 25 kg"].unit == "kg"
        assert lines["Plancha OSB 15 mm"].quantity == 24
        assert lines["Cemento 25 kg"].source_row == 4
        assert result.rows_read == 6 and result.rows_skipped == 2

    def test_advertencias(self):
        warnings = " ".join(parse_bom("presupuesto.csv", self.CSV).warnings)
        assert "metro lineal" in warnings  # ml en presupuestos = metro lineal
        assert "sin cantidad valida" in warnings
        assert "fusionaron 1" in warnings
        assert "Pistola" in warnings  # termino fuera de alcance (guardrails)

    def test_sin_encabezados_usa_orden_material_cantidad_unidad(self):
        result = parse_bom("lista.csv", "Cemento 25 kg,10,saco\nClavo corriente 4 pulgadas,5,kg\n".encode())
        assert [(line.query, line.quantity, line.unit) for line in result.lines] == [
            ("Cemento 25 kg", 10, "saco"), ("Clavo corriente 4 pulgadas", 5, "kg"),
        ]

    def test_limite_de_lineas(self):
        rows = "\n".join(f"Material numero {i},1,u" for i in range(45)).encode()
        result = parse_bom("grande.csv", rows)
        assert len(result.lines) == 30 and any("45 materiales" in w for w in result.warnings)


class TestXlsx:
    def _xlsx(self) -> bytes:
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Cubicación", None, None])
        sheet.append(["Material", "Cantidad", "Un"])
        sheet.append(["Malla ACMA C92", 12, "u"])
        sheet.append(["Hormigón premezclado", 3, "m3"])
        sheet.append([None, None, None])
        sheet.append(["Pintura latex 1 galon", 4.5, "galon"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    def test_lee_excel(self):
        result = parse_bom("cubicacion.xlsx", self._xlsx())
        assert [(line.query, line.quantity, line.unit) for line in result.lines] == [
            ("Malla ACMA C92", 12, "unidades"), ("Hormigón premezclado", 3, "m3"), ("Pintura latex 1 galon", 4.5, "galon"),
        ]
        assert any("metro cubico" in warning for warning in result.warnings)


class TestErrores:
    def test_vacio(self):
        with pytest.raises(BomImportError, match="vacio"):
            parse_bom("x.csv", b"")

    def test_formato_no_soportado(self):
        with pytest.raises(BomImportError, match="Formato"):
            parse_bom("lista.pdf", b"%PDF-1.7")

    def test_excel_corrupto(self):
        with pytest.raises(BomImportError, match="Excel"):
            parse_bom("lista.xlsx", b"no es un zip")

    def test_sin_materiales(self):
        with pytest.raises(BomImportError, match="No se encontraron"):
            parse_bom("x.csv", b"Material;Cantidad\nCemento;cero\n")


class TestApi:
    @pytest.fixture(scope="class")
    def client(self):
        from app.main import app

        with TestClient(app) as test_client:
            yield test_client

    def test_importar_por_api(self, client):
        response = client.post("/basket/import", params={"filename": "lista.csv"},
                               content="Material;Cantidad;Unidad\nCemento 25 kg;40;saco\n".encode())
        assert response.status_code == 200
        assert response.json()["lines"][0] == {"query": "Cemento 25 kg", "quantity": 40, "unit": "saco", "source_row": 2}

    def test_archivo_demasiado_grande(self, client):
        response = client.post("/basket/import", params={"filename": "x.csv"}, content=b"a" * (2 * 1024 * 1024 + 1))
        assert response.status_code == 413
