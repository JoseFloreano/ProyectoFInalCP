import streamlit as st
import pandas as pd
import requests
import re
import json
import time
from datetime import datetime
import folium
from streamlit_folium import st_folium
import plotly.express as px
import plotly.graph_objects as go

# Configuración de la página
st.set_page_config(
    page_title="Monitor de Calidad del Aire CDMX",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ========================================
# Estilos CSS personalizados
# ========================================
st.markdown(
    """
    <style>
    .main {
        padding: 0rem 1rem;
    }
    .stAlert {
        margin-top: 1rem;
    }
    div[data-testid="stMetricValue"] {
        font-size: 2rem;
    }
    .calidad-buena {
        background-color: #d4edda;
        color: #155724;
        padding: 10px;
        border-radius: 8px;
        border-left: 5px solid #28a745;
        margin: 10px 0;
    }
    .calidad-regular {
        background-color: #fff3cd;
        color: #856404;
        padding: 10px;
        border-radius: 8px;
        border-left: 5px solid #ffc107;
        margin: 10px 0;
    }
    .calidad-mala {
        background-color: #f8d7da;
        color: #721c24;
        padding: 10px;
        border-radius: 8px;
        border-left: 5px solid #dc3545;
        margin: 10px 0;
    }
    </style>
""",
    unsafe_allow_html=True,
)


# ========================================
# Funciones de evaluación de calidad
# ========================================
def calidad_co(co):
    if pd.isna(co):
        return None
    if co <= 5.5:
        return "Buena"
    elif co <= 11:
        return "Regular"
    else:
        return "Mala"


def calidad_o3(o3):
    if pd.isna(o3):
        return None
    if o3 <= 0.055:
        return "Buena"
    elif o3 <= 0.095:
        return "Regular"
    else:
        return "Mala"


def calidad_no2(no2):
    if pd.isna(no2):
        return None
    if no2 <= 0.10:
        return "Buena"
    elif no2 <= 0.21:
        return "Regular"
    else:
        return "Mala"


def calidad_nox(nox):
    if pd.isna(nox):
        return None
    if nox <= 0.10:
        return "Buena"
    elif nox <= 0.20:
        return "Regular"
    else:
        return "Mala"


def calidad_no(no):
    if pd.isna(no):
        return None
    if no <= 0.05:
        return "Buena"
    elif no <= 0.15:
        return "Regular"
    else:
        return "Mala"


# ========================================
# Funciones de obtención de datos
# ========================================
@st.cache_data(ttl=600)  # Cache por 10 minutos
def get_sinaica_data(estId):
    """Obtiene datos de SINAICA"""
    try:
        url = f"https://sinaica.inecc.gob.mx/estacion.php?estId={estId}"
        html = requests.get(url, timeout=10).text
        pattern = r"conts\s*=\s*(\{.*?\});"
        match = re.search(pattern, html, re.DOTALL)

        dfs = []
        columnas_base = [
            "id",
            "parametro",
            "fecha",
            "hora",
            "valorAct",
            "siglas",
            "nombre",
            "descripcion",
            "tipoParametro",
            "activo",
        ]

        if match:
            conts_js = match.group(1)
            conts = json.loads(conts_js)
            for key in ["CO", "NO", "NO2", "NOx", "O3", "PM10", "PM2.5", "SO2"]:
                data = conts.get(key)

                if not isinstance(data, list):
                    continue

                filas = []
                for row in data:
                    if row is None:
                        filas.append(
                            {
                                "id": None,
                                "parametro": key,
                                "fecha": None,
                                "hora": None,
                                "valorAct": None,
                                "siglas": key,
                                "nombre": None,
                                "descripcion": None,
                                "tipoParametro": None,
                                "activo": None,
                            }
                        )
                    elif isinstance(row, dict):
                        filas.append(row)

                df = pd.DataFrame(filas, columns=columnas_base)
                dfs.append(df)

        # Datos meteorológicos
        pattern = r"meteo\s*=\s*(\{.*?\});"
        match = re.search(pattern, html, re.DOTALL)

        if match:
            meteo_js = match.group(1)
            meteo = json.loads(meteo_js)
            for key in ["DV", "HR", "TMP", "VV"]:
                data = meteo.get(key)

                if not isinstance(data, list):
                    continue

                filas = []
                for row in data:
                    if row is None:
                        filas.append(
                            {
                                "id": None,
                                "parametro": key,
                                "fecha": None,
                                "hora": None,
                                "valorAct": None,
                                "siglas": key,
                                "nombre": None,
                                "descripcion": None,
                                "tipoParametro": None,
                                "activo": None,
                            }
                        )
                    elif isinstance(row, dict):
                        filas.append(row)

                df = pd.DataFrame(filas, columns=columnas_base)
                dfs.append(df)

        if not dfs:
            return None

        df_total = pd.concat(dfs, ignore_index=True)
        df_wide = df_total.pivot_table(
            index=["fecha", "hora"], columns="parametro", values="valorAct"
        )
        return df_wide.tail(1)
    except Exception as e:
        st.error(f"Error obteniendo datos SINAICA: {e}")
        return None


@st.cache_data(ttl=600)
def get_openaq_data(estId, API_KEY):
    """Obtiene datos de OpenAQ"""
    try:
        headers = {"X-API-Key": API_KEY}

        # Obtener sensores
        url = f"https://api.openaq.org/v3/locations/{estId}"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        dfs = []
        for sensor in data["results"][0]["sensors"]:
            SENSOR_ID = sensor["id"]

            url = f"https://api.openaq.org/v3/sensors/{SENSOR_ID}"
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            sensor_data = response.json()

            df_sensor = pd.json_normalize(sensor_data["results"], sep="_")
            df_sensor_clean = df_sensor[
                ["parameter_name", "latest_value", "latest_datetime_local"]
            ].rename(
                columns={
                    "parameter_name": "parametro",
                    "latest_value": "valorAct",
                    "latest_datetime_local": "datetime_local",
                }
            )

            dfs.append(df_sensor_clean)
            time.sleep(0.2)

        if not dfs:
            return None

        df_total = pd.concat(dfs, ignore_index=True)
        df_total["datetime_local"] = pd.to_datetime(df_total["datetime_local"])
        df_total["fecha"] = df_total["datetime_local"].dt.date
        df_total["hora"] = df_total["datetime_local"].dt.hour
        df_total["parametro"] = df_total["parametro"].str.upper()

        fecha_max = df_total["fecha"].max()
        hora_max = df_total[df_total["fecha"] == fecha_max]["hora"].max()

        df_ult = df_total[
            (df_total["fecha"] == fecha_max) & (df_total["hora"] == hora_max)
        ]

        df_wide = df_ult.pivot_table(
            index=["fecha", "hora"], columns="parametro", values="valorAct"
        )
        return df_wide
    except Exception as e:
        st.error(f"Error obteniendo datos OpenAQ: {e}")
        return None


def evaluar_calidad_aire(df):
    """Evalúa la calidad del aire"""
    if df is None or df.empty:
        return None

    df = df.copy()
    orden = {"Buena": 1, "Regular": 2, "Mala": 3}

    if "CO" in df.columns:
        df["calidad_CO"] = df["CO"].apply(calidad_co)
    if "O3" in df.columns:
        df["calidad_O3"] = df["O3"].apply(calidad_o3)
    if "NO2" in df.columns:
        df["calidad_NO2"] = df["NO2"].apply(calidad_no2)
    if "NOX" in df.columns:
        df["calidad_NOx"] = df["NOX"].apply(calidad_nox)
    if "NO" in df.columns:
        df["calidad_NO"] = df["NO"].apply(calidad_no)

    def calidad_global(row):
        calidades = [
            row.get("calidad_CO"),
            row.get("calidad_O3"),
            row.get("calidad_NO2"),
            row.get("calidad_NOx"),
            row.get("calidad_NO"),
        ]
        calidades = [c for c in calidades if c is not None]
        if not calidades:
            return None
        return max(calidades, key=lambda x: orden[x])

    df["calidad_global"] = df.apply(calidad_global, axis=1)
    return df


# ========================================
# Configuración de estaciones
# ========================================
ESTACIONES = {
    "Ajusco Medio": {"lat": 19.1547, "lng": -99.2063, "sinaica": 242, "openaq": 480393},
    "Benito Juárez": {"lat": 19.3706, "lng": -99.1591, "sinaica": 300, "openaq": 10860},
    "Camarones": {"lat": 19.4586, "lng": -99.1853, "sinaica": 244, "openaq": 10722},
    "Centro de Ciencias de la Atmósfera": {
        "lat": 19.3264,
        "lng": -99.1764,
        "sinaica": 245,
        "openaq": 10534,
    },
    "Cuajimalpa": {"lat": 19.3650, "lng": -99.2919, "sinaica": 246, "openaq": 223434},
    "Gustavo A. Madero": {
        "lat": 19.4858,
        "lng": -99.1281,
        "sinaica": 302,
        "openaq": 10632,
    },
    "Hospital General de México": {
        "lat": 19.4116,
        "lng": -99.1522,
        "sinaica": 251,
        "openaq": 1134,
    },
    "Merced": {"lat": 19.4244, "lng": -99.1197, "sinaica": 256, "openaq": 10748},
    "Miguel Hidalgo": {
        "lat": 19.4006,
        "lng": -99.2025,
        "sinaica": 263,
        "openaq": 10735,
    },
    "Pedregal": {"lat": 19.3250, "lng": -99.2039, "sinaica": 259, "openaq": 10658},
    "Santiago Acahualtepec": {
        "lat": 19.4833,
        "lng": -99.0089,
        "sinaica": 432,
        "openaq": 10802,
    },
    "UAM Iztapalapa": {
        "lat": 19.3617,
        "lng": -99.0739,
        "sinaica": 268,
        "openaq": 10804,
    },
}

API_KEYS = [
    "934a33cfc397140c9f15c38a528f79384b5d180f31cb344dc217840f3a7cff93",
    "23a0b5d725eaf67585d9c4b3d8e1fcd02cd10c0ae4cbaf47cade3de6de27d0cc",
]


# ========================================
# Funciones auxiliares
# ========================================
def get_color_calidad(calidad):
    """Retorna el color según la calidad"""
    if calidad == "Buena":
        return "green"
    elif calidad == "Regular":
        return "orange"
    elif calidad == "Mala":
        return "red"
    return "gray"


def crear_mapa(datos_estaciones):
    """Crea el mapa interactivo con Folium"""
    m = folium.Map(location=[19.4326, -99.1332], zoom_start=11, tiles="OpenStreetMap")

    for estacion, info in ESTACIONES.items():
        # Buscar datos de la estación
        calidad = None
        fuente = "Sin datos"
        valores = {}

        if datos_estaciones and estacion in datos_estaciones:
            datos = datos_estaciones[estacion]
            calidad = datos.get("calidad_global")
            fuente = datos.get("fuente", "Sin datos")
            valores = datos.get("valores", {})

        color = get_color_calidad(calidad)

        # Crear popup con información
        popup_html = f"""
        <div style="font-family: Arial; width: 250px;">
            <h4 style="margin: 0 0 10px 0; color: #333;">{estacion}</h4>
            <p style="margin: 5px 0;"><strong>Calidad:</strong> 
                <span style="color: {color}; font-weight: bold;">
                    {calidad if calidad else 'Sin datos'}
                </span>
            </p>
            <p style="margin: 5px 0;"><strong>Fuente:</strong> {fuente}</p>
            <hr style="margin: 10px 0;">
            <p style="margin: 5px 0; font-size: 12px;"><strong>Contaminantes:</strong></p>
        """

        for cont, valor in valores.items():
            if valor is not None and not pd.isna(valor):
                # Intentar formatear como número, si no es posible, mostrar como texto
                try:
                    if isinstance(valor, (int, float)):
                        valor_str = f"{valor:.3f}"
                    else:
                        valor_str = str(valor)
                except:
                    valor_str = str(valor)

                popup_html += f"""
                <p style="margin: 2px 0; font-size: 11px;">
                    {cont}: {valor_str}
                </p>
                """

        popup_html += "</div>"

        folium.CircleMarker(
            location=[info["lat"], info["lng"]],
            radius=12,
            popup=folium.Popup(popup_html, max_width=300),
            color=color,
            fill=True,
            fillColor=color,
            fillOpacity=0.7,
            weight=2,
        ).add_to(m)

    return m


def mostrar_alerta_calidad(calidad, estacion):
    """Muestra una alerta visual según la calidad"""
    if calidad == "Buena":
        st.success(f"✅ **{estacion}**: Calidad del aire BUENA")
    elif calidad == "Regular":
        st.warning(f"⚠️ **{estacion}**: Calidad del aire REGULAR")
    elif calidad == "Mala":
        st.error(f"🚨 **{estacion}**: Calidad del aire MALA")
    else:
        st.info(f"ℹ️ **{estacion}**: Sin datos disponibles")


# ========================================
# Interfaz Principal
# ========================================
st.title("🌍 Monitor de Calidad del Aire - Ciudad de México")
st.markdown("### Monitoreo en tiempo real de estaciones de calidad del aire")

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuración")

    st.markdown("---")

    st.markdown("### 📡 Fuentes de Datos")
    fuente_seleccionada = st.radio(
        "Selecciona la fuente:",
        ["Ambas", "SINAICA", "OpenAQ"],
        help="Elige qué API consultar para los datos",
    )

    st.markdown("---")

    st.markdown("### 🏢 Estaciones")
    estaciones_seleccionadas = st.multiselect(
        "Filtrar estaciones:",
        options=list(ESTACIONES.keys()),
        default=list(ESTACIONES.keys()),
        help="Selecciona las estaciones que deseas monitorear",
    )

    st.markdown("---")

    st.markdown("### 🎨 Filtro de Calidad")
    filtro_calidad = st.multiselect(
        "Mostrar solo:",
        ["Buena", "Regular", "Mala"],
        default=["Buena", "Regular", "Mala"],
    )

    st.markdown("---")

    if st.button("🔄 Limpiar Cache", use_container_width=True):
        st.cache_data.clear()
        st.success("Cache limpiado!")
        st.rerun()

# Botón principal para obtener datos
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if st.button(
        "📡 OBTENER DATOS ACTUALIZADOS", type="primary", use_container_width=True
    ):
        st.session_state.datos_obtenidos = True

# Obtener y mostrar datos
if "datos_obtenidos" in st.session_state and st.session_state.datos_obtenidos:

    with st.spinner("🔄 Obteniendo datos de las estaciones..."):
        resultados = []
        datos_para_mapa = {}
        progress_bar = st.progress(0)
        total_estaciones = len(estaciones_seleccionadas)

        for idx, estacion in enumerate(estaciones_seleccionadas):
            info = ESTACIONES[estacion]

            # SINAICA
            if fuente_seleccionada in ["Ambas", "SINAICA"]:
                with st.spinner(f"Consultando SINAICA: {estacion}..."):
                    try:
                        df_sinaica = get_sinaica_data(info["sinaica"])
                        if df_sinaica is not None and not df_sinaica.empty:
                            df_sinaica = evaluar_calidad_aire(df_sinaica)
                            df_sinaica["fuente"] = "SINAICA"
                            df_sinaica["estacion"] = estacion
                            resultados.append(df_sinaica.reset_index())

                            # Guardar para el mapa
                            if (
                                estacion not in datos_para_mapa
                                or datos_para_mapa[estacion].get("fuente") != "SINAICA"
                            ):
                                try:
                                    calidad = (
                                        df_sinaica["calidad_global"].iloc[0]
                                        if "calidad_global" in df_sinaica.columns
                                        else None
                                    )
                                    valores_dict = {}

                                    # Filtrar solo valores numéricos para el mapa
                                    for col in df_sinaica.columns:
                                        if col not in [
                                            "fecha",
                                            "hora",
                                            "fuente",
                                            "estacion",
                                        ]:
                                            val = df_sinaica[col].iloc[0]
                                            if val is not None and not pd.isna(val):
                                                valores_dict[col] = val

                                    datos_para_mapa[estacion] = {
                                        "calidad_global": calidad,
                                        "fuente": "SINAICA",
                                        "valores": valores_dict,
                                    }
                                except Exception as e:
                                    st.warning(
                                        f"Error procesando datos de mapa para {estacion} (SINAICA): {e}"
                                    )
                    except Exception as e:
                        st.error(f"Error consultando SINAICA para {estacion}: {e}")

            # OpenAQ
            if fuente_seleccionada in ["Ambas", "OpenAQ"]:
                with st.spinner(f"Consultando OpenAQ: {estacion}..."):
                    try:
                        api_key = API_KEYS[idx % len(API_KEYS)]
                        df_openaq = get_openaq_data(info["openaq"], api_key)
                        if df_openaq is not None and not df_openaq.empty:
                            df_openaq = evaluar_calidad_aire(df_openaq)
                            df_openaq["fuente"] = "OPENAQ"
                            df_openaq["estacion"] = estacion
                            resultados.append(df_openaq.reset_index())

                            # Guardar para el mapa (si no hay datos de SINAICA)
                            if estacion not in datos_para_mapa:
                                try:
                                    calidad = (
                                        df_openaq["calidad_global"].iloc[0]
                                        if "calidad_global" in df_openaq.columns
                                        else None
                                    )
                                    valores_dict = {}

                                    # Filtrar solo valores numéricos para el mapa
                                    for col in df_openaq.columns:
                                        if col not in [
                                            "fecha",
                                            "hora",
                                            "fuente",
                                            "estacion",
                                        ]:
                                            val = df_openaq[col].iloc[0]
                                            if val is not None and not pd.isna(val):
                                                valores_dict[col] = val

                                    datos_para_mapa[estacion] = {
                                        "calidad_global": calidad,
                                        "fuente": "OPENAQ",
                                        "valores": valores_dict,
                                    }
                                except Exception as e:
                                    st.warning(
                                        f"Error procesando datos de mapa para {estacion} (OpenAQ): {e}"
                                    )
                    except Exception as e:
                        st.error(f"Error consultando OpenAQ para {estacion}: {e}")

            progress_bar.progress((idx + 1) / total_estaciones)

        progress_bar.empty()

        if resultados:
            df_resultados = pd.concat(resultados, ignore_index=True)

            # Filtrar por calidad
            if filtro_calidad:
                df_resultados = df_resultados[
                    df_resultados["calidad_global"].isin(filtro_calidad)
                ]

            st.success(
                f"✅ Datos obtenidos exitosamente de {len(estaciones_seleccionadas)} estaciones!"
            )

            # Métricas generales
            st.markdown("### 📊 Resumen General")
            col1, col2, col3, col4 = st.columns(4)

            total = len(df_resultados)
            buenas = len(df_resultados[df_resultados["calidad_global"] == "Buena"])
            regulares = len(df_resultados[df_resultados["calidad_global"] == "Regular"])
            malas = len(df_resultados[df_resultados["calidad_global"] == "Mala"])

            with col1:
                st.metric("Total de Registros", total)
            with col2:
                st.metric(
                    "Buena 🟢",
                    buenas,
                    delta=f"{(buenas/total*100):.1f}%" if total > 0 else "0%",
                )
            with col3:
                st.metric(
                    "Regular 🟡",
                    regulares,
                    delta=f"{(regulares/total*100):.1f}%" if total > 0 else "0%",
                )
            with col4:
                st.metric(
                    "Mala 🔴",
                    malas,
                    delta=f"{(malas/total*100):.1f}%" if total > 0 else "0%",
                )

            # Tabs para diferentes vistas
            tab1, tab2, tab3, tab4 = st.tabs(
                ["🗺️ Mapa Interactivo", "🚨 Alertas", "📋 Tabla de Datos", "📈 Gráficos"]
            )

            with tab1:
                st.markdown("### 🗺️ Mapa de Calidad del Aire")
                try:
                    mapa = crear_mapa(datos_para_mapa)
                    st_folium(mapa, width=1400, height=600)
                except Exception as e:
                    st.error(f"Error al crear el mapa: {e}")
                    st.info("Mostrando datos disponibles en las otras pestañas")

                st.markdown(
                    """
                **Leyenda:**
                - 🟢 Verde: Calidad Buena
                - 🟡 Naranja: Calidad Regular
                - 🔴 Rojo: Calidad Mala
                - ⚫ Gris: Sin datos
                """
                )

            with tab2:
                st.markdown("### 🚨 Alertas de Calidad por Estación")

                for _, row in df_resultados.iterrows():
                    estacion = row["estacion"]
                    calidad = row["calidad_global"]
                    fuente = row["fuente"]

                    with st.expander(
                        f"{estacion} - {fuente} ({calidad if calidad else 'Sin datos'})"
                    ):
                        mostrar_alerta_calidad(calidad, estacion)

                        col1, col2 = st.columns(2)
                        with col1:
                            st.write("**Información General:**")
                            st.write(f"- Fecha: {row.get('fecha', 'N/A')}")
                            st.write(f"- Hora: {row.get('hora', 'N/A')}")
                            st.write(f"- Fuente: {fuente}")

                        with col2:
                            st.write("**Contaminantes:**")
                            contaminantes_info = []

                            if "CO" in row and not pd.isna(row["CO"]):
                                calidad_co_val = row.get("calidad_CO", "N/A")
                                try:
                                    co_val = f"{float(row['CO']):.3f}"
                                except:
                                    co_val = str(row["CO"])
                                contaminantes_info.append(
                                    f"- CO: {co_val} ppm ({calidad_co_val})"
                                )

                            if "O3" in row and not pd.isna(row["O3"]):
                                calidad_o3_val = row.get("calidad_O3", "N/A")
                                try:
                                    o3_val = f"{float(row['O3']):.3f}"
                                except:
                                    o3_val = str(row["O3"])
                                contaminantes_info.append(
                                    f"- O3: {o3_val} ppm ({calidad_o3_val})"
                                )

                            if "NO2" in row and not pd.isna(row["NO2"]):
                                calidad_no2_val = row.get("calidad_NO2", "N/A")
                                try:
                                    no2_val = f"{float(row['NO2']):.3f}"
                                except:
                                    no2_val = str(row["NO2"])
                                contaminantes_info.append(
                                    f"- NO2: {no2_val} ppm ({calidad_no2_val})"
                                )

                            if "NOX" in row and not pd.isna(row["NOX"]):
                                calidad_nox_val = row.get("calidad_NOx", "N/A")
                                try:
                                    nox_val = f"{float(row['NOX']):.3f}"
                                except:
                                    nox_val = str(row["NOX"])
                                contaminantes_info.append(
                                    f"- NOx: {nox_val} ppm ({calidad_nox_val})"
                                )

                            if "NO" in row and not pd.isna(row["NO"]):
                                calidad_no_val = row.get("calidad_NO", "N/A")
                                try:
                                    no_val = f"{float(row['NO']):.3f}"
                                except:
                                    no_val = str(row["NO"])
                                contaminantes_info.append(
                                    f"- NO: {no_val} ppm ({calidad_no_val})"
                                )

                            if "PM10" in row and not pd.isna(row["PM10"]):
                                try:
                                    pm10_val = f"{float(row['PM10']):.1f}"
                                except:
                                    pm10_val = str(row["PM10"])
                                contaminantes_info.append(f"- PM10: {pm10_val} µg/m³")

                            if "PM2.5" in row and not pd.isna(row["PM2.5"]):
                                try:
                                    pm25_val = f"{float(row['PM2.5']):.1f}"
                                except:
                                    pm25_val = str(row["PM2.5"])
                                contaminantes_info.append(f"- PM2.5: {pm25_val} µg/m³")

                            if contaminantes_info:
                                for info in contaminantes_info:
                                    st.write(info)
                            else:
                                st.write("No hay datos de contaminantes disponibles")

            with tab3:
                st.markdown("### 📋 Tabla Completa de Datos")

                # Seleccionar columnas relevantes
                columnas_mostrar = [
                    "estacion",
                    "fuente",
                    "fecha",
                    "hora",
                    "calidad_global",
                ]
                contaminantes = ["CO", "O3", "NO2", "NOX", "NO", "PM10", "PM2.5", "SO2"]

                for cont in contaminantes:
                    if cont in df_resultados.columns:
                        columnas_mostrar.append(cont)

                df_display = df_resultados[columnas_mostrar].copy()

                # Aplicar formato condicional
                def highlight_calidad(val):
                    if val == "Buena":
                        return "background-color: #d4edda; color: #155724"
                    elif val == "Regular":
                        return "background-color: #fff3cd; color: #856404"
                    elif val == "Mala":
                        return "background-color: #f8d7da; color: #721c24"
                    return ""

                st.dataframe(
                    df_display.style.applymap(
                        highlight_calidad, subset=["calidad_global"]
                    ),
                    use_container_width=True,
                    height=400,
                )

                # Botón de descarga
                csv = df_display.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="📥 Descargar datos CSV",
                    data=csv,
                    file_name=f'calidad_aire_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv',
                    mime="text/csv",
                )

            with tab4:
                st.markdown("### 📈 Análisis Gráfico")

                # Gráfico de barras: Calidad por estación
                fig_calidad = px.histogram(
                    df_resultados,
                    x="estacion",
                    color="calidad_global",
                    title="Distribución de Calidad del Aire por Estación",
                    color_discrete_map={
                        "Buena": "green",
                        "Regular": "orange",
                        "Mala": "red",
                    },
                    barmode="group",
                )
                fig_calidad.update_layout(xaxis_tickangle=-45, height=500)
                st.plotly_chart(fig_calidad, use_container_width=True)

                # Gráfico de contaminantes
                st.markdown("#### Niveles de Contaminantes")
                contaminante_sel = st.selectbox(
                    "Selecciona un contaminante:",
                    ["CO", "O3", "NO2", "NOX", "NO", "PM10", "PM2.5", "SO2"],
                )

                if contaminante_sel in df_resultados.columns:
                    df_cont = df_resultados[
                        ["estacion", "fuente", contaminante_sel, "calidad_global"]
                    ].dropna()

                    fig_cont = px.bar(
                        df_cont,
                        x="estacion",
                        y=contaminante_sel,
                        color="calidad_global",
                        title=f"Niveles de {contaminante_sel} por Estación",
                        color_discrete_map={
                            "Buena": "green",
                            "Regular": "orange",
                            "Mala": "red",
                        },
                        facet_col="fuente",
                    )
                    fig_cont.update_layout(xaxis_tickangle=-45, height=500)
                    st.plotly_chart(fig_cont, use_container_width=True)

                # Comparación SINAICA vs OpenAQ
                if fuente_seleccionada == "Ambas":
                    st.markdown("#### Comparación SINAICA vs OpenAQ")

                    df_comp = (
                        df_resultados.groupby(["estacion", "fuente"])["calidad_global"]
                        .first()
                        .unstack(fill_value="Sin datos")
                    )

                    fig_comp = go.Figure()

                    if "SINAICA" in df_comp.columns:
                        calidad_map = {
                            "Buena": 1,
                            "Regular": 2,
                            "Mala": 3,
                            "Sin datos": 0,
                        }
                        sinaica_values = df_comp["SINAICA"].map(calidad_map)
                        fig_comp.add_trace(
                            go.Bar(name="SINAICA", x=df_comp.index, y=sinaica_values)
                        )

                    if "OPENAQ" in df_comp.columns:
                        openaq_values = df_comp["OPENAQ"].map(calidad_map)
                        fig_comp.add_trace(
                            go.Bar(name="OpenAQ", x=df_comp.index, y=openaq_values)
                        )

                    fig_comp.update_layout(
                        title="Comparación de Fuentes de Datos",
                        xaxis_tickangle=-45,
                        yaxis=dict(
                            tickmode="array",
                            tickvals=[0, 1, 2, 3],
                            ticktext=["Sin datos", "Buena", "Regular", "Mala"],
                        ),
                        height=500,
                        barmode="group",
                    )
                    st.plotly_chart(fig_comp, use_container_width=True)

        else:
            st.warning(
                "⚠️ No se pudieron obtener datos de ninguna estación. Por favor, intenta nuevamente."
            )

else:
    # Pantalla inicial
    st.info(
        "👆 Presiona el botón **'OBTENER DATOS ACTUALIZADOS'** para comenzar el monitoreo"
    )

    # Mostrar mapa sin datos
    st.markdown("### 🗺️ Ubicación de las Estaciones")
    mapa_inicial = crear_mapa({})
    st_folium(mapa_inicial, width=1400, height=600)

    # Información adicional
    st.markdown("---")
    st.markdown("### ℹ️ Información")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(
            """
        **📡 Fuentes de Datos:**
        - **SINAICA**: Sistema Nacional de Información de la Calidad del Aire
        - **OpenAQ**: Plataforma global de datos de calidad del aire
        
        **🎯 Parámetros Monitoreados:**
        - CO (Monóxido de Carbono)
        - O3 (Ozono)
        - NO2 (Dióxido de Nitrógeno)
        - NOx (Óxidos de Nitrógeno)
        - NO (Monóxido de Nitrógeno)
        - PM10 y PM2.5 (Material Particulado)
        - SO2 (Dióxido de Azufre)
        """
        )

    with col2:
        st.markdown(
            """
        **📊 Clasificación de Calidad:**
        - 🟢 **Buena**: Calidad satisfactoria, sin riesgo
        - 🟡 **Regular**: Aceptable, grupos sensibles deben tomar precauciones
        - 🔴 **Mala**: Puede afectar a grupos sensibles
        
        **🏢 Estaciones Monitoreadas:**
        """
        )
        for est in list(ESTACIONES.keys())[:6]:
            st.markdown(f"- {est}")
        if len(ESTACIONES) > 6:
            st.markdown(f"- ... y {len(ESTACIONES) - 6} más")

# Footer
st.markdown("---")
st.markdown(
    """
<div style='text-align: center; color: #666; padding: 20px;'>
    <p>💻 Desarrollado para el monitoreo de calidad del aire en CDMX</p>
    <p>🔄 Los datos se actualizan en tiempo real desde las fuentes oficiales</p>
</div>
""",
    unsafe_allow_html=True,
)
