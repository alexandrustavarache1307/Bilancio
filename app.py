import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox
import re
import uuid
import plotly.express as px

# ==============================================================================
# 1. CONFIGURAZIONE PAGINA
# ==============================================================================
st.set_page_config(
    page_title="Piano Pluriennale", 
    layout="wide", 
    page_icon="☁️"
)

# ==============================================================================
# 2. MAPPA PAROLE CHIAVE
# ==============================================================================
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

# ==============================================================================
# 3. CONNESSIONE AI FOGLI GOOGLE
# ==============================================================================
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("Errore connessione. Controlla i secrets!")
    st.stop()

# ==============================================================================
# 4. FUNZIONI DI CARICAMENTO DATI
# ==============================================================================

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

# --- CARICAMENTO BUDGET (CORRETTO E POTENZIATO) ---
@st.cache_data(ttl=0)  # TTL=0 per aggiornamento immediato
def get_budget_data():
    try:
        df_bud = conn.read(worksheet="DB_BUDGET", usecols=list(range(14))).fillna(0)
        
        # 1. Pulisce i nomi delle colonne (es. "Gen " diventa "Gen")
        df_bud.columns = [str(c).strip() for c in df_bud.columns]
        
        # 2. Pulisce le stringhe nelle colonne Categoria e Tipo
        if "Categoria" in df_bud.columns:
            df_bud["Categoria"] = df_bud["Categoria"].astype(str).str.strip()
        if "Tipo" in df_bud.columns:
            df_bud["Tipo"] = df_bud["Tipo"].astype(str).str.strip()

        # 3. Converte le colonne dei mesi in numeri puri
        for col in df_bud.columns:
            if col not in ["Categoria", "Tipo"]:
                # Rimuove simboli valuta e converte virgola in punto
                df_bud[col] = df_bud[col].astype(str).str.replace('€','').str.replace('.','').str.replace(',','.')
                df_bud[col] = pd.to_numeric(df_bud[col], errors='coerce').fillna(0)
        
        return df_bud
    except Exception as e:
        return pd.DataFrame()

CAT_ENTRATE, CAT_USCITE = get_categories()

# ==============================================================================
# 5. LOGICHE DI ELABORAZIONE (MAIL & SMART CATEGORY)
# ==============================================================================

def trova_categoria_smart(descrizione, lista_categorie_disponibili):
    desc_lower = descrizione.lower()
    # Prima cerca le parole chiave esatte
    for parola_chiave, target_categoria in MAPPA_KEYWORD.items():
        if parola_chiave in desc_lower:
            for cat in lista_categorie_disponibili:
                if target_categoria.lower() in cat.lower():
                    return cat
    # Poi cerca corrispondenze parziali
    for cat in lista_categorie_disponibili:
        if cat.lower() in desc_lower:
            return cat
    return "DA VERIFICARE"

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

def crea_prospetto(df, index_col, columns_col, agg_func='sum'):
    if df.empty: return pd.DataFrame()
    pivot = df.pivot_table(index=index_col, columns=columns_col, values='Importo', aggfunc=agg_func, fill_value=0)
    pivot["TOTALE"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("TOTALE", ascending=False)
    pivot.loc["TOTALE"] = pivot.sum()
    return pivot

# --- FUNZIONI DI STILE PER LE TABELLE ---
def style_delta_uscite(val):
    """Verde se positivo (risparmio), Rosso se negativo (sforamento)"""
    color = 'green' if val >= 0 else 'red'
    return f'color: {color}; font-weight: bold'

def style_delta_entrate(val):
    """Verde se positivo (più entrate), Rosso se negativo (meno entrate)"""
    color = 'green' if val >= 0 else 'red'
    return f'color: {color}; font-weight: bold'

# ==============================================================================
# 6. UI: SESSION STATE E CARICAMENTO DB
# ==============================================================================

st.title("☁️ Piano Pluriennale 2026")

# Carica DB Transazioni
try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    df_cloud["Importo"] = pd.to_numeric(df_cloud["Importo"], errors='coerce').fillna(0)
    
    # Pulizia colonne chiave per garantire il match
    if "Categoria" in df_cloud.columns: 
        df_cloud["Categoria"] = df_cloud["Categoria"].astype(str).str.strip()
    if "Tipo" in df_cloud.columns: 
        df_cloud["Tipo"] = df_cloud["Tipo"].astype(str).str.strip()
        
except:
    df_cloud = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

# Session State
if "df_mail_found" not in st.session_state: st.session_state["df_mail_found"] = pd.DataFrame()
if "df_mail_discarded" not in st.session_state: st.session_state["df_mail_discarded"] = pd.DataFrame()
if "df_manual_entry" not in st.session_state: st.session_state["df_manual_entry"] = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

# ==============================================================================
# 7. TABS
# ==============================================================================
tab1, tab2, tab3 = st.tabs(["📥 NUOVE & IMPORTA", "📊 REPORT & BUDGET", "🗂 STORICO & MODIFICA"])

# ------------------------------------------------------------------------------
# TAB 1: IMPORTAZIONE
# ------------------------------------------------------------------------------
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

# ------------------------------------------------------------------------------
# TAB 2: REPORT & BUDGET
# ------------------------------------------------------------------------------
with tab2:
    df_budget = get_budget_data()
    
    # --- DEBUGGER: MOSTRA QUALI COLONNE VEDE IL CODICE ---
    with st.expander("🛠️ DEBUG - Verifica Nomi Colonne"):
        st.write("Colonne trovate nel file DB_BUDGET:", list(df_budget.columns))
        st.write("Verifica che i nomi qui sopra coincidano con il mese che selezioni sotto (es: 'Gen', 'Feb').")

    df_ana = df_cloud.copy()
    df_ana["Anno"] = df_ana["Data"].dt.year
    df_ana["MeseNum"] = df_ana["Data"].dt.month
    
    map_mesi = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu', 7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}
    
    col_f1, col_f2 = st.columns(2)
    with col_f1: 
        anno_sel = st.selectbox("📅 Anno", sorted(df_ana["Anno"].unique(), reverse=True) if not df_ana.empty else [2026])
    with col_f2: 
        mese_sel_nome = st.selectbox("📆 Mese Analisi", list(map_mesi.values()), index=datetime.now().month-1)
    
    mese_sel_num = [k for k, v in map_mesi.items() if v == mese_sel_nome][0]
    df_anno = df_ana[df_ana["Anno"] == anno_sel]
    
    # --- KPI GLOBAL ---
    ent_tot = df_anno[df_anno["Tipo"] == "Entrata"]["Importo"].sum()
    usc_tot = df_anno[df_anno["Tipo"] == "Uscita"]["Importo"].sum()
    saldo = ent_tot - usc_tot
    
    k1, k2, k3 = st.columns(3)
    k1.metric("Entrate Totali (Anno)", f"{ent_tot:,.2f} €")
    k2.metric("Uscite Totali (Anno)", f"{usc_tot:,.2f} €", delta_color="inverse")
    k3.metric("Saldo Netto (Anno)", f"{saldo:,.2f} €")
    
    st.divider()

    # --- LOGICA BUDGET ---
    # Verifica esistenza colonna mese nel budget
    if not df_budget.empty and mese_sel_nome in df_budget.columns:
        
        # 1. Prepara Budget
        bud = df_budget[["Categoria", "Tipo", mese_sel_nome]].rename(columns={mese_sel_nome: "Budget"})
        if mese_sel_nome != "Gen": 
            bud = bud[bud["Categoria"] != "SALDO INIZIALE"]
        
        # 2. Prepara Reale
        real = df_anno[(df_anno["MeseNum"]==mese_sel_num)].groupby(["Categoria","Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo":"Reale"})
        if mese_sel_nome != "Gen": 
            real = real[real["Categoria"] != "SALDO INIZIALE"]

        # 3. Merge
        comp = pd.merge(bud, real, on=["Categoria","Tipo"], how="outer").fillna(0)
        
        # 4. Calcoli e Pulizia
        comp["Budget"] = pd.to_numeric(comp["Budget"], errors='coerce').fillna(0)
        comp["Reale"] = pd.to_numeric(comp["Reale"], errors='coerce').fillna(0)
        comp["Delta"] = comp["Budget"] - comp["Reale"]

        # KPI Mese
        b_m = comp[comp["Tipo"]=="Uscita"]["Budget"].sum()
        r_m = comp[comp["Tipo"]=="Uscita"]["Reale"].sum()
        st.metric(f"In Tasca ({mese_sel_nome})", f"{(b_m - r_m):,.2f} €")

        # Alert Sforamenti
        sfori = comp[(comp["Tipo"]=="Uscita") & (comp["Delta"] < 0)]
        for _, r in sfori.iterrows():
            st.error(f"⚠️ Sforamento **{r['Categoria']}**: {abs(r['Delta']):.2f} €")

        # Tabella Uscite
        st.markdown("### 🔴 Uscite vs Budget")
        out = comp[comp["Tipo"]=="Uscita"].copy()
        if not out.empty:
            out["Delta"] = out["Budget"] - out["Reale"]
            
            c_g, c_t = st.columns([1, 1.5])
            with c_g: 
                if out["Reale"].sum() > 0: 
                    st.plotly_chart(px.pie(out, values='Reale', names='Categoria', hole=0.4), use_container_width=True)
            with c_t:
                st.dataframe(
                    out.style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
                    .map(style_delta_uscite, subset=["Delta"]),
                    use_container_width=True, hide_index=True
                )
        
        # Tabella Entrate
        st.markdown("### 🟢 Entrate vs Budget")
        inc = comp[comp["Tipo"]=="Entrata"].copy()
        if not inc.empty:
            inc["Delta"] = inc["Reale"] - inc["Budget"]
            st.dataframe(
                inc.style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
                .map(style_delta_entrate, subset=["Delta"]),
                use_container_width=True, hide_index=True
            )

    else:
        st.warning(f"⚠️ Dati Budget non trovati per la colonna '{mese_sel_nome}'. Controlla il Debugger sopra.")

    # --- STORICO MENSILI ---
    st.divider()
    st.subheader("📅 Andamento Mensile")
    piv = crea_prospetto(df_anno[df_anno["Tipo"]=="Uscita"], "Categoria", "MeseNum").rename(columns=map_mesi)
    st.dataframe(piv.style.format("{:.2f} €").background_gradient(cmap="Reds", axis=None), use_container_width=True)

    # --- STORICO ANNUALE ---
    col_a1, col_a2 = st.columns(2)
    with col_a1:
        st.markdown("**Top 10 Spese**")
        st.bar_chart(df_anno[df_anno["Tipo"]=="Uscita"].groupby("Categoria")["Importo"].sum().sort_values(ascending=False).head(10), color="#ff4b4b", horizontal=True)
    with col_a2:
        st.markdown("**Trend Mensile**")
        trend = df_anno.groupby(["MeseNum", "Tipo"])["Importo"].sum().unstack().fillna(0).rename(index=map_mesi)
        st.bar_chart(trend, color=["#2ecc71", "#ff4b4b"])

# ------------------------------------------------------------------------------
# TAB 3: MODIFICA STORICO
# ------------------------------------------------------------------------------
with tab3:
    st.markdown("### 🗂 Modifica Database Completo")
    
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
        st.success("Database aggiornato correttamnte!")
        st.rerun()
