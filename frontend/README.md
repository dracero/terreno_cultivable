# AgroJEV PBA — Frontend (Astro 5 + Leaflet + Motor Topográfico DEM/D8)

Interfaz web interactiva con diseño **Glassmorphism** para auditar la aptitud agronómica, capacidad de uso INTA (Clases I–VIII), riesgo de anegamiento y geomorfología topográfica de parcelas rurales en la Provincia de Buenos Aires.

## Estructura de Componentes

```text
frontend/
├── src/
│   ├── components/
│   │   ├── Header.astro          # Barra superior con estado de conexión al backend JEV y badges STAC
│   │   ├── MapViewer.astro       # Visor Leaflet multicapa (Esri, OpenTopoMap, JRC, DEM, Curvas Marching Squares, Vectores D8)
│   │   ├── TopoStudyPanel.astro  # Estudio topográfico (TWI, TPI, USLE LS, Napa, Zonificación 4 ambientes y Perfil SVG A→B)
│   │   ├── AgentMonitor.astro    # Telemetría en tiempo real de los 3 agentes (GeoExtractor, HydroRisk, AgroVerdict)
│   │   └── VerdictPanel.astro    # Dictamen ejecutivo (Score 0–100, Semáforo, Clase/Subclase INTA, IP, Cultivos y Obras)
│   ├── layouts/
│   │   └── Layout.astro          # Variables CSS globales, tipografía y tema oscuro Glassmorphism
│   └── pages/
│       └── index.astro           # Orquestador del dashboard, dibujo de transectas A→B y exportación GeoJSON
└── astro.config.mjs              # Servidor Astro configurado en el puerto 3000
```

## Capas Cartográficas y Herramientas Interactivas

- **Capas Base y Satelitales STAC**: Imagen satelital de alta resolución (Esri World Imagery), relieve topográfico (OpenTopoMap), ocurrencia histórica de agua superficial JRC (35 años) y sombreado de elevación Copernicus DEM 30m.
- **Superposiciones Vectoriales DEM**:
  - **Curvas de Nivel (Marching Squares)**: Isolíneas maestras e intermedias con etiquetas de cota (m.s.n.m.).
  - **Vectores Hidrológicos D8**: Flechas de dirección de flujo laminar y vías preferenciales de escurrimiento/cañadas.
- **Corte Topográfico A→B a Medida**: Permite trazar cualquier transecta sobre el lote con 2 clics para recalcular el perfil de elevación, pendiente local y profundidad de la napa freática en tiempo real.
- **Exportación GIS**: Descarga directa de curvas de nivel, vectores D8 y centroide diagnosticado en formato `.geojson` estándar para QGIS / ArcGIS.

## Comandos de Ejecución

Desde la raíz del monorepo (`npm run dev` levanta simultáneamente el backend en `:8000` y el frontend en `:3000`), o directamente dentro de `frontend/`:

| Comando | Descripción |
| :--- | :--- |
| `npm install` | Instala las dependencias de Astro 5 |
| `npm run dev` | Inicia el servidor de desarrollo en `http://localhost:3000` |
| `npm run build` | Compila el sitio estático de producción en `./dist/` |
| `npm run preview` | Previsualiza el build de producción localmente |
