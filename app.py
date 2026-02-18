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
st.set_page_config(
    page_title="Piano Pluriennale",
    layout="wide",
    page_icon="☁️"
)

# Mappa Mesi Completa
MAP_MESI = {
    1: 'Gen', 
    2: 'Feb', 
    3: 'Mar', 
    4: 'Apr', 
    5: 'Mag', 
    6: 'Giu',
    7: 'Lug', 
    8: 'Ago', 
    9: 'Set', 
    10: 'Ott', 
    11: 'Nov', 
    12: 'Dic'
}
MAP_NUM_MESI = {v: k for k, v in MAP_MESI.items()}

# --- 🧠 MAPPA PAROLE CHIAVE (ESPLOSA) ---
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
    "netflix": "VARIE", 
    "spotify": "SPOTIFY", 
    "dazn": "VARIE", 
    "disney": "VARIE",
    "farmacia": "VARIE", 
    "medico": "VARIE", 
    "ticket": "VARIE",
    "ICM": "CARBURANTE",
    "TAMOIL": "CARBURANTE"
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
        
        # Pulizia Entrate (Ciclo For Esplicito)
        raw_entrate = df_cat.iloc[3:23, 0].dropna().unique().tolist()
        cat_entrate = []
        for x in raw_entrate:
            valore_pulito = str(x).strip()
            if valore_pulito != "":
                cat_entrate.append(valore_pulito)
        cat_entrate.sort()
        
        # Pulizia Uscite (Ciclo For Esplicito)
        raw_uscite = df_cat.iloc[2:23, 1].dropna().unique().tolist()
        cat_uscite = []
        for x in raw_uscite:
            valore_pulito = str(x).strip()
            if valore_pulito != "":
                cat_uscite.append(valore_pulito)
        cat_uscite.sort()
        
        # Aggiunta Default se mancano
        if "DA VERIFICARE" not in cat_entrate:
            cat_entrate.insert(0, "DA VERIFICARE")
        
        if "DA VERIFICARE" not in cat_uscite:
            cat_uscite.insert(0, "DA VERIFICARE")
        
        return cat_entrate, cat_uscite
    except Exception as e:
        # Fallback in caso di errore
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

        # Funzione Normalizzazione Mese
        def normalizza_mese(val):
            v = str(val).strip().lower()
            if v.startswith('gen') or v in ['1', '01']: return 'Gen'
            if v.startswith('feb') or v in ['2', '02']: return 'Feb'
            if v.startswith('mar') or v in ['3', '03']: return 'Mar'
            if v.startswith('apr') or v in ['4', '04']: return 'Apr'
            if v.startswith('mag') or v in ['5', '05']: return 'Mag'
            if v.startswith('giu') or v in ['6', '06']: return 'Giu'
            if v.startswith('lug') or v in ['7', '07']: return 'Lug'
            if v.startswith('ago') or v in ['8', '08']: return 'Ago'
            if v.startswith('set') or v in ['9', '09']: return 'Set'
            if v.startswith('ott') or v == '10': return 'Ott'
            if v.startswith('nov') or v == '11': return 'Nov'
            if v.startswith('dic') or v == '12': return 'Dic'
            return v.capitalize()

        if "Mese" in df_bud.columns:
            df_bud["Mese"] = df_bud["Mese"].apply(normalizza_mese)

        # Funzione Normalizzazione Tipo
        def normalizza_tipo(val):
            v = str(val).strip().lower()
            if 'usc' in v or 'spes' in v:
                return 'Uscita'
            if 'ent' in v or 'ric' in v:
                return 'Entrata'
            return v.capitalize()

        if "Tipo" in df_bud.columns:
            df_bud["Tipo"] = df_bud["Tipo"].apply(normalizza_tipo)
            
        # Funzione Fix Importi
        if "Importo" in df_bud.columns:
            def pulisci_numero(val):
                s = str(val).strip().replace('€', '')
                if '.' in s and ',' in s: 
                    # Caso 1.000,00 -> togli punto, cambia virgola in punto
                    s = s.replace('.', '').replace(',', '.')
                elif ',' in s: 
                    # Caso 100,00 -> cambia virgola in punto
                    s = s.replace(',', '.')
                return s
            
            df_bud["Importo"] = df_bud["Importo"].apply(pulisci_numero)
            df_bud["Importo"] = pd.to_numeric(df_bud["Importo"], errors='coerce').fillna(0)
        
        return df_bud
    except:
        return pd.DataFrame()

# ==============================================================================
# 4. FUNZIONI UTILI (MAIL, GRAFICI, LOGICA, COLORI)
# ==============================================================================

def trova_categoria_smart(descrizione, lista_categorie_disponibili):
    """Assegna una categoria in base alle parole chiave."""
    desc_lower = descrizione.lower()
    
    # 1. Controllo Keyword Dirette
    for parola_chiave, target_categoria in MAPPA_KEYWORD.items():
        if parola_chiave in desc_lower:
            # Verifico se la categoria target esiste nella lista disponibile
            for cat in lista_categorie_disponibili:
                if target_categoria.lower() in cat.lower():
                    return cat
                    
    # 2. Controllo Corrispondenza Nome Categoria
    for cat in lista_categorie_disponibili:
        if cat.lower() in desc_lower:
            return cat
            
    return "DA VERIFICARE"

def scarica_spese_da_gmail():
    """Legge la mail, riconosce Stipendio, PayPal e Rata Auto (tramite IBAN)."""
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
            # mark_seen=False -> NON segna la mail come letta
            for msg in mailbox.fetch(limit=50, reverse=True, mark_seen=False): 
                
                soggetto = msg.subject
                corpo = msg.text or msg.html
                corpo_clean = " ".join(corpo.split())
                
                # Filtro: deve esserci 'widiba' (case insensitive)
                if "widiba" not in corpo_clean.lower() and "widiba" not in soggetto.lower():
                      continue

                importo = 0.0
                tipo = "Uscita" # Default
                descrizione = "Transazione Generica"
                categoria_suggerita = "DA VERIFICARE"
                trovato = False

                # --- 1. REGEX USCITE ---
                regex_uscite = [
                    r'(?:pagamento|prelievo|addebito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:presso|per|a favore di|su)\s+(.*?)(?:\.|$)',
                    r'ha\s+prelevato\s+([\d.,]+)\s+euro.*?(?:presso)\s+(.*?)(?:\.|$)'
                ]
                
                # --- 2. REGEX ENTRATE ---
                regex_entrate_data = [
                    (r'(?:accredito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:per|da|a favore di)\s+(.*?)(?:\.|$)', 1, 2),
                    (r'accredito\s+per\s+(.*?)\s+di\s+([\d.,]+)\s+euro', 2, 1),
                    (r'hai\s+ricevuto\s+([\d.,]+)\s+euro\s+da\s+(.*?)(?:\.|$)', 1, 2)
                ]

                # A. Cerca nelle USCITE
                for rx in regex_uscite:
                    match = re.search(rx, corpo_clean, re.IGNORECASE)
                    if match:
                        importo_str = match.group(1)
                        desc_temp = match.group(2).strip()
                        importo = float(importo_str.replace('.', '').replace(',', '.'))
                        tipo = "Uscita"
                        descrizione = desc_temp
                        
                        # --- MODIFICA SPECIFICA RATA AUTO ---
                        # Se c'è l'IBAN della rata, sovrascriviamo la descrizione
                        if "IT77J0338501601100000720458" in corpo_clean:
                            descrizione = "Rata Auto"
                            # Se vuoi assegnare una categoria automatica, scommenta la riga sotto:
                            # categoria_suggerita = "AUTO" o "DEBITI"
                        
                        if categoria_suggerita == "DA VERIFICARE":
                             categoria_suggerita = trova_categoria_smart(descrizione, CAT_USCITE)
                             
                        trovato = True
                        break 

                # B. Cerca nelle ENTRATE (se non è un'uscita)
                if not trovato:
                    for rx_data in regex_entrate_data:
                        rx_pattern = rx_data[0]
                        idx_imp = rx_data[1]
                        idx_desc = rx_data[2]
                        
                        match = re.search(rx_pattern, corpo_clean, re.IGNORECASE)
                        if match:
                            importo_str = match.group(idx_imp)
                            desc_temp = match.group(idx_desc).strip()
                            
                            importo = float(importo_str.replace('.', '').replace(',', '.'))
                            tipo = "Entrata"
                            descrizione = desc_temp
                            
                            if "paypal" in corpo_clean.lower():
                                descrizione = f"PayPal - {descrizione}"
                                
                            categoria_suggerita = trova_categoria_smart(descrizione, CAT_ENTRATE)
                            trovato = True
                            break

                # C. Salvataggio o Scarto
                if trovato:
                    firma_univoca = f"{msg.date.strftime('%Y%m%d')}-{importo}-{descrizione[:10]}"
                    transazione = {
                        "Data": msg.date.strftime("%Y-%m-%d"),
                        "Descrizione": descrizione,
                        "Importo": importo,
                        "Tipo": tipo,
                        "Categoria": categoria_suggerita, 
                        "Mese": msg.date.strftime('%b-%y'),
                        "Firma": firma_univoca
                    }
                    nuove_transazioni.append(transazione)
                else:
                    firma_errore = f"ERR-{msg.date.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
                    scartata = {
                        "Data": msg.date.strftime("%Y-%m-%d"),
                        "Descrizione": soggetto,
                        "Importo": 0.0,
                        "Tipo": "Uscita",
                        "Categoria": "DA VERIFICARE",
                        "Mese": msg.date.strftime('%b-%y'),
                        "Firma": firma_errore
                    }
                    mail_scartate.append(scartata)
                    
    except Exception as e:
        st.error(f"Errore lettura mail: {e}")
        
    return pd.DataFrame(nuove_transazioni), pd.DataFrame(mail_scartate)
def style_delta_standard(val):
    """
    Stile per Entrate e Utile:
    - Positivo (>= 0) -> Verde
    - Negativo (< 0) -> Rosso
    """
    if val >= 0:
        return 'color: green; font-weight: bold'
    else:
        return 'color: red; font-weight: bold'

def style_delta_spese(val):
    """
    Stile per Uscite (Logica Risparmio):
    - Positivo (Budget > Reale, ho risparmiato) -> Verde
    - Negativo (Budget < Reale, ho sforato) -> Rosso
    """
    if val >= 0:
        return 'color: green; font-weight: bold'
    else:
        return 'color: red; font-weight: bold'

def genera_grafico_avanzato(df, tipo_grafico, col_valore, col_label, titolo, color_sequence):
    """Genera il grafico in base al selettore dell'utente."""
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
    """Crea un grafico Gauge (tachimetro)."""
    fig = go.Figure(go.Indicator(
        mode = "gauge+number",
        value = valore,
        title = {'text': titolo, 'font': {'size': 14}},
        gauge = {
            'axis': {'range': [None, max_v]},
            'bar': {'color': "darkblue"},
            'steps': [
                {'range': [0, soglia_ok], 'color': "lightgray"},
                {'range': [soglia_ok, max_v], 'color': "lightgreen"}
            ],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': valore
            }
        }
    ))
    fig.update_layout(height=200, margin=dict(l=20, r=20, t=30, b=20))
    return fig

# ==============================================================================
# 5. CARICAMENTO DATI INIZIALE
# ==============================================================================
st.title("☁️ Piano Pluriennale 2026")

try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    df_cloud["Importo"] = pd.to_numeric(df_cloud["Importo"], errors='coerce').fillna(0)
    
    # Pulizia Categoria
    if "Categoria" in df_cloud.columns:
        df_cloud["Categoria"] = df_cloud["Categoria"].astype(str).str.strip()
    
    # --- FIX CRITICO: AGGIUNTA COLONNE GLOBALI PER EVITARE KEYERROR ---
    if not df_cloud.empty and "Data" in df_cloud.columns:
        df_cloud["Anno"] = df_cloud["Data"].dt.year
        df_cloud["MeseNum"] = df_cloud["Data"].dt.month
    else:
        # Se il DB è vuoto, inizializza colonne vuote
        df_cloud["Anno"] = 2026
        df_cloud["MeseNum"] = 1

except Exception as e:
    st.error(f"Errore caricamento DB: {e}")
    df_cloud = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma", "Anno", "MeseNum"])

# Inizializzazione Session State
if "df_mail_found" not in st.session_state:
    st.session_state["df_mail_found"] = pd.DataFrame()
if "df_mail_discarded" not in st.session_state:
    st.session_state["df_mail_discarded"] = pd.DataFrame()
if "df_manual_entry" not in st.session_state:
    st.session_state["df_manual_entry"] = pd.DataFrame(columns=["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese", "Firma"])

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
    # 1. Caricamento Dati
    df_budget_b = get_budget_data()
    # Usiamo una copia locale per non toccare il globale
    df_analysis_b = df_cloud.copy()
    
    st.markdown("### 🏦 Bilancio di Esercizio")
    
    # 2. Selettori Periodo
    cb1, cb2, cb3 = st.columns(3)
    with cb1:
        lista_anni = sorted(df_analysis_b["Anno"].unique(), reverse=True)
        if not lista_anni: lista_anni = [2026]
        anno_b = st.selectbox("📅 Anno Riferimento", lista_anni, key="a_bil")
    with cb2:
        per_b = st.selectbox("📊 Periodo", ["Mensile", "Trimestrale", "Semestrale", "Annuale"], key="p_bil")
    
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

    # 3. Calcoli Dati Reali
    reale_raw = df_analysis_b[(df_analysis_b["Anno"] == anno_b) & (df_analysis_b["MeseNum"].isin(l_num_b))]
    if not reale_raw.empty:
        consuntivo_b = reale_raw.groupby(["Categoria", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Reale"})
    else:
        consuntivo_b = pd.DataFrame(columns=["Categoria", "Tipo", "Reale"])
    
    # 4. Calcoli Dati Budget
    preventivo_b = pd.DataFrame()
    if not df_budget_b.empty and "Mese" in df_budget_b.columns:
        b_raw = df_budget_b[df_budget_b["Mese"].isin(l_mesi_b)]
        if not b_raw.empty:
            preventivo_b = b_raw.groupby(["Categoria", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Budget"})

    # 5. Merge
    bilancio = pd.merge(preventivo_b, consuntivo_b, on=["Categoria", "Tipo"], how="outer").fillna(0)
    if "Budget" not in bilancio.columns: bilancio["Budget"] = 0.0
    if "Reale" not in bilancio.columns: bilancio["Reale"] = 0.0

    # 6. Estrazione Valori Chiave
    # Saldo Iniziale
    saldo_ini_row = bilancio[bilancio["Categoria"] == "SALDO INIZIALE"]
    saldo_ini_bud = saldo_ini_row["Budget"].sum()
    saldo_ini_real = saldo_ini_row["Reale"].sum()
    
    # Logica Fix Saldo Iniziale Gennaio
    is_gennaio_incluso = "Gen" in l_mesi_b
    if is_gennaio_incluso and saldo_ini_real == 0:
        saldo_ini_real = saldo_ini_bud

    # Entrate Operative
    ent_op_df = bilancio[(bilancio["Tipo"]=="Entrata") & (bilancio["Categoria"]!="SALDO INIZIALE")]
    ent_op_bud = ent_op_df["Budget"].sum()
    ent_op_real = ent_op_df["Reale"].sum()

    # Uscite Operative
    usc_op_df = bilancio[bilancio["Tipo"]=="Uscita"]
    usc_op_bud = usc_op_df["Budget"].sum()
    usc_op_real = usc_op_df["Reale"].sum()

    # Utile
    utile_bud = ent_op_bud - usc_op_bud
    utile_real = ent_op_real - usc_op_real
    
    # Saldo Finale
    saldo_fin_bud = saldo_ini_bud + utile_bud
    saldo_fin_real = saldo_ini_real + utile_real

    # ==========================================================================
    # LOGICA PRIVACY MODE (Inserita qui, dopo i calcoli)
    # ==========================================================================
    if "nascondi_saldi" not in st.session_state:
        st.session_state["nascondi_saldi"] = False

    st.write("") # Spaziatura
    col_priv, _ = st.columns([2, 8])
    with col_priv:
        icona = "🫣" if st.session_state["nascondi_saldi"] else "👁️"
        label = "Mostra Dati" if st.session_state["nascondi_saldi"] else "Nascondi Dati"
        
        if st.button(f"{icona} {label}", key="btn_privacy_tab1"):
            st.session_state["nascondi_saldi"] = not st.session_state["nascondi_saldi"]

    def fmt_priv(valore):
        if st.session_state["nascondi_saldi"]:
            return "**** €"
        return f"{valore:,.2f} €"
    # ==========================================================================

    # 7. Display Metriche
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    
    m1.metric("💰 Saldo Iniziale", 
              fmt_priv(saldo_ini_real), 
              delta=None if st.session_state["nascondi_saldi"] else f"Budget: {saldo_ini_bud:,.2f} €")
              
    m2.metric("📈 Entrate Operative", 
              fmt_priv(ent_op_real), 
              delta=None if st.session_state["nascondi_saldi"] else f"{(ent_op_real-ent_op_bud):,.2f} € vs Budget")
              
    m3.metric("📉 Uscite Totali", 
              fmt_priv(usc_op_real), 
              delta=None if st.session_state["nascondi_saldi"] else f"{(usc_op_real-usc_op_bud):,.2f} € vs Budget", 
              delta_color="inverse")
              
    m4.metric("🏁 Saldo Finale", 
              fmt_priv(saldo_fin_real), 
              delta=None if st.session_state["nascondi_saldi"] else f"Utile: {utile_real:,.2f} €")

    # 8. Schemini Dettaglio
    st.divider()
    col_schemino_sx, col_schemino_dx = st.columns(2)
    
    # Schemino Entrate
    with col_schemino_sx:
        st.subheader("🟢 Dettaglio Entrate")
        df_e_view = ent_op_df[["Categoria", "Budget", "Reale"]].copy()
        df_e_view["Delta"] = df_e_view["Reale"] - df_e_view["Budget"]
        st.dataframe(
            df_e_view.sort_values("Reale", ascending=False)
            .style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
            .map(lambda v: style_delta_standard(v), subset=["Delta"]), 
            use_container_width=True
        )
        st.info(f"**Totale Entrate Operative:** {ent_op_real:,.2f} € (Budget: {ent_op_bud:,.2f} €)")

    # Schemino Uscite
    with col_schemino_dx:
        st.subheader("🔴 Dettaglio Uscite")
        df_u_view = usc_op_df[["Categoria", "Budget", "Reale"]].copy()
        df_u_view["Risparmio"] = df_u_view["Budget"] - df_u_view["Reale"]
        st.dataframe(
            df_u_view.sort_values("Reale", ascending=False)
            .style.format("{:.2f} €", subset=["Budget", "Reale", "Risparmio"])
            .map(lambda v: style_delta_spese(v), subset=["Risparmio"]), 
            use_container_width=True
        )
        st.info(f"**Totale Uscite:** {usc_op_real:,.2f} € (Budget: {usc_op_bud:,.2f} €)")

    st.markdown("---")
    
    # 9. Utile Finale
    col_utile_real, col_utile_bud = st.columns(2)
    
    if utile_real >= 0: colore_utile = "green"
    else: colore_utile = "red"
        
    if utile_bud >= 0: colore_utile_bud = "green"
    else: colore_utile_bud = "red"
    
    # Applichiamo la privacy anche qui
    txt_utile_real = "**** €" if st.session_state["nascondi_saldi"] else f"{utile_real:+,.2f} €"
    txt_utile_bud = "**** €" if st.session_state["nascondi_saldi"] else f"{utile_bud:+,.2f} €"
    
    with col_utile_real:
        st.markdown(f"### 💡 Utile REALE: :{colore_utile}[{txt_utile_real}]")
    with col_utile_bud:
        st.markdown(f"### 📋 Utile BUDGET: :{colore_utile_bud}[{txt_utile_bud}]")
# ==============================================================================
# TAB 2: INDICI & KPI
# ==============================================================================
with tab_kpi:
    st.markdown("### 🚀 Cruscotto Indici Finanziari")
    
    col_target, col_legenda = st.columns([1, 3])
    with col_target:
        target_patrimoniale = st.number_input("🎯 Obiettivo Annuale (€)", value=10000.0, step=500.0)
    with col_legenda:
        with st.expander("ℹ️ Spiegazione Indici (Legenda)"):
            st.markdown("""
            * **ROE (Rendimento):** Quanto rendono le tue risorse totali.
            * **IER (Efficienza Risparmio):** Percentuale delle entrate che diventa risparmio.
            * **Growth (Crescita):** Di quanto è cresciuto il patrimonio rispetto all'inizio anno.
            * **IAT (Avanzamento Target):** Percentuale di completamento dell'obiettivo annuale.
            * **IPP (Performance):** Indice combinato di progresso ed efficienza.
            """)

    st.markdown("---")
    
    # Filtri per KPI
    ck1, ck2 = st.columns(2)
    with ck1:
        lista_anni_k = sorted(df_cloud["Anno"].unique(), reverse=True)
        if not lista_anni_k: lista_anni_k = [2026]
        anno_k = st.selectbox("📅 Anno KPI", lista_anni_k, key="a_kpi")
    with ck2:
        per_k = st.selectbox("📊 Periodo KPI", ["Mensile", "Trimestrale", "Semestrale", "Annuale"], key="p_kpi")
    
    # Logica Filtro Mesi
    l_mesi_k = []
    l_num_k = []
    if per_k == "Mensile":
        m = datetime.now().month
        l_num_k = [m]
    elif per_k == "Trimestrale":
        mese_corr = datetime.now().month
        if mese_corr <= 3: l_num_k = [1,2,3]
        elif mese_corr <= 6: l_num_k = [4,5,6]
        elif mese_corr <= 9: l_num_k = [7,8,9]
        else: l_num_k = [10,11,12]
    elif per_k == "Semestrale":
        mese_corr = datetime.now().month
        if mese_corr <= 6: l_num_k = list(range(1,7))
        else: l_num_k = list(range(7,13))
    elif per_k == "Annuale":
        l_num_k = list(range(1, 13))
    else:
        l_num_k = list(range(1, 13))

    # --- CALCOLO DATI ---
    
    # 1. Dati Periodo Selezionato
    df_kpi_per = df_cloud[(df_cloud["Anno"] == anno_k) & (df_cloud["MeseNum"].isin(l_num_k))]
    
    # 2. Dati Intero Anno (per Target)
    df_kpi_anno = df_cloud[df_cloud["Anno"] == anno_k]
    
    # 3. Saldo Iniziale (Gennaio)
    bud_g = get_budget_data()
    saldo_ini_anno = 0.0
    if not bud_g.empty:
        # Cerca saldo iniziale di Gennaio
        mask_saldo = (bud_g["Mese"]=="Gen") & (bud_g["Categoria"]=="SALDO INIZIALE")
        if mask_saldo.any():
            saldo_ini_anno = bud_g[mask_saldo]["Importo"].sum()
    
    # 4. Totali Annuali
    ent_tot_anno = df_kpi_anno[(df_kpi_anno["Tipo"]=="Entrata") & (df_kpi_anno["Categoria"]!="SALDO INIZIALE")]["Importo"].sum()
    usc_tot_anno = df_kpi_anno[df_kpi_anno["Tipo"]=="Uscita"]["Importo"].sum()
    utile_anno = ent_tot_anno - usc_tot_anno
    saldo_fin_anno = saldo_ini_anno + utile_anno
    risorse_disp_anno = saldo_ini_anno + ent_tot_anno

    # 5. Totali Periodo
    ent_periodo = df_kpi_per[(df_kpi_per["Tipo"]=="Entrata") & (df_kpi_per["Categoria"]!="SALDO INIZIALE")]["Importo"].sum()
    usc_periodo = df_kpi_per[df_kpi_per["Tipo"]=="Uscita"]["Importo"].sum()
    utile_periodo = ent_periodo - usc_periodo

    # --- FORMULE KPI (ESTESE) ---
    
    # ROE
    if risorse_disp_anno > 0:
        roe = ((saldo_fin_anno - saldo_ini_anno) / risorse_disp_anno * 100)
    else:
        roe = 0
    
    # IER (Annuale)
    if ent_tot_anno > 0:
        ier = (utile_anno / ent_tot_anno * 100)
    else:
        ier = 0
    
    # Growth
    if saldo_ini_anno > 0:
        growth = ((saldo_fin_anno - saldo_ini_anno) / saldo_ini_anno * 100)
    else:
        growth = 0
    
    # IAT
    delta_target = target_patrimoniale - saldo_ini_anno
    if delta_target > 0:
        iat = ((saldo_fin_anno - saldo_ini_anno) / delta_target * 100)
    else:
        iat = 0
    
    # IAT Lineare
    iat_lineare = (datetime.now().month / 12) * 100

    # IER Periodo
    if ent_periodo > 0:
        ier_periodo = (utile_periodo / ent_periodo * 100)
    else:
        ier_periodo = 0

    # IER Giornaliero
    if risorse_disp_anno > 0:
        ier_giornaliero = (saldo_fin_anno / risorse_disp_anno * 100)
    else:
        ier_giornaliero = 0

    # IPP
    if delta_target > 0:
        term_iat = (saldo_fin_anno - saldo_ini_anno) / delta_target
    else:
        term_iat = 0
        
    if risorse_disp_anno > 0:
        term_eff = saldo_fin_anno / risorse_disp_anno
    else:
        term_eff = 0
        
    ipp = term_iat * term_eff * 100

    # Burn Rate
    giorni_periodo = 30 * len(l_num_k)
    if giorni_periodo > 0:
        burn_rate = usc_periodo / giorni_periodo
    else:
        burn_rate = 0

    # --- VISUALIZZAZIONE KPI ---
    st.markdown("##### 📌 KPI Annuali (Macro)")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("ROE (Rendimento)", f"{roe:.2f}%")
    k2.metric("Growth (Crescita)", f"{growth:.2f}%")
    k3.metric("IER (Annuale)", f"{ier:.2f}%")
    k4.metric("IAT (Target)", f"{iat:.2f}%", delta=f"{iat-iat_lineare:.1f}% vs Lineare")
    
    st.markdown("##### ⚡ KPI Operativi (Periodo Selezionato)")
    ka1, ka2, ka3, ka4 = st.columns(4)
    ka1.metric("IER Periodo", f"{ier_periodo:.1f}%")
    ka2.metric("Burn Rate", f"{burn_rate:.2f} €/gg")
    ka3.metric("IER Giornaliero", f"{ier_giornaliero:.2f}%")
    ka4.metric("IPP (Score)", f"{ipp:.2f}")

    st.divider()
    
    # Grafici Gauge
    gc1, gc2 = st.columns(2)
    with gc1:
        st.plotly_chart(crea_tachimetro(ier, "Efficienza Risparmio (IER)", max_v=50, soglia_ok=20), use_container_width=True)
    with gc2:
        st.plotly_chart(crea_tachimetro(iat, "Avanzamento Obiettivo (IAT)", max_v=100, soglia_ok=iat_lineare), use_container_width=True)
    
    st.info(f"💡 **IAT Lineare atteso:** {iat_lineare:.1f}% (Siamo al mese {datetime.now().month})")

    # Grafico Andamento Saldo
    st.markdown("### 📈 Andamento Saldo nel Periodo")
    if not df_kpi_per.empty:
        daily_io = df_kpi_per.groupby(["Data", "Tipo"])["Importo"].sum().unstack().fillna(0)
        
        if "Entrata" not in daily_io.columns:
            daily_io["Entrata"] = 0
        if "Uscita" not in daily_io.columns:
            daily_io["Uscita"] = 0
            
        daily_io["Netto"] = daily_io["Entrata"] - daily_io["Uscita"]
        daily_io["Saldo Cumulativo"] = daily_io["Netto"].cumsum()
        
        fig_trend = px.area(daily_io, y="Saldo Cumulativo", title="Evoluzione Saldo (Netto) nel Periodo")
        st.plotly_chart(fig_trend, use_container_width=True)
    else:
        st.info("Nessun dato per il grafico temporale nel periodo selezionato.")

# ==============================================================================
# TAB 3: ANALISI GRAFICA AVANZATA
# ==============================================================================
with tab_graf:
    df_budget_g = get_budget_data()
    
    c1, c2, c3 = st.columns(3)
    with c1:
        lista_anni_g = sorted(df_cloud["Anno"].unique(), reverse=True)
        if not lista_anni_g: lista_anni_g = [2026]
        anno_g = st.selectbox("📅 Anno", lista_anni_g, key="a_graf")
    with c2:
        per_g = st.selectbox("📊 Periodo", ["Mensile", "Trimestrale", "Semestrale", "Annuale"], key="p_graf")
    
    l_mesi_g = []
    l_num_g = []
    with c3:
        if per_g == "Mensile":
            m = st.selectbox("Mese", list(MAP_MESI.values()), index=datetime.now().month-1, key="m_graf")
            l_mesi_g = [m]
            l_num_g = [MAP_NUM_MESI[m]]
        elif per_g == "Trimestrale":
            t = st.selectbox("Trimestre", ["Q1 (Gen-Mar)", "Q2 (Apr-Giu)", "Q3 (Lug-Set)", "Q4 (Ott-Dic)"], key="t_graf")
            if "Q1" in t: l_num_g = [1, 2, 3]
            elif "Q2" in t: l_num_g = [4, 5, 6]
            elif "Q3" in t: l_num_g = [7, 8, 9]
            else: l_num_g = [10, 11, 12]
            l_mesi_g = [MAP_MESI[n] for n in l_num_g]
        elif per_g == "Semestrale":
            s = st.selectbox("Semestre", ["Semestre 1 (Gen-Giu)", "Semestre 2 (Lug-Dic)"], key="s_graf")
            if "1" in s: l_num_g = [1, 2, 3, 4, 5, 6]
            else: l_num_g = [7, 8, 9, 10, 11, 12]
            l_mesi_g = [MAP_MESI[n] for n in l_num_g]
        elif per_g == "Annuale":
            st.write("Tutto l'anno")
            l_num_g = list(range(1, 13))
            l_mesi_g = list(MAP_MESI.values())

    df_filt_g = df_cloud[(df_cloud["Anno"] == anno_g) & (df_cloud["MeseNum"].isin(l_num_g))]
    
    if not df_filt_g.empty:
        cons_g = df_filt_g.groupby(["Categoria", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Reale"})
    else:
        cons_g = pd.DataFrame(columns=["Categoria", "Tipo", "Reale"])
    
    prev_g = pd.DataFrame()
    if not df_budget_g.empty and "Mese" in df_budget_g.columns:
        b_filt_g = df_budget_g[df_budget_g["Mese"].isin(l_mesi_g)]
        if not b_filt_g.empty:
            prev_g = b_filt_g.groupby(["Categoria", "Tipo"])["Importo"].sum().reset_index().rename(columns={"Importo": "Budget"})

    # Filtro Saldo Iniziale
    if not prev_g.empty:
        prev_g = prev_g[prev_g["Categoria"] != "SALDO INIZIALE"]
    if not cons_g.empty:
        cons_g = cons_g[cons_g["Categoria"] != "SALDO INIZIALE"]

    merged_g = pd.merge(prev_g, cons_g, on=["Categoria", "Tipo"], how="left").fillna(0) if not prev_g.empty else cons_g.copy()
    if "Budget" not in merged_g.columns: merged_g["Budget"] = 0.0
    
    # Delta Generico (Solo per calcoli interni)
    merged_g["Delta"] = merged_g["Budget"] - merged_g["Reale"]

    st.markdown("#### 🎨 Configurazione")
    cg1, cg2 = st.columns(2)
    with cg1: source_data = st.radio("Sorgente:", ["Reale", "Budget"], horizontal=True)
    with cg2: chart_type = st.selectbox("Grafico:", ["Torta (Donut)", "Barre Orizzontali", "Treemap (Mappa)"])
    col_val = "Reale" if "Reale" in source_data else "Budget"

    cl, cr = st.columns(2)
    
    # Sezione Uscite
    out_g = merged_g[merged_g["Tipo"]=="Uscita"].copy()
    # Calcolo Risparmio (Budget - Reale)
    out_g["Risparmio"] = out_g["Budget"] - out_g["Reale"]

    with cl:
        st.markdown(f"### 🔴 Uscite ({col_val})")
        if not out_g.empty:
            fig = genera_grafico_avanzato(out_g, chart_type, col_val, "Categoria", "Uscite", px.colors.sequential.RdBu)
            if fig: st.plotly_chart(fig, use_container_width=True)
            # Applicazione stile corretto per le Spese (Risparmio = Verde)
            st.dataframe(
                out_g.sort_values("Budget", ascending=False)
                .style.format("{:.2f} €", subset=["Budget", "Reale", "Risparmio"])
                .map(lambda v: style_delta_spese(v), subset=["Risparmio"]),
                use_container_width=True
            )
    
    # Sezione Entrate
    inc_g = merged_g[merged_g["Tipo"]=="Entrata"].copy()
    # Calcolo Delta Entrate (Reale - Budget)
    inc_g["Delta"] = inc_g["Reale"] - inc_g["Budget"]

    with cr:
        st.markdown(f"### 🟢 Entrate ({col_val})")
        if not inc_g.empty:
            fig = genera_grafico_avanzato(inc_g, chart_type, col_val, "Categoria", "Entrate", px.colors.sequential.Teal)
            if fig: st.plotly_chart(fig, use_container_width=True)
            # Applicazione stile standard (Positivo = Verde)
            st.dataframe(
                inc_g.sort_values("Reale", ascending=False)
                .style.format("{:.2f} €", subset=["Budget", "Reale", "Delta"])
                .map(lambda v: style_delta_standard(v), subset=["Delta"]),
                use_container_width=True
            )

# ==============================================================================
# TAB 4: IMPORTA
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

    # Box Errori Mail
    if not st.session_state["df_mail_discarded"].empty:
        with st.expander(f"⚠️ {len(st.session_state['df_mail_discarded'])} Mail Scartate", expanded=True):
            st.dataframe(st.session_state["df_mail_discarded"][["Data", "Descrizione"]], use_container_width=True)
            if st.button("⬇️ Recupera"):
                recuperate = st.session_state["df_mail_discarded"].copy()
                st.session_state["df_manual_entry"] = pd.concat([st.session_state["df_manual_entry"], recuperate], ignore_index=True)
                st.session_state["df_mail_discarded"] = pd.DataFrame()
                st.rerun()

    # Divisione Tabelle
    df_new = st.session_state["df_mail_found"]
    
    df_view_entrate = pd.DataFrame()
    df_view_uscite = pd.DataFrame()
    
    if not df_new.empty:
        if "Firma" in df_cloud.columns:
            firme_esistenti = df_cloud["Firma"].astype(str).tolist()
            df_new = df_new[~df_new["Firma"].astype(str).isin(firme_esistenti)]
        
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
    
    ed_man = st.data_editor(
        st.session_state["df_manual_entry"],
        num_rows="dynamic",
        column_config={"Categoria": st.column_config.SelectboxColumn(options=sorted(CAT_USCITE + CAT_ENTRATE))},
        key="edit_manual", use_container_width=True
    )

    if st.button("💾 SALVA TUTTO", type="primary"):
        save_list = []
        
        # 1. Aggiungo le Entrate se ci sono
        if not ed_ent.empty: 
            save_list.append(ed_ent)
        
        # 2. Aggiungo le Uscite se ci sono
        if not ed_usc.empty: 
            save_list.append(ed_usc)
        
        # 3. Gestione Manuale (con il FIX Anti-Crash)
        if not ed_man.empty:
            # --- FIX ANTI-CRASH ---
            # Forziamo la colonna Importo a essere numerica. 
            # Se c'è testo o vuoto, diventa 0.0 (così non rompe il > 0)
            ed_man["Importo"] = pd.to_numeric(ed_man["Importo"], errors='coerce').fillna(0.0)
            
            # Ora il filtro funziona sicuro
            v = ed_man[ed_man["Importo"] > 0].copy()
            
            # Se dopo il filtro c'è ancora qualcosa, preparo i dati
            if not v.empty:
                v["Data"] = pd.to_datetime(v["Data"])
                v["Mese"] = v["Data"].dt.strftime('%b-%y')
                # Generiamo una firma univoca per queste righe manuali
                v["Firma"] = [f"MAN-{uuid.uuid4().hex[:6]}" for _ in range(len(v))]
                save_list.append(v)
        
        # 4. Se c'è qualcosa da salvare (Entrate, Uscite o Manuali)
        if save_list:
            fin = pd.concat([df_cloud] + save_list, ignore_index=True)
            fin["Data"] = pd.to_datetime(fin["Data"]).dt.strftime("%Y-%m-%d")
            
            conn.update(worksheet="DB_TRANSAZIONI", data=fin)
            
            # Pulisco le tabelle temporanee
            st.session_state["df_mail_found"] = pd.DataFrame()
            st.session_state["df_manual_entry"] = pd.DataFrame()
            st.session_state["df_mail_discarded"] = pd.DataFrame()
            
            st.balloons()
            st.success("✅ Tutto salvato correttamente!")
            st.rerun()

# ==============================================================================
# TAB 5: STORICO
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









