"""
Tests del normalizador y deduplicador semántico.

Ejecutar:
    pytest tests/test_normalizer.py -v
"""
import pytest
from app.schemas import ProductOffer
from app.services.normalizer import normalize_offer, semantic_deduplicate


def make_offer(**kwargs) -> ProductOffer:
    defaults = dict(
        title="Martillo Stanley 16oz",
        store="Sodimac",
        source="sodimac",
        price_text="CLP 15.990",
        extracted_price=15990.0,
        currency="CLP",
    )
    defaults.update(kwargs)
    return ProductOffer(**defaults)


class TestNormalizeOffer:
    def test_titulo_limpiado(self):
        o = make_offer(title="  Martillo   Stanley  16oz  ")
        result = normalize_offer(o)
        assert result.title == "Martillo Stanley 16oz"

    def test_precio_extraido_si_falta(self):
        o = make_offer(extracted_price=None, price_text="CLP 9.990")
        result = normalize_offer(o)
        assert result.extracted_price == 9990.0

    def test_moneda_normalizada(self):
        o = make_offer(currency="clp")
        result = normalize_offer(o)
        assert result.currency == "CLP"

    def test_oferta_sin_precio_no_falla(self):
        o = make_offer(extracted_price=None, price_text="Agotado")
        result = normalize_offer(o)
        assert result is not None  # no debe lanzar excepción

    def test_link_https(self):
        o = make_offer(link="http://www.sodimac.cl/producto/123")
        result = normalize_offer(o)
        # Link debe mantenerse
        assert result.link is not None


class TestSemanticDeduplicate:
    def test_duplicados_eliminados(self):
        offers = [
            make_offer(title="Martillo Stanley 16oz", extracted_price=15990),
            make_offer(title="Martillo Stanley 16 oz", extracted_price=15990),  # casi igual
            make_offer(title="Taladro Bosch 550W",   extracted_price=45990),
        ]
        result = semantic_deduplicate(offers)
        # Los dos martillos deben quedar como uno, el taladro se mantiene
        assert len(result) == 2

    def test_productos_distintos_se_mantienen(self):
        offers = [
            make_offer(title="Cemento Melón 25kg",  extracted_price=6990),
            make_offer(title="Arena Gruesa 25kg",   extracted_price=4990),
            make_offer(title="Cal Hidratada 20kg",  extracted_price=5490),
        ]
        result = semantic_deduplicate(offers)
        assert len(result) == 3

    def test_lista_vacia(self):
        assert semantic_deduplicate([]) == []

    def test_un_solo_producto(self):
        o = make_offer()
        result = semantic_deduplicate([o])
        assert len(result) == 1

    def test_mismo_producto_tres_tiendas(self):
        """El mismo producto en 3 tiendas distintas NO debe deduplicarse."""
        offers = [
            make_offer(title="Tornillo PH 3/4 caja 100u", store="Sodimac",    extracted_price=3990),
            make_offer(title="Tornillo PH 3/4 caja 100u", store="Easy",       extracted_price=4100),
            make_offer(title="Tornillo PH 3/4 caja 100u", store="Construmart",extracted_price=3750),
        ]
        result = semantic_deduplicate(offers)
        # Mismo nombre pero distintas tiendas → puede deduplicar o no,
        # depende del umbral. Lo importante es que no lanza excepción.
        assert len(result) == 3


class TestAnomalyDetection:
    def test_precio_muy_alto_marcado(self):
        from app.services.anomaly_detector import detect_price_anomalies
        offers = [
            make_offer(title="Cemento",  extracted_price=5_000),
            make_offer(title="Cemento",  extracted_price=5_500),
            make_offer(title="Cemento",  extracted_price=5_200),
            make_offer(title="Cemento",  extracted_price=500_000),  # absurdo
        ]
        result = detect_price_anomalies(offers)
        flags = [o.anomaly_flag for o in result]
        assert "precio_muy_alto" in flags

    def test_precios_normales_no_marcados(self):
        from app.services.anomaly_detector import detect_price_anomalies
        offers = [
            make_offer(extracted_price=5_000),
            make_offer(extracted_price=5_200),
            make_offer(extracted_price=4_800),
            make_offer(extracted_price=5_100),
        ]
        result = detect_price_anomalies(offers)
        ok_flags = [o for o in result if o.anomaly_flag == "ok"]
        assert len(ok_flags) >= 3

    def test_mad_no_fuerza_atipicos(self):
        """Con precios coherentes no se debe marcar una fraccion fija como anomala."""
        from app.services.anomaly_detector import detect_price_anomalies
        offers = [make_offer(title="Cemento", extracted_price=5_000 + i * 50, semantic_group=0) for i in range(12)]
        result = detect_price_anomalies(offers)
        assert all(o.anomaly_flag == "ok" for o in result)

    def test_grupo_pequeno_con_precio_extremo(self):
        """Grupos < 3 ya no quedan 'ok' por defecto si el precio es absurdo vs la busqueda."""
        from app.services.anomaly_detector import detect_price_anomalies
        offers = [make_offer(extracted_price=5_000 + i * 100, semantic_group=0) for i in range(5)]
        offers.append(make_offer(title="Tipo de Entrega", extracted_price=25_000_000, semantic_group=1))
        result = detect_price_anomalies(offers)
        assert result[-1].anomaly_flag == "precio_muy_alto"
        assert all(o.anomaly_flag == "ok" for o in result[:-1])
