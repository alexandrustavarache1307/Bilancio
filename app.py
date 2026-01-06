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
    for cat in lista_categorie_disponibili:
        if cat.lower() in desc_lower:
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
                corpo = msg.text or msg.html
                corpo_clean = " ".join(corpo.split())
                
                if "widiba" not in corpo_clean.lower() and "widiba" not in soggetto.lower():
                     continue

                importo = 0.0
                tipo = "Uscita"
                descrizione = "Transazione Generica"
                categoria_suggerita = "DA VERIFICARE"
                trovato = False

                regex_uscite = [
                    r'(?:pagamento|prelievo|addebito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:presso|per|a favore di|su)\s+(.*?)(?:\.|$)',
                    r'ha\s+prelevato\s+([\d.,]+)\s+euro.*?(?:presso)\s+(.*?)(?:\.|$)'
                ]
                regex_entrate = [
                    r'(?:accredito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:per|da|a favore di)\s+(.*?)(?:\.|$)',
                    r'hai\s+ricevuto\s+([\d.,]+)\s+euro\s+da\s+(.*?)(?:\.|$)'
                ]

                # PROVA USCITE
                for rx in regex_uscite:
                    match = re.search(rx, corpo_clean, re.IGNORECASE)
                    if match:
                        importo_str = match.group(1)
                        desc_temp = match.group(2).strip() if len(match.groups()) > 1 else soggetto
                        importo = float(importo_str.replace('.', '').replace(',', '.'))
                        tipo = "Uscita"
                        descrizione = desc_temp
                        categoria_suggerita = trova_categoria_smart(descrizione, CAT_USCITE)
                        trovato = True
                        break 

                # PROVA ENTRATE
                if not trovato:
                    for rx in regex_entrate:
                        match = re.search(rx, corpo_clean, re.IGNORECASE)
                        if match:
                            importo_str = match.group(1)
                            desc_temp = match.group(2).strip() if len(match.groups()) > 1 else soggetto
                            importo = float(importo_str.replace('.', '').replace(',', '.'))
                            tipo = "Entrata"
                            descrizione = desc_temp
                            categoria_suggerita = trova_categoria_smart(descrizione, CAT_ENTRATE)
                            trovato = True
                            break

                if trovato:
                    firma = f"{msg.date.strftime('%Y%m%d')}-{importo}-{descrizione[:10]}"
                    nuove_transazioni.append({
                        "Data": msg.date.strftime("%Y-%m-%d"),
                        "Descrizione": descrizione,
                        "Importo": importo,
                        "Tipo": tipo,
                        "Categoria": categoria_suggerita,
                        "Mese": msg.date.strftime('%b-%y'),
                        "Firma": firma
                    })
                else:
                    mail_scartate.append({
                        "Data": msg.date.strftime("%Y-%m-%d"),
                        "Descrizione": soggetto,
                        "Importo": 0.0,
                        "Tipo": "Uscita",
                        "Categoria": "DA VERIFICARE",
                        "Mese": msg.date.strftime('%b-%y'),
                        "Firma": f"ERR-{msg.date.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
                    })
                    
    except Exception as e:
        st.error(f"Errore lettura mail: {e}")
        
    return pd.DataFrame(nuove_transazioni), pd.DataFrame(mail_scartate)

# --- FUNZIONE GENERAZIONE PIVOT ---
def crea_prospetto(df, index_col, columns_col, agg_func='sum'):
    if df.empty: return pd.DataFrame()
    pivot = df.pivot_table(index=index_col, columns=columns_col, values='Importo', aggfunc=agg_func, fill_value=0)
    pivot["TOTALE"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("TOTALE", ascending=False)
    pivot.loc["TOTALE"] = pivot.sum()
    return pivot

# --- INIZIO UI ---
st.title("☁️ Piano Pluriennale 2026")

# Carica DB
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

# TABS
tab1, tab2, tab3 = st.tabs(["📥 NUOVE & IMPORTA", "📊 REPORT & PROSPETTI", "🗂 STORICO & MODIFICA"])

# ==========================================
# TAB 1: IMPORTAZIONE
# ==========================================
with tab1:
    col_search, col_actions = st.columns([1, 4])
    with col_search:
        if st.button("🔎 Cerca Nuove Mail", type="primary"):
            with st.spinner("Analisi mail in corso..."):
                df_mail, df_scartate = scarica_spese_da_gmail()
                st.session_state["df_mail_found"] = df_mail
                st.session_state["df_mail_discarded"] = df_scartate
    
    st.divider()

    # Recupero Scartate
    if not st.session_state["df_mail_discarded"].empty:
        with st.expander(f"⚠️ Ci sono {len(st.session_state['df_mail_discarded'])} mail Widiba non riconosciute", expanded=True):
            st.dataframe(st.session_state["df_mail_discarded"][["Data", "Descrizione"]], use_container_width=True, hide_index=True)
            if st.button("⬇️ Recupera e Correggi Manualmente"):
                recuperate = st.session_state["df_mail_discarded"].copy()
                st.session_state["df_manual_entry"] = pd.concat([st.session_state["df_manual_entry"], recuperate], ignore_index=True)
                st.session_state["df_mail_discarded"] = pd.DataFrame()
                st.rerun()

    # Visualizzazione e Editor
    df_view_entrate = pd.DataFrame()
    df_view_uscite = pd.DataFrame()
    
    if not st.session_state["df_mail_found"].empty:
        df_clean = st.session_state["df_mail_found"]
        if "Firma" in df_cloud.columns:
            firme_esistenti = df_cloud["Firma"].astype(str).tolist()
            df_clean = df_clean[~df_clean["Firma"].astype(str).isin(firme_esistenti)]
        
        df_clean["Data"] = pd.to_datetime(df_clean["Data"], errors='coerce')
        df_view_entrate = df_clean[df_clean["Tipo"] == "Entrata"]
        df_view_uscite = df_clean[df_clean["Tipo"] == "Uscita"]

    st.markdown("##### 💰 Nuove Entrate")
    if not df_view_entrate.empty:
        edited_entrate = st.data_editor(
            df_view_entrate,
            column_config={"Categoria": st.column_config.SelectboxColumn(options=CAT_ENTRATE, required=True), "Tipo": st.column_config.Column(disabled=True), "Data": st.column_config.DateColumn(format="YYYY-MM-DD", required=True), "Importo": st.column_config.NumberColumn(format="%.2f €")},
            key="edit_entrate_mail", use_container_width=True
        )
    else:
        st.info("Nessuna nuova entrata.")

    st.markdown("##### 💸 Nuove Uscite")
    if not df_view_uscite.empty:
        edited_uscite = st.data_editor(
            df_view_uscite,
            column_config={"Categoria": st.column_config.SelectboxColumn(options=CAT_USCITE, required=True), "Tipo": st.column_config.Column(disabled=True), "Data": st.column_config.DateColumn(format="YYYY-MM-DD", required=True), "Importo": st.column_config.NumberColumn(format="%.2f €")},
            key="edit_uscite_mail", use_container_width=True
        )
    else:
        st.info("Nessuna nuova uscita.")

    st.markdown("---")
    st.markdown("##### ✍️ Manuale / Correzioni")
    if st.session_state["df_manual_entry"].empty:
        st.session_state["df_manual_entry"] = pd.DataFrame([{"Data": datetime.now(), "Descrizione": "Spesa contanti", "Importo": 0.0, "Tipo": "Uscita", "Categoria": "DA VERIFICARE", "Firma": "", "Mese": ""}])
    
    st.session_state["df_manual_entry"]["Data"] = pd.to_datetime(st.session_state["df_manual_entry"]["Data"], errors='coerce')
    edited_manual = st.data_editor(
        st.session_state["df_manual_entry"],
        num_rows="dynamic",
        column_config={"Categoria": st.column_config.SelectboxColumn(options=sorted(CAT_USCITE + CAT_ENTRATE), required=True), "Tipo": st.column_config.SelectboxColumn(options=["Uscita", "Entrata"], required=True), "Data": st.column_config.DateColumn(format="YYYY-MM-DD", required=True), "Importo": st.column_config.NumberColumn(format="%.2f €")},
        key="edit_manual", use_container_width=True
    )

    if st.button("💾 SALVA TUTTO NEL CLOUD", type="primary", use_container_width=True):
        da_salvare = []
        if not df_view_entrate.empty: da_salvare.append(edited_entrate)
        if not df_view_uscite.empty: da_salvare.append(edited_uscite)
        if not edited_manual.empty:
            valid_manual = edited_manual[edited_manual["Importo"] > 0]
            if not valid_manual.empty:
                valid_manual["Data"] = pd.to_datetime(valid_manual["Data"])
                valid_manual["Mese"] = valid_manual["Data"].dt.strftime('%b-%y')
                valid_manual["Firma"] = valid_manual.apply(lambda x: x["Firma"] if x["Firma"] and str(x["Firma"]) != "nan" else f"MAN-{x['Data'].strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}", axis=1)
                da_salvare.append(valid_manual)
        
        if da_salvare:
            df_new_total = pd.concat(da_salvare, ignore_index=True)
            df_final = pd.concat([df_cloud, df_new_total], ignore_index=True)
            df_final["Data"] = pd.to_datetime(df_final["Data"])
            df_final = df_final.sort_values("Data", ascending=False)
            df_final["Data"] = df_final["Data"].dt.strftime("%Y-%m-%d")
            conn.update(worksheet="DB_TRANSAZIONI", data=df_final)
            st.session_state["df_mail_found"] = pd.DataFrame()
            st.session_state["df_manual_entry"] = pd.DataFrame()
            st.session_state["df_mail_discarded"] = pd.DataFrame()
            st.balloons()
            st.success("✅ Tutto salvato correttamente!")
            st.rerun()

# ==========================================
# TAB 2: REPORT & PROSPETTI
# ==========================================
with tab2:
    if df_cloud.empty:
        st.warning("Nessun dato nel database.")
    else:
        df_analysis = df_cloud.copy()
        df_analysis["Anno"] = df_analysis["Data"].dt.year
        df_analysis["MeseNum"] = df_analysis["Data"].dt.month
        map_mesi = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu', 7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}

        # Filtri
        col_f1, col_f2 = st.columns(2)
        with col_f1: anno_sel = st.selectbox("📅 Anno", sorted(df_analysis["Anno"].unique(), reverse=True) if not df_analysis.empty else [2026])
        with col_f2: mese_sel_nome = st.selectbox("📆 Mese Analisi", list(map_mesi.values()), index=datetime.now().month-1)
        
        mese_sel_num = [k for k, v in map_mesi.items() if v == mese_sel_nome][0]
        df_anno = df_analysis[df_analysis["Anno"] == anno_sel]
        df_mese = df_anno[df_anno["MeseNum"] == mese_sel_num]

        # KPI Globali Anno
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Entrate Totali (Anno)", f"{df_anno[df_anno['Tipo']=='Entrata']['Importo'].sum():,.2f} €")
        k2.metric("Uscite Totali (Anno)", f"{df_anno[df_anno['Tipo']=='Uscita']['Importo'].sum():,.2f} €")
        k3.metric("Saldo Netto", f"{(df_anno[df_anno['Tipo']=='Entrata']['Importo'].sum() - df_anno[df_anno['Tipo']=='Uscita']['Importo'].sum()):,.2f} €")

        # LOGICA BUDGET
        df_budget = get_budget_data()
        reale_u_mese = df_mese[df_mese["Tipo"] == "Uscita"].groupby("Categoria")["Importo"].sum().reset_index()
        
        if not df_budget.empty and mese_sel_nome in df_budget.columns:
            bud_u = df_budget[df_budget["Tipo"] == "Uscita"][["Categoria", mese_sel_nome]].rename(columns={mese_sel_nome: "Budget"})
            
            # Logica SALDO INIZIALE: escluso se non è Gennaio
            if mese_sel_nome != "Gen":
                bud_u = bud_u[bud_u["Categoria"] != "SALDO INIZIALE"]
                reale_u_mese = reale_u_mese[reale_u_mese["Categoria"] != "SALDO INIZIALE"]

            comp = pd.merge(bud_u, reale_u_mese, on="Categoria", how="outer").fillna(0).rename(columns={"Importo": "Reale"})
            comp["Delta"] = comp["Budget"] - comp["Reale"]
            
            k4.metric("In Tasca (Mese)", f"{(comp['Budget'].sum() - comp['Reale'].sum()):,.2f} €")
            st.divider()
            
            # Alerts
            sfori = comp[comp["Delta"] < 0]
            for _, r in sfori.iterrows():
                st.error(f"⚠️ **SFORAMENTO {r['Categoria']}**: Budget superato di {abs(r['Delta']):.2f} €!")

            # Grafico e Tabella
            g_left, g_right = st.columns([1, 1.2])
            with g_left:
                if not reale_u_mese.empty:
                    fig = px.pie(reale_u_mese, values='Importo', names='Categoria', title=f"Spese {mese_sel_nome}", hole=.4)
                    st.plotly_chart(fig, use_container_width=True)
            with g_right:
                st.markdown("### 📊 Budget vs Reale")
                st.dataframe(
                    comp.style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
                    .map(lambda x: 'color:red; font-weight:bold' if x < 0 else 'color:green', subset=['Delta']), 
                    use_container_width=True, 
                    hide_index=True
                )

        st.divider()
        st.subheader("📅 Riepiloghi Storici")
        sub_t1, sub_t2, sub_t3, sub_t4 = st.tabs(["Mensile", "Trimestrale", "Semestrale", "Annuale"])

        with sub_t1:
            st.markdown("**USCITE MENSILI**")
            pivot_u = crea_prospetto(df_anno[df_anno["Tipo"] == "Uscita"], "Categoria", "MeseNum").rename(columns=map_mesi)
            st.dataframe(pivot_u.style.format("{:.2f} €").background_gradient(cmap="Reds", axis=None), use_container_width=True)

        with sub_t2:
            df_anno["Trimestre"] = "Q" + df_anno["Data"].dt.quarter.astype(str)
            st.dataframe(crea_prospetto(df_anno[df_anno["Tipo"] == "Uscita"], "Categoria", "Trimestre").style.format("{:.2f} €"), use_container_width=True)

        with sub_t3:
            df_anno["Semestre"] = df_anno["MeseNum"].apply(lambda x: "H1" if x <= 6 else "H2")
            st.dataframe(crea_prospetto(df_anno[df_anno["Tipo"] == "Uscita"], "Categoria", "Semestre").style.format("{:.2f} €"), use_container_width=True)

        with sub_t4:
            col_a1, col_a2 = st.columns(2)
            with col_a1:
                st.markdown("**Top 10 Spese Anno**")
                st.bar_chart(df_anno[df_anno["Tipo"]=="Uscita"].groupby("Categoria")["Importo"].sum().sort_values(ascending=False).head(10), color="#ff4b4b", horizontal=True)
            with col_a2:
                st.markdown("**Andamento Mensile**")
                trend = df_anno.groupby(["MeseNum", "Tipo"])["Importo"].sum().unstack().fillna(0).rename(index=map_mesi)
                st.bar_chart(trend, color=["#2ecc71", "#ff4b4b"])

# ==========================================
# TAB 3: MODIFICA STORICO
# ==========================================
with tab3:
    st.markdown("### 🗂 Modifica Database Completo")
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    
    df_storico_edited = st.data_editor(
        df_cloud,
        num_rows="dynamic",
        use_container_width=True,
        height=600,
        column_config={
            "Categoria": st.column_config.SelectboxColumn(options=sorted(list(set(CAT_USCITE + CAT_ENTRATE))), required=True),
            "Tipo": st.column_config.SelectboxColumn(options=["Entrata", "Uscita"], required=True),
            "Data": st.column_config.DateColumn(format="YYYY-MM-DD", required=True),
            "Importo": st.column_config.NumberColumn(format="%.2f €")
        },
        key="editor_storico"
    )
    
    if st.button("🔄 AGGIORNA STORICO", type="primary"):
        df_to_update = df_storico_edited.copy()
        df_to_update["Data"] = pd.to_datetime(df_to_update["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=df_to_update)
        st.success("Database aggiornato correttamente!")
        st.rerun()
