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

# --- CARICAMENTO BUDGET (VERSIONE ROBUSTA E FIXATA) ---
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
            return val.capitalize()

        if "Mese" in df_bud.columns:
            df_bud["Mese"] = df_bud["Mese"].apply(normalizza_mese)

        # --- 2. NORMALIZZAZIONE TIPO ---
        def normalizza_tipo(val):
            val = str(val).strip().lower()
            if 'usc' in val or 'spes' in val: return 'Uscita'
            if 'ent' in val or 'ric' in val: return 'Entrata'
            return val.capitalize()

        if "Tipo" in df_bud.columns:
            df_bud["Tipo"] = df_bud["Tipo"].apply(normalizza_tipo)
            
        # --- 3. FIX IMPORTI ---
        if "Importo" in df_bud.columns:
            def pulisci_numero(val):
                s = str(val).strip().replace('€', '')
                if '.' in s and ',' in s: s = s.replace('.', '').replace(',', '.')
                elif ',' in s: s = s.replace(',', '.')
                return s
            df_bud["Importo"] = df_bud["Importo"].apply(pulisci_numero)
            df_bud["Importo"] = pd.to_numeric(df_bud["Importo"], errors='coerce').fillna(0)
        
        return df_bud
    except:
        return pd.DataFrame()

# --- UTILS E LOGICA ---
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

# --- FUNZIONI DI STILE E GRAFICA ---
def style_delta(val, inverse=False):
    if inverse:
        color = 'green' if val >= 0 else 'red'
    else:
        color = 'red' if val < 0 else 'green'
    return f'color: {color}; font-weight: bold'

def genera_grafico_avanzato(df, tipo_grafico, col_valore, col_label, titolo, color_sequence):
    """Genera il grafico in base al selettore dell'utente"""
    if df.empty or df[col_valore].sum() == 0:
        return None
    
    if tipo_grafico == "Torta (Donut)":
        fig = px.pie(df, values=col_valore, names=col_label, hole=0.4, title=titolo, color_discrete_sequence=color_sequence)
        # Forza le etichette dentro
        fig.update_traces(textposition='inside', textinfo='percent+label')
        
    elif tipo_grafico == "Barre Orizzontali":
        fig = px.bar(df, x=col_valore, y=col_label, orientation='h', title=titolo, text_auto='.2s', color=col_valore, color_continuous_scale=color_sequence)
        fig.update_layout(yaxis={'categoryorder':'total ascending'})
        
    elif tipo_grafico == "Treemap (Mappa)":
        fig = px.treemap(df, path=[col_label], values=col_valore, title=titolo, color=col_valore, color_continuous_scale=color_sequence)
        
    else:
        return None
    
    return fig

# ==============================================================================
# MAIN APP
# ==============================================================================
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
    df_budget = get_budget_data()
    df_analysis = df_cloud.copy()
    df_analysis["Anno"] = df_analysis["Data"].dt.year
    df_analysis["MeseNum"] = df_analysis["Data"].dt.month
    
    # ------------------------------------------------------------------
    # SELEZIONE PERIODI
    # ------------------------------------------------------------------
    c1, c2, c3 = st.columns(3)
    with c1: anno_sel = st.selectbox("📅 Anno", sorted(df_analysis["Anno"].unique(), reverse=True) if not df_analysis.empty else [2026])
    with c2: periodo_sel = st.selectbox("📊 Periodo Analisi", ["Mensile", "Trimestrale", "Semestrale", "Annuale"])
    
    lista_mesi_target = [] 
    lista_num_target = []
    
    with c3:
        if periodo_sel == "Mensile":
            mese_sel = st.selectbox("Mese", list(MAP_MESI.values()), index=datetime.now().month-1)
            lista_mesi_target = [mese_sel]
            lista_num_target = [MAP_NUM_MESI[mese_sel]]
        elif periodo_sel == "Trimestrale":
            trim = st.selectbox("Trimestre", ["Q1 (Gen-Mar)", "Q2 (Apr-Giu)", "Q3 (Lug-Set)", "Q4 (Ott-Dic)"])
            if "Q1" in trim: lista_num_target = [1, 2, 3]
            elif "Q2" in trim: lista_num_target = [4, 5, 6]
            elif "Q3" in trim: lista_num_target = [7, 8, 9]
            else: lista_num_target = [10, 11, 12]
            lista_mesi_target = [MAP_MESI[n] for n in lista_num_target]
        elif periodo_sel == "Semestrale":
            sem = st.selectbox("Semestre", ["Semestre 1 (Gen-Giu)", "Semestre 2 (Lug-Dic)"])
            if "1" in sem: lista_num_target = [1, 2, 3, 4, 5, 6]
            else: lista_num_target = [7, 8, 9, 10, 11, 12]
            lista_mesi_target = [MAP_MESI[n] for n in lista_num_target]
        elif periodo_sel == "Annuale":
            st.write("Tutto l'anno")
            lista_num_target = list(range(1, 13))
            lista_mesi_target = list(MAP_MESI.values())

    # --- FILTRI E KPI ---
    df_anno = df_analysis[df_analysis["Anno"] == anno_sel]
    df_target_reale = df_anno[df_anno["MeseNum"].isin(lista_num_target)]

    # Determina se includere Saldo Iniziale (Solo Gennaio)
    is_gennaio_mensile = (periodo_sel == "Mensile" and "Gen" in lista_mesi_target)
    
    # Calcolo KPI
    ent_kpi = df_target_reale[df_target_reale["Tipo"]=="Entrata"]["Importo"].sum()
    usc_kpi = df_target_reale[df_target_reale["Tipo"]=="Uscita"]["Importo"].sum()
    
    if not is_gennaio_mensile:
        ent_kpi = df_target_reale[(df_target_reale["Tipo"]=="Entrata") & (df_target_reale["Categoria"] != "SALDO INIZIALE")]["Importo"].sum()

    k1, k2, k3 = st.columns(3)
    k1.metric(f"Entrate ({periodo_sel})", f"{ent_kpi:,.2f} €")
    k2.metric(f"Uscite ({periodo_sel})", f"{usc_kpi:,.2f} €", delta_color="inverse")
    k3.metric("Saldo Periodo", f"{(ent_kpi-usc_kpi):,.2f} €")
    st.divider()

    # --- VISTA PRINCIPALE ---
    view_mode = st.radio("Vista", ["📊 Analisi Budget", "📈 Trend Annuale"], horizontal=True)

    if view_mode == "📊 Analisi Budget":
        
        # 1. Raggruppa Consuntivo
        consuntivo = df_target_reale.groupby(["Categoria", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Reale"}) if not df_target_reale.empty else pd.DataFrame(columns=["Categoria", "Tipo", "Reale"])

        # 2. Raggruppa Budget
        preventivo = pd.DataFrame()
        if not df_budget.empty and "Mese" in df_budget.columns:
            b_filt = df_budget[df_budget["Mese"].isin(lista_mesi_target)]
            if not b_filt.empty:
                preventivo = b_filt.groupby(["Categoria", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Budget"})

        # Filtro Saldo Iniziale (Rimuove da tutto tranne se Gennaio)
        if not is_gennaio_mensile:
            if not preventivo.empty: preventivo = preventivo[preventivo["Categoria"] != "SALDO INIZIALE"]
            if not consuntivo.empty: consuntivo = consuntivo[consuntivo["Categoria"] != "SALDO INIZIALE"]

        # 3. Merge
        merged = pd.merge(preventivo, consuntivo, on=["Categoria", "Tipo"], how="left").fillna(0) if not preventivo.empty else consuntivo.copy()
        if "Budget" not in merged.columns: merged["Budget"] = 0.0

        # FIX SPECIALE: Se Gennaio, copia Budget Saldo Iniziale su Reale se manca
        if is_gennaio_mensile:
            mask = (merged["Categoria"] == "SALDO INIZIALE")
            if mask.any():
                merged.loc[mask & (merged["Reale"] == 0), "Reale"] = merged.loc[mask, "Budget"]

        merged["Delta"] = merged["Budget"] - merged["Reale"]

        # --- PLANCIA DI COMANDO GRAFICI ---
        st.markdown("#### 🎨 Configurazione Grafici")
        ctl1, ctl2 = st.columns(2)
        with ctl1:
            source_data = st.radio("Sorgente Dati Grafico:", ["Reale (Consuntivo)", "Budget (Preventivo)"], horizontal=True)
        with ctl2:
            chart_type = st.selectbox("Tipo di Grafico:", ["Torta (Donut)", "Barre Orizzontali", "Treemap (Mappa)"])
        
        col_valore = "Reale" if "Reale" in source_data else "Budget"

        # --- SEZIONE GRAFICA ---
        c_left, c_right = st.columns([1, 1])

        # USCITE
        out = merged[merged["Tipo"]=="Uscita"].copy()
        with c_left:
            st.markdown(f"### 🔴 Uscite ({col_valore})")
            if not out.empty:
                fig = genera_grafico_avanzato(out, chart_type, col_valore, "Categoria", "Distribuzione Uscite", px.colors.sequential.RdBu)
                if fig: st.plotly_chart(fig, use_container_width=True)
                st.dataframe(out[["Categoria", "Budget", "Reale", "Delta"]].sort_values("Budget", ascending=False).style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"]).map(lambda v: style_delta(v, inverse=True), subset=["Delta"]), use_container_width=True)
        
        # ENTRATE
        inc = merged[merged["Tipo"]=="Entrata"].copy()
        with c_right:
            st.markdown(f"### 🟢 Entrate ({col_valore})")
            if not inc.empty:
                fig = genera_grafico_avanzato(inc, chart_type, col_valore, "Categoria", "Distribuzione Entrate", px.colors.sequential.Teal)
                if fig: st.plotly_chart(fig, use_container_width=True)
                st.dataframe(inc[["Categoria", "Budget", "Reale", "Delta"]].sort_values("Reale", ascending=False).style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"]).map(lambda v: style_delta(v), subset=["Delta"]), use_container_width=True)

    elif view_mode == "📈 Trend Annuale":
        st.subheader("Andamento categorie durante l'anno")
        piv = df_filt = df_anno[df_anno["Tipo"]=="Uscita"].pivot_table(index="Categoria", columns="MeseNum", values="Importo", aggfunc="sum", fill_value=0).rename(columns=MAP_MESI)
        st.dataframe(piv.style.format("{:.2f} €").background_gradient(cmap="Reds", axis=None), use_container_width=True)

with tab3:
    st.markdown("### DB Completo"); ed = st.data_editor(df_cloud, num_rows="dynamic")
    if st.button("AGGIORNA DB"):
        s = ed.copy(); s["Data"] = pd.to_datetime(s["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=s); st.success("Fatto!"); st.rerun()
