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

# --- 🧠 MAPPA PAROLE CHIAVE ---
MAPPA_KEYWORD = {
    "lidl": "USCITE/PRANZO", "conad": "USCITE/PRANZO", "esselunga": "USCITE/PRANZO",
    "coop": "USCITE/PRANZO", "carrefour": "USCITE/PRANZO", "eurospin": "USCITE/PRANZO",
    "aldi": "USCITE/PRANZO", "ristorante": "USCITE/PRANZO", "pizzeria": "USCITE/PRANZO",
    "sushi": "USCITE/PRANZO", "mcdonald": "USCITE/PRANZO", "burger king": "USCITE/PRANZO",
    "bar ": "USCITE/PRANZO", "caffè": "USCITE/PRANZO", "eni": "CARBURANTE",
    "q8": "CARBURANTE", "esso": "CARBURANTE", "benzina": "CARBURANTE",
    "autostrade": "VARIE", "telepass": "VARIE", "amazon": "VARIE", "paypal": "PERSONALE",
}

# --- CONNESSIONE ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("Errore connessione. Controlla i secrets!")
    st.stop()

# --- CARICAMENTO CATEGORIE ---
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

CAT_ENTRATE, CAT_USCITE = get_categories()

# --- CARICAMENTO BUDGET (4 COLONNE: Mese, Categoria, Tipo, Importo) ---
@st.cache_data(ttl=0) 
def get_budget_data():
    try:
        # Legge le prime 4 colonne
        df_bud = conn.read(worksheet="DB_BUDGET", usecols=list(range(4))).fillna(0)
        
        # Assegna i nomi standard se ci sono almeno 4 colonne
        if len(df_bud.columns) >= 4:
            df_bud.columns = ["Mese", "Categoria", "Tipo", "Importo"]
        
        # Pulizia Testi
        for col in ["Mese", "Categoria", "Tipo"]:
            df_bud[col] = df_bud[col].astype(str).str.strip()
            
        # Pulizia Numeri
        df_bud["Importo"] = df_bud["Importo"].astype(str).str.replace('€','').str.replace('.','').str.replace(',','.')
        df_bud["Importo"] = pd.to_numeric(df_bud["Importo"], errors='coerce').fillna(0)
        
        return df_bud
    except: return pd.DataFrame()

# --- UTILS ---
def trova_categoria_smart(descrizione, lista_categorie_disponibili):
    desc_lower = descrizione.lower()
    for parola_chiave, target_categoria in MAPPA_KEYWORD.items():
        if parola_chiave in desc_lower:
            for cat in lista_categorie_disponibili:
                if target_categoria.lower() in cat.lower(): return cat
    for cat in lista_categorie_disponibili:
        if cat.lower() in desc_lower: return cat
    return "DA VERIFICARE"

def scarica_spese_da_gmail():
    nuove_transazioni = []
    mail_scartate = [] 
    if "email" not in st.secrets: return pd.DataFrame(), pd.DataFrame()
    user, pwd, server = st.secrets["email"]["user"], st.secrets["email"]["password"], st.secrets["email"]["imap_server"]
    try:
        with MailBox(server).login(user, pwd) as mailbox:
            for msg in mailbox.fetch(limit=50, reverse=True): 
                soggetto = msg.subject
                corpo = " ".join((msg.text or msg.html).split())
                if "widiba" not in corpo.lower() and "widiba" not in soggetto.lower(): continue
                
                importo, tipo, descrizione, trovato = 0.0, "Uscita", "Transazione Generica", False
                regex_uscite = [r'(?:pagamento|prelievo|addebito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:presso|per|a favore di|su)\s+(.*?)(?:\.|$)', r'ha\s+prelevato\s+([\d.,]+)\s+euro.*?(?:presso)\s+(.*?)(?:\.|$)']
                regex_entrate = [r'(?:accredito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:per|da|a favore di)\s+(.*?)(?:\.|$)', r'hai\s+ricevuto\s+([\d.,]+)\s+euro\s+da\s+(.*?)(?:\.|$)']

                for rx in regex_uscite:
                    match = re.search(rx, corpo, re.IGNORECASE)
                    if match:
                        importo = float(match.group(1).replace('.', '').replace(',', '.'))
                        descrizione = match.group(2).strip()
                        tipo = "Uscita"
                        trovato = True; break 
                if not trovato:
                    for rx in regex_entrate:
                        match = re.search(rx, corpo, re.IGNORECASE)
                        if match:
                            importo = float(match.group(1).replace('.', '').replace(',', '.'))
                            descrizione = match.group(2).strip()
                            tipo = "Entrata"
                            trovato = True; break

                if trovato:
                    cat_sugg = trova_categoria_smart(descrizione, CAT_USCITE if tipo=="Uscita" else CAT_ENTRATE)
                    nuove_transazioni.append({"Data": msg.date.strftime("%Y-%m-%d"), "Descrizione": descrizione, "Importo": importo, "Tipo": tipo, "Categoria": cat_sugg, "Mese": msg.date.strftime('%b-%y'), "Firma": f"{msg.date.strftime('%Y%m%d')}-{importo}-{descrizione[:10]}"})
                else:
                    mail_scartate.append({"Data": msg.date.strftime("%Y-%m-%d"), "Descrizione": soggetto, "Importo": 0.0, "Tipo": "Uscita", "Categoria": "DA VERIFICARE", "Mese": msg.date.strftime('%b-%y'), "Firma": f"ERR-{uuid.uuid4().hex[:6]}"})
    except Exception as e: st.error(f"Errore mail: {e}")
    return pd.DataFrame(nuove_transazioni), pd.DataFrame(mail_scartate)

def crea_prospetto(df, index_col, columns_col, agg_func='sum'):
    if df.empty: return pd.DataFrame()
    pivot = df.pivot_table(index=index_col, columns=columns_col, values='Importo', aggfunc=agg_func, fill_value=0)
    pivot["TOTALE"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("TOTALE", ascending=False)
    pivot.loc["TOTALE"] = pivot.sum()
    return pivot

def style_negative_positive(val): return f'color: {"red" if val < 0 else "green"}; font-weight: bold'
def style_variance_uscite(val): return f'color: {"green" if val >= 0 else "red"}; font-weight: bold'
def style_variance_entrate(val): return f'color: {"green" if val >= 0 else "red"}; font-weight: bold'

# --- MAIN ---
st.title("☁️ Piano Pluriennale 2026")

try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    df_cloud["Importo"] = pd.to_numeric(df_cloud["Importo"], errors='coerce').fillna(0)
    if "Categoria" in df_cloud.columns: df_cloud["Categoria"] = df_cloud["Categoria"].astype(str).str.strip()
except: df_cloud = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

if "df_mail_found" not in st.session_state: st.session_state["df_mail_found"] = pd.DataFrame()
if "df_mail_discarded" not in st.session_state: st.session_state["df_mail_discarded"] = pd.DataFrame()
if "df_manual_entry" not in st.session_state: st.session_state["df_manual_entry"] = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

tab1, tab2, tab3 = st.tabs(["📥 NUOVE & IMPORTA", "📊 REPORT & BUDGET", "🗂 STORICO & MODIFICA"])

with tab1:
    col_search, col_actions = st.columns([1, 4])
    with col_search:
        if st.button("🔎 Cerca Nuove Mail", type="primary"):
            with st.spinner("Analisi mail..."):
                df_mail, df_scartate = scarica_spese_da_gmail()
                st.session_state["df_mail_found"] = df_mail
                st.session_state["df_mail_discarded"] = df_scartate
    st.divider()
    if not st.session_state["df_mail_discarded"].empty:
        with st.expander(f"⚠️ {len(st.session_state['df_mail_discarded'])} Mail Scartate", expanded=True):
            st.dataframe(st.session_state["df_mail_discarded"])
            if st.button("⬇️ Recupera Manualmente"):
                st.session_state["df_manual_entry"] = pd.concat([st.session_state["df_manual_entry"], st.session_state["df_mail_discarded"]], ignore_index=True)
                st.session_state["df_mail_discarded"] = pd.DataFrame(); st.rerun()
    df_mail = st.session_state["df_mail_found"]
    if not df_mail.empty:
        firme = df_cloud["Firma"].astype(str).tolist() if "Firma" in df_cloud.columns else []
        df_clean = df_mail[~df_mail["Firma"].astype(str).isin(firme)]
        st.subheader("💰 Nuove Transazioni"); st.data_editor(df_clean, column_config={"Categoria": st.column_config.SelectboxColumn(options=CAT_ENTRATE)})
    
    st.markdown("##### ✍️ Manuale")
    if st.session_state["df_manual_entry"].empty: st.session_state["df_manual_entry"] = pd.DataFrame([{"Data": datetime.now(), "Descrizione": "", "Importo": 0.0, "Tipo": "Uscita", "Categoria": "DA VERIFICARE"}])
    edited_manual = st.data_editor(st.session_state["df_manual_entry"], num_rows="dynamic", column_config={"Categoria": st.column_config.SelectboxColumn(options=sorted(CAT_USCITE + CAT_ENTRATE))})
    
    if st.button("💾 SALVA TUTTO", type="primary", use_container_width=True):
        da_salvare = []
        if not df_mail.empty: da_salvare.append(df_mail_edit) # type: ignore
        if not edited_manual.empty:
            valid = edited_manual[edited_manual["Importo"] > 0].copy()
            if not valid.empty:
                valid["Data"] = pd.to_datetime(valid["Data"]); valid["Mese"] = valid["Data"].dt.strftime('%b-%y'); valid["Firma"] = [f"MAN-{uuid.uuid4().hex[:6]}" for _ in range(len(valid))]
                da_salvare.append(valid)
        if da_salvare:
            final = pd.concat([df_cloud] + da_salvare, ignore_index=True)
            final["Data"] = pd.to_datetime(final["Data"]).dt.strftime("%Y-%m-%d")
            conn.update(worksheet="DB_TRANSAZIONI", data=final)
            st.session_state["df_mail_found"] = pd.DataFrame(); st.session_state["df_manual_entry"] = pd.DataFrame(); st.balloons(); st.rerun()

# --- TAB 2 ---
with tab2:
    df_budget = get_budget_data()
    
    # --------------------------------------------------------
    # 🕵️‍♂️ BOX DIAGNOSTICO - FONDAMENTALE
    # --------------------------------------------------------
    with st.expander("🕵️‍♂️ DEBUG BUDGET (Clicca qui per capire perché è vuoto)", expanded=True):
        if df_budget.empty:
            st.error("Il file DB_BUDGET sembra vuoto o illeggibile.")
        else:
            st.write("1. Colonne trovate:", df_budget.columns.tolist())
            st.write("2. Mesi trovati nel file (Colonna A):", df_budget["Mese"].unique().tolist() if "Mese" in df_budget.columns else "Colonna 'Mese' non trovata")
            st.dataframe(df_budget.head())

    df_analysis = df_cloud.copy()
    df_analysis["Anno"] = df_analysis["Data"].dt.year
    df_analysis["MeseNum"] = df_analysis["Data"].dt.month
    map_mesi = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu', 7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}
    
    c1, c2 = st.columns(2)
    with c1: anno_sel = st.selectbox("📅 Anno", sorted(df_analysis["Anno"].unique(), reverse=True) if not df_analysis.empty else [2026])
    with c2: mese_sel_nome = st.selectbox("📆 Mese", list(map_mesi.values()), index=datetime.now().month-1)
    mese_sel_num = [k for k, v in map_mesi.items() if v == mese_sel_nome][0]
    
    df_anno = df_analysis[df_analysis["Anno"] == anno_sel]
    k1, k2, k3 = st.columns(3)
    k1.metric("Entrate", f"{df_anno[df_anno['Tipo']=='Entrata']['Importo'].sum():,.2f} €")
    k2.metric("Uscite", f"{df_anno[df_anno['Tipo']=='Uscita']['Importo'].sum():,.2f} €")
    k3.metric("Saldo", f"{(df_anno[df_anno['Tipo']=='Entrata']['Importo'].sum()-df_anno[df_anno['Tipo']=='Uscita']['Importo'].sum()):,.2f} €")
    st.divider()

    vista = st.radio("Vista", ["📊 Confronto Mensile", "📈 Trend Annuale"], horizontal=True)

    if vista == "📊 Confronto Mensile":
        st.subheader(f"Analisi Budget: {mese_sel_nome} {anno_sel}")
        
        # 1. Recupera Reale
        df_mese = df_anno[df_anno["MeseNum"] == mese_sel_num]
        consuntivo = df_mese.groupby(["Categoria", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Reale"})
        
        # 2. Recupera Budget (FILTRANDO LE RIGHE)
        preventivo = pd.DataFrame()
        if not df_budget.empty and "Mese" in df_budget.columns:
            # Qui sta la magia: Filtra le righe dove Mese == mese_sel_nome
            preventivo = df_budget[df_budget["Mese"] == mese_sel_nome].copy()
            preventivo = preventivo.rename(columns={"Importo": "Budget"})
            
            if mese_sel_nome != "Gen":
                preventivo = preventivo[preventivo["Categoria"] != "SALDO INIZIALE"]
                consuntivo = consuntivo[consuntivo["Categoria"] != "SALDO INIZIALE"]
        
        # 3. Merge Left Join sul Budget
        if not preventivo.empty:
            df_merge = pd.merge(preventivo, consuntivo, on=["Categoria", "Tipo"], how="left").fillna(0)
        else:
            df_merge = consuntivo.copy()
            df_merge["Budget"] = 0.0
            st.warning(f"Nessuna riga trovata nel budget per il mese: '{mese_sel_nome}'")

        df_merge["Delta"] = df_merge["Budget"] - df_merge["Reale"]
        
        # Uscite
        st.markdown("### 🔴 Uscite")
        out = df_merge[df_merge["Tipo"]=="Uscita"].copy()
        if not out.empty:
            c_g, c_t = st.columns([1, 1.5])
            with c_g: 
                if out["Reale"].sum()>0: st.plotly_chart(px.pie(out, values='Reale', names='Categoria', hole=0.4, title="Speso"), use_container_width=True)
            with c_t:
                st.dataframe(out[["Categoria", "Budget", "Reale", "Delta"]].sort_values("Budget", ascending=False).style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"]).map(style_variance_uscite, subset=["Delta"]), use_container_width=True)
        
        # Entrate
        st.markdown("### 🟢 Entrate")
        inc = df_merge[df_merge["Tipo"]=="Entrata"].copy()
        if not inc.empty:
            inc["Delta"] = inc["Reale"] - inc["Budget"]
            st.dataframe(inc[["Categoria", "Budget", "Reale", "Delta"]].style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"]).map(style_variance_entrate, subset=["Delta"]), use_container_width=True)

    elif vista == "📈 Trend Annuale":
        pivot = df_anno[df_anno["Tipo"]=="Uscita"].pivot_table(index="Categoria", columns="MeseNum", values="Importo", aggfunc="sum", fill_value=0).rename(columns=map_mesi)
        st.dataframe(pivot.style.format("{:.2f} €").background_gradient(cmap="Reds", axis=None), use_container_width=True)

with tab3:
    st.markdown("### Modifica Storico"); ed = st.data_editor(df_cloud, num_rows="dynamic")
    if st.button("AGGIORNA DB"):
        s = ed.copy(); s["Data"] = pd.to_datetime(s["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=s); st.success("Fatto!"); st.rerun()
