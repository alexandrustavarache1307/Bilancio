import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox
import re 

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Bilancio Cloud", layout="wide", page_icon="☁️")

# --- 🧠 CERVELLO AI: MAPPA PAROLE CHIAVE -> TUA CATEGORIA ---
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
        # CORREZIONE QUI: Usiamo [0, 2] invece di "A,C"
        # 0 = Colonna A, 2 = Colonna C
        df_cat = conn.read(worksheet="2026", usecols=[0, 2], header=None)
        
        # LOGICA ENTRATE: Prende celle A4:A23 (indici 3:23) dalla colonna 0
        cat_entrate = df_cat.iloc[3:23, 0].dropna().unique().tolist()
        
        # LOGICA USCITE: Prende celle C3:C23 (indici 2:23) dalla colonna 1 (perché abbiamo scaricato solo 2 colonne)
        cat_uscite = df_cat.iloc[2:23, 1].dropna().unique().tolist()

        # Pulisce e ordina
        cat_entrate = sorted([str(x) for x in cat_entrate if str(x).strip() != ""])
        cat_uscite = sorted([str(x) for x in cat_uscite if str(x).strip() != ""])
        
        # Fallback di sicurezza
        if "DA VERIFICARE" not in cat_entrate: cat_entrate.insert(0, "DA VERIFICARE")
        if "DA VERIFICARE" not in cat_uscite: cat_uscite.insert(0, "DA VERIFICARE")
        
        return cat_entrate, cat_uscite
    except Exception as e:
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
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(6)), ttl=0)

df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')

# Inizializza session state
if "df_preview_entrate" not in st.session_state:
    st.session_state["df_preview_entrate"] = pd.DataFrame()
if "df_preview_uscite" not in st.session_state:
    st.session_state["df_preview_uscite"] = pd.DataFrame()

# TASTO CERCA
if st.button("🔎 CERCA E CATEGORIZZA", type="primary"):
    with st.spinner("Analisi in corso..."):
        df_mail = scarica_spese_da_gmail()
        
        if not df_mail.empty:
            if "Firma" in df_cloud.columns:
                firme_esistenti = df_cloud["Firma"].astype(str).tolist()
                df_nuove = df_mail[~df_mail["Firma"].astype(str).isin(firme_esistenti)]
            else:
                df_nuove = df_mail 
            
            if not df_nuove.empty:
                st.session_state["df_preview_entrate"] = df_nuove[df_nuove["Tipo"] == "Entrata"]
                st.session_state["df_preview_uscite"] = df_nuove[df_nuove["Tipo"] == "Uscita"]
                st.toast(f"Trovate {len(df_nuove)} nuove operazioni!", icon="🔥")
            else:
                st.session_state["df_preview_entrate"] = pd.DataFrame()
                st.session_state["df_preview_uscite"] = pd.DataFrame()
                st.info("Tutto aggiornato.")
        else:
            st.warning("Nessuna mail rilevante trovata (Widiba) nelle ultime 30.")

# Verifica dati
has_data = not st.session_state["df_preview_entrate"].empty or not st.session_state["df_preview_uscite"].empty

if has_data:
    st.divider()
    
    # --- TABELLA ENTRATE ---
    df_entrate_edit = pd.DataFrame()
    if not st.session_state["df_preview_entrate"].empty:
        st.success("💰 ENTRATE DA REGISTRARE")
        df_entrate_edit = st.data_editor(
            st.session_state["df_preview_entrate"],
            column_config={
                "Categoria": st.column_config.SelectboxColumn(
                    "Categoria Entrata",
                    options=CAT_ENTRATE,
                    required=True
                )
            },
            use_container_width=True,
            key="edit_entrate",
            hide_index=True
        )

    # --- TABELLA USCITE ---
    df_uscite_edit = pd.DataFrame()
    if not st.session_state["df_preview_uscite"].empty:
        st.error("💸 USCITE DA REGISTRARE")
        df_uscite_edit = st.data_editor(
            st.session_state["df_preview_uscite"],
            column_config={
                "Categoria": st.column_config.SelectboxColumn(
                    "Categoria Spesa",
                    options=CAT_USCITE,
                    required=True
                )
            },
            use_container_width=True,
            key="edit_uscite",
            hide_index=True
        )

    st.markdown("---")
    
    col1, col2 = st.columns([1, 1])
    
    if col1.button("💾 SALVA TUTTO NEL DATABASE", type="primary", use_container_width=True):
        liste_da_unire = []
        if not df_entrate_edit.empty: liste_da_unire.append(df_entrate_edit)
        if not df_uscite_edit.empty: liste_da_unire.append(df_uscite_edit)
        
        if liste_da_unire:
            df_final = pd.concat([df_cloud, pd.concat(liste_da_unire)], ignore_index=True)
            df_final["Data"] = pd.to_datetime(df_final["Data"], errors='coerce')
            df_final = df_final.sort_values("Data", ascending=False)
            df_final["Data"] = df_final["Data"].dt.strftime("%Y-%m-%d")
            
            conn.update(worksheet="DB_TRANSAZIONI", data=df_final)
            
            st.session_state["df_preview_entrate"] = pd.DataFrame()
            st.session_state["df_preview_uscite"] = pd.DataFrame()
            st.balloons()
            st.success("✅ Salvataggio riuscito!")
            st.rerun()

    if col2.button("❌ Annulla / Pulisci"):
        st.session_state["df_preview_entrate"] = pd.DataFrame()
        st.session_state["df_preview_uscite"] = pd.DataFrame()
        st.rerun()

st.divider()
st.caption("Ultimi movimenti salvati:")
st.dataframe(df_cloud.head(5), use_container_width=True)
