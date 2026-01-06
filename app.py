import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox
import re
import uuid
import plotly.express as px
import plotly.graph_objects as go

# ==============================================================================
# 1. CONFIGURAZIONE PAGINA
# ==============================================================================
st.set_page_config(page_title="Piano Pluriennale", layout="wide", page_icon="☁️")

# Mappa Mesi per conversioni e visualizzazione
MAP_MESI = {
    1: 'Gen', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'Mag', 6: 'Giu',
    7: 'Lug', 8: 'Ago', 9: 'Set', 10: 'Ott', 11: 'Nov', 12: 'Dic'
}
MAP_NUM_MESI = {v: k for k, v in MAP_MESI.items()}

# --- 🧠 MAPPA PAROLE CHIAVE (IL CERVELLO) ---
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
# 2. CONNESSIONE AI FOGLI GOOGLE
# ==============================================================================
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("Errore connessione. Controlla i secrets!")
    st.stop()

# ==============================================================================
# 3. FUNZIONI DI CARICAMENTO E PULIZIA DATI
# ==============================================================================

@st.cache_data(ttl=60)
def get_categories():
    """Carica le categorie dal foglio '2026'."""
    try:
        df_cat = conn.read(worksheet="2026", usecols=[0, 2], header=None)
        
        # Estrazione e pulizia Entrate
        cat_entrate = df_cat.iloc[3:23, 0].dropna().unique().tolist()
        cat_entrate = sorted([str(x).strip() for x in cat_entrate if str(x).strip() != ""])
        
        # Estrazione e pulizia Uscite
        cat_uscite = df_cat.iloc[2:23, 1].dropna().unique().tolist()
        cat_uscite = sorted([str(x).strip() for x in cat_uscite if str(x).strip() != ""])
        
        # Aggiunta Default
        if "DA VERIFICARE" not in cat_entrate:
            cat_entrate.insert(0, "DA VERIFICARE")
        if "DA VERIFICARE" not in cat_uscite:
            cat_uscite.insert(0, "DA VERIFICARE")
        
        return cat_entrate, cat_uscite
    except Exception as e:
        return ["DA VERIFICARE"], ["DA VERIFICARE"]

CAT_ENTRATE, CAT_USCITE = get_categories()
LISTA_TUTTE = sorted(list(set(CAT_ENTRATE + CAT_USCITE)))


@st.cache_data(ttl=0) 
def get_budget_data():
    """Carica il budget dal foglio DB_BUDGET e normalizza i dati."""
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

        # --- NORMALIZZAZIONE MESE ---
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

        # --- NORMALIZZAZIONE TIPO ---
        def normalizza_tipo(val):
            val = str(val).strip().lower()
            if 'usc' in val or 'spes' in val: return 'Uscita'
            if 'ent' in val or 'ric' in val: return 'Entrata'
            return val.capitalize()

        if "Tipo" in df_bud.columns:
            df_bud["Tipo"] = df_bud["Tipo"].apply(normalizza_tipo)
            
        # --- FIX IMPORTI ---
        if "Importo" in df_bud.columns:
            def pulisci_numero(val):
                s = str(val).strip().replace('€', '')
                if '.' in s and ',' in s: 
                    s = s.replace('.', '').replace(',', '.')
                elif ',' in s: 
                    s = s.replace(',', '.')
                return s
            
            df_bud["Importo"] = df_bud["Importo"].apply(pulisci_numero)
            df_bud["Importo"] = pd.to_numeric(df_bud["Importo"], errors='coerce').fillna(0)
        
        return df_bud
    except:
        return pd.DataFrame()

# ==============================================================================
# 4. FUNZIONI UTILI (MAIL, GRAFICI, LOGICA)
# ==============================================================================

def trova_categoria_smart(descrizione, lista_categorie_disponibili):
    """Assegna una categoria in base alle parole chiave."""
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

def scarica_spese_da_gmail():
    """Legge la mail di Widiba e cerca transazioni."""
    nuove_transazioni = []
    mail_scartate = [] 
    
    if "email" not in st.secrets:
        st.error("Mancano i secrets per la mail!")
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

def style_delta(val, inverse=False):
    if inverse:
        color = 'green' if val >= 0 else 'red'
    else:
        color = 'red' if val < 0 else 'green'
    return f'color: {color}; font-weight: bold'

def genera_grafico_avanzato(df, tipo_grafico, col_valore, col_label, titolo, color_sequence):
    if df.empty or df[col_valore].sum() == 0:
        return None
    
    if tipo_grafico == "Torta (Donut)":
        fig = px.pie(df, values=col_valore, names=col_label, hole=0.4, title=titolo, color_discrete_sequence=color_sequence)
        fig.update_traces(textposition='inside', textinfo='percent+label')
        
    elif tipo_grafico == "Barre Orizzontali":
        fig = px.bar(df, x=col_valore, y=col_label, orientation='h', title=titolo, text_auto='.2s', color=col_valore, color_continuous_scale=color_sequence)
        fig.update_layout(yaxis={'categoryorder':'total ascending'})
        
    elif tipo_grafico == "Treemap (Mappa)":
        fig = px.treemap(df, path=[col_label], values=col_valore, title=titolo, color=col_valore, color_continuous_scale=color_sequence)
        
    else:
        return None
    
    return fig

def crea_tachimetro(valore, titolo, min_v=0, max_v=100, soglia_ok=50):
    fig = go.Figure(go.Indicator(
        mode = "gauge+number",
        value = valore,
        title = {'text': titolo, 'font': {'size': 14}},
        gauge = {
            'axis': {'range': [None, max_v]},
            'bar': {'color': "darkblue"},
            'steps': [
                {'range': [0, soglia_ok], 'color': "lightgray"},
                {'range': [soglia_ok, max_v], 'color': "lightgreen"}],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': valore}}))
    fig.update_layout(height=200, margin=dict(l=20, r=20, t=30, b=20))
    return fig

# ==============================================================================
# 5. AVVIO APPLICAZIONE E CARICAMENTO
# ==============================================================================
st.title("☁️ Piano Pluriennale 2026")

try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    df_cloud["Importo"] = pd.to_numeric(df_cloud["Importo"], errors='coerce').fillna(0)
    if "Categoria" in df_cloud.columns:
        df_cloud["Categoria"] = df_cloud["Categoria"].astype(str).str.strip()
except:
    df_cloud = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

if "df_mail_found" not in st.session_state: st.session_state["df_mail_found"] = pd.DataFrame()
if "df_mail_discarded" not in st.session_state: st.session_state["df_mail_discarded"] = pd.DataFrame()
if "df_manual_entry" not in st.session_state: st.session_state["df_manual_entry"] = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

# ==============================================================================
# 6. DEFINIZIONE TABS PRINCIPALI
# ==============================================================================
tab_bil, tab_kpi, tab_graf, tab_imp, tab_stor = st.tabs([
    "📑 BILANCIO", 
    "📈 INDICI & KPI", 
    "📊 ANALISI GRAFICA", 
    "📥 IMPORTA", 
    "🗂 STORICO"
])

# ==============================================================================
# TAB 1: RIEPILOGO & BILANCIO
# ==============================================================================
with tab_bil:
    df_budget_b = get_budget_data()
    df_analysis_b = df_cloud.copy()
    df_analysis_b["Anno"] = df_analysis_b["Data"].dt.year
    df_analysis_b["MeseNum"] = df_analysis_b["Data"].dt.month
    
    st.markdown("### 🏦 Bilancio di Esercizio")
    
    cb1, cb2, cb3 = st.columns(3)
    with cb1: anno_b = st.selectbox("📅 Anno Riferimento", sorted(df_analysis_b["Anno"].unique(), reverse=True) if not df_analysis_b.empty else [2026], key="a_bil")
    with cb2: per_b = st.selectbox("📊 Periodo", ["Mensile", "Trimestrale", "Semestrale", "Annuale"], key="p_bil")
    
    l_mesi_b = []
    l_num_b = []
    
    with cb3:
        if per_b == "Mensile":
            m = st.selectbox("Mese", list(MAP_MESI.values()), index=datetime.now().month-1, key="m_bil")
            l_mesi_b = [m]
            l_num_b = [MAP_NUM_MESI[m]]
        elif per_b == "Trimestrale":
            t = st.selectbox("Trimestre", ["Q1 (Gen-Mar)", "Q2 (Apr-Giu)", "Q3 (Lug-Set)", "Q4 (Ott-Dic)"], key="t_bil")
            if "Q1" in t: l_num_b = [1, 2, 3]
            elif "Q2" in t: l_num_b = [4, 5, 6]
            elif "Q3" in t: l_num_b = [7, 8, 9]
            else: l_num_b = [10, 11, 12]
            l_mesi_b = [MAP_MESI[n] for n in l_num_b]
        elif per_b == "Semestrale":
            s = st.selectbox("Semestre", ["Semestre 1 (Gen-Giu)", "Semestre 2 (Lug-Dic)"], key="s_bil")
            if "1" in s: l_num_b = [1, 2, 3, 4, 5, 6]
            else: l_num_b = [7, 8, 9, 10, 11, 12]
            l_mesi_b = [MAP_MESI[n] for n in l_num_b]
        elif per_b == "Annuale":
            st.write("Tutto l'anno")
            l_num_b = list(range(1, 13))
            l_mesi_b = list(MAP_MESI.values())

    # Calcolo Dati Reali
    reale_raw = df_analysis_b[(df_analysis_b["Anno"] == anno_b) & (df_analysis_b["MeseNum"].isin(l_num_b))]
    if not reale_raw.empty:
        consuntivo_b = reale_raw.groupby(["Categoria", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Reale"})
    else:
        consuntivo_b = pd.DataFrame(columns=["Categoria", "Tipo", "Reale"])
    
    # Calcolo Dati Budget
    preventivo_b = pd.DataFrame()
    if not df_budget_b.empty and "Mese" in df_budget_b.columns:
        b_raw = df_budget_b[df_budget_b["Mese"].isin(l_mesi_b)]
        if not b_raw.empty:
            preventivo_b = b_raw.groupby(["Categoria", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Budget"})

    # Unione dati
    bilancio = pd.merge(preventivo_b, consuntivo_b, on=["Categoria", "Tipo"], how="outer").fillna(0)
    if "Budget" not in bilancio.columns: bilancio["Budget"] = 0.0
    if "Reale" not in bilancio.columns: bilancio["Reale"] = 0.0

    # Estrazione Valori Chiave
    saldo_ini_row = bilancio[bilancio["Categoria"] == "SALDO INIZIALE"]
    saldo_ini_bud = saldo_ini_row["Budget"].sum()
    saldo_ini_real = saldo_ini_row["Reale"].sum()
    
    is_gennaio_incluso = "Gen" in l_mesi_b
    if is_gennaio_incluso and saldo_ini_real == 0:
        saldo_ini_real = saldo_ini_bud

    ent_op_df = bilancio[(bilancio["Tipo"]=="Entrata") & (bilancio["Categoria"]!="SALDO INIZIALE")]
    ent_op_bud = ent_op_df["Budget"].sum()
    ent_op_real = ent_op_df["Reale"].sum()

    usc_op_df = bilancio[bilancio["Tipo"]=="Uscita"]
    usc_op_bud = usc_op_df["Budget"].sum()
    usc_op_real = usc_op_df["Reale"].sum()

    utile_bud = ent_op_bud - usc_op_bud
    utile_real = ent_op_real - usc_op_real
    saldo_fin_bud = saldo_ini_bud + utile_bud
    saldo_fin_real = saldo_ini_real + utile_real

    # Display Metriche
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("💰 Saldo Iniziale (Reale)", f"{saldo_ini_real:,.2f} €", delta=f"Budget: {saldo_ini_bud:,.2f} €", delta_color="off")
    m2.metric("📈 Entrate Operative (Reale)", f"{ent_op_real:,.2f} €", delta=f"{(ent_op_real-ent_op_bud):,.2f} € vs Budget")
    m3.metric("📉 Uscite Totali (Reale)", f"{usc_op_real:,.2f} €", delta=f"{(usc_op_bud-usc_op_real):,.2f} € vs Budget", delta_color="inverse")
    m4.metric("🏁 Saldo Finale (Reale)", f"{saldo_fin_real:,.2f} €", delta=f"Utile Periodo: {utile_real:,.2f} €")
    
    st.divider()

    col_schemino_sx, col_schemino_dx = st.columns(2)
    with col_schemino_sx:
        st.subheader("🟢 Dettaglio Entrate")
        df_e_view = ent_op_df[["Categoria", "Budget", "Reale"]].copy()
        df_e_view["Delta"] = df_e_view["Reale"] - df_e_view["Budget"]
        st.dataframe(
            df_e_view.sort_values("Reale", ascending=False)
            .style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
            .map(lambda v: style_delta(v), subset=["Delta"]), 
            use_container_width=True
        )
        st.info(f"**Totale Entrate Operative:** {ent_op_real:,.2f} € (Budget: {ent_op_bud:,.2f} €)")

    with col_schemino_dx:
        st.subheader("🔴 Dettaglio Uscite")
        df_u_view = usc_op_df[["Categoria", "Budget", "Reale"]].copy()
        df_u_view["Delta"] = df_u_view["Budget"] - df_u_view["Reale"]
        st.dataframe(
            df_u_view.sort_values("Reale", ascending=False)
            .style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
            .map(lambda v: style_delta(v, inverse=True), subset=["Delta"]), 
            use_container_width=True
        )
        st.info(f"**Totale Uscite:** {usc_op_real:,.2f} € (Budget: {usc_op_bud:,.2f} €)")

    st.markdown("---")
    st.markdown(f"### 💡 Risultato Netto del Periodo (Utile): **{utile_real:+,.2f} €**")

# ==============================================================================
# TAB 2: INDICI & KPI
# ==============================================================================
with tab_kpi:
    st.markdown("### 🚀 Cruscotto Indici Finanziari")
    
    # Configurazione Target
    col_target, col_legenda = st.columns([1, 3])
    with col_target:
        target_patrimoniale = st.number_input("🎯 Obiettivo Annuale (€)", value=10000.0, step=500.0, help="Inserisci il saldo finale che vuoi raggiungere entro fine anno")
    
    with col_legenda:
        with st.expander("ℹ️ Spiegazione Indici (Legenda)"):
            st.markdown("""
            * **ROE (Rendimento):** Rendimento sulle risorse disponibili. `(Saldo Fin - Saldo Ini) / (Saldo Ini + Entrate)`.
            * **Growth (Crescita):** Crescita patrimonio. `(Saldo Fin - Saldo Ini) / Saldo Ini`.
            * **IER (Risparmio):** Efficienza annuale. `Utile / Entrate`.
            * **IER Giornaliero:** Efficienza ad oggi. `Saldo Attuale / (Saldo Ini + Entrate)`.
            * **IAT (Target):** Avanzamento obiettivo. `(Saldo Fin - Saldo Ini) / (Target - Saldo Ini)`.
            * **IPP (Performance):** Indice combinato di progresso ed efficienza.
            """)

    # Calcoli Annuali per KPI
    df_ana_k = df_cloud[df_cloud["Data"].dt.year == datetime.now().year]
    
    # Saldo Iniziale Anno (Gennaio)
    bud_g = get_budget_data()
    saldo_ini_anno = 0.0
    if not bud_g.empty:
        saldo_ini_anno = bud_g[(bud_g["Mese"]=="Gen") & (bud_g["Categoria"]=="SALDO INIZIALE")]["Importo"].sum()
    
    ent_tot_anno = df_ana_k[(df_ana_k["Tipo"]=="Entrata") & (df_ana_k["Categoria"]!="SALDO INIZIALE")]["Importo"].sum()
    usc_tot_anno = df_ana_k[df_ana_k["Tipo"]=="Uscita"]["Importo"].sum()
    utile_anno = ent_tot_anno - usc_tot_anno
    saldo_fin_anno = saldo_ini_anno + utile_anno
    
    risorse_disp = saldo_ini_anno + ent_tot_anno
    
    # --- FORMULE KPI ---
    
    # 1. ROE
    roe = ((saldo_fin_anno - saldo_ini_anno) / risorse_disp * 100) if risorse_disp > 0 else 0
    
    # 2. IER (Annuale)
    ier = (utile_anno / ent_tot_anno * 100) if ent_tot_anno > 0 else 0
    
    # 3. Growth
    growth = ((saldo_fin_anno - saldo_ini_anno) / saldo_ini_anno * 100) if saldo_ini_anno > 0 else 0
    
    # 4. IAT
    delta_target = target_patrimoniale - saldo_ini_anno
    iat = ((saldo_fin_anno - saldo_ini_anno) / delta_target * 100) if delta_target > 0 else 0
    
    # 5. IAT Lineare
    iat_lineare = (datetime.now().month / 12) * 100

    # 6. IER Giornaliero (NUOVO)
    # Saldo Attuale / (Saldo Iniziale + Entrate Cumulative)
    ier_giornaliero = (saldo_fin_anno / risorse_disp * 100) if risorse_disp > 0 else 0

    # 7. IPP (NUOVO)
    # (Avanzamento Target %) * (Efficienza Risorse %)
    term_iat = (saldo_fin_anno - saldo_ini_anno) / delta_target if delta_target > 0 else 0
    term_eff = saldo_fin_anno / risorse_disp if risorse_disp > 0 else 0
    ipp = term_iat * term_eff * 100

    # --- VISUALIZZAZIONE KPI ---
    
    # Riga 1: Indici Generali
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("ROE (Rendimento)", f"{roe:.2f}%", help="Rendimento sul capitale disponibile")
    k2.metric("Growth (Crescita)", f"{growth:.2f}%", help="Crescita pura del patrimonio")
    k3.metric("IER (Risparmio)", f"{ier:.2f}%", help="Utile / Entrate")
    k4.metric("IAT (Target)", f"{iat:.2f}%", delta=f"{iat-iat_lineare:.1f}% vs Lineare", help="Avanzamento verso l'obiettivo annuale")
    
    # Riga 2: Indici Avanzati (NUOVI)
    st.divider()
    ka1, ka2 = st.columns(2)
    ka1.metric("IER Giornaliero", f"{ier_giornaliero:.2f}%", help="Efficienza risorse ad oggi: Saldo Attuale / Risorse Totali")
    ka2.metric("IPP (Performance)", f"{ipp:.2f}", help="Indice combinato: Avanzamento Target * Efficienza Risorse")
    
    st.divider()
    
    # Grafici Gauge
    gc1, gc2 = st.columns(2)
    with gc1:
        st.plotly_chart(crea_tachimetro(ier, "Efficienza Risparmio (IER)", max_v=50, soglia_ok=20), use_container_width=True)
    with gc2:
        st.plotly_chart(crea_tachimetro(iat, "Avanzamento Obiettivo (IAT)", max_v=100, soglia_ok=iat_lineare), use_container_width=True)

# ==============================================================================
# TAB 3: ANALISI GRAFICA AVANZATA
# ==============================================================================
with tab_graf:
    df_budget_g, df_analysis_g = get_budget_data(), df_cloud.copy()
    df_analysis_g["Anno"], df_analysis_g["MeseNum"] = df_analysis_g["Data"].dt.year, df_analysis_g["Data"].dt.month
    
    c1, c2, c3 = st.columns(3)
    with c1: anno_g = st.selectbox("📅 Anno", sorted(df_analysis_g["Anno"].unique(), reverse=True) if not df_analysis_g.empty else [2026], key="a_graf")
    with c2: per_g = st.selectbox("📊 Periodo", ["Mensile", "Trimestrale", "Semestrale", "Annuale"], key="p_graf")
    
    l_mesi_g, l_num_g = [], []
    with c3:
        if per_g == "Mensile":
            m = st.selectbox("Mese", list(MAP_MESI.values()), index=datetime.now().month-1, key="m_graf")
            l_mesi_g, l_num_g = [m], [MAP_NUM_MESI[m]]
        elif per_g == "Trimestrale":
            t = st.selectbox("Trimestre", ["Q1 (Gen-Mar)", "Q2 (Apr-Giu)", "Q3 (Lug-Set)", "Q4 (Ott-Dic)"], key="t_graf")
            l_num_g = [1,2,3] if "Q1" in t else [4,5,6] if "Q2" in t else [7,8,9] if "Q3" in t else [10,11,12]
            l_mesi_g = [MAP_MESI[n] for n in l_num_g]
        elif per_g == "Semestrale":
            s = st.selectbox("Semestre", ["Semestre 1 (Gen-Giu)", "Semestre 2 (Lug-Dic)"], key="s_graf")
            l_num_g = range(1,7) if "1" in s else range(7,13)
            l_mesi_g = [MAP_MESI[n] for n in l_num_g]
        elif per_g == "Annuale":
            st.write("Tutto l'anno")
            l_num_g = list(range(1, 13))
            l_mesi_g = list(MAP_MESI.values())

    df_filt_g = df_analysis_g[(df_analysis_g["Anno"] == anno_g) & (df_analysis_g["MeseNum"].isin(l_num_g))]
    
    cons_g = df_filt_g.groupby(["Categoria", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Reale"}) if not df_filt_g.empty else pd.DataFrame(columns=["Categoria", "Tipo", "Reale"])
    
    prev_g = pd.DataFrame()
    if not df_budget_g.empty and "Mese" in df_budget_g.columns:
        b_filt_g = df_budget_g[df_budget_g["Mese"].isin(l_mesi_g)]
        if not b_filt_g.empty:
            prev_g = b_filt_g.groupby(["Categoria", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Budget"})

    # Esclusione Saldo Iniziale dai grafici
    if not prev_g.empty: prev_g = prev_g[prev_g["Categoria"] != "SALDO INIZIALE"]
    if not cons_g.empty: cons_g = cons_g[cons_g["Categoria"] != "SALDO INIZIALE"]

    merged_g = pd.merge(prev_g, cons_g, on=["Categoria", "Tipo"], how="left").fillna(0) if not prev_g.empty else cons_g.copy()
    if "Budget" not in merged_g.columns: merged_g["Budget"] = 0.0
    merged_g["Delta"] = merged_g["Budget"] - merged_g["Reale"]

    st.markdown("#### 🎨 Configurazione")
    cg1, cg2 = st.columns(2)
    with cg1: source_data = st.radio("Sorgente:", ["Reale", "Budget"], horizontal=True)
    with cg2: chart_type = st.selectbox("Grafico:", ["Torta (Donut)", "Barre Orizzontali", "Treemap (Mappa)"])
    col_val = "Reale" if "Reale" in source_data else "Budget"

    cl, cr = st.columns(2)
    
    out_g = merged_g[merged_g["Tipo"]=="Uscita"].copy()
    with cl:
        st.markdown(f"### 🔴 Uscite ({col_val})")
        if not out_g.empty:
            fig = genera_grafico_avanzato(out_g, chart_type, col_val, "Categoria", "Uscite", px.colors.sequential.RdBu)
            if fig: st.plotly_chart(fig, use_container_width=True)
            st.dataframe(
                out_g[["Categoria", "Budget", "Reale", "Delta"]]
                .sort_values("Budget", ascending=False)
                .style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
                .map(lambda v: style_delta(v, inverse=True), subset=["Delta"]),
                use_container_width=True
            )
    
    inc_g = merged_g[merged_g["Tipo"]=="Entrata"].copy()
    with cr:
        st.markdown(f"### 🟢 Entrate ({col_val})")
        if not inc_g.empty:
            fig = genera_grafico_avanzato(inc_g, chart_type, col_val, "Categoria", "Entrate", px.colors.sequential.Teal)
            if fig: st.plotly_chart(fig, use_container_width=True)
            st.dataframe(
                inc_g[["Categoria", "Budget", "Reale", "Delta"]]
                .sort_values("Reale", ascending=False)
                .style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
                .map(lambda v: style_delta(v), subset=["Delta"]),
                use_container_width=True
            )

# ==============================================================================
# TAB 4: IMPORTA (GESTIONE MAIL E MANUALE)
# ==============================================================================
with tab_imp:
    col_search, col_actions = st.columns([1, 4])
    with col_search:
        if st.button("🔎 Cerca Mail", type="primary"):
            with st.spinner("Analisi mail in corso..."):
                df_mail, df_scartate = scarica_spese_da_gmail()
                st.session_state["df_mail_found"] = df_mail
                st.session_state["df_mail_discarded"] = df_scartate
    
    st.divider()

    # Visualizzazione Mail Scartate
    if not st.session_state["df_mail_discarded"].empty:
        with st.expander(f"⚠️ {len(st.session_state['df_mail_discarded'])} Mail Scartate", expanded=True):
            st.dataframe(st.session_state["df_mail_discarded"][["Data", "Descrizione"]], use_container_width=True, hide_index=True)
            if st.button("⬇️ Recupera e Correggi Manualmente"):
                recuperate = st.session_state["df_mail_discarded"].copy()
                st.session_state["df_manual_entry"] = pd.concat([st.session_state["df_manual_entry"], recuperate], ignore_index=True)
                st.session_state["df_mail_discarded"] = pd.DataFrame()
                st.rerun()

    # Visualizzazione Mail Trovate (Separata)
    df_new = st.session_state["df_mail_found"]
    
    df_view_entrate = pd.DataFrame()
    df_view_uscite = pd.DataFrame()
    
    if not df_new.empty:
        exist = df_cloud["Firma"].astype(str).tolist() if "Firma" in df_cloud.columns else []
        df_new = df_new[~df_new["Firma"].astype(str).isin(exist)]
        
        df_view_entrate = df_new[df_new["Tipo"] == "Entrata"]
        df_view_uscite = df_new[df_new["Tipo"] == "Uscita"]

    st.markdown("##### 💰 Nuove Entrate")
    if not df_view_entrate.empty:
        ed_ent = st.data_editor(
            df_view_entrate,
            column_config={"Categoria": st.column_config.SelectboxColumn(options=CAT_ENTRATE)},
            key="k_ent", use_container_width=True
        )
    else:
        ed_ent = pd.DataFrame()
        st.info("Nessuna nuova entrata trovata.")

    st.markdown("##### 💸 Nuove Uscite")
    if not df_view_uscite.empty:
        ed_usc = st.data_editor(
            df_view_uscite,
            column_config={"Categoria": st.column_config.SelectboxColumn(options=CAT_USCITE)},
            key="k_usc", use_container_width=True
        )
    else:
        ed_usc = pd.DataFrame()
        st.info("Nessuna nuova uscita trovata.")

    st.markdown("---")
    st.markdown("##### ✍️ Manuale / Correzioni")
    
    # Editor Manuale
    ed_man = st.data_editor(
        st.session_state["df_manual_entry"],
        num_rows="dynamic",
        column_config={"Categoria": st.column_config.SelectboxColumn(options=sorted(CAT_USCITE + CAT_ENTRATE))},
        key="edit_manual", use_container_width=True
    )

    if st.button("💾 SALVA TUTTO", type="primary"):
        save_list = []
        if not ed_ent.empty: save_list.append(ed_ent)
        if not ed_usc.empty: save_list.append(ed_usc)
        if not ed_man.empty:
            v = ed_man[ed_man["Importo"] > 0].copy()
            if not v.empty:
                v["Data"] = pd.to_datetime(v["Data"])
                v["Mese"] = v["Data"].dt.strftime('%b-%y')
                v["Firma"] = [f"MAN-{uuid.uuid4().hex[:6]}" for _ in range(len(v))]
                save_list.append(v)
        
        if save_list:
            fin = pd.concat([df_cloud] + save_list, ignore_index=True)
            fin["Data"] = pd.to_datetime(fin["Data"]).dt.strftime("%Y-%m-%d")
            conn.update(worksheet="DB_TRANSAZIONI", data=fin)
            st.session_state["df_mail_found"] = pd.DataFrame()
            st.session_state["df_manual_entry"] = pd.DataFrame()
            st.session_state["df_mail_discarded"] = pd.DataFrame()
            st.balloons()
            st.success("✅ Tutto salvato correttamente!")
            st.rerun()

# ==============================================================================
# TAB 5: STORICO (DB COMPLETO)
# ==============================================================================
with tab_stor:
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
