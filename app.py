import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox
import re 

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Bilancio Cloud", layout="wide", page_icon="☁️")

# --- MAPPA PAROLE CHIAVE -> CATEGORIA ---
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
        df_cat = conn.read(worksheet="2026", usecols="A,C", header=None)
        
        # Entrate (A4:A23 -> indice 3:23)
        cat_entrate = df_cat.iloc[3:23, 0].dropna().unique().tolist()
        # Uscite (C3:C23 -> indice 2:23)
        cat_uscite = df_cat.iloc[2:23, 1].dropna().unique().tolist()

        cat_entrate = sorted([str(x) for x in cat_entrate if str(x).strip() != ""])
        cat_uscite = sorted([str(x) for x in cat_uscite if str(x).strip() != ""])
        
        if "DA VERIFICARE" not in cat_entrate: cat_entrate.insert(0, "DA VERIFICARE")
        if "DA VERIFICARE" not in cat_uscite: cat_uscite.insert(0, "DA VERIFICARE")
        
        return cat_entrate, cat_uscite
    except Exception as e:
        st.error(f"Errore lettura categorie: {e}")
        return ["DA VERIFICARE"], ["DA VERIFICARE"]

CAT_ENTRATE, CAT_USCITE = get_categories()

# --- CERVELLO SMART ---
def trova_categoria_smart(descrizione, lista_categorie_disponibili):
    desc_lower = descrizione.lower()
    for parola_chiave, target_categoria in MAPPA_KEYWORD.items():
        if parola_chiave in desc_lower:
            for cat in lista_categorie_disponibili:
                if target_categoria in cat.lower():
                    return cat
    for cat in lista_categorie_disponibili:
        if cat.lower() in desc_lower:
            return cat
    return "DA VERIFICARE"

# --- LETTURA MAIL ---
def scarica_spese_da_gmail():
    nuove_transazioni = []
    user = st.secrets["email"]["user"]
    pwd = st.secrets["email"]["password"]
    server = st.secrets["email"]["imap_server"]
    
    try:
        with MailBox(server).login(user, pwd) as mailbox:
            for msg in mailbox.fetch(limit=30, reverse=True): 
                
                soggetto = msg.subject
                corpo = msg.text or msg.html
                corpo_clean = " ".join(corpo.split())
                
                if "widiba" not in corpo_clean.lower() and "widiba" not in soggetto.lower():
                     continue

                importo = 0.0
                tipo = "Uscita"
                descrizione = "Spesa Generica"
                categoria_s
