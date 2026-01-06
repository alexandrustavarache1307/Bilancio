import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox
import re 

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Bilancio Cloud", layout="wide", page_icon="☁️")

# --- 🧠 IL CERVELLO: MAPPA PAROLE CHIAVE -> TUA CATEGORIA ---
MAPPA_KEYWORD = {
    # IMPORTANTE: Aggiorna queste associazioni con le parole chiave reali del tuo Excel!
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
        df_cat = conn.read(worksheet="2026", usecols=[0, 2], header=None)
        cat_entrate = df_cat.iloc[3:23, 0].dropna().unique().tolist()
        cat_uscite = df_cat.iloc[2:23, 1].dropna().unique().tolist()
        
        cat_entrate = sorted([str(x).strip() for x in cat_entrate if str(x).strip() != ""])
        cat_uscite = sorted([str(x).strip() for x in cat_uscite if str(x).strip() != ""])
        
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
                if target_categoria.lower() in cat.lower():
                    return cat
    for cat in lista_categorie_disponibili:
        if cat.lower() in desc_lower:
            return cat
    return "DA VERIFICARE"

# --- LETTURA MAIL POTENZIATA (ASPIRATUTTO) ---
def scarica_spese_da_gmail():
    nuove_transazioni = []
    
    if "email" not in st.secrets:
        st.error("Mancano i secrets!")
        return pd.DataFrame()

    user = st.secrets["email"]["user"]
    pwd = st.secrets["email"]["password"]
    server = st.secrets["email"]["imap_server"]
    
    try:
        with MailBox(server).login(user, pwd) as mailbox:
            # 1. CERCA NELLE ULTIME 100 MAIL (Così non scappa nulla)
            for msg in mailbox.fetch(limit=30, reverse=True): 
                
                soggetto = msg.subject
                corpo = msg.text or msg.html
                corpo_clean = " ".join(corpo.split())
                
                # Deve essere Widiba
                if "widiba" not in corpo_clean.lower() and "widiba" not in soggetto.lower():
                     continue

                importo = 0.0
                tipo = "Uscita"
                descrizione = "Transazione Generica"
                categoria_suggerita = "DA VERIFICARE"
                trovato = False

                # --- NUOVA LOGICA DI RICONOSCIMENTO ---
                # Usiamo regex più flessibili per catturare tutto (Bonifici, Prelievi, Addebiti, SDD)
                
                # PATTERN PER LE USCITE (Pagamenti, Prelievi, Addebiti, Bonifici in uscita)
                # Cerca frasi tipo: "pagamento di...", "prelievo di...", "addebito di..."
                regex_uscite = [
                    r'(?:pagamento|prelievo|addebito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:presso|per|a favore di|su)\s+(.*?)(?:\.|$)',
                    r'ha\s+prelevato\s+([\d.,]+)\s+euro.*?(?:presso)\s+(.*?)(?:\.|$)' # Caso specifico prelievo
                ]

                # PATTERN PER LE ENTRATE (Accrediti, Bonifici in entrata)
                regex_entrate = [
                    r'(?:accredito|bonifico).*?di\s+([\d.,]+)\s+euro.*?(?:per|da|a favore di)\s+(.*?)(?:\.|$)',
                    r'hai\s+ricevuto\s+([\d.,]+)\s+euro\s+da\s+(.*?)(?:\.|$)'
                ]

                # 1. PROVA USCITE
                for rx in regex_uscite:
                    match = re.search(rx, corpo_clean, re.IGNORECASE)
                    if match:
                        importo_str = match.group(1)
                        # Se riesce a catturare la descrizione bene, altrimenti usa il soggetto
                        desc_temp = match.group(2).strip() if len(match.groups()) > 1 else soggetto
                        
                        importo = float(importo_str.replace('.', '').replace(',', '.'))
                        tipo = "Uscita"
                        descrizione = desc_temp
                        categoria_suggerita = trova_categoria_smart(descrizione, CAT_USCITE)
                        trovato = True
                        break # Trovato! Smetti di cercare

                # 2. SE NON È USCITA, PROVA ENTRATE
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
                    
    except Exception as e:
        st.error(f"Errore lettura mail: {e}")
        
    return pd.DataFrame(nuove_transazioni)

# --- INTERFACCIA UTENTE ---
st.title("☁️ Bilancio 2026 - Versione Aspiratutto")

try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
except:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(6)), ttl=0)

df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')

if "df_preview_entrate" not in st.session_state:
    st.session_state["df_preview_entrate"] = pd.DataFrame()
if "df_preview_uscite" not in st.session_state:
    st.session_state["df_preview_uscite"] = pd.DataFrame()

# TASTO CERCA
if st.button("🔎 CERCA TUTTE LE TRANSAZIONI (Ultime 100 mail)", type="primary"):
    with st.spinner("Analisi approfondita mail Widiba..."):
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
                st.info("Nessuna transazione *nuova* trovata.")
        else:
            st.warning("Nessuna mail Widiba con importi trovata nelle ultime 100.")

has_data = not st.session_state["df_preview_entrate"].empty or not st.session_state["df_preview_uscite"].empty

if has_data:
    st.divider()
    
    # ENTRATE
    df_entrate_edit = pd.DataFrame()
    if not st.session_state["df_preview_entrate"].empty:
        st.success("💰 ENTRATE")
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

    # USCITE
    df_uscite_edit = pd.DataFrame()
    if not st.session_state["df_preview_uscite"].empty:
        st.error("💸 USCITE")
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
    
    if col1.button("💾 SALVA TUTTO", type="primary", use_container_width=True):
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

    if col2.button("❌ Annulla"):
        st.session_state["df_preview_entrate"] = pd.DataFrame()
        st.session_state["df_preview_uscite"] = pd.DataFrame()
        st.rerun()

st.divider()
st.caption("Ultimi movimenti salvati:")
st.dataframe(df_cloud.head(5), use_container_width=True)
