import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox
import re 

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Bilancio Cloud", layout="wide", page_icon="☁️")

# --- 🧠 CERVELLO AI: MAPPA PAROLE CHIAVE -> TUA CATEGORIA ---
# Modifica qui se vuoi aggiungere nuove associazioni
MAPPA_KEYWORD = {
    "lidl": "alimentar",
    "conad": "alimentar",
    "esselunga": "alimentar",
    "coop": "alimentar",
    "carrefour": "alimentar",
    "eurospin": "alimentar",
    "aldi": "alimentar",
    "md discount": "alimentar",
    "ristorante": "ristora",
    "pizzeria": "ristora",
    "sushi": "ristora",
    "mcdonald": "ristora",
    "burger king": "ristora",
    "bar ": "colazion",
    "caffè": "colazion",
    "starbucks": "colazion",
    "eni": "auto",
    "q8": "auto",
    "esso": "auto",
    "tamoil": "auto",
    "benzina": "auto",
    "autostrade": "auto",
    "telepass": "auto",
    "amazon": "shopping",
    "zara": "abbigliamento",
    "h&m": "abbigliamento",
    "farmacia": "salute",
    "medico": "salute",
    "netflix": "abbonament",
    "spotify": "abbonament",
    "disney": "abbonament",
    "google": "abbonament",
    "paypal": "paypal",
    "stipendio": "stipendio",
    "bonifico": "bonifico"
}

# --- CONNESSIONE GOOGLE SHEETS ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("Errore connessione. Controlla i secrets!")
    st.stop()

# --- CARICAMENTO CATEGORIE DAL FOGLIO '2026' ---
@st.cache_data(ttl=60)
def get_categories():
    try:
        # Legge colonne A e C del foglio 2026
        df_cat = conn.read(worksheet="2026", usecols="A,C", header=None)
        
        # LOGICA ENTRATE: Prende celle A4:A23 (indici 3:23)
        cat_entrate = df_cat.iloc[3:23, 0].dropna().unique().tolist()
        
        # LOGICA USCITE: Prende celle C3:C23 (indici 2:23)
        cat_uscite = df_cat.iloc[2:23, 1].dropna().unique().tolist()

        # Pulisce e ordina
        cat_entrate = sorted([str(x) for x in cat_entrate if str(x).strip() != ""])
        cat_uscite = sorted([str(x) for x in cat_uscite if str(x).strip() != ""])
        
        # Fallback di sicurezza
        if "DA VERIFICARE" not in cat_entrate: cat_entrate.insert(0, "DA VERIFICARE")
        if "DA VERIFICARE" not in cat_uscite: cat_uscite.insert(0, "DA VERIFICARE")
        
        return cat_entrate, cat_uscite
    except Exception as e:
        # Gestione errore se il foglio non si legge
        st.error(f"Errore lettura categorie: {e}")
        return ["DA VERIFICARE"], ["DA VERIFICARE"]

# Carica le categorie all'avvio
CAT_ENTRATE, CAT_USCITE = get_categories()

# --- FUNZIONE SMART: Sceglie la categoria giusta ---
def trova_categoria_smart(descrizione, lista_categorie_disponibili):
    desc_lower = descrizione.lower()
    
    # 1. Cerca parole chiave
    for parola_chiave, target_categoria in MAPPA_KEYWORD.items():
        if parola_chiave in desc_lower:
            for cat in lista_categorie_disponibili:
                if target_categoria in cat.lower():
                    return cat
    
    # 2. Cerca corrispondenza diretta nel nome
    for cat in lista_categorie_disponibili:
        if cat.lower() in desc_lower:
            return cat
            
    return "DA VERIFICARE"

# --- LETTURA MAIL ---
def scarica_spese_da_gmail():
    nuove_transazioni = []
    
    # Legge credenziali dai secrets
    if "email" in st.secrets:
        user = st.secrets["email"]["user"]
        pwd = st.secrets["email"]["password"]
        server = st.secrets["email"]["imap_server"]
    else:
        st.error("Mancano i secrets per l'email!")
        return pd.DataFrame()
    
    try:
        with MailBox(server).login(user, pwd) as mailbox:
            for msg in mailbox.fetch(limit=30, reverse=True): 
                
                soggetto = msg.subject
                corpo = msg.text or msg.html
                corpo_clean = " ".join(corpo.split())
                
                # Filtro rapido Widiba
                if "widiba" not in corpo_clean.lower() and "widiba" not in soggetto.lower():
                     continue

                importo = 0.0
                tipo = "Uscita"
                descrizione = "Spesa Generica"
                categoria_suggerita = "DA VERIFICARE"
                trovato = False

                match_uscita = re.search(r'pagamento di\s+([\d.,]+)\s+euro.*?presso\s+(.*?)(?:\.|$)', corpo_clean, re.IGNORECASE)
                match_entrata = re.search(r'accredito di\s+([\d.,]+)\s+euro\s+per\s+(.*?)(?:\.|$)', corpo_clean, re.IGNORECASE)

                if match_uscita:
                    importo_str = match_uscita.group(1)
                    negozio = match_uscita.group(2).strip()
                    importo = float(importo_str.replace('.', '').replace(',', '.'))
                    tipo = "Uscita"
                    descrizione = negozio
                    # CERCA SOLO TRA LE USCITE
                    categoria_suggerita = trova_categoria_smart(negozio, CAT_USCITE)
                    trovato = True
                    
                elif match_entrata:
                    importo_str = match_entrata.group(1)
                    motivo = match_entrata.group(2).strip()
                    importo = float(importo_str.replace('.', '').replace(',', '.'))
                    tipo = "Entrata"
                    descrizione = motivo
                    if "estero" in motivo.lower() and "paypal" in corpo_clean.lower():
                        descrizione = "Accredito PayPal"
                    # CERCA SOLO TRA LE ENTRATE
                    categoria_suggerita = trova_categoria_smart(descrizione, CAT_ENTRATE)
                    trovato = True

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
                    
    except Exception as e:
        st.error(f"Errore lettura mail: {e}")
        
    return pd.DataFrame(nuove_transazioni)

# --- INTERFACCIA UTENTE ---
st.title("☁️ Bilancio 2026 - Smart AI")

# Lettura DB esistente
try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
except:
    # Se fallisce (es. manca colonna Firma), legge 6 colonne
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(6)), ttl=0)

df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')

# Inizializza session state per le tabelle temporanee
if "df_preview_entrate" not in st.session_state:
    st.session_state["df_preview_entrate"] = pd.DataFrame()
if "df_preview_uscite" not in st.session_state:
    st.session_state["df_preview_uscite"] = pd.DataFrame()

# TASTO CERCA
if st.button("🔎 CERCA E CATEGORIZZA", type="primary"):
    with st.spinner("Analisi in corso..."):
        df_mail = scarica
