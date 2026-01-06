import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox
import re 

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Bilancio Cloud", layout="wide", page_icon="☁️")

# --- CONNESSIONE ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("Errore connessione. Controlla i secrets!")
    st.stop()

# --- 1. CARICAMENTO CATEGORIE (DAL FOGLIO '2026') ---
@st.cache_data(ttl=60) # Cache per non rileggere ogni secondo
def get_categories():
    try:
        # Leggiamo il foglio '2026' senza intestazioni (header=None) per prendere le celle esatte
        df_cat = conn.read(worksheet="2026", usecols="A,C", header=None)
        
        # Range Entrate: A4:A23 (Indici Python: 3 a 23)
        # Nota: Python conta da 0, quindi riga 4 excel = indice 3
        cat_entrate = df_cat.iloc[3:23, 0].dropna().unique().tolist()
        
        # Range Uscite: C3:C23 (Indici Python: 2 a 23)
        cat_uscite = df_cat.iloc[2:23, 1].dropna().unique().tolist() # Colonna 1 perchè abbiamo letto solo A e C (quindi A=0, C=1)

        # Pulizia e Ordinamento
        cat_entrate = sorted([str(x) for x in cat_entrate if str(x).strip() != ""])
        cat_uscite = sorted([str(x) for x in cat_uscite if str(x).strip() != ""])
        
        return cat_entrate, cat_uscite
    except Exception as e:
        st.error(f"Errore lettura categorie dal foglio '2026': {e}")
        return ["DA VERIFICARE"], ["DA VERIFICARE"]

CAT_ENTRATE, CAT_USCITE = get_categories()

# --- 2. FUNZIONE MAIL ---
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
                categoria = "DA VERIFICARE"
                trovato = False

                # REGEX
                match_uscita = re.search(r'pagamento di\s+([\d.,]+)\s+euro.*?presso\s+(.*?)(?:\.|$)', corpo_clean, re.IGNORECASE)
                match_entrata = re.search(r'accredito di\s+([\d.,]+)\s+euro\s+per\s+(.*?)(?:\.|$)', corpo_clean, re.IGNORECASE)

                if match_uscita:
                    importo_str = match_uscita.group(1)
                    negozio = match_uscita.group(2).strip()
                    importo = float(importo_str.replace('.', '').replace(',', '.'))
                    tipo = "Uscita"
                    descrizione = negozio
                    trovato = True
                    
                elif match_entrata:
                    importo_str = match_entrata.group(1)
                    motivo = match_entrata.group(2).strip()
                    importo = float(importo_str.replace('.', '').replace(',', '.'))
                    tipo = "Entrata"
                    descrizione = motivo
                    if "estero" in motivo.lower() and "paypal" in corpo_clean.lower():
                        descrizione = "Accredito PayPal"
                        # Qui potremmo provare a indovinare una categoria se vuoi, ma la lasciamo scegliere a te
                    trovato = True

                if trovato:
                    firma = f"{msg.date.strftime('%Y%m%d')}-{importo}-{descrizione[:10]}"
                    nuove_transazioni.append({
                        "Data": msg.date.strftime("%Y-%m-%d"),
                        "Descrizione": descrizione,
                        "Importo": importo,
                        "Tipo": tipo,
                        "Categoria": categoria,
                        "Mese": msg.date.strftime('%b-%y'),
                        "Firma": firma
                    })
                    
    except Exception as e:
        st.error(f"Errore lettura mail: {e}")
        
    return pd.DataFrame(nuove_transazioni)

# --- INTERFACCIA ---
st.title("☁️ Bilancio 2026")

# Lettura DB esistente
try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
except:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(6)), ttl=0)

df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')

# Inizializza stati separati per Entrate e Uscite
if "df_preview_entrate" not in st.session_state:
    st.session_state["df_preview_entrate"] = pd.DataFrame()
if "df_preview_uscite" not in st.session_state:
    st.session_state["df_preview_uscite"] = pd.DataFrame()

# TASTO CERCA
if st.button("🔎 CERCA TRANSAZIONI", type="primary"):
    with st.spinner("Analisi mail in corso..."):
        df_mail = scarica_spese_da_gmail()
        
        if not df_mail.empty:
            # Filtro duplicati
            if "Firma" in df_cloud.columns:
                firme_esistenti = df_cloud["Firma"].astype(str).tolist()
                df_nuove = df_mail[~df_mail["Firma"].astype(str).isin(firme_esistenti)]
            else:
                df_nuove = df_mail 
            
            if not df_nuove.empty:
                # SEPARIAMO SUBITO ENTRATE E USCITE
                st.session_state["df_preview_entrate"] = df_nuove[df_nuove["Tipo"] == "Entrata"]
                st.session_state["df_preview_uscite"] = df_nuove[df_nuove["Tipo"] == "Uscita"]
                st.toast(f"Trovate {len(df_nuove)} nuove operazioni!", icon="🔥")
            else:
                st.session_state["df_preview_entrate"] = pd.DataFrame()
                st.session_state["df_preview_uscite"] = pd.DataFrame()
                st.info("Nessuna transazione nuova.")
        else:
            st.warning("Nessuna mail rilevante trovata.")

# --- SEZIONE DI MODIFICA (DIVISA) ---
has_data = not st.session_state["df_preview_entrate"].empty or not st.session_state["df_preview_uscite"].empty

if has_data:
    st.divider()
    st.markdown("### 📝 Controlla e Categorizza")

    # 1. TABELLA ENTRATE (Se ce ne sono)
    df_entrate_edit = pd.DataFrame()
    if not st.session_state["df_preview_entrate"].empty:
        st.success("💰 ENTRATE TROVATE")
        df_entrate_edit = st.data_editor(
            st.session_state["df_preview_entrate"],
            column_config={
                "Categoria": st.column_config.SelectColumn(
                    "Categoria Entrata",
                    options=CAT_ENTRATE,  # <--- SOLO CATEGORIE ENTRATE
                    required=True
                )
            },
            use_container_width=True,
            key="edit_entrate",
            hide_index=True
        )

    # 2. TABELLA USCITE (Se ce ne sono)
    df_uscite_edit = pd.DataFrame()
    if not st.session_state["df_preview_uscite"].empty:
        st.error("💸 USCITE TROVATE")
        df_uscite_edit = st.data_editor(
            st.session_state["df_preview_uscite"],
            column_config={
                "Categoria": st.column_config.SelectColumn(
                    "Categoria Spesa",
                    options=CAT_USCITE,  # <--- SOLO CATEGORIE USCITE
                    required=True
                )
            },
            use_container_width=True,
            key="edit_uscite",
            hide_index=True
        )

    st.markdown("---")
    
    # 3. SALVATAGGIO UNIFICATO
    col1, col2 = st.columns([1, 1])
    
    if col1.button("💾 SALVA TUTTO NEL DATABASE", type="primary", use_container_width=True):
        # Mettiamo insieme i pezzi (anche se uno dei due è vuoto, concat gestisce tutto)
        liste_da_unire = []
        if not df_entrate_edit.empty: liste_da_unire.append(df_entrate_edit)
        if not df_uscite_edit.empty: liste_da_unire.append(df_uscite_edit)
        
        if liste_da_unire:
            df_da_salvare = pd.concat(liste_da_unire)
            
            # Uniamo al cloud
            df_final = pd.concat([df_cloud, df_da_salvare], ignore_index=True)
            
            # Fix date e ordinamento
            df_final["Data"] = pd.to_datetime(df_final["Data"], errors='coerce')
            df_final = df_final.sort_values("Data", ascending=False)
            df_final["Data"] = df_final["Data"].dt.strftime("%Y-%m-%d")
            
            conn.update(worksheet="DB_TRANSAZIONI", data=df_final)
            
            # Reset
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
st.caption("Ultimi movimenti nel DB:")
st.dataframe(df_cloud.head(5), use_container_width=True)
