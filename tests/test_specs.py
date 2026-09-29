"""Relevancia por especificacion y precio por unidad."""
import pytest

from app.schemas import ProductOffer
from app.services.specs import (
    annotate_offers, core_terms, extract_quantities, is_comparable, pack_content, relevance, spec_match,
)


def offer(title: str, price: float = 5000, store: str = "Sodimac") -> ProductOffer:
    return ProductOffer(title=title, store=store, source="test", extracted_price=price, anomaly_flag="ok")


class TestQuantities:
    @pytest.mark.parametrize("text, dimension, value", [
        ("Cemento 25 kg", "masa", 25_000),
        ("Cemento 42,5 kilos", "masa", 42_500),
        ("Pintura 0.25 l", "volumen", 250),
        ("Pintura látex 1 galón", "volumen", pytest.approx(3785.41)),
        ("Cerámica 2,16 m2", "area", 2.16),
        ("Broca 13mm", "largo", pytest.approx(0.013)),
        ('Tornillo 6x1 1/4"', "largo", pytest.approx(0.03175)),
        ("Taladro 750W", "potencia", 750),
        ("Tornillo caja 1000 unidades", "conteo", 1000),
    ])
    def test_extrae_magnitud(self, text, dimension, value):
        assert any(q.dimension == dimension and q.value == value for q in extract_quantities(text))

    def test_set_de_piezas_no_es_contenido(self):
        assert pack_content("Kit Taladro + Set 100 Piezas") is None

    def test_dimensiones_no_generan_conteo(self):
        assert all(q.dimension != "conteo" for q in extract_quantities("Plancha OSB 9.5 mm 1.22 x 2.44 m"))


class TestRelevance:
    def test_terminos_nucleo(self):
        assert core_terms("tornillos volcanita 1 pulgada") == ["tornillo", "volcanita"]
        assert core_terms("cemento 25 kg") == ["cemento"]

    def test_otro_producto_misma_medida(self):
        assert relevance("cemento 25 kg", "Arena Fina 25 kg Saco") == 0

    def test_accesorio_recibe_credito_parcial(self):
        score = relevance("taladro percutor", "Mandril Percutor 13mm Para Taladro Inalámbrico")
        assert 0 < score < 0.75

    def test_plural_y_tildes(self):
        assert relevance("plancha yeso carton", "Planchas Yeso-Cartón 15 mm") == 1


class TestSpecMatch:
    def test_misma_medida(self):
        assert spec_match("cemento 25 kg", "Cemento Melón especial 25 Kg") == "ok"

    def test_otra_medida(self):
        assert spec_match("cemento 25 kg", "Cemento gris 1 kg") == "mismatch"

    def test_pulgadas_equivalen_a_mm(self):
        assert spec_match("taladro 13 mm", 'Taladro percutor 1/2" 710W') == "ok"

    def test_titulo_sin_medida(self):
        assert spec_match("cemento 25 kg", "Cemento especial") == "unknown"


class TestAnnotate:
    def test_precio_por_unidad_y_comparabilidad(self):
        offers = annotate_offers("cemento 25 kg", [
            offer("Cemento 25 kg", 5090), offer("Cemento 1 kg", 890), offer("Arena 25 kg", 970),
        ])
        assert offers[0].unit == "kg" and offers[0].unit_price == pytest.approx(203.6)
        assert [is_comparable(o) for o in offers] == [True, False, False]
