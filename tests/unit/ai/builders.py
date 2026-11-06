"""Documentos extraídos "corretos" para os PDFs fictícios: o que um extrator perfeito devolveria.

Cada evidence é um trecho literal do texto gerado em tests/fixtures/documentos/generate.py.
"""

from typing import Any

from flowstream.ai.schemas import AirWaybill, BillOfLading, CommercialInvoice, PackingList


def f(valor: Any, evidence: str | None = None) -> dict[str, Any]:
    if valor is None:
        return {"valor": None, "evidence": None}
    return {"valor": valor, "evidence": evidence if evidence is not None else str(valor)}


NULL = f(None)


def bl_payload() -> dict[str, Any]:
    return {
        "numero_bl": f("MAEU2409001234", "B/L No.: MAEU2409001234"),
        "embarcador": f(
            "Ningbo Machinery Export Co., Ltd.", "Shipper: Ningbo Machinery Export Co., Ltd."
        ),
        "consignatario": f("Importadora Exemplo Ltda", "Consignee: Importadora Exemplo Ltda"),
        "notificar": f("Same as consignee", "Notify Party: Same as consignee"),
        "porto_carregamento": f("CNNGB", "Port of Loading: CNNGB - Ningbo"),
        "porto_descarga": f("BRITJ", "Port of Discharge: BRITJ - Itajai"),
        "navio": f("MSC AURORA", "Vessel: MSC AURORA"),
        "viagem": f("412W", "Voyage: 412W"),
        "data_embarque": f("2026-09-14", "Shipped on board: 14/09/2026"),
        "conteineres": [
            {
                "numero": f("MSKU1234565", "Container MSKU1234565"),
                "lacre": f("SL998877", "Seal SL998877"),
                "tipo": f("40HC", "SL998877  40HC"),
                "volumes": f("120", "40HC  120 packages"),
                "peso_bruto_kg": f("18500.50", "120 packages  18,500.50 kg"),
            },
            {
                "numero": f("TGHU7654320", "Container TGHU7654320"),
                "lacre": f("SL998878", "Seal SL998878"),
                "tipo": f("40HC", "SL998878  40HC"),
                "volumes": f("80", "40HC   80 packages"),
                "peso_bruto_kg": f("11200.00", "80 packages  11,200.00 kg"),
            },
        ],
        "volumes_total": f("200", "Total packages: 200"),
        "peso_bruto_total_kg": f("29700.50", "Total gross weight: 29,700.50 kg"),
        "cubagem_m3": f("118.40", "Measurement: 118.40 m3"),
        "descricao_mercadoria": f(
            "Machine parts (gears and bearings)",
            "Description of goods: Machine parts (gears and bearings)",
        ),
        "ncm": [f("84834010", "HS Code: 8483.40.10")],
        "frete": f("PREPAID", "Freight: PREPAID"),
    }


def packing_payload() -> dict[str, Any]:
    return {
        "numero_packing_list": f("PL-2026-0458", "Packing List No.: PL-2026-0458"),
        "numero_invoice": f("CI-2026-0458", "Invoice No.: CI-2026-0458"),
        "data_emissao": f("2026-09-10", "Date: 10/09/2026"),
        "exportador": f(
            "Ningbo Machinery Export Co., Ltd.", "Exporter: Ningbo Machinery Export Co., Ltd."
        ),
        "importador": f("Importadora Exemplo Ltda", "Importer: Importadora Exemplo Ltda"),
        "volumes_total": f("200", "Total packages: 200"),
        "peso_bruto_total_kg": f("29700.50", "Total gross weight: 29,700.50 kg"),
        "peso_liquido_total_kg": f("28700.00", "Total net weight: 28,700.00 kg"),
        "cubagem_m3": f("118.40", "Total measurement: 118.40 m3"),
        "conteineres": [
            f("MSKU1234565", "Containers: MSKU1234565, TGHU7654320"),
            f("TGHU7654320", "Containers: MSKU1234565, TGHU7654320"),
        ],
        "itens": [
            {
                "descricao": f("Gears, steel", "Item 1  Gears, steel"),
                "quantidade": f("1500", "qty 1,500"),
                "volumes": f("120", "1,500  120 packages"),
                "peso_liquido_kg": f("17900.00", "net 17,900.00 kg"),
                "peso_bruto_kg": f("18500.50", "gross 18,500.50 kg"),
            },
            {
                "descricao": f("Ball bearings", "Item 2  Ball bearings"),
                "quantidade": f("4000", "qty 4,000"),
                "volumes": f("80", "4,000   80 packages"),
                "peso_liquido_kg": f("10800.00", "net 10,800.00 kg"),
                "peso_bruto_kg": f("11200.00", "gross 11,200.00 kg"),
            },
        ],
    }


def invoice_payload() -> dict[str, Any]:
    return {
        "numero_invoice": f("CI-2026-0458", "Invoice No.: CI-2026-0458"),
        "data_emissao": f("2026-09-10", "Date: 10/09/2026"),
        "exportador": f(
            "Ningbo Machinery Export Co., Ltd.", "Seller: Ningbo Machinery Export Co., Ltd."
        ),
        "importador": f("Importadora Exemplo Ltda", "Buyer: Importadora Exemplo Ltda"),
        "importador_cnpj": f("00.000.123/0001-22", "CNPJ 00.000.123/0001-22"),
        "incoterm": f("FOB", "Incoterm: FOB Ningbo"),
        "moeda": f("USD", "Currency: USD"),
        "itens": [
            {
                "descricao": f("Gears, steel", "Item 1  Gears, steel"),
                "ncm": f("84834010", "NCM 8483.40.10"),
                "quantidade": f("1500", "1,500 PCS"),
                "unidade": f("PCS", "1,500 PCS"),
                "valor_unitario": f("12.40", "USD 12.40"),
                "valor_total": f("18600.00", "USD 18,600.00"),
            },
            {
                "descricao": f("Ball bearings", "Item 2  Ball bearings"),
                "ncm": f("84821010", "NCM 8482.10.10"),
                "quantidade": f("4000", "4,000 PCS"),
                "unidade": f("PCS", "4,000 PCS"),
                "valor_unitario": f("3.15", "USD 3.15"),
                "valor_total": f("12600.00", "USD 12,600.00"),
            },
        ],
        "valor_total": f("31200.00", "Total: USD 31,200.00"),
        "pais_origem": f("China", "Country of origin: China"),
        "frete": NULL,
        "seguro": NULL,
    }


def awb_payload() -> dict[str, Any]:
    return {
        "numero_awb": f("020-44556676", "AWB No.: 020-44556676"),
        "embarcador": f("Frankfurt Precision GmbH", "Shipper: Frankfurt Precision GmbH"),
        "consignatario": f("Importadora Exemplo Ltda", "Consignee: Importadora Exemplo Ltda"),
        "aeroporto_origem": f("FRA", "Airport of Departure: FRA"),
        "aeroporto_destino": f("GRU", "Airport of Destination: GRU"),
        "voo": f("LH 506", "Flight: LH 506"),
        "data_voo": f("2026-09-22", "LH 506 / 22/09/2026"),
        "volumes": f("12", "No. of pieces: 12"),
        "peso_bruto_kg": f("340.50", "Gross weight: 340.50 kg"),
        "peso_taxavel_kg": f("410.00", "Chargeable weight: 410.00 kg"),
        "descricao_mercadoria": f(
            "Measuring instruments", "Nature of goods: Measuring instruments"
        ),
    }


def bl() -> BillOfLading:
    return BillOfLading.model_validate(bl_payload())


def packing() -> PackingList:
    return PackingList.model_validate(packing_payload())


def invoice() -> CommercialInvoice:
    return CommercialInvoice.model_validate(invoice_payload())


def awb() -> AirWaybill:
    return AirWaybill.model_validate(awb_payload())
