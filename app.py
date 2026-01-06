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
st.set_page_config(page_title="Piano Pluriennale", layout="wide", page_icon="☁️")

# Mappa Mesi per conversioni e visualizzazione
MAP_MESI = {1:'Gen', 2:'Feb', 3:'Mar', 4:'Apr', 5:'Mag', 6:'Giu', 7:'Lug', 8:'Ago', 9:'Set', 10:'Ott', 11:'Nov', 12:'Dic'}
MAP_NUM_MESI = {v: k for k, v in MAP_MESI.items()}

# --- 🧠 IL CERVELLO: MAPPA PAROLE CHIAVE ---
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
# 2. CONNESSIONE
# ==============================================================================
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
LISTA_TUTTE = sorted(list(set(CAT_ENTRATE + CAT_USCITE)))

# --- CARICAMENTO BUDGET (BLINDATO: Normalizza Mese, Tipo e Importo) ---
@st.cache_data(ttl=0) 
def get_budget_data():
    try:
        # Legge solo le prime 4 colonne
        df_bud = conn.read(worksheet="DB_BUDGET", usecols=list(range(4))).fillna(0)
        
        # Rinomina colonne standard
        if len(df_bud.columns) >= 4:
            df_bud.columns = ["Mese", "Categoria", "Tipo", "Importo"]
        
        # Pulizia base spazi
        for col in ["Mese", "Categoria", "Tipo"]:
            if col in df_bud.columns:
                df_bud[col] = df_bud[col].astype(str).str.strip()

        # --- 1. NORMALIZZAZIONE MESE ---
        def normalizza_mese(val):
            val = str(val).strip().lower()
            if val.startswith('gen') or val in ['1', '01']: return 'Gen'
            if val.startswith('feb') or val in ['2', '02']: return 'Feb'
            if val.startswith('mar') or val in ['3', '03']: return 'Mar'
            if val.startswith('apr') or val in ['4', '04']: return 'Apr'
            if val.startswith('mag') or val in ['5', '05']: return 'Mag'
            if val.startswith('giu') or val in ['6', '06']: return 'Giu'
            if val.startswith('lug') or val in ['7', '07']: return 'Lug'
            if val.startswith('ago') or val in ['8', '08']: return 'Ago'
            if val.startswith('set') or val in ['9', '09']: return 'Set'
            if val.startswith('ott') or val == '10': return 'Ott'
            if val.startswith('nov') or val == '11': return 'Nov'
            if val.startswith('dic') or val == '12': return 'Dic'
            return val.capitalize() # Fallback

        if "Mese" in df_bud.columns:
            df_bud["Mese"] = df_bud["Mese"].apply(normalizza_mese)

        # --- 2. NORMALIZZAZIONE TIPO (Fix per "Uscite" vs "Uscita") ---
        def normalizza_tipo(val):
            val = str(val).strip().lower()
            # Se contiene "usc" (uscite, uscita) o "spes" (spese) -> Uscita
            if 'usc' in val or 'spes' in val: return 'Uscita'
            # Se contiene "ent" (entrate, entrata) o "ric" (ricavi) -> Entrata
            if 'ent' in val or 'ric' in val: return 'Entrata'
            return val.capitalize()

        if "Tipo" in df_bud.columns:
            df_bud["Tipo"] = df_bud["Tipo"].apply(normalizza_tipo)
            
        # --- 3. FIX IMPORTI (Virgole e Punti) ---
        if "Importo" in df_bud.columns:
            def pulisci_numero(val):
                s = str(val).strip().replace('€', '')
                if '.' in s and ',' in s: s = s.replace('.', '').replace(',', '.') # 1.000,00 -> 1000.00
                elif ',' in s: s = s.replace(',', '.') # 100,00 -> 100.00
                return s
            df_bud["Importo"] = df_bud["Importo"].apply(pulisci_numero)
            df_bud["Importo"] = pd.to_numeric(df_bud["Importo"], errors='coerce').fillna(0)
        
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

# --- FUNZIONE PIVOT ---
def crea_prospetto(df, index_col, columns_col, agg_func='sum'):
    if df.empty: return pd.DataFrame()
    pivot = df.pivot_table(index=index_col, columns=columns_col, values='Importo', aggfunc=agg_func, fill_value=0)
    pivot["TOTALE"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("TOTALE", ascending=False)
    pivot.loc["TOTALE"] = pivot.sum()
    return pivot

# --- FUNZIONI DI STILE ---
def style_negative_positive(val):
    return f'color: {"red" if val < 0 else "green"}; font-weight: bold'
def style_variance_uscite(val):
    return f'color: {"green" if val >= 0 else "red"}; font-weight: bold'
def style_variance_entrate(val):
    return f'color: {"green" if val >= 0 else "red"}; font-weight: bold'

# ==============================================================================
# CARICAMENTO DATI PRINCIPALI
# ==============================================================================
st.title("☁️ Piano Pluriennale 2026")

try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    df_cloud["Importo"] = pd.to_numeric(df_cloud["Importo"], errors='coerce').fillna(0)
    # Pulizia Categoria DB per match sicuro
    if "Categoria" in df_cloud.columns:
        df_cloud["Categoria"] = df_cloud["Categoria"].astype(str).str.strip()
except:
    df_cloud = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

# Session State
if "df_mail_found" not in st.session_state: st.session_state["df_mail_found"] = pd.DataFrame()
if "df_mail_discarded" not in st.session_state: st.session_state["df_mail_discarded"] = pd.DataFrame()
if "df_manual_entry" not in st.session_state: st.session_state["df_manual_entry"] = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

# TABS
tab1, tab2, tab3 = st.tabs(["📥 NUOVE & IMPORTA", "📊 REPORT & BUDGET", "🗂 STORICO & MODIFICA"])

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

    # Visualizzazione e Editor Nuove
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
# TAB 2: REPORT & BUDGET
# ==========================================
with tab2:
    if df_cloud.empty:
        st.warning("Nessun dato nel database transazioni.")
    else:
        # Carica Budget
        df_budget = get_budget_data()
        
        # --------------------------------------------------------
        # 🕵️‍♂️ BOX DIAGNOSTICO - FONDAMENTALE (CON TIPI E MESI)
        # --------------------------------------------------------
        with st.expander("🕵️‍♂️ DEBUG BUDGET (Clicca qui se vedi tutto a zero)", expanded=False):
            if df_budget.empty:
                st.error("Il file DB_BUDGET sembra vuoto o illeggibile.")
            else:
                st.write("Visualizzazione completa dei dati caricati (Mese e Tipo Normalizzati):")
                st.write(f"Tipi Trovati unici: {df_budget['Tipo'].unique()}")
                st.write(f"Mesi Trovati unici: {df_budget['Mese'].unique()}")
                st.dataframe(df_budget, use_container_width=True)

        # Prepara dati per analisi
        df_analysis = df_cloud.copy()
        df_analysis["Anno"] = df_analysis["Data"].dt.year
        df_analysis["MeseNum"] = df_analysis["Data"].dt.month
        
        # Filtro Anno
        col_f1, col_f2 = st.columns(2)
        with col_f1: anno_sel = st.selectbox("📅 Anno", sorted(df_analysis["Anno"].unique(), reverse=True) if not df_analysis.empty else [2026])
        df_anno = df_analysis[df_analysis["Anno"] == anno_sel]

        # --- KPI GLOBAL ---
        tot_entrate = df_anno[df_anno["Tipo"] == "Entrata"]["Importo"].sum()
        tot_uscite = df_anno[df_anno["Tipo"] == "Uscita"]["Importo"].sum()
        saldo = tot_entrate - tot_uscite
        k1, k2, k3 = st.columns(3)
        k1.metric("Totale Entrate", f"{tot_entrate:,.2f} €")
        k2.metric("Totale Uscite", f"{tot_uscite:,.2f} €", delta_color="inverse")
        k3.metric("Saldo Netto", f"{saldo:,.2f} €", delta=f"{saldo:,.2f} €")
        st.divider()

        # --- SELETTORE VISTA ---
        vista = st.radio("Seleziona Vista:", ["📊 Confronto Mensile (Budget)", "📈 Trend Annuale"], horizontal=True)

        if vista == "📊 Confronto Mensile (Budget)":
            with col_f2: mese_sel_nome = st.selectbox("Seleziona Mese:", list(MAP_MESI.values()), index=datetime.now().month-1)
            mese_sel_num = MAP_NUM_MESI[mese_sel_nome]

            st.subheader(f"Analisi Budget: {mese_sel_nome} {anno_sel}")

            # 1. Calcola Consuntivo (Reale)
            df_mese = df_anno[df_anno["MeseNum"] == mese_sel_num]
            consuntivo = df_mese.groupby(["Categoria", "Tipo"])["Importo"].sum().reset_index()
            consuntivo.rename(columns={"Importo": "Reale"}, inplace=True)

            # 2. Calcola Preventivo (Budget) - LOGICA FILTRO PER MESE
            preventivo = pd.DataFrame()
            if not df_budget.empty and "Mese" in df_budget.columns:
                # Filtra le righe dove la colonna Mese è uguale al mese selezionato
                preventivo = df_budget[df_budget["Mese"] == mese_sel_nome].copy()
                preventivo = preventivo.rename(columns={"Importo": "Budget"})
                
                # PROTEZIONE SALDO INIZIALE
                if mese_sel_nome != "Gen":
                    preventivo = preventivo[preventivo["Categoria"] != "SALDO INIZIALE"]
                    consuntivo = consuntivo[consuntivo["Categoria"] != "SALDO INIZIALE"]

            # 3. Unisci (Merge) - Left Join sul Budget per vedere tutto il preventivato
            if not preventivo.empty:
                df_merge = pd.merge(preventivo, consuntivo, on=["Categoria", "Tipo"], how="left").fillna(0)
            else:
                df_merge = consuntivo.copy()
                df_merge["Budget"] = 0.0

            # FORZA NUMERI PRIMA DI QUALSIASI OPERAZIONE
            df_merge["Budget"] = pd.to_numeric(df_merge["Budget"], errors='coerce').fillna(0)
            df_merge["Reale"] = pd.to_numeric(df_merge["Reale"], errors='coerce').fillna(0)

            # --- ALERT SFORAMENTI ---
            df_merge["Delta"] = df_merge["Budget"] - df_merge["Reale"]
            sfori = df_merge[(df_merge["Tipo"]=="Uscita") & (df_merge["Delta"] < 0)]
            for _, r in sfori.iterrows():
                st.error(f"⚠️ Sforamento **{r['Categoria']}**: {abs(r['Delta']):.2f} €")

            # --- TABELLA USCITE ---
            st.markdown("### 🔴 Uscite vs Budget")
            # FILTRO CRUCIALE: Qui filtra per "Uscita" (normalizzato)
            df_out = df_merge[df_merge["Tipo"] == "Uscita"].copy()
            if not df_out.empty:
                df_out["Risparmio (Delta)"] = df_out["Budget"] - df_out["Reale"]
                df_out = df_out[["Categoria", "Budget", "Reale", "Risparmio (Delta)"]].sort_values("Budget", ascending=False)
                
                # Totali
                tot_bud = df_out["Budget"].sum()
                tot_real = df_out["Reale"].sum()
                tot_delta = tot_bud - tot_real
                
                col_t1, col_t2, col_t3 = st.columns(3)
                col_t1.metric("Budget Uscite", f"{tot_bud:,.2f} €")
                col_t2.metric("Spese Reali", f"{tot_real:,.2f} €")
                col_t3.metric("Risparmio Totale", f"{tot_delta:,.2f} €", delta=f"{tot_delta:,.2f} €")

                col_g, col_t = st.columns([1, 1.5])
                with col_g:
                    if tot_real > 0:
                        fig = px.pie(df_out, values='Reale', names='Categoria', hole=0.4, title="Distribuzione Spese")
                        st.plotly_chart(fig, use_container_width=True)
                    elif tot_bud > 0:
                         fig = px.pie(df_out, values='Budget', names='Categoria', hole=0.4, title="Budget Previsto")
                         st.plotly_chart(fig, use_container_width=True)

                with col_t:
                    st.dataframe(
                        df_out.style.format("{:.2f} €", subset=["Budget", "Reale", "Risparmio (Delta)"])
                        .map(style_variance_uscite, subset=["Risparmio (Delta)"])
                        .background_gradient(cmap="Reds", subset=["Reale"]), 
                        use_container_width=True,
                        hide_index=True
                    )
            else:
                st.info("Nessun dato di budget o spesa trovato per le uscite.")

            # --- TABELLA ENTRATE ---
            st.markdown("### 🟢 Entrate vs Budget")
            # FILTRO CRUCIALE: Qui filtra per "Entrata" (normalizzato)
            df_in = df_merge[df_merge["Tipo"] == "Entrata"].copy()
            if not df_in.empty:
                df_in["Extra (Delta)"] = df_in["Reale"] - df_in["Budget"]
                df_in = df_in[["Categoria", "Budget", "Reale", "Extra (Delta)"]].sort_values("Budget", ascending=False)
                
                st.dataframe(
                    df_in.style.format("{:.2f} €", subset=["Budget", "Reale", "Extra (Delta)"])
                    .map(style_variance_entrate, subset=["Extra (Delta)"])
                    .background_gradient(cmap="Greens", subset=["Reale"]),
                    use_container_width=True,
                    hide_index=True
                )

        elif vista == "📈 Trend Annuale":
            st.subheader("Andamento categorie durante l'anno")
            # Pivot classico solo Consuntivo
            df_u = df_anno[df_anno["Tipo"] == "Uscita"]
            pivot_u = df_u.pivot_table(index="Categoria", columns="MeseNum", values="Importo", aggfunc="sum", fill_value=0)
            pivot_u = pivot_u.rename(columns=MAP_MESI)
            
            st.markdown("**Uscite Mensili (Consuntivo)**")
            st.dataframe(pivot_u.style.format("{:.2f} €").background_gradient(cmap="Reds", axis=None), use_container_width=True)

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
        st.success("Database aggiornato correttamnte!")
        st.rerun()
