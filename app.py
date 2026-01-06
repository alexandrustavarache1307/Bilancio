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

# --- IL CERVELLO: MAPPA PAROLE CHIAVE ---
MAPPA_KEYWORD = {
    "lidl": "USCITE/PRANZO",
    "conad": "USCITE/PRANZO",
    "esselunga": "USCITE/PRANZO",
    "coop": "USCITE/PRANZO",
    "carrefour": "USCITE/PRANZO",
    "eurospin": "USCITE/PRANZO",
    "aldi": "USCITE/PRANZO",
    "ristorante": "USCITE/PRANZO",
    "pizzeria": "USCITE/PRANZO",
    "sushi": "USCITE/PRANZO",
    "mcdonald": "USCITE/PRANZO",
    "burger king": "USCITE/PRANZO",
    "bar ": "USCITE/PRANZO",
    "caffè": "USCITE/PRANZO",
    "eni": "CARBURANTE",
    "q8": "CARBURANTE",
    "esso": "CARBURANTE",
    "benzina": "CARBURANTE",
    "autostrade": "VARIE",
    "telepass": "VARIE",
    "amazon": "VARIE",
    "paypal": "PERSONALE",
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
        cat_entrate = df_cat.iloc[3:23, 0].dropna().unique().tolist()
        cat_uscite = df_cat.iloc[2:23, 1].dropna().unique().tolist()
        cat_entrate = sorted([str(x).strip() for x in cat_entrate if str(x).strip() != ""])
        cat_uscite = sorted([str(x).strip() for x in cat_uscite if str(x).strip() != ""])
        if "DA VERIFICARE" not in cat_entrate: cat_entrate.insert(0, "DA VERIFICARE")
        if "DA VERIFICARE" not in cat_uscite: cat_uscite.insert(0, "DA VERIFICARE")
        return cat_entrate, cat_uscite
    except Exception as e:
        return ["DA VERIFICARE"], ["DA VERIFICARE"]

CAT_ENTRATE, CAT_USCITE = get_categories()

# --- CARICAMENTO BUDGET ---
@st.cache_data(ttl=60)
def get_budget_data():
    try:
        df_bud = conn.read(worksheet="DB_BUDGET", usecols=list(range(14))).fillna(0)
        df_bud.columns = [str(c).strip() for c in df_bud.columns]
        return df_bud
    except:
        return pd.DataFrame()

# --- CERVELLO SMART ---
def trova_categoria_smart(descrizione, lista_categorie_disponibili):
    desc_lower = descrizione.lower()
    for parola_chiave, target_categoria in MAPPA_KEYWORD.items():
        if parola_chiave in desc_lower:
            for cat in lista_categorie_disponibili:
                if target_categoria.lower() in cat.lower():
                    return cat
    return "DA VERIFICARE"

# --- LETTURA MAIL ---
def scarica_spese_da_gmail():
    nuove_transazioni = []
    mail_scartate = []
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
                trovato = False
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
                        desc = match.group(2).strip()
                        nuowe = {"Data": msg.date.strftime("%Y-%m-%d"), "Descrizione": desc, "Importo": importo, "Tipo": "Uscita", "Categoria": trova_categoria_smart(desc, CAT_USCITE), "Mese": msg.date.strftime('%b-%y'), "Firma": f"{msg.date.strftime('%Y%m%d')}-{importo}-{desc[:10]}"}
                        nuove_transazioni.append(nuowe)
                        trovato = True; break
                if not trovato:
                    for rx in regex_entrate:
                        match = re.search(rx, corpo_clean, re.IGNORECASE)
                        if match:
                            importo = float(match.group(1).replace('.', '').replace(',', '.'))
                            desc = match.group(2).strip()
                            nuowe = {"Data": msg.date.strftime("%Y-%m-%d"), "Descrizione": desc, "Importo": importo, "Tipo": "Entrata", "Categoria": trova_categoria_smart(desc, CAT_ENTRATE), "Mese": msg.date.strftime('%b-%y'), "Firma": f"{msg.date.strftime('%Y%m%d')}-{importo}-{desc[:10]}"}
                            nuove_transazioni.append(nuowe)
                            trovato = True; break
                if not trovato:
                    mail_scartate.append({"Data": msg.date.strftime("%Y-%m-%d"), "Descrizione": soggetto, "Importo": 0.0, "Tipo": "Uscita", "Categoria": "DA VERIFICARE", "Mese": msg.date.strftime('%b-%y'), "Firma": f"ERR-{uuid.uuid4().hex[:6]}"})
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

# --- CARICAMENTO DB ---
try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    df_cloud["Importo"] = pd.to_numeric(df_cloud["Importo"], errors='coerce').fillna(0)
except:
    df_cloud = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

# Session State
if "df_mail_found" not in st.session_state: st.session_state["df_mail_found"] = pd.DataFrame()
if "df_mail_discarded" not in st.session_state: st.session_state["df_mail_discarded"] = pd.DataFrame()
if "df_manual_entry" not in st.session_state: st.session_state["df_manual_entry"] = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

tab1, tab2, tab3 = st.tabs(["📥 NUOVE & IMPORTA", "📊 REPORT & PROSPETTI", "🗂 STORICO & MODIFICA"])

# --- TAB 1 ---
with tab1:
    if st.button("🔎 Cerca Nuove Mail", type="primary"):
        with st.spinner("Analisi mail in corso..."):
            df_m, df_s = scarica_spese_da_gmail()
            st.session_state["df_mail_found"], st.session_state["df_mail_discarded"] = df_m, df_s
    st.divider()
    if not st.session_state["df_mail_discarded"].empty:
        with st.expander("⚠️ Mail non riconosciute", expanded=True):
            st.dataframe(st.session_state["df_mail_discarded"], use_container_width=True, hide_index=True)
            if st.button("⬇️ Recupera Manualmente"):
                st.session_state["df_manual_entry"] = pd.concat([st.session_state["df_manual_entry"], st.session_state["df_mail_discarded"]], ignore_index=True)
                st.session_state["df_mail_discarded"] = pd.DataFrame(); st.rerun()

    df_mail = st.session_state["df_mail_found"]
    if not df_mail.empty:
        firme_esistenti = df_cloud["Firma"].astype(str).tolist() if "Firma" in df_cloud.columns else []
        df_clean = df_mail[~df_mail["Firma"].astype(str).isin(firme_esistenti)]
        st.subheader("💰 Nuove Transazioni")
        df_mail_edit = st.data_editor(df_clean, column_config={"Categoria": st.column_config.SelectboxColumn(options=sorted(CAT_USCITE + CAT_ENTRATE))}, use_container_width=True)

    st.subheader("✍️ Inserimento Manuale")
    if st.session_state["df_manual_entry"].empty:
        st.session_state["df_manual_entry"] = pd.DataFrame([{"Data": datetime.now(), "Descrizione": "", "Importo": 0.0, "Tipo": "Uscita", "Categoria": "DA VERIFICARE"}])
    df_man = st.data_editor(st.session_state["df_manual_entry"], num_rows="dynamic", use_container_width=True)

    if st.button("💾 SALVA NEL CLOUD", type="primary"):
        da_salvare = [df_cloud]
        if not df_mail.empty: da_salvare.append(df_mail_edit)
        valid_man = df_man[df_man["Importo"] > 0].copy()
        if not valid_man.empty:
            valid_man["Data"] = pd.to_datetime(valid_man["Data"])
            valid_man["Mese"] = valid_man["Data"].dt.strftime('%b-%y')
            valid_man["Firma"] = [f"MAN-{uuid.uuid4().hex[:6]}" for _ in range(len(valid_man))]
            da_salvare.append(valid_man)
        final_df = pd.concat(da_salvare, ignore_index=True)
        final_df["Data"] = pd.to_datetime(final_df["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=final_df)
        st.session_state["df_mail_found"] = pd.DataFrame(); st.session_state["df_manual_entry"] = pd.DataFrame()
        st.balloons(); st.rerun()

# --- TAB 2: REPORT & BUDGET ---
with tab2:
    if df_cloud.empty:
        st.warning("Nessun dato nel database.")
    else:
        df_analysis = df_cloud.copy()
        df_analysis["Anno"] = df_analysis["Data"].dt.year
        df_analysis["MeseNum"] = df_analysis["Data"].dt.month
        map_mesi = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu', 7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}

        col_f1, col_f2 = st.columns(2)
        with col_f1: anno_sel = st.selectbox("📅 Anno", sorted(df_analysis["Anno"].unique(), reverse=True) if not df_analysis.empty else [2026])
        with col_f2: mese_sel_nome = st.selectbox("📆 Mese Analisi", list(map_mesi.values()), index=datetime.now().month-1)
        
        mese_sel_num = [k for k, v in map_mesi.items() if v == mese_sel_nome][0]
        df_anno = df_analysis[df_analysis["Anno"] == anno_sel]
        df_mese = df_anno[df_anno["MeseNum"] == mese_sel_num]

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Entrate (Anno)", f"{df_anno[df_anno['Tipo']=='Entrata']['Importo'].sum():,.2f} €")
        k2.metric("Uscite (Anno)", f"{df_anno[df_anno['Tipo']=='Uscita']['Importo'].sum():,.2f} €")
        k3.metric("Saldo Netto", f"{(df_anno[df_anno['Tipo']=='Entrata']['Importo'].sum() - df_anno[df_anno['Tipo']=='Uscita']['Importo'].sum()):,.2f} €")

        # LOGICA BUDGET
        df_budget = get_budget_data()
        reale_u_mese = df_mese[df_mese["Tipo"] == "Uscita"].groupby("Categoria")["Importo"].sum().reset_index()
        
        if not df_budget.empty and mese_sel_nome in df_budget.columns:
            bud_u = df_budget[df_budget["Tipo"] == "Uscita"][["Categoria", mese_sel_nome]].rename(columns={mese_sel_nome: "Budget"})
            if mese_sel_nome != "Gen":
                bud_u = bud_u[bud_u["Categoria"] != "SALDO INIZIALE"]
                reale_u_mese = reale_u_mese[reale_u_mese["Categoria"] != "SALDO INIZIALE"]

            comp = pd.merge(bud_u, reale_u_mese, on="Categoria", how="outer").fillna(0).rename(columns={"Importo": "Reale"})
            comp["Delta"] = comp["Budget"] - comp["Reale"]
            k4.metric("In Tasca (Mese)", f"{(comp['Budget'].sum() - comp['Reale'].sum()):,.2f} €", delta=f"{(comp['Budget'].sum() - comp['Reale'].sum()):,.2f} €")
            
            st.divider()
            sfori = comp[comp["Delta"] < 0]
            for _, r in sfori.iterrows(): st.error(f"⚠️ **SFORAMENTO {r['Categoria']}**: Budget superato di {abs(r['Delta']):.2f} €!")

            g_l, g_r = st.columns([1, 1.2])
            with g_l:
                if not reale_u_mese.empty:
                    fig = px.pie(reale_u_mese, values='Importo', names='Categoria', title=f"Spese {mese_sel_nome}", hole=.4)
                    st.plotly_chart(fig, use_container_width=True)
            with g_r:
                st.dataframe(comp.style.format(precision=2, decimal=",", thousands=".", subset=["Budget", "Reale", "Delta"]).map(lambda x: 'color:red; font-weight:bold' if x < 0 else 'color:green', subset=['Delta']), use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("📅 Prospetti Storici")
        sub_t1, sub_t2, sub_t3, sub_t4 = st.tabs(["Mensile", "Trimestrale", "Semestrale", "Annuale"])
        with sub_t1:
            st.markdown("**USCITE**")
            st.dataframe(crea_prospetto(df_anno[df_anno["Tipo"]=="Uscita"], "Categoria", "MeseNum").rename(columns=map_mesi).style.format("{:.2f} €"), use_container_width=True)

# --- TAB 3 ---
with tab3:
    db_edit = st.data_editor(df_cloud, num_rows="dynamic", use_container_width=True, height=500, column_config={"Categoria": st.column_config.SelectboxColumn(options=sorted(CAT_USCITE + CAT_ENTRATE))})
    if st.button("🔄 AGGIORNA STORICO"):
        df_save = db_edit.copy(); df_save["Data"] = pd.to_datetime(df_save["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=df_save); st.success("DB aggiornato!"); st.rerun()
