"""Tests de contrato de adaptadores, sin red.

Los fixtures reproducen la forma de los datos embebidos que publica cada tienda
(observada en 2026-09). Si una tienda cambia de plataforma, el adaptador debe
seguir sin romperse y estos tests documentan el formato esperado.
"""
import json

import pytest

from app.adapters import easy, falabella, mercadolibre, paris, sodimac
from app.adapters._price_utils import to_count, to_rating


def next_data_html(page_props: dict) -> str:
    payload = json.dumps({"props": {"pageProps": page_props}})
    return f'<html><script id="__NEXT_DATA__" type="application/json">{payload}</script></html>'


FALABELLA_ITEM = {
    "productId": "118254676",
    "displayName": "Taladro Inalámbrico Percutor Pro 13 Mm",
    "brand": "LERNEN",
    "url": "https://www.falabella.com/falabella-cl/product/118254676/taladro",
    "sellerName": "Lernen",
    "mediaUrls": ["https://media.falabella.com/img.jpg"],
    "meatStickers": [{"label": 'Llega mañana<div style="x">Plus</div>'}],
    "prices": [
        {"type": "cmrPrice", "crossed": False, "price": ["51.990"]},
        {"type": "eventPrice", "crossed": False, "price": ["54.990"]},
        {"type": "normalPrice", "crossed": True, "price": ["89.990"]},
    ],
    "rating": "4.6600",
    "totalReviews": "53",
}

SODIMAC_ITEM = {
    "productId": "3267326",
    "displayName": "Cemento especial 25 Kg",
    "brand": "Melon",
    "events": [{"description": "Despacho Gratis", "value": ""}],
    "prices": [{"type": "NORMAL", "price": "5.090", "priceWithoutFormatting": 5090, "unit": "C/U"}],
    "rating": "4.81",
    "totalReviews": "836",
    "mediaUrls": [],
}

EASY_ITEM = {
    "productName": "Cemento especial 25 kg",
    "brand": "Grupo Tx",
    "linkText": "cemento-especial-25-kg-1363022/p",
    "sellerName": "",
    "isMarketplace": False,
    "availableQuantity": 1,
    "prices": {"currency": "CLP", "normalPrice": 4990, "offerPrice": 4790},
    "ppumPrices": {"currency": "CLP", "contentUnit": "kg", "normalPrice": 200, "offerPrice": 192},
    "imageUrl": "https://easycl.vteximg.com.br/x.jpg",
}


class TestFalabella:
    def test_precio_vigente_excluye_tarjeta_y_tachado(self):
        offer = falabella.parse_platform_item(
            FALABELLA_ITEM, store="Falabella", source="falabella",
            price_types=falabella.FALABELLA_PRICE_TYPES,
        )
        assert offer.extracted_price == 54_990
        assert "normal 89.990" in offer.price_text and "tarjeta 51.990" in offer.price_text
        assert offer.title.startswith("LERNEN ")
        assert offer.seller == "Lernen"
        assert offer.rating == pytest.approx(4.66) and offer.reviews == 53
        assert "<" not in offer.delivery

    def test_search_lee_next_data(self, monkeypatch):
        html = next_data_html({"results": [FALABELLA_ITEM], "pagination": {"count": 1}})
        monkeypatch.setattr(falabella, "fetch_html", lambda *args, **kwargs: html)
        offers = falabella.FalabellaAdapter().search("taladro", max_results=10)
        assert len(offers) == 1 and offers[0].extracted_price == 54_990

    def test_sin_titulo_o_precio_se_descarta(self):
        types = falabella.FALABELLA_PRICE_TYPES
        assert falabella.parse_platform_item({"displayName": "", "prices": []}, "F", "f", types) is None
        assert falabella.parse_platform_item({"displayName": "X", "prices": []}, "F", "f", types) is None


class TestSodimac:
    def test_search_lee_search_props(self, monkeypatch):
        html = next_data_html({"searchProps": {"searchData": {
            "results": [SODIMAC_ITEM], "pagination": {"count": 1, "perPage": 28},
        }}})
        monkeypatch.setattr(sodimac, "fetch_html", lambda *args, **kwargs: html)
        offers = sodimac.SodimacAdapter().search("cemento", max_results=10)
        assert len(offers) == 1
        offer = offers[0]
        assert offer.extracted_price == 5090
        assert offer.link == "https://www.sodimac.cl/sodimac-cl/product/3267326"
        assert offer.delivery == "Despacho Gratis"

    def test_precio_combo_normal_es_referencia(self):
        item = {**SODIMAC_ITEM, "prices": [
            {"type": "NORMAL", "label": "", "priceWithoutFormatting": 259_890},
            {"type": "COMBO", "label": "Normal", "priceWithoutFormatting": 293_966},
        ]}
        offer = falabella.parse_platform_item(item, "Sodimac", "sodimac", sodimac.SODIMAC_PRICE_TYPES)
        assert offer.extracted_price == 259_890


class TestEasy:
    def test_producto_con_precio_por_unidad(self):
        offer = easy.parse_easy_product(EASY_ITEM)
        assert offer.extracted_price == 4790
        assert "[192/kg]" in offer.price_text
        assert offer.link == "https://www.easy.cl/cemento-especial-25-kg-1363022/p"

    def test_search_lee_server_products(self, monkeypatch):
        html = next_data_html({"serverProductsResponse": {"productList": [EASY_ITEM], "recordsFiltered": 1}})
        monkeypatch.setattr(easy, "fetch_html", lambda *args, **kwargs: html)
        assert len(easy.EasyAdapter().search("cemento", max_results=10)) == 1


class TestParis:
    def test_item_list_jsonld(self, monkeypatch):
        block = {
            "@context": "https://schema.org", "@type": "WebPage",
            "mainEntity": {"@type": "ItemList", "itemListElement": [{
                "@type": "ListItem", "position": 1,
                "item": {
                    "@type": "Product", "name": "Cemento especial 25 kg",
                    "brand": {"@type": "Brand", "name": "Grupo TX"},
                    "offers": {"@type": "Offer", "price": 4790, "priceCurrency": "CLP",
                               "url": "https://www.paris.cl/cemento-EA36SZMTWT.html"},
                },
            }]},
        }
        html = f'<script type="application/ld+json">{json.dumps(block)}</script>'
        monkeypatch.setattr(paris, "fetch_html", lambda *args, **kwargs: html)
        offers = paris.ParisAdapter().search("cemento")
        assert len(offers) == 1
        assert offers[0].extracted_price == 4790
        assert offers[0].title == "Grupo TX Cemento especial 25 kg"


class TestMercadoLibre:
    def test_sin_credenciales_no_llama_a_la_red(self, monkeypatch):
        monkeypatch.setattr(mercadolibre.settings, "mercadolibre_client_id", "")
        monkeypatch.setattr(mercadolibre.requests, "get", lambda *a, **k: pytest.fail("no debe llamar a la red"))
        assert mercadolibre.MercadoLibreAdapter().search("cemento") == []


class TestConversores:
    def test_rating_bajo_10_se_conserva(self):
        assert to_rating("4.7694") == pytest.approx(4.77)
        assert to_rating("7") is None

    def test_conteo_pequeno_y_con_miles(self):
        assert to_count("9") == 9
        assert to_count("1.234") == 1234
        assert to_count(None) is None
