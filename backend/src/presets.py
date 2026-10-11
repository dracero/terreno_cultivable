from typing import List
from .schemas import PresetLocation

PRESET_LOCATIONS: List[PresetLocation] = [
    PresetLocation(
        id="chascomus_salado",
        name="Chascomús (Cuenca Baja del Salado)",
        partido="Chascomús",
        lat=-35.5765,
        lon=-58.0125,
        description="Zona representativa de la Pampa Deprimida con alta recurrencia de agua, cañadas y lagunas encadenadas.",
        badge="Alto Riesgo Hídrico / Bajos",
        typology="Pampa Deprimida"
    ),
    PresetLocation(
        id="pehuajo_arenosa",
        name="Pehuajó (Pampa Arenosa)",
        partido="Pehuajó",
        lat=-35.8115,
        lon=-61.8950,
        description="Llanura con médanos y bajos sin pendiente definida; riesgo de anegamiento prolongado en ciclos húmedos.",
        badge="Anegamiento Plano Lento",
        typology="Pampa Arenosa"
    ),
    PresetLocation(
        id="pergamino_nucleo",
        name="Pergamino (Zona Núcleo Agrícola)",
        partido="Pergamino",
        lat=-33.8920,
        lon=-60.5730,
        description="Pampa Ondulada con suelos Argiudoles de máxima productividad agrícola, lomas bien drenadas y mínimo riesgo hídrico.",
        badge="Máxima Aptitud Agrícola",
        typology="Pampa Ondulada"
    ),
    PresetLocation(
        id="dolores_samborombon",
        name="Dolores (Bajos de Samborombón)",
        partido="Dolores",
        lat=-36.3130,
        lon=-57.6790,
        description="Proximidad a la Bahía de Samborombón con cotas inferiores a 5 msnm, suelos con limitaciones halomórficas y escurrimiento muy lento.",
        badge="Humedal / Suelo de Cría",
        typology="Cuenca Deprimida / Costa"
    ),
    PresetLocation(
        id="tandil_serrana",
        name="Tandil (Sistema Serrano)",
        partido="Tandil",
        lat=-37.3210,
        lon=-59.1330,
        description="Relieve serrano de Tandilia con excelente pendiente natural, cotas sobre 180 msnm y nulo riesgo de acumulación hídrica.",
        badge="Drenaje Rápido / Relieve Fuerte",
        typology="Zona Serrana"
    ),
    PresetLocation(
        id="saladillo_media",
        name="Saladillo (Cuenca Media)",
        partido="Saladillo",
        lat=-35.6370,
        lon=-59.7780,
        description="Zona de transición mixta agrícola-ganadera en la cuenca del Arroyo Saladillo, sensible a picos de precipitación.",
        badge="Aptitud Mixta",
        typology="Pampa Mixta"
    )
]
