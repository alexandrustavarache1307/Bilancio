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

# --- CONNESSIONE ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("Errore connessione Google Sheets. Controlla i secrets!")
    st.stop()

# --- CARICAMENTO CATEGORIE E BUDGET ---
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

# --- LOGICA SMART CATEGORIA ---
def trova_categoria_smart(descrizione, lista_categorie_disponibili):
    desc_lower = descrizione.lower()
    for parola_chiave, target_categoria in MAPPA_KEYWORD.items():
        if parola_chiave in desc_lower:
            for cat in lista_categorie_disponibili:
                if target_categoria.lower() in cat.lower(): return cat
    return "DA VERIFICARE"

# --- LETTURA MAIL WIDIBA ---
def scarica_spese_da_gmail():
    nuove_transazioni, mail_scartate = [], []
    if "email" not in st.secrets: return pd.DataFrame(), pd.DataFrame()
    
    try:
        with MailBox(st.secrets["email"]["imap_server"]).login(st.secrets["email"]["user"], st.secrets["email"]["password"]) as mailbox:
            for msg in mailbox.fetch(limit=50, reverse=True):
                soggetto = msg.subject
                corpo_clean = " ".join((msg.text or msg.html).split())
                if "widiba" not in corpo_clean.lower() and "widiba" not in soggetto.lower(): continue
                
                regex_uscite = [r'(?:pagamento|prelievo|addebito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:presso|per|a favore di|su)\s+(.*?)(?:\.|$)', r'ha\s+prelevato\s+([\d.,]+)\s+euro.*?(?:presso)\s+(.*?)(?:\.|$)']
                regex_entrate = [r'(?:accredito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:per|da|a favore di)\s+(.*?)(?:\.|$)', r'hai\s+ricevuto\s+([\d.,]+)\s+euro\s+da\s+(.*?)(?:\.|$)']

                trovato = False
                for rx in regex_uscite:
                    m = re.search(rx, corpo_clean, re.IGNORECASE)
                    if m:
                        importo = float(m.group(1).replace('.', '').replace(',', '.'))
                        desc = m.group(2).strip()
                        nuove_transazioni.append({"Data": msg.date.strftime("%Y-%m-%d"), "Descrizione": desc, "Importo": importo, "Tipo": "Uscita", "Categoria": trova_categoria_smart(desc, CAT_USCITE), "Mese": msg.date.strftime('%b-%y'), "Firma": f"{msg.date.strftime('%Y%m%d')}-{importo}-{desc[:5]}"})
                        trovato = True; break
                
                if not trovato:
                    for rx in regex_entrate:
                        m = re.search(rx, corpo_clean, re.IGNORECASE)
                        if m:
                            importo = float(m.group(1).replace('.', '').replace(',', '.'))
                            desc = m.group(2).strip()
                            nuove_transazioni.append({"Data": msg.date.strftime("%Y-%m-%d"), "Descrizione": desc, "Importo": importo, "Tipo": "Entrata", "Categoria": trova_categoria_smart(desc, CAT_ENTRATE), "Mese": msg.date.strftime('%b-%y'), "Firma": f"{msg.date.strftime('%Y%m%d')}-{importo}-{desc[:5]}"})
                            trovato = True; break
                
                if not trovato:
                    mail_scartate.append({"Data": msg.date.strftime("%Y-%m-%d"), "Descrizione": soggetto, "Importo": 0.0, "Tipo": "Uscita", "Categoria": "DA VERIFICARE", "Mese": msg.date.strftime('%b-%y'), "Firma": f"ERR-{uuid.uuid4().hex[:6]}"})
    except Exception as e: st.error(f"Errore Gmail: {e}")
    return pd.DataFrame(nuove_transazioni), pd.DataFrame(mail_scartate)

# --- CARICAMENTO DB ---
try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    df_cloud["Importo"] = pd.to_numeric(df_cloud["Importo"], errors='coerce').fillna(0)
except:
    df_cloud = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

# --- SESSION STATES ---
if "df_mail_found" not in st.session_state: st.session_state["df_mail_found"] = pd.DataFrame()
if "df_mail_discarded" not in st.session_state: st.session_state["df_mail_discarded"] = pd.DataFrame()
if "df_manual_entry" not in st.session_state: st.session_state["df_manual_entry"] = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

# --- INTERFACCIA ---
st.title("☁️ Piano Pluriennale 2026")
tab1, tab2, tab3 = st.tabs(["📥 NUOVE & IMPORTA", "📊 REPORT & BUDGET", "🗂 STORICO & MODIFICA"])

# --- TAB 1: IMPORTAZIONE ---
with tab1:
    col_btn, _ = st.columns([1, 4])
    if col_btn.button("🔎 Cerca Nuove Mail Widiba", type="primary"):
        with st.spinner("Analisi in corso..."):
            df_m, df_s = scarica_spese_da_gmail()
            st.session_state["df_mail_found"], st.session_state["df_mail_discarded"] = df_m, df_s

    if not st.session_state["df_mail_discarded"].empty:
        with st.expander(f"⚠️ {len(st.session_state['df_mail_discarded'])} Mail non riconosciute"):
            st.dataframe(st.session_state["df_mail_discarded"][["Data", "Descrizione"]], use_container_width=True)
            if st.button("⬇️ Sposta in Correzioni"):
                st.session_state["df_manual_entry"] = pd.concat([st.session_state["df_manual_entry"], st.session_state["df_mail_discarded"]], ignore_index=True)
                st.session_state["df_mail_discarded"] = pd.DataFrame(); st.rerun()

    df_mail = st.session_state["df_mail_found"]
    if not df_mail.empty:
        firme_esistenti = df_cloud["Firma"].astype(str).tolist() if "Firma" in df_cloud.columns else []
        df_mail = df_mail[~df_mail["Firma"].astype(str).isin(firme_esistenti)]
        
        st.subheader("💰 Nuove Transazioni Identificate")
        df_mail_edit = st.data_editor(df_mail, column_config={
            "Categoria": st.column_config.SelectboxColumn(options=sorted(CAT_USCITE + CAT_ENTRATE)),
            "Tipo": st.column_config.SelectboxColumn(options=["Uscita", "Entrata"])
        }, use_container_width=True, key="ed_mail_auto")
    
    st.subheader("✍️ Inserimento Manuale / Correzioni")
    if st.session_state["df_manual_entry"].empty:
        st.session_state["df_manual_entry"] = pd.DataFrame([{"Data": datetime.now(), "Descrizione": "", "Importo": 0.0, "Tipo": "Uscita", "Categoria": "DA VERIFICARE"}])
    df_man = st.data_editor(st.session_state["df_manual_entry"], num_rows="dynamic", use_container_width=True, key="ed_manual")

    if st.button("💾 SALVA TUTTO NEL CLOUD", type="primary", use_container_width=True):
        da_salvare = [df_cloud]
        if not st.session_state["df_mail_found"].empty: da_salvare.append(df_mail_edit)
        if not df_man.empty: da_salvare.append(df_man[df_man["Importo"] > 0])
        
        final_df = pd.concat(da_salvare, ignore_index=True)
        final_df["Data"] = pd.to_datetime(final_df["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=final_df)
        st.session_state["df_mail_found"] = pd.DataFrame()
        st.session_state["df_manual_entry"] = pd.DataFrame()
        st.balloons(); st.rerun()

# --- TAB 2: REPORT & BUDGET ---
with tab2:
    df_budget = get_budget_data()
    map_mesi = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu', 7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}
    
    c1, c2 = st.columns(2)
    anno_sel = c1.selectbox("Anno:", sorted(df_cloud["Data"].dt.year.unique(), reverse=True) if not df_cloud.empty else [2026])
    mese_sel = c2.selectbox("Mese:", list(map_mesi.values()), index=datetime.now().month-1)
    mese_num = [k for k,v in map_mesi.items() if v==mese_sel][0]

    # Dati Reali del mese
    df_m = df_cloud[(df_cloud["Data"].dt.month == mese_num) & (df_cloud["Data"].dt.year == anno_sel)]
    reale_u = df_m[df_m["Tipo"]=="Uscita"].groupby("Categoria")["Importo"].sum().reset_index()
    
    # Dati Budget (Logica Saldo Iniziale)
    bud_u = df_budget[df_budget["Tipo"]=="Uscita"][["Categoria", mese_sel]].rename(columns={mese_sel: "Budget"})
    
    # Se non è Gennaio, escludiamo il Saldo Iniziale dal calcolo uscite/budget
    if mese_sel != "Gen":
        bud_u = bud_u[bud_u["Categoria"] != "SALDO INIZIALE"]
        reale_u = reale_u[reale_u["Categoria"] != "SALDO INIZIALE"]

    comp = pd.merge(bud_u, reale_u, on="Categoria", how="outer").fillna(0).rename(columns={"Importo":"Reale"})
    comp["Delta"] = comp["Budget"] - comp["Reale"]

    # --- RIEPILOGO KPI ---
    budget_tot = comp["Budget"].sum()
    speso_tot = comp["Reale"].sum()
    rimanente = budget_tot - speso_tot
    
    st.divider()
    k1, k2, k3 = st.columns(3)
    k1.metric("Budget Uscite", f"{budget_tot:,.2f} €")
    k2.metric("Spese Reali", f"{speso_tot:,.2f} €")
    k3.metric("Ancora in Tasca", f"{rimanente:,.2f} €", delta=f"{rimanente:,.2f} €")
    st.divider()

    # Alerts sforamento
    sfori = comp[comp["Delta"] < 0]
    for _, r in sfori.iterrows():
        st.error(f"⚠️ **SFORAMENTO {r['Categoria']}**: Hai superato il budget di {abs(r['Delta']):.2f} €!")

    col_g1, col_g2 = st.columns([1, 1.2])
    with col_g1:
        if not reale_u.empty:
            st.plotly_chart(px.pie(reale_u, values='Importo', names='Categoria', title="Ripartizione Spese", hole=.4), use_container_width=True)
    with col_g2:
        st.dataframe(
            comp.style.format(precision=2, decimal=",", thousands=".", subset=["Budget", "Reale", "Delta"])
            .map(lambda x: 'color:red; font-weight:bold' if x < 0 else 'color:green', subset=['Delta']),
            use_container_width=True, hide_index=True
        )

# --- TAB 3: STORICO ---
with tab3:
    st.subheader("🗂 Database Completo Transazioni")
    edited_db = st.data_editor(df_cloud, num_rows="dynamic", use_container_width=True)
    if st.button("🔄 Aggiorna Database Storico"):
        df_update = edited_db.copy()
        df_update["Data"] = pd.to_datetime(df_update["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=df_update)
        st.success("Database aggiornato con successo!")
        st.rerun()
