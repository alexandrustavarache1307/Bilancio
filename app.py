import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox
import re
import uuid
import plotly.express as px

# ==============================================================================
# --- CONFIGURAZIONE PAGINA ---
# ==============================================================================
st.set_page_config(page_title="Piano Pluriennale", layout="wide", page_icon="☁️")

# --- 🧠 IL CERVELLO: MAPPA PAROLE CHIAVE ---
MAPPA_KEYWORD = {
    "lidl": "USCITE/PRANZO", "conad": "USCITE/PRANZO", "esselunga": "USCITE/PRANZO",
    "coop": "USCITE/PRANZO", "carrefour": "USCITE/PRANZO", "eurospin": "USCITE/PRANZO",
    "aldi": "USCITE/PRANZO", "ristorante": "USCITE/PRANZO", "pizzeria": "USCITE/PRANZO",
    "sushi": "USCITE/PRANZO", "mcdonald": "USCITE/PRANZO", "burger king": "USCITE/PRANZO",
    "bar ": "USCITE/PRANZO", "caffè": "USCITE/PRANZO", "eni": "CARBURANTE",
    "q8": "CARBURANTE", "esso": "CARBURANTE", "benzina": "CARBURANTE",
    "autostrade": "VARIE", "telepass": "VARIE", "amazon": "VARIE", "paypal": "PERSONALE",
}

# ==============================================================================
# --- CONNESSIONE E CARICAMENTO DATI ---
# ==============================================================================
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("Errore connessione. Controlla i secrets!")
    st.stop()

@st.cache_data(ttl=60)
def get_categories():
    try:
        df_cat = conn.read(worksheet="2026", usecols=[0, 2], header=None)
        cat_entrate = df_cat.iloc[3:23, 0].dropna().unique().tolist()
        cat_uscite = df_cat.iloc[2:23, 1].dropna().unique().tolist()
        cat_entrate = sorted([str(x).strip() for x in cat_entrate if str(x).strip() != ""])
        cat_uscite = sorted([str(x).strip() for x in cat_uscite if str(x).strip() != ""])
        if "DA VERIFICARE" not in cat_entrate: cat_entrate.insert(0, "DA VERIFICARE")
        if "DA VERIFICARE" not in cat_uscite: cat_uscite.insert(0, "DA VERIFICARE")
        return cat_entrate, cat_uscite
    except:
        return ["DA VERIFICARE"], ["DA VERIFICARE"]

@st.cache_data(ttl=60)
def get_budget_data():
    try:
        df_bud = conn.read(worksheet="DB_BUDGET", usecols=list(range(14))).fillna(0)
        # Pulizia nomi colonne per evitare KeyError (es. "Gen " -> "Gen")
        df_bud.columns = [str(c).strip() for c in df_bud.columns]
        return df_bud
    except:
        return pd.DataFrame()

CAT_ENTRATE, CAT_USCITE = get_categories()

# ==============================================================================
# --- LOGICA DI PARSING E UTILITY ---
# ==============================================================================
def trova_categoria_smart(descrizione, lista_categorie_disponibili):
    desc_lower = descrizione.lower()
    for parola_chiave, target_categoria in MAPPA_KEYWORD.items():
        if parola_chiave in desc_lower:
            for cat in lista_categorie_disponibili:
                if target_categoria.lower() in cat.lower():
                    return cat
    return "DA VERIFICARE"

def scarica_spese_da_gmail():
    nuove_transazioni, mail_scartate = [], []
    if "email" not in st.secrets:
        st.error("Mancano i secrets!")
        return pd.DataFrame(), pd.DataFrame()

    user = st.secrets["email"]["user"]
    pwd = st.secrets["email"]["password"]
    server = st.secrets["email"]["imap_server"]
    
    try:
        with MailBox(server).login(user, pwd) as mailbox:
            for msg in mailbox.fetch(limit=50, reverse=True): 
                soggetto = msg.subject
                corpo_clean = " ".join((msg.text or msg.html).split())
                
                if "widiba" not in corpo_clean.lower() and "widiba" not in soggetto.lower():
                     continue

                importo, tipo, descrizione, trovato = 0.0, "Uscita", "Transazione Generica", False
                regex_uscite = [
                    r'(?:pagamento|prelievo|addebito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:presso|per|a favore di|su)\s+(.*?)(?:\.|$)',
                    r'ha\s+prelevato\s+([\d.,]+)\s+euro.*?(?:presso)\s+(.*?)(?:\.|$)'
                ]
                regex_entrate = [
                    r'(?:accredito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:per|da|a favore di)\s+(.*?)(?:\.|$)',
                    r'hai\s+ricevuto\s+([\d.,]+)\s+euro\s+da\s+(.*?)(?:\.|$)'
                ]

                for rx in regex_uscite:
                    match = re.search(rx, corpo_clean, re.IGNORECASE)
                    if match:
                        importo = float(match.group(1).replace('.', '').replace(',', '.'))
                        descrizione, tipo = match.group(2).strip(), "Uscita"
                        trovato = True; break 
                
                if not trovato:
                    for rx in regex_entrate:
                        match = re.search(rx, corpo_clean, re.IGNORECASE)
                        if match:
                            importo = float(match.group(1).replace('.', '').replace(',', '.'))
                            descrizione, tipo = match.group(2).strip(), "Entrata"
                            trovato = True; break

                if trovato:
                    firma = f"{msg.date.strftime('%Y%m%d')}-{importo}-{descrizione[:10]}"
                    nuove_transazioni.append({
                        "Data": msg.date.strftime("%Y-%m-%d"),
                        "Descrizione": descrizione, "Importo": importo,
                        "Tipo": tipo, "Categoria": trova_categoria_smart(descrizione, CAT_USCITE if tipo=="Uscita" else CAT_ENTRATE),
                        "Mese": msg.date.strftime('%b-%y'), "Firma": firma
                    })
                else:
                    mail_scartate.append({
                        "Data": msg.date.strftime("%Y-%m-%d"),
                        "Descrizione": soggetto, "Importo": 0.0,
                        "Tipo": "Uscita", "Categoria": "DA VERIFICARE",
                        "Mese": msg.date.strftime('%b-%y'),
                        "Firma": f"ERR-{uuid.uuid4().hex[:6]}"
                    })
    except Exception as e:
        st.error(f"Errore lettura mail: {e}")
    return pd.DataFrame(nuove_transazioni), pd.DataFrame(mail_scartate)

def crea_prospetto(df, index_col, columns_col):
    if df.empty: return pd.DataFrame()
    pivot = df.pivot_table(index=index_col, columns=columns_col, values='Importo', aggfunc='sum', fill_value=0)
    pivot["TOTALE"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("TOTALE", ascending=False)
    pivot.loc["TOTALE"] = pivot.sum()
    return pivot

# ==============================================================================
# --- LOGICA UI ---
# ==============================================================================
# Carica DB Transazioni
try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    df_cloud["Importo"] = pd.to_numeric(df_cloud["Importo"], errors='coerce').fillna(0)
except:
    df_cloud = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

# Session State Init
if "df_mail_found" not in st.session_state: st.session_state["df_mail_found"] = pd.DataFrame()
if "df_mail_discarded" not in st.session_state: st.session_state["df_mail_discarded"] = pd.DataFrame()
if "df_manual_entry" not in st.session_state: st.session_state["df_manual_entry"] = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

tab1, tab2, tab3 = st.tabs(["📥 NUOVE & IMPORTA", "📊 REPORT & BUDGET", "🗂 STORICO & MODIFICA"])

# --- TAB 1: IMPORTAZIONE ---
with tab1:
    if st.button("🔎 Cerca Nuove Mail Widiba", type="primary"):
        with st.spinner("Aspiratutto in azione..."):
            df_m, df_s = scarica_spese_da_gmail()
            st.session_state["df_mail_found"], st.session_state["df_mail_discarded"] = df_m, df_s
    
    st.divider()

    if not st.session_state["df_mail_discarded"].empty:
        with st.expander(f"⚠️ Ci sono {len(st.session_state['df_mail_discarded'])} mail non riconosciute", expanded=True):
            st.dataframe(st.session_state["df_mail_discarded"][["Data", "Descrizione"]], use_container_width=True, hide_index=True)
            if st.button("⬇️ Recupera e Correggi Manualmente"):
                st.session_state["df_manual_entry"] = pd.concat([st.session_state["df_manual_entry"], st.session_state["df_mail_discarded"]], ignore_index=True)
                st.session_state["df_mail_discarded"] = pd.DataFrame(); st.rerun()

    df_mail = st.session_state["df_mail_found"]
    if not df_mail.empty:
        firme_esistenti = df_cloud["Firma"].astype(str).tolist() if "Firma" in df_cloud.columns else []
        df_clean = df_mail[~df_mail["Firma"].astype(str).isin(firme_esistenti)]
        
        st.subheader("💰 Nuove Transazioni Identificate")
        df_mail_edit = st.data_editor(df_clean, column_config={
            "Categoria": st.column_config.SelectboxColumn(options=sorted(CAT_USCITE + CAT_ENTRATE)),
            "Data": st.column_config.DateColumn(format="YYYY-MM-DD")
        }, use_container_width=True, key="ed_mail_auto")

    st.subheader("✍️ Inserimento Manuale / Contanti")
    if st.session_state["df_manual_entry"].empty:
        st.session_state["df_manual_entry"] = pd.DataFrame([{"Data": datetime.now(), "Descrizione": "", "Importo": 0.0, "Tipo": "Uscita", "Categoria": "DA VERIFICARE"}])
    
    st.session_state["df_manual_entry"]["Data"] = pd.to_datetime(st.session_state["df_manual_entry"]["Data"], errors='coerce')
    df_man_edit = st.data_editor(st.session_state["df_manual_entry"], num_rows="dynamic", use_container_width=True, key="ed_manual")

    if st.button("💾 SALVA TUTTO NEL DATABASE", type="primary", use_container_width=True):
        da_salvare = [df_cloud]
        if not df_mail.empty: da_salvare.append(df_mail_edit)
        df_valid_man = df_man_edit[df_man_edit["Importo"] > 0].copy()
        if not df_valid_man.empty:
            df_valid_man["Data"] = pd.to_datetime(df_valid_man["Data"])
            df_valid_man["Mese"] = df_valid_man["Data"].dt.strftime('%b-%y')
            df_valid_man["Firma"] = [f"MAN-{uuid.uuid4().hex[:6]}" for _ in range(len(df_valid_man))]
            da_salvare.append(df_valid_man)
        
        final_df = pd.concat(da_salvare, ignore_index=True)
        final_df["Data"] = pd.to_datetime(final_df["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=final_df)
        st.session_state["df_mail_found"] = pd.DataFrame(); st.session_state["df_manual_entry"] = pd.DataFrame()
        st.balloons(); st.success("Salvataggio completato!"); st.rerun()

# --- TAB 2: REPORT & BUDGET ---
with tab2:
    df_budget = get_budget_data()
    map_mesi = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu', 7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}
    
    col_f1, col_f2 = st.columns(2)
    with col_f1: anno_sel = st.selectbox("Seleziona Anno:", sorted(df_cloud["Data"].dt.year.unique(), reverse=True) if not df_cloud.empty else [2026])
    with col_f2: mese_sel = st.selectbox("Seleziona Mese:", list(map_mesi.values()), index=datetime.now().month-1)
    mese_num = [k for k,v in map_mesi.items() if v == mese_sel][0]

    df_m = df_cloud[(df_cloud["Data"].dt.month == mese_num) & (df_cloud["Data"].dt.year == anno_sel)]
    reale_u = df_m[df_m["Tipo"] == "Uscita"].groupby("Categoria")["Importo"].sum().reset_index()
    
    if not df_budget.empty and mese_sel in df_budget.columns:
        bud_u = df_budget[df_budget["Tipo"] == "Uscita"][["Categoria", mese_sel]].rename(columns={mese_sel: "Budget"})
        
        # Logica Saldo Iniziale (Solo Gennaio)
        if mese_sel != "Gen":
            bud_u = bud_u[bud_u["Categoria"] != "SALDO INIZIALE"]
            reale_u = reale_u[reale_u["Categoria"] != "SALDO INIZIALE"]

        comp = pd.merge(bud_u, reale_u, on="Categoria", how="outer").fillna(0).rename(columns={"Importo": "Reale"})
        comp["Delta"] = comp["Budget"] - comp["Reale"]

        st.divider()
        k1, k2, k3 = st.columns(3)
        b_tot, r_tot = comp["Budget"].sum(), comp["Reale"].sum()
        k1.metric("Budget Uscite", f"{b_tot:,.2f} €")
        k2.metric("Spese Reali", f"{r_tot:,.2f} €")
        k3.metric("Ancora in Tasca", f"{(b_tot - r_tot):,.2f} €", delta=f"{(b_tot - r_tot):,.2f} €")
        st.divider()

        sfori = comp[comp["Delta"] < 0]
        for _, r in sfori.iterrows():
            st.error(f"⚠️ **SFORAMENTO {r['Categoria']}**: Hai superato il budget di {abs(r['Delta']):.2f} €!")

        g_left, g_right = st.columns([1, 1.2])
        with g_left:
            if not reale_u.empty:
                fig = px.pie(reale_u, values='Importo', names='Categoria', title=f"Ripartizione Spese {mese_sel}", hole=.4)
                st.plotly_chart(fig, use_container_width=True)
        with g_right:
            st.dataframe(comp.style.format(precision=2, decimal=",", thousands=".", subset=["Budget", "Reale", "Delta"]).map(lambda x: 'color:red; font-weight:bold' if x < 0 else 'color:green', subset=['Delta']), use_container_width=True, hide_index=True)
    else:
        st.warning(f"Dati Budget non trovati per la colonna '{mese_sel}' in DB_BUDGET.")

    with st.expander("📊 Prospetti Storici Mensili"):
        df_analysis = df_cloud[df_cloud["Data"].dt.year == anno_sel].copy()
        df_analysis["MeseNum"] = df_analysis["Data"].dt.month
        st.dataframe(crea_prospetto(df_analysis[df_analysis["Tipo"]=="Uscita"], "Categoria", "MeseNum").rename(columns=map_mesi).style.format("{:.2f} €"), use_container_width=True)

# --- TAB 3: STORICO ---
with tab3:
    db_edit = st.data_editor(df_cloud, num_rows="dynamic", use_container_width=True, height=600, column_config={
        "Categoria": st.column_config.SelectboxColumn(options=sorted(CAT_USCITE + CAT_ENTRATE)),
        "Data": st.column_config.DateColumn(format="YYYY-MM-DD")
    })
    if st.button("🔄 APPLICA MODIFICHE AL DATABASE"):
        df_save = db_edit.copy()
        df_save["Data"] = pd.to_datetime(df_save["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=df_save)
        st.success("Database aggiornato correttamente!"); st.rerun()
