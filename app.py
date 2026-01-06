import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox
import re
import uuid
import plotly.express as px

# ==============================================================================
# 1. CONFIGURAZIONE PAGINA E FUNZIONI DI UTILITÀ
# ==============================================================================
st.set_page_config(page_title="Piano Pluriennale", layout="wide", page_icon="☁️")

# Funzione per pulire le chiavi di unione (Risolve il problema del matching)
def clean_key(series):
    """Rimuove spazi extra e converte in maiuscolo per garantire il match tra Budget e Reale"""
    return series.astype(str).str.strip().str.upper()

# Mappa mesi per conversioni
MAP_MESI = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu', 7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}

# Mappa Keyword completa
MAPPA_KEYWORD = {
    "lidl": "USCITE/PRANZO", "conad": "USCITE/PRANZO", "esselunga": "USCITE/PRANZO",
    "coop": "USCITE/PRANZO", "carrefour": "USCITE/PRANZO", "eurospin": "USCITE/PRANZO",
    "aldi": "USCITE/PRANZO", "ristorante": "USCITE/PRANZO", "pizzeria": "USCITE/PRANZO",
    "sushi": "USCITE/PRANZO", "mcdonald": "USCITE/PRANZO", "burger king": "USCITE/PRANZO",
    "bar ": "USCITE/PRANZO", "caffè": "USCITE/PRANZO", "eni": "CARBURANTE",
    "q8": "CARBURANTE", "esso": "CARBURANTE", "benzina": "CARBURANTE",
    "autostrade": "VARIE", "telepass": "VARIE", "amazon": "VARIE", "paypal": "PERSONALE",
    "netflix": "SVAGO", "spotify": "SVAGO", "dazn": "SVAGO", "disney": "SVAGO",
    "farmacia": "SALUTE", "medico": "SALUTE", "ticket": "SALUTE"
}

# ==============================================================================
# 2. CONNESSIONE E CARICAMENTO DATI
# ==============================================================================
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"Errore critico di connessione: {e}")
    st.stop()

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
LISTA_TUTTE = sorted(list(set(CAT_ENTRATE + CAT_USCITE)))

@st.cache_data(ttl=0) # Cache disabilitata per vedere subito modifiche al file
def get_budget_data():
    try:
        df_bud = conn.read(worksheet="DB_BUDGET", usecols=list(range(14))).fillna(0)
        # 1. Pulisce i nomi delle colonne (es. "Gen " -> "Gen")
        df_bud.columns = [str(c).strip() for c in df_bud.columns]
        
        # 2. Crea colonna chiave pulita per il match
        if "Categoria" in df_bud.columns:
            df_bud["Categoria_Match"] = clean_key(df_bud["Categoria"])
        
        # 3. Converte le colonne dei mesi in numeri puri (rimuove € e formatta)
        for col in df_bud.columns:
            if col not in ["Categoria", "Tipo", "Categoria_Match"]:
                df_bud[col] = df_bud[col].astype(str).str.replace('€','').str.replace('.','').str.replace(',','.')
                df_bud[col] = pd.to_numeric(df_bud[col], errors='coerce').fillna(0)
        return df_bud
    except: return pd.DataFrame()

# ==============================================================================
# 3. LOGICA DI ELABORAZIONE
# ==============================================================================
def trova_categoria_smart(descrizione, lista_categorie_disponibili):
    desc_lower = descrizione.lower()
    # Match esatto keyword
    for parola_chiave, target_categoria in MAPPA_KEYWORD.items():
        if parola_chiave in desc_lower:
            for cat in lista_categorie_disponibili:
                if target_categoria.lower() in cat.lower(): return cat
    # Match parziale nome categoria
    for cat in lista_categorie_disponibili:
        if cat.lower() in desc_lower: return cat
    return "DA VERIFICARE"

def scarica_spese_da_gmail():
    nuove_transazioni, mail_scartate = [], []
    if "email" not in st.secrets:
        st.error("Configurazione email mancante nei secrets."); return pd.DataFrame(), pd.DataFrame()
    
    user = st.secrets["email"]["user"]
    pwd = st.secrets["email"]["password"]
    server = st.secrets["email"]["imap_server"]
    
    try:
        with MailBox(server).login(user, pwd) as mailbox:
            for msg in mailbox.fetch(limit=50, reverse=True):
                soggetto = msg.subject
                corpo_clean = " ".join((msg.text or msg.html).split())
                
                if "widiba" not in corpo_clean.lower() and "widiba" not in soggetto.lower(): continue

                importo, tipo, descrizione, trovato = 0.0, "Uscita", "Transazione Generica", False
                
                # Regex potenti
                regex_uscite = [
                    r'(?:pagamento|prelievo|addebito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:presso|per|a favore di|su)\s+(.*?)(?:\.|$)',
                    r'ha\s+prelevato\s+([\d.,]+)\s+euro.*?(?:presso)\s+(.*?)(?:\.|$)'
                ]
                regex_entrate = [
                    r'(?:accredito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:per|da|a favore di)\s+(.*?)(?:\.|$)',
                    r'hai\s+ricevuto\s+([\d.,]+)\s+euro\s+da\s+(.*?)(?:\.|$)'
                ]

                # Analisi Uscite
                for rx in regex_uscite:
                    match = re.search(rx, corpo_clean, re.IGNORECASE)
                    if match:
                        importo = float(match.group(1).replace('.', '').replace(',', '.'))
                        descrizione = match.group(2).strip()
                        tipo = "Uscita"
                        trovato = True; break 
                
                # Analisi Entrate
                if not trovato:
                    for rx in regex_entrate:
                        match = re.search(rx, corpo_clean, re.IGNORECASE)
                        if match:
                            importo = float(match.group(1).replace('.', '').replace(',', '.'))
                            descrizione = match.group(2).strip()
                            tipo = "Entrata"
                            trovato = True; break

                if trovato:
                    cat_sugg = trova_categoria_smart(descrizione, CAT_USCITE if tipo=="Uscita" else CAT_ENTRATE)
                    nuove_transazioni.append({
                        "Data": msg.date.strftime("%Y-%m-%d"),
                        "Descrizione": descrizione, "Importo": importo,
                        "Tipo": tipo, "Categoria": cat_sugg,
                        "Mese": msg.date.strftime('%b-%y'),
                        "Firma": f"{msg.date.strftime('%Y%m%d')}-{importo}-{descrizione[:10]}"
                    })
                else:
                    mail_scartate.append({
                        "Data": msg.date.strftime("%Y-%m-%d"), "Descrizione": soggetto, 
                        "Importo": 0.0, "Tipo": "Uscita", "Categoria": "DA VERIFICARE", 
                        "Mese": msg.date.strftime('%b-%y'), "Firma": f"ERR-{uuid.uuid4().hex[:6]}"
                    })
    except Exception as e: st.error(f"Errore lettura mail: {e}")
    return pd.DataFrame(nuove_transazioni), pd.DataFrame(mail_scartate)

def crea_prospetto(df, index_col, columns_col):
    if df.empty: return pd.DataFrame()
    pivot = df.pivot_table(index=index_col, columns=columns_col, values='Importo', aggfunc='sum', fill_value=0)
    pivot["TOTALE"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("TOTALE", ascending=False)
    pivot.loc["TOTALE"] = pivot.sum()
    return pivot

# Funzioni Stile Tabelle
def style_delta_uscite(val): return f'color: {"green" if val >= 0 else "red"}; font-weight: bold'
def style_delta_entrate(val): return f'color: {"green" if val >= 0 else "red"}; font-weight: bold'

# ==============================================================================
# 4. CARICAMENTO DB E SESSION STATE
# ==============================================================================
try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    df_cloud["Importo"] = pd.to_numeric(df_cloud["Importo"], errors='coerce').fillna(0)
    # CREIAMO LA CHIAVE DI MATCHING ANCHE QUI
    if "Categoria" in df_cloud.columns:
        df_cloud["Categoria_Match"] = clean_key(df_cloud["Categoria"])
except:
    df_cloud = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

if "df_mail_found" not in st.session_state: st.session_state["df_mail_found"] = pd.DataFrame()
if "df_mail_discarded" not in st.session_state: st.session_state["df_mail_discarded"] = pd.DataFrame()
if "df_manual_entry" not in st.session_state: st.session_state["df_manual_entry"] = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

# ==============================================================================
# 5. UI PRINCIPALE - TABS
# ==============================================================================
tab1, tab2, tab3 = st.tabs(["📥 NUOVE & IMPORTA", "📊 REPORT & BUDGET", "🗂 STORICO & MODIFICA"])

# --- TAB 1: IMPORTAZIONE ---
with tab1:
    col_search, col_act = st.columns([1, 4])
    with col_search:
        if st.button("🔎 Cerca Mail", type="primary"):
            with st.spinner("Analisi in corso..."):
                df_m, df_s = scarica_spese_da_gmail()
                st.session_state["df_mail_found"] = df_m
                st.session_state["df_mail_discarded"] = df_s
    
    st.divider()

    if not st.session_state["df_mail_discarded"].empty:
        with st.expander(f"⚠️ {len(st.session_state['df_mail_discarded'])} Mail Scartate (Da verificare)", expanded=True):
            st.dataframe(st.session_state["df_mail_discarded"][["Data", "Descrizione"]], use_container_width=True)
            if st.button("⬇️ Recupera in Manuale"):
                st.session_state["df_manual_entry"] = pd.concat([st.session_state["df_manual_entry"], st.session_state["df_mail_discarded"]], ignore_index=True)
                st.session_state["df_mail_discarded"] = pd.DataFrame(); st.rerun()

    df_mail = st.session_state["df_mail_found"]
    if not df_mail.empty:
        firme_esistenti = df_cloud["Firma"].astype(str).tolist() if "Firma" in df_cloud.columns else []
        df_clean = df_mail[~df_mail["Firma"].astype(str).isin(firme_esistenti)]
        
        st.subheader("💰 Nuove Transazioni Identificate")
        df_mail_edit = st.data_editor(
            df_clean,
            column_config={
                "Categoria": st.column_config.SelectboxColumn(options=LISTA_TUTTE),
                "Data": st.column_config.DateColumn(format="YYYY-MM-DD")
            }, use_container_width=True
        )

    st.subheader("✍️ Inserimento Manuale")
    if st.session_state["df_manual_entry"].empty:
        st.session_state["df_manual_entry"] = pd.DataFrame([{"Data": datetime.now(), "Descrizione": "", "Importo": 0.0, "Tipo": "Uscita", "Categoria": "DA VERIFICARE"}])
    
    df_man_edit = st.data_editor(
        st.session_state["df_manual_entry"],
        num_rows="dynamic",
        column_config={
            "Categoria": st.column_config.SelectboxColumn(options=LISTA_TUTTE),
            "Tipo": st.column_config.SelectboxColumn(options=["Uscita", "Entrata"]),
            "Data": st.column_config.DateColumn(format="YYYY-MM-DD"),
            "Importo": st.column_config.NumberColumn(format="%.2f €")
        }, use_container_width=True
    )

    if st.button("💾 SALVA TUTTO NEL DATABASE", type="primary", use_container_width=True):
        da_salvare = [df_cloud.drop(columns=["Categoria_Match"], errors="ignore")]
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
        st.session_state["df_mail_found"] = pd.DataFrame()
        st.session_state["df_manual_entry"] = pd.DataFrame()
        st.balloons(); st.success("Salvataggio Completato!"); st.rerun()

# ==============================================================================
# TAB 2: REPORT & BUDGET (NUOVA LOGICA BUDGET-CENTRICA)
# ==============================================================================
with tab2:
    # 1. CARICAMENTO PRIMARIO DEL BUDGET
    df_budget = get_budget_data()
    
    # Filtri Temporali
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1: 
        anno_sel = st.selectbox("📅 Anno", sorted(df_cloud["Data"].dt.year.unique(), reverse=True) if not df_cloud.empty else [2026])
    
    # Selettore Mese (Per ora Mensile come richiesto)
    with col_f2:
        mese_sel_nome = st.selectbox("📆 Mese", list(MAP_MESI.values()), index=datetime.now().month-1)
    
    mese_sel_num = [k for k,v in MAP_MESI.items() if v==mese_sel_nome][0]

    # --- DATI BUDGET DEL MESE ---
    if not df_budget.empty and mese_sel_nome in df_budget.columns:
        # Costruisco il dataframe del preventivo per il mese selezionato
        # Includo Categoria_Match per il futuro merge
        df_preventivo = df_budget[["Categoria", "Categoria_Match", "Tipo", mese_sel_nome]].copy()
        df_preventivo = df_preventivo.rename(columns={mese_sel_nome: "Budget"})
        
        # Gestione Saldo Iniziale (visibile solo a Gennaio)
        if mese_sel_nome != "Gen":
            df_preventivo = df_preventivo[df_preventivo["Categoria"] != "SALDO INIZIALE"]

        # --- KPI SOLO BUDGET (CRUSCOTTO PREVENTIVO) ---
        prev_entrate = df_preventivo[df_preventivo["Tipo"]=="Entrata"]["Budget"].sum()
        prev_uscite = df_preventivo[df_preventivo["Tipo"]=="Uscita"]["Budget"].sum()
        prev_saldo = prev_entrate - prev_uscite

        st.markdown(f"### 📊 Preventivo: {mese_sel_nome} {anno_sel}")
        b1, b2, b3 = st.columns(3)
        b1.metric("Entrate Previste", f"{prev_entrate:,.2f} €")
        b2.metric("Uscite Previste", f"{prev_uscite:,.2f} €")
        b3.metric("Saldo Previsto", f"{prev_saldo:,.2f} €")
        
        st.divider()

        # --- RECUPERO DATI REALI (SE ESISTONO) ---
        df_reale_anno = df_cloud[df_cloud["Data"].dt.year == anno_sel]
        df_reale_mese = df_reale_anno[df_reale_anno["Data"].dt.month == mese_sel_num]
        
        # Raggruppo il reale
        if not df_reale_mese.empty:
            consuntivo = df_reale_mese.groupby(["Categoria_Match", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Reale"})
        else:
            consuntivo = pd.DataFrame(columns=["Categoria_Match", "Tipo", "Reale"])

        # --- MERGE BUDGET-CENTRICO ---
        # Partiamo dal df_preventivo (Left) e uniamo il consuntivo (Right)
        # Così le righe del budget restano sempre, anche se il reale è vuoto.
        df_finale = pd.merge(df_preventivo, consuntivo[["Categoria_Match", "Reale"]], on="Categoria_Match", how="left").fillna(0)
        
        # Calcolo Delta
        df_finale["Budget"] = pd.to_numeric(df_finale["Budget"])
        df_finale["Reale"] = pd.to_numeric(df_finale["Reale"])
        df_finale["Delta"] = df_finale["Budget"] - df_finale["Reale"]

        # --- KPI CONFRONTO (REALE vs BUDGET) ---
        real_uscite_tot = df_finale[df_finale["Tipo"]=="Uscita"]["Reale"].sum()
        delta_tot_uscite = prev_uscite - real_uscite_tot
        
        st.markdown(f"### 📉 Consuntivo vs Budget")
        c1, c2 = st.columns(2)
        c1.metric("Spese Effettive", f"{real_uscite_tot:,.2f} €")
        c2.metric("Rimanente da Spendere", f"{delta_tot_uscite:,.2f} €", delta=f"{delta_tot_uscite:,.2f} €")

        # --- TABELLA DETTAGLIO ---
        col_grafico, col_tabella = st.columns([1, 1.5])
        
        # Grafico distribuzione budget
        df_uscite_view = df_finale[df_finale["Tipo"]=="Uscita"].copy()
        
        with col_grafico:
            # Mostriamo la torta di come era PREVISTO spendere i soldi
            st.caption("Distribuzione Budget")
            if prev_uscite > 0:
                fig = px.pie(df_uscite_view, values='Budget', names='Categoria', hole=0.4)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Nessun budget uscite definito.")

        with col_tabella:
            st.caption("Dettaglio Voci")
            # Ordiniamo per Budget decrescente (così vedi prima le voci grosse)
            st.dataframe(
                df_uscite_view[["Categoria", "Budget", "Reale", "Delta"]]
                .sort_values("Budget", ascending=False)
                .style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
                .map(style_delta_uscite, subset=["Delta"]),
                use_container_width=True, hide_index=True
            )
            
    else:
        st.warning(f"Nessun dato di Budget trovato per il mese: {mese_sel_nome}. Controlla il foglio DB_BUDGET.")

    # --- STORICI ---
    st.divider()
    st.subheader("📅 Storico Mensile")
    df_anno_u = df_cloud[(df_cloud["Data"].dt.year == anno_sel) & (df_cloud["Tipo"]=="Uscita")]
    if not df_anno_u.empty:
        df_anno_u["MeseNum"] = df_anno_u["Data"].dt.month
        piv = crea_prospetto(df_anno_u, "Categoria", "MeseNum").rename(columns=MAP_MESI)
        st.dataframe(piv.style.format("{:.2f} €").background_gradient(cmap="Reds", axis=None), use_container_width=True)

# ==============================================================================
# TAB 3: MODIFICA STORICO
# ==============================================================================
with tab3:
    st.markdown("### 🗂 Modifica Database Completo")
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    # Nascondo la colonna tecnica Categoria_Match all'utente
    ed_full = st.data_editor(
        df_cloud.drop(columns=["Categoria_Match"], errors="ignore"), 
        num_rows="dynamic", height=600, use_container_width=True
    )
    
    if st.button("AGGIORNA DB COMPLETO", type="primary"):
        save_full = ed_full.copy()
        save_full["Data"] = pd.to_datetime(save_full["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=save_full)
        st.success("Database aggiornato!"); st.rerun()
