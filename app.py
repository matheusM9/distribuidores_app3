# -----------------------------
# CONFIGURAÇÃO STREAMLIT
# -----------------------------
import streamlit as st

# ⚠️ Deve ser a primeira chamada Streamlit
st.set_page_config(page_title="Distribuidores", layout="wide")

# -----------------------------
# IMPORTS
# -----------------------------
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
import requests
import json
import bcrypt
import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe
from google.oauth2 import service_account
from streamlit_cookies_manager import EncryptedCookieManager
import re

# -----------------------------
# COOKIES (LOGIN PERSISTENTE)
# -----------------------------
cookies = EncryptedCookieManager(
    prefix="distribuidores_login",
    password="chave_secreta_segura_123"
)
if not cookies.ready():
    st.stop()

# -----------------------------
# GOOGLE SHEETS (via Streamlit Secrets)
# -----------------------------
SHEET_ID = "1g71GcTvRi5H4AnZu1SSoE_6PZ9ZP8KpP-YUeRrYAGJU"
SHEET_NAME = "Sheet1"

# Carrega o JSON diretamente do Streamlit Secrets
service_account_info = json.loads(st.secrets["SERVICE_ACCOUNT"]["SERVICE_ACCOUNT_JSON"])

# Corrige quebras de linha na chave privada
service_account_info["private_key"] = service_account_info["private_key"].replace("\\n", "\n")



creds = service_account.Credentials.from_service_account_info(
    service_account_info,
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
)

client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

# -----------------------------
# FUNÇÕES GOOGLE SHEETS
# -----------------------------
def ler_dados_sheets():
    df = get_as_dataframe(sheet, evaluate_formulas=True).fillna("")
    for col in ["Distribuidor", "Contato", "Estado", "Cidade", "Latitude", "Longitude"]:
        if col not in df.columns:
            df[col] = ""
    return df[["Distribuidor", "Contato", "Estado", "Cidade", "Latitude", "Longitude"]]

def salvar_dados_sheets(df):
    df = df.dropna(subset=["Distribuidor", "Contato", "Estado", "Cidade"])
    df = df[df["Distribuidor"].astype(str).str.strip() != ""]
    sheet.clear()
    set_with_dataframe(sheet, df, include_index=False, include_column_header=True)

# -----------------------------
# FUNÇÕES AUXILIARES
# -----------------------------
@st.cache_data
def carregar_estados():
    url = "https://servicodados.ibge.gov.br/api/v1/localidades/estados"
    resp = requests.get(url)
    return sorted(resp.json(), key=lambda e: e['nome'])

@st.cache_data
def carregar_cidades(uf):
    url = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"
    resp = requests.get(url)
    return sorted(resp.json(), key=lambda c: c['nome'])

@st.cache_data
def carregar_todas_cidades():
    cidades = []
    estados = carregar_estados()
    for estado in estados:
        uf = estado["sigla"]
        url = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"
        resp = requests.get(url)
        if resp.status_code == 200:
            for c in resp.json():
                cidades.append(f"{c['nome']} - {uf}")
    return sorted(cidades)

def obter_coordenadas(cidade, estado):
    geolocator = Nominatim(user_agent="distribuidores_app", timeout=5)
    try:
        location = geolocator.geocode(f"{cidade}, {estado}, Brasil")
        if location:
            return location.latitude, location.longitude
        else:
            return "", ""
    except (GeocoderTimedOut, GeocoderUnavailable):
        return "", ""

@st.cache_data
def obter_geojson_cidade(cidade, estado_sigla):
    cidades_data = carregar_cidades(estado_sigla)
    cidade_info = next((c for c in cidades_data if c["nome"] == cidade), None)
    if not cidade_info:
        return None
    geojson_url = f"https://servicodados.ibge.gov.br/api/v2/malhas/{cidade_info['id']}?formato=application/vnd.geo+json&qualidade=intermediaria"
    try:
        resp = requests.get(geojson_url, timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return None

@st.cache_data
def obter_geojson_estados():
    url = "https://servicodados.ibge.gov.br/api/v2/malhas/?formato=application/vnd.geo+json&qualidade=simplificada&incluir=estados"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            geojson = resp.json()
            for feature in geojson.get("features", []):
                feature["properties"]["style"] = {
                    "color": "#000000",
                    "weight": 3,
                    "dashArray": "0",
                    "fillOpacity": 0
                }
            return geojson
    except:
        pass
    return None

def cor_distribuidor(nome):
    h = abs(hash(nome)) % 0xAAAAAA
    h += 0x111111
    return f"#{h:06X}"

def criar_mapa(df, filtro_distribuidores=None):
    mapa = folium.Map(location=[-14.2350, -51.9253], zoom_start=5, tiles="CartoDB positron")

    for _, row in df.iterrows():
        if filtro_distribuidores and row["Distribuidor"] not in filtro_distribuidores:
            continue
        cidade = row["Cidade"]
        estado = row["Estado"]
        geojson = obter_geojson_cidade(cidade, estado)
        cor = cor_distribuidor(row["Distribuidor"])
        if geojson and "features" in geojson:
            folium.GeoJson(
                geojson,
                style_function=lambda feature, cor=cor: {
                    "fillColor": cor,
                    "color": "#666666",
                    "weight": 1.2,
                    "fillOpacity": 0.55
                },
                tooltip=f"{row['Distribuidor']} ({cidade} - {estado})"
            ).add_to(mapa)
        else:
            try:
                lat = float(row["Latitude"]) if row["Latitude"] else -14.2350
                lon = float(row["Longitude"]) if row["Longitude"] else -51.9253
                folium.Marker(
                    location=[lat, lon],
                    icon=folium.Icon(color="blue", icon="building", prefix="fa"),
                    popup=f"{row['Distribuidor']} ({cidade} - {estado})"
                ).add_to(mapa)
            except:
                continue

    geo_estados = obter_geojson_estados()
    if geo_estados:
        folium.GeoJson(
            geo_estados,
            name="Divisas Estaduais",
            style_function=lambda f: f.get("properties", {}).get("style", {
                "color": "#000000",
                "weight": 3,
                "fillOpacity": 0
            }),
            tooltip=folium.GeoJsonTooltip(fields=["nome"], aliases=["Estado:"])
        ).add_to(mapa)

    folium.LayerControl().add_to(mapa)
    return mapa

# -----------------------------
# LOGIN PERSISTENTE
# -----------------------------
USUARIOS_FILE = "usuarios.json"

def init_usuarios():
    try:
        with open(USUARIOS_FILE, "r") as f:
            usuarios = json.load(f)
            if not isinstance(usuarios, dict):
                raise ValueError("Formato inválido")
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        senha_hash = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt()).decode()
        usuarios = {"admin": {"senha": senha_hash, "nivel": "editor"}}
        with open(USUARIOS_FILE, "w") as f:
            json.dump(usuarios, f, indent=4)
    return usuarios

usuarios = init_usuarios()
usuario_cookie = cookies.get("usuario", "")
nivel_cookie = cookies.get("nivel", "")

if usuario_cookie and nivel_cookie:
    logado = True
    usuario_atual = usuario_cookie
    nivel_acesso = nivel_cookie
else:
    logado = False
    usuario_atual = None
    nivel_acesso = None

if not logado:
    st.title("🔐 Login de Acesso")
    usuario = st.text_input("Usuário")
    senha = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if usuario in usuarios and bcrypt.checkpw(senha.encode(), usuarios[usuario]["senha"].encode()):
            cookies["usuario"] = usuario
            cookies["nivel"] = usuarios[usuario]["nivel"]
            cookies.save()
            st.success(f"Bem-vindo, {usuario}!")
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos!")
    st.stop()

st.sidebar.write(f"👤 {usuario_atual} ({nivel_acesso})")
if st.sidebar.button("🚪 Sair"):
    cookies["usuario"] = ""
    cookies["nivel"] = ""
    cookies.save()
    st.rerun()

# -----------------------------
# CARREGAR DADOS
# -----------------------------
if "df" not in st.session_state:
    try:
        st.session_state.df = ler_dados_sheets()
    except:
        st.session_state.df = pd.DataFrame(columns=["Distribuidor", "Contato", "Estado", "Cidade", "Latitude", "Longitude"])

menu = ["Cadastro", "Lista / Editar / Excluir", "Mapa"]
choice = st.sidebar.radio("Navegação", menu)

# -----------------------------
# FUNÇÃO PARA VALIDAR TELEFONE
# -----------------------------
def validar_telefone(tel):
    padrao = r'^\(\d{2}\) \d{4,5}-\d{4}$'
    return re.match(padrao, tel)

# -----------------------------
# CADASTRO
# -----------------------------
if choice == "Cadastro" and nivel_cookie == "editor":
    st.subheader("Cadastrar Novo Distribuidor")
    col1, col2 = st.columns(2)
    with col1:
        estados = carregar_estados()
        siglas = [e["sigla"] for e in estados]
        estado_sel = st.selectbox("Estado", siglas)
        cidades = [c["nome"] for c in carregar_cidades(estado_sel)] if estado_sel else []
        cidades_sel = st.multiselect("Cidades", cidades)
    with col2:
        nome = st.text_input("Nome do Distribuidor")
        contato = st.text_input("Contato (formato: (XX) XXXXX-XXXX)")

    if st.button("Adicionar Distribuidor"):
        if not nome.strip() or not contato.strip() or not estado_sel or not cidades_sel:
            st.error("Preencha todos os campos!")
        elif not validar_telefone(contato.strip()):
            st.error("Contato inválido! Use o formato (XX) XXXXX-XXXX")
        elif nome in st.session_state.df["Distribuidor"].tolist():
            st.error("Distribuidor já cadastrado!")
        else:
            cidades_ocupadas = []
            for c in cidades_sel:
                if c in st.session_state.df["Cidade"].tolist():
                    dist_existente = st.session_state.df.loc[st.session_state.df["Cidade"] == c, "Distribuidor"].iloc[0]
                    cidades_ocupadas.append(f"{c} (atualmente atribuída a {dist_existente})")
            if cidades_ocupadas:
                st.error("As seguintes cidades já estão atribuídas a outros distribuidores:\n" + "\n".join(cidades_ocupadas))
            else:
                novos = []
                for c in cidades_sel:
                    lat, lon = obter_coordenadas(c, estado_sel)
                    novos.append({"Distribuidor": nome, "Contato": contato, "Estado": estado_sel, "Cidade": c, "Latitude": lat, "Longitude": lon})
                st.session_state.df = pd.concat([st.session_state.df, pd.DataFrame(novos)], ignore_index=True)
                salvar_dados_sheets(st.session_state.df)
                st.success("Distribuidor cadastrado com sucesso!")

# -----------------------------
# LISTAR / EDITAR / EXCLUIR
# -----------------------------
elif choice == "Lista / Editar / Excluir":
    st.subheader("Distribuidores Cadastrados")
    st.dataframe(st.session_state.df)

# -----------------------------
# MAPA
# -----------------------------
elif choice == "Mapa":
    st.subheader("Mapa de Distribuidores")
    mapa = criar_mapa(st.session_state.df)
    st_data = st_folium(mapa, width=1200, height=700)
