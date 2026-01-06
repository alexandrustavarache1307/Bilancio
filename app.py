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
                soggetto, corpo = msg.subject, " ".join((msg.text or msg.html).split())
                if "widiba" not in corpo.lower() and "widiba" not in soggetto.lower(): continue
                
                importo, tipo, descrizione, trovato = 0.0, "Uscita", "Transazione Generica", False
                regex_uscite = [r'(?:pagamento|prelievo|addebito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:presso|per|a favore di|su)\s+(.*?)(?:\.|$)', r'ha\s+prelevato\s+([\d.,]+)\s+euro.*?(?:presso)\s+(.*?)(?:\.|$)']
                regex_entrate = [r'(?:accredito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:per|da|a favore di)\s+(.*?)(?:\.|$)', r'hai\s+ricevuto\s+([\d.,]+)\s+euro\s+da\s+(.*?)(?:\.|$)']

                for rx in regex_uscite:
                    match = re.search(rx, corpo, re.IGNORECASE)
                    if match: importo, descrizione, tipo, trovato = float(match.group(1).replace('.','').replace(',','.')), match.group(2).strip(), "Uscita", True; break
                if not trovato:
                    for rx in regex_entrate:
                        match = re.search(rx, corpo, re.IGNORECASE)
                        if match: importo, descrizione, tipo, trovato = float(match.group(1).replace('.','').replace(',','.')), match.group(2).strip(), "Entrata", True; break

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

# ==============================================================================
# MAIN
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
    df_analysis = df_cloud.copy()
    df_analysis["Anno"] = df_analysis["Data"].dt.year
    df_analysis["MeseNum"] = df_analysis["Data"].dt.month
    
    # ------------------------------------------------------------------
    # SELEZIONE PERIODI (Mensile, Trimestrale, Semestrale, Annuale)
    # ------------------------------------------------------------------
    c1, c2, c3 = st.columns(3)
    with c1: anno_sel = st.selectbox("📅 Anno", sorted(df_analysis["Anno"].unique(), reverse=True) if not df_analysis.empty else [2026])
    with c2: periodo_sel = st.selectbox("📊 Periodo Analisi", ["Mensile", "Trimestrale", "Semestrale", "Annuale"])
    
    lista_mesi_target = [] # Nomi mesi (Gen, Feb) per filtro Budget
    lista_num_target = []  # Numeri mesi (1, 2) per filtro Transazioni
    
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

    # --- FILTRO DATI REALI ---
    df_anno = df_analysis[df_analysis["Anno"] == anno_sel]
    # Filtra solo i mesi selezionati
    df_target_reale = df_anno[df_anno["MeseNum"].isin(lista_num_target)]

    # --- KPI GLOBAL (Sempre Annuali per contesto, o del periodo?) ---
    # Utente vuole contesto periodo selezionato
    ent_p = df_target_reale[df_target_reale["Tipo"]=="Entrata"]["Importo"].sum()
    usc_p = df_target_reale[df_target_reale["Tipo"]=="Uscita"]["Importo"].sum()
    
    # Per il Saldo Iniziale: ESCLUDERE SEMPRE tranne se è GENNAIO (Mensile)
    # Se periodo include Gennaio ma è aggregato (es. Q1), escludiamo saldo iniziale dalle entrate per non falsare
    mostra_saldo_iniziale = (periodo_sel == "Mensile" and "Gen" in lista_mesi_target)
    
    if not mostra_saldo_iniziale:
        # Rimuove dai KPI
        ent_p = df_target_reale[(df_target_reale["Tipo"]=="Entrata") & (df_target_reale["Categoria"] != "SALDO INIZIALE")]["Importo"].sum()

    k1, k2, k3 = st.columns(3)
    k1.metric(f"Entrate ({periodo_sel})", f"{ent_p:,.2f} €")
    k2.metric(f"Uscite ({periodo_sel})", f"{usc_p:,.2f} €", delta_color="inverse")
    k3.metric("Saldo Periodo", f"{(ent_p-usc_p):,.2f} €")
    st.divider()

    # --- VISTAS ---
    vista = st.radio("Vista", ["📊 Confronto Budget vs Consuntivo", "📈 Trend Annuale"], horizontal=True)

    if vista == "📊 Confronto Budget vs Consuntivo":
        st.subheader(f"Analisi: {periodo_sel} {anno_sel}")
        
        # 1. Raggruppa Consuntivo (Reale)
        if not df_target_reale.empty:
            consuntivo = df_target_reale.groupby(["Categoria", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Reale"})
        else:
            consuntivo = pd.DataFrame(columns=["Categoria", "Tipo", "Reale"])

        # 2. Raggruppa Preventivo (Budget)
        preventivo = pd.DataFrame()
        if not df_budget.empty and "Mese" in df_budget.columns:
            # Filtra per i mesi target
            df_bud_filt = df_budget[df_budget["Mese"].isin(lista_mesi_target)]
            if not df_bud_filt.empty:
                # Somma gli importi per categoria (es. somma budget Gen+Feb+Mar)
                preventivo = df_bud_filt.groupby(["Categoria", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Budget"})

        # --- FILTRO SALDO INIZIALE (Logic: Remove unless Single Month Jan) ---
        if not mostra_saldo_iniziale:
            if not preventivo.empty: preventivo = preventivo[preventivo["Categoria"] != "SALDO INIZIALE"]
            if not consuntivo.empty: consuntivo = consuntivo[consuntivo["Categoria"] != "SALDO INIZIALE"]

        # 3. Merge
        if not preventivo.empty:
            df_merge = pd.merge(preventivo, consuntivo, on=["Categoria", "Tipo"], how="left").fillna(0)
        else:
            df_merge = consuntivo.copy()
            df_merge["Budget"] = 0.0
            if periodo_sel == "Mensile": st.warning(f"Budget non trovato per {lista_mesi_target[0]}")

        # Calcoli finali
        df_merge["Budget"] = pd.to_numeric(df_merge["Budget"]); df_merge["Reale"] = pd.to_numeric(df_merge["Reale"])
        df_merge["Delta"] = df_merge["Budget"] - df_merge["Reale"]
        
        # Visualizzazione Uscite
        st.markdown("### 🔴 Uscite")
        out = df_merge[df_merge["Tipo"]=="Uscita"].copy()
        if not out.empty:
            c_g, c_t = st.columns([1, 1.5])
            with c_g: 
                if out["Reale"].sum()>0: st.plotly_chart(px.pie(out, values='Reale', names='Categoria', hole=0.4, title="Spese Reali"), use_container_width=True)
                elif out["Budget"].sum()>0: st.plotly_chart(px.pie(out, values='Budget', names='Categoria', hole=0.4, title="Budget Previsto"), use_container_width=True)
            with c_t:
                st.dataframe(out[["Categoria", "Budget", "Reale", "Delta"]].sort_values("Budget", ascending=False).style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"]).map(style_variance_uscite, subset=["Delta"]), use_container_width=True)
        
        # Visualizzazione Entrate
        st.markdown("### 🟢 Entrate")
        inc = df_merge[df_merge["Tipo"]=="Entrata"].copy()
        if not inc.empty:
            inc["Delta"] = inc["Reale"] - inc["Budget"]
            st.dataframe(inc[["Categoria", "Budget", "Reale", "Delta"]].sort_values("Reale", ascending=False).style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"]).map(style_variance_entrate, subset=["Delta"]), use_container_width=True)

    elif vista == "📈 Trend Annuale":
        st.subheader("Andamento categorie durante l'anno")
        pivot = df_anno[df_anno["Tipo"]=="Uscita"].pivot_table(index="Categoria", columns="MeseNum", values="Importo", aggfunc="sum", fill_value=0).rename(columns=MAP_MESI)
        st.dataframe(pivot.style.format("{:.2f} €").background_gradient(cmap="Reds", axis=None), use_container_width=True)

with tab3:
    st.markdown("### Modifica Storico"); ed = st.data_editor(df_cloud, num_rows="dynamic")
    if st.button("AGGIORNA DB"):
        s = ed.copy(); s["Data"] = pd.to_datetime(s["Data"]).dt.strftime("%Y-%m-%d")
        conn.update(worksheet="DB_TRANSAZIONI", data=s); st.success("Fatto!"); st.rerun()
