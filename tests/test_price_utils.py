"""
Tests de parseo de precios CLP.
Verifica que el parser detecte correctamente el formato chileno
(punto = separador de miles, NO decimal).

Ejecutar:
    pytest tests/test_price_utils.py -v
"""
import pytest
from app.adapters._price_utils import clp_to_float


class TestCLPParsing:
    """El formato chileno usa punto como separador de miles: $5.990 = 5990 CLP."""

    # ── Formato chileno con punto de miles ───────────────────────────────────
    def test_punto_de_miles_basico(self):
        assert clp_to_float("$5.990") == 5990.0

    def test_punto_de_miles_grande(self):
        assert clp_to_float("$1.234.567") == 1_234_567.0

    def test_punto_de_miles_sin_signo(self):
        assert clp_to_float("5.990") == 5990.0

    def test_punto_de_miles_con_texto(self):
        assert clp_to_float("CLP 89.990") == 89_990.0

    def test_cuatro_digitos_sin_punto(self):
        assert clp_to_float("9990") == 9990.0

    def test_cinco_digitos_sin_punto(self):
        assert clp_to_float("15990") == 15_990.0

    # ── Enteros y flotantes directos (desde API) ──────────────────────────────
    def test_int_directo(self):
        assert clp_to_float(5990) == 5990.0

    def test_float_entero(self):
        assert clp_to_float(15990.0) == 15_990.0

    def test_float_menor_que_mil(self):
        """Valores reales como 990.5 deben tratarse como precio válido."""
        result = clp_to_float(990.5)
        assert result == 990.5

    # ── Precios absurdos que deben rechazarse ─────────────────────────────────
    def test_precio_billones_rechazado(self):
        """El bug original: $5.990 parseado como 5.99 → multiplicado = miles de millones."""
        # 2_495_000_000 está muy por encima del máximo de 30M
        assert clp_to_float(2_495_000_000) is None

    def test_precio_cero_rechazado(self):
        assert clp_to_float(0) is None

    def test_precio_negativo_rechazado(self):
        assert clp_to_float(-100) is None

    def test_precio_menor_que_minimo(self):
        assert clp_to_float(5) is None  # < 10 CLP mínimo

    # ── Valores vacíos y None ─────────────────────────────────────────────────
    def test_none(self):
        assert clp_to_float(None) is None

    def test_string_vacio(self):
        assert clp_to_float("") is None

    def test_string_sin_numeros(self):
        assert clp_to_float("sin precio") is None

    def test_agotado(self):
        assert clp_to_float("Agotado") is None

    # ── Precios con descuento y texto extra ───────────────────────────────────
    def test_precio_con_descuento(self):
        assert clp_to_float("$12.990 (-20%)") == 12_990.0

    def test_precio_con_moneda(self):
        assert clp_to_float("CLP 45.990") == 45_990.0

    def test_precio_con_espacios(self):
        assert clp_to_float("  29.990  ") == 29_990.0

    # ── Rango esperado de productos de ferretería ─────────────────────────────
    def test_precio_minimo_valido(self):
        """Tornillo suelto: $10 mínimo aceptable."""
        assert clp_to_float(10) == 10.0

    def test_precio_maximo_valido(self):
        """Equipo industrial caro: $29.000.000 aceptable."""
        assert clp_to_float(29_000_000) == 29_000_000.0

    def test_precio_sobre_maximo_rechazado(self):
        assert clp_to_float(31_000_000) is None


class TestCLPEdgeCases:
    """Casos límite especiales del formato CLP."""

    def test_tres_decimales_es_miles(self):
        """1.500 en Chile = 1500, NO 1.5."""
        assert clp_to_float("1.500") == 1500.0

    def test_dos_puntos_miles(self):
        """1.234.567 → 1234567."""
        assert clp_to_float("1.234.567") == 1_234_567.0

    def test_coma_decimal_europeo(self):
        """Algunos textos usan coma como decimal: 1.234,50 → 1234.50."""
        result = clp_to_float("1.234,50")
        assert result is not None
        assert result == pytest.approx(1234.5, rel=0.01)


class TestCLPContextoRetail:
    """Textos de tarjetas retail con varios montos: se debe elegir el precio vigente."""

    @pytest.mark.parametrize("text, expected", [
        ("Antes $9.990 Ahora $5.990", 5990.0),
        ("$5.990 $9.990", 5990.0),
        ("Precio normal $9.990", 9990.0),
        ("Ahorra $4.000 Precio $12.990", 12_990.0),
        ("Envío gratis $5.990", 5990.0),
        ("Despacho $3.990 $19.990", 19_990.0),
        ("$89.990 12 cuotas de $7.499", 89_990.0),
    ])
    def test_elige_precio_vigente(self, text, expected):
        assert clp_to_float(text) == expected

    @pytest.mark.parametrize("text", ["12 cuotas de $1.000", "12 cuotas sin interés de $1.000"])
    def test_cuota_sola_no_es_precio(self, text):
        assert clp_to_float(text) is None
