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
# GOOGLE SHEETS
# -----------------------------
SHEET_ID = "1g71GcTvRi5H4AnZu1SSoE_6PZ9ZP8KpP-YUeRrYAGJU"
SHEET_NAME = "Sheet1"
CRED_JSON = "service_account.json"

creds = service_account.Credentials.from_service_account_file(
    CRED_JSON,
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)


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
    """Carrega as divisas dos estados com destaque visual."""
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
                    novos.append([nome, contato, estado_sel, c, lat, lon])
                novo_df = pd.DataFrame(novos, columns=st.session_state.df.columns)
                st.session_state.df = pd.concat([st.session_state.df, novo_df], ignore_index=True)
                salvar_dados_sheets(st.session_state.df)
                st.success(f"✅ Distribuidor '{nome}' adicionado!")

# -----------------------------
# LISTA / EDITAR / EXCLUIR
# -----------------------------
elif choice == "Lista / Editar / Excluir":
    st.subheader("Distribuidores Cadastrados")
    st.dataframe(st.session_state.df.drop(columns=["Latitude", "Longitude"]), use_container_width=True)

    if nivel_cookie == "editor":
        with st.expander("✏️ Editar"):
            if not st.session_state.df.empty:
                dist_edit = st.selectbox("Distribuidor", st.session_state.df["Distribuidor"].unique())
                dados = st.session_state.df[st.session_state.df["Distribuidor"] == dist_edit]
                nome_edit = st.text_input("Nome", value=dist_edit)
                contato_edit = st.text_input("Contato", value=dados.iloc[0]["Contato"])
                estado_edit = st.selectbox(
                    "Estado",
                    sorted(st.session_state.df["Estado"].unique()),
                    index=sorted(st.session_state.df["Estado"].unique()).index(dados.iloc[0]["Estado"])
                )
                cidades_disponiveis = [c["nome"] for c in carregar_cidades(estado_edit)]
                cidades_novas = st.multiselect("Cidades", cidades_disponiveis, default=dados["Cidade"].tolist())

                if st.button("Salvar Alterações"):
                    if not validar_telefone(contato_edit.strip()):
                        st.error("Contato inválido! Use o formato (XX) XXXXX-XXXX")
                    else:
                        outras_linhas = st.session_state.df[st.session_state.df["Distribuidor"] != dist_edit]
                        cidades_ocupadas = []
                        for cidade in cidades_novas:
                            if cidade in outras_linhas["Cidade"].tolist():
                                dist_existente = outras_linhas.loc[outras_linhas["Cidade"] == cidade, "Distribuidor"].iloc[0]
                                cidades_ocupadas.append(f"{cidade} (atualmente atribuída a {dist_existente})")
                        if cidades_ocupadas:
                            st.error("As seguintes cidades já estão atribuídas a outros distribuidores:\n" + "\n".join(cidades_ocupadas))
                        else:
                            st.session_state.df = st.session_state.df[st.session_state.df["Distribuidor"] != dist_edit]
                            novos = []
                            for cidade in cidades_novas:
                                lat, lon = obter_coordenadas(cidade, estado_edit)
                                novos.append([nome_edit, contato_edit, estado_edit, cidade, lat, lon])
                            novo_df = pd.DataFrame(novos, columns=st.session_state.df.columns)
                            st.session_state.df = pd.concat([st.session_state.df, novo_df], ignore_index=True)
                            salvar_dados_sheets(st.session_state.df)
                            st.success("✅ Alterações salvas!")

        with st.expander("🗑️ Excluir"):
            if not st.session_state.df.empty:
                dist_del = st.selectbox("Distribuidor para excluir", st.session_state.df["Distribuidor"].unique())
                if st.button("Excluir Distribuidor"):
                    st.session_state.df = st.session_state.df[st.session_state.df["Distribuidor"] != dist_del]
                    salvar_dados_sheets(st.session_state.df)
                    st.success(f"🗑️ '{dist_del}' removido!")

# -----------------------------
# MAPA COM AUTOCOMPLETE
# -----------------------------
elif choice == "Mapa":
    st.subheader("🗺️ Mapa de Distribuidores")
    distribuidores = st.multiselect("Filtrar Distribuidores", st.session_state.df["Distribuidor"].unique())

    st.markdown("### 🔎 Buscar Cidade")
    todas_cidades = carregar_todas_cidades()
    cidade_selecionada = st.selectbox("Digite o nome da cidade e selecione:", [""] + todas_cidades)

    if cidade_selecionada:
        cidade_nome, estado_sigla = cidade_selecionada.split(" - ")
        df_cidade = st.session_state.df[
            (st.session_state.df["Cidade"].str.lower() == cidade_nome.lower()) &
            (st.session_state.df["Estado"].str.upper() == estado_sigla.upper())
        ]
        if df_cidade.empty:
            st.warning(f"❌ Nenhum distribuidor encontrado em **{cidade_nome} - {estado_sigla}**.")
        else:
            st.success(f"✅ {len(df_cidade)} distribuidor(es) encontrado(s) em **{cidade_nome} - {estado_sigla}**:")
            st.dataframe(df_cidade[["Distribuidor", "Contato", "Estado", "Cidade"]], use_container_width=True)
            mapa = criar_mapa(df_cidade)
            st_folium(mapa, width=1200, height=700)
            st.stop()

    mapa = criar_mapa(st.session_state.df, filtro_distribuidores=distribuidores if distribuidores else None)
    st_folium(mapa, width=1200, height=700)
