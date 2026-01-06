import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox
import re
import uuid
import plotly.express as px

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Piano Pluriennale", layout="wide", page_icon="☁️")

# --- 🧠 MAPPA KEYWORD (Mantenuta come prima) ---
MAPPA_KEYWORD = {
    "lidl": "USCITE/PRANZO", "conad": "USCITE/PRANZO", "esselunga": "USCITE/PRANZO",
    "coop": "USCITE/PRANZO", "carrefour": "USCITE/PRANZO", "eurospin": "USCITE/PRANZO",
    "eni": "CARBURANTE", "q8": "CARBURANTE", "esso": "CARBURANTE", "amazon": "VARIE",
}

# --- CONNESSIONE ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("Errore connessione. Controlla i secrets!")
    st.stop()

# --- CARICAMENTO DATI ---
@st.cache_data(ttl=60)
def get_categories():
    try:
        df_cat = conn.read(worksheet="2026", usecols=[0, 2], header=None)
        cat_entrate = sorted([str(x).strip() for x in df_cat.iloc[3:23, 0].dropna().unique() if str(x).strip() != ""])
        cat_uscite = sorted([str(x).strip() for x in df_cat.iloc[2:23, 1].dropna().unique() if str(x).strip() != ""])
        if "DA VERIFICARE" not in cat_entrate: cat_entrate.insert(0, "DA VERIFICARE")
        if "DA VERIFICARE" not in cat_uscite: cat_uscite.insert(0, "DA VERIFICARE")
        return cat_entrate, cat_uscite
    except: return ["DA VERIFICARE"], ["DA VERIFICARE"]

@st.cache_data(ttl=60)
def get_budget_data():
    try:
        return conn.read(worksheet="DB_BUDGET", usecols=list(range(14))).fillna(0)
    except: return pd.DataFrame()

CAT_ENTRATE, CAT_USCITE = get_categories()

# --- CARICAMENTO DB TRANSAZIONI ---
try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    df_cloud["Importo"] = pd.to_numeric(df_cloud["Importo"], errors='coerce').fillna(0)
except:
    df_cloud = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

# --- INTERFACCIA TABS ---
tab1, tab2, tab3 = st.tabs(["📥 NUOVE & IMPORTA", "📊 REPORT & BUDGET", "🗂 STORICO & MODIFICA"])

# --- TAB 2: REPORT & BUDGET (CON LOGICA SALDO E ALERT) ---
with tab2:
    df_budget = get_budget_data()
    map_mesi = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu', 7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}
    
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        anno_sel = st.selectbox("Anno:", sorted(df_cloud["Data"].dt.year.unique(), reverse=True) if not df_cloud.empty else [2026])
    with col_s2:
        mese_sel = st.selectbox("Mese:", list(map_mesi.values()), index=datetime.now().month-1)
    
    mese_num = [k for k,v in map_mesi.items() if v==mese_sel][0]

    # Filtraggio dati del mese
    df_m = df_cloud[(df_cloud["Data"].dt.month == mese_num) & (df_cloud["Data"].dt.year == anno_sel)]
    
    # Calcolo Consuntivo (Escludendo il saldo iniziale dai calcoli di spesa)
    reale_u = df_m[df_m["Tipo"]=="Uscita"].groupby("Categoria")["Importo"].sum().reset_index()
    
    # Preparazione Budget (Rimuoviamo SALDO INIZIALE dal confronto spese se non è Gennaio)
    bud_u = df_budget[df_budget["Tipo"]=="Uscita"][["Categoria", mese_sel]].rename(columns={mese_sel: "Budget"})
    
    if mese_sel != "Gen":
        bud_u = bud_u[bud_u["Categoria"] != "SALDO INIZIALE"]
        reale_u = reale_u[reale_u["Categoria"] != "SALDO INIZIALE"]

    # Merge e Delta
    comp = pd.merge(bud_u, reale_u, on="Categoria", how="outer").fillna(0).rename(columns={"Importo":"Reale"})
    comp["Delta"] = comp["Budget"] - comp["Reale"]

    # --- KPI: QUANTO RESTA IN TASCA ---
    budget_tot_mese = comp["Budget"].sum()
    speso_tot_mese = comp["Reale"].sum()
    rimanente = budget_tot_mese - speso_tot_mese
    
    st.divider()
    k1, k2, k3 = st.columns(3)
    k1.metric("Budget Uscite", f"{budget_tot_mese:,.2f} €")
    k2.metric("Speso Reale", f"{speso_tot_mese:,.2f} €")
    k3.metric("Ancora da spendere", f"{rimanente:,.2f} €", delta=f"{rimanente:,.2f} €", delta_color="normal")
    st.divider()

    # Alerts sforamento
    sfori = comp[comp["Delta"] < 0]
    for _, r in sfori.iterrows():
        st.error(f"⚠️ **SFORAMENTO {r['Categoria']}**: Hai superato il preventivo di {abs(r['Delta']):.2f} €!")

    # Grafici e Tabella
    c_left, c_right = st.columns([1, 1.2])
    with c_left:
        if not reale_u.empty:
            st.plotly_chart(px.pie(reale_u, values='Importo', names='Categoria', title="Distribuzione Spese", hole=.4), use_container_width=True)
    
    with c_right:
        st.markdown("### Dettaglio vs Budget")
        # Fix per l'errore: usiamo .map e precisione numerica
        st.dataframe(
            comp.style.format(precision=2, decimal=",", thousands=".", subset=["Budget", "Reale", "Delta"])
            .map(lambda x: 'color:red; font-weight:bold' if x < 0 else 'color:green', subset=['Delta']),
            use_container_width=True, hide_index=True
        )

# (Il resto delle Tab rimane come nell'ultima versione completa che ti ho dato)
