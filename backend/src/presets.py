from typing import List
from .schemas import PresetLocation

PRESET_LOCATIONS: List[PresetLocation] = [
    PresetLocation(
        id="pergamino_nucleo",
        name="Pergamino (Zona Núcleo Agrícola)",
        partido="Pergamino",
        lat=-33.9500,
        lon=-60.6200,
        description="Parcela agrícola real de Pampa Ondulada con 94%+ de cobertura cultivada (WorldCover 10m), excelente drenaje y nulo riesgo hídrico.",
        badge="Alta Aptitud Agrícola",
        typology="Pampa Ondulada Rural"
    ),
    PresetLocation(
        id="rio_salado_ribera",
        name="Río Salado (Parcela Ribereña Fluvial)",
        partido="General Paz",
        lat=-35.6850,
        lon=-58.4550,
        description="Lote atravesado y bordeado por el Río Salado; permite validar detección satelital de cauce fluvial, distancia al agua y buffer ribereño.",
        badge="Río / Lote Ribereño",
        typology="Planicie Aluvial Fluvial"
    ),
    PresetLocation(
        id="delta_parana_humedal",
        name="Delta del Paraná (Humedal Fluvial)",
        partido="Islas del Ibicuy",
        lat=-33.8900,
        lon=-58.8800,
        description="Ambiente palustre del Delta Inferior con predominio de humedal (WorldCover 90), brazos fluviales y alta recurrencia hídrica JRC.",
        badge="Humedal / Delta",
        typology="Delta y Humedales"
    ),
    PresetLocation(
        id="costa_chapadmalal",
        name="Chapadmalal (Costa y Acantilado Marino)",
        partido="General Pueyrredón",
        lat=-38.1550,
        lon=-57.6280,
        description="Frente costero atlántico con barrancas litorales e interacción directa mar-tierra; restringido por dinámica costera y aerosol salino.",
        badge="Costa Marina / Acantilado",
        typology="Borde Costero Atlántico"
    ),
    PresetLocation(
        id="laguna_chascomus",
        name="Laguna de Chascomús (Espejo de Agua)",
        partido="Chascomús",
        lat=-35.6050,
        lon=-58.0250,
        description="Espejo lacustre permanente del sistema Encadenadas del Salado (MNDWI positivo y JRC > 90%). No cultivable.",
        badge="Espejo Lacustre Permanente",
        typology="Cuerpo de Agua Continental"
    ),
    PresetLocation(
        id="dolores_bajos",
        name="Dolores (Bajos de Samborombón)",
        partido="Dolores",
        lat=-36.3600,
        lon=-57.5800,
        description="Bajos rurales de cota somera con pastizales naturales y bañados hidromórficos; aptitud exclusivamente ganadera.",
        badge="Ganadero / Bañados",
        typology="Pampa Deprimida"
    ),
    PresetLocation(
        id="pehuajo_arenosa",
        name="Pehuajó (Pampa Arenosa Rural)",
        partido="Pehuajó",
        lat=-35.8700,
        lon=-61.8200,
        description="Planicie agrícola-ganadera de muy baja pendiente (0.2%) con presencia histórica puntual de lagunas en bajos arenosos.",
        badge="Llanura Muy Plana",
        typology="Pampa Arenosa"
    ),
    PresetLocation(
        id="tandil_serrana",
        name="Tandil (Piedemonte Agrícola)",
        partido="Tandil",
        lat=-37.3900,
        lon=-59.0500,
        description="Piedemonte periserrano de Tandilia con pendiente moderada (~2.1%), suelos profundos cultivados y rápida evacuación pluvial.",
        badge="Piedemonte Bien Drenado",
        typology="Piedemonte Serrano"
    ),
    PresetLocation(
        id="sierra_ventana_cordon",
        name="Sierra de la Ventana (Cordón Serrano)",
        partido="Tornquist",
        lat=-38.1450,
        lon=-61.9750,
        description="Cordón rocoso escarpado (>30% de pendiente, cota >700 msnm y desniveles >400 m). Inapto para laboreo agrícola.",
        badge="Relieve Serrano Escarpado",
        typology="Macizo Serrano"
    ),
]
