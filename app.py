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

# --- FUNZIONE MAIL ---
def scarica_spese_da_gmail():
    nuove_transazioni = []
    user = st.secrets["email"]["user"]
    pwd = st.secrets["email"]["password"]
    server = st.secrets["email"]["imap_server"]
    
    try:
        with MailBox(server).login(user, pwd) as mailbox:
            # Cerca le ultime 30 mail
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
                categoria = "DA VERIFICARE"
                trovato = False

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
                        categoria = "Trasferimenti"
                    trovato = True

                if trovato:
                    # Crea una firma unica per questa transazione
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
st.title("☁️ Dashboard Bilancio v2") # Ho cambiato il titolo per farti capire se è aggiornata

# Legge il foglio (tenta di leggere 7 colonne inclusa la Firma)
try:
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0)
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
except:
    # Se fallisce (magari manca la colonna Firma), legge solo le prime 6
    df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(6)), ttl=0)
    df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')
    st.warning("⚠️ Aggiungi la colonna 'Firma' al foglio Google (colonna G) per evitare duplicati!")

# --- GESTIONE MEMORIA (Session State) ---
if "df_preview" not in st.session_state:
    st.session_state["df_preview"] = pd.DataFrame()

# Tasto Cerca (Sempre visibile in alto)
if st.button("🔎 CERCA TRANSAZIONI NELLA MAIL", type="primary", use_container_width=True):
    with st.spinner("Sto leggendo le mail..."):
        df_mail = scarica_spese_da_gmail()
        
        if not df_mail.empty:
            # Filtro duplicati
            if "Firma" in df_cloud.columns:
                firme_esistenti = df_cloud["Firma"].astype(str).tolist()
                df_nuove = df_mail[~df_mail["Firma"].astype(str).isin(firme_esistenti)]
            else:
                df_nuove = df_mail # Se manca la colonna firma, mostra tutto
            
            if not df_nuove.empty:
                st.session_state["df_preview"] = df_nuove
                st.toast(f"Trovate {len(df_nuove)} transazioni!", icon="🔥")
            else:
                st.session_state["df_preview"] = pd.DataFrame()
                st.info("Nessuna transazione *nuova* trovata (erano già tutte salvate).")
        else:
            st.warning("Nessuna mail di Widiba trovata nelle ultime 30.")

# --- ZONA DI SALVATAGGIO (Appare solo se ci sono dati) ---
if not st.session_state["df_preview"].empty:
    st.divider()
    st.markdown("### 👇 Controlla qui sotto e SALVA")
    
    # Tabella modificabile
    df_da_salvare = st.data_editor(
        st.session_state["df_preview"],
        num_rows="dynamic",
        use_container_width=True,
        key="editor_dati"
    )
    
    # BOTTONE SALVA GIGANTE
    if st.button("💾 CLICCA QUI PER SALVARE NEL FOGLIO GOOGLE 💾", type="primary", use_container_width=True):
        # Unione e salvataggio
        df_final = pd.concat([df_cloud, df_da_salvare], ignore_index=True)
        
        # Ordina per data (più recenti in alto)
        df_final = df_final.sort_values("Data", ascending=False)
        
        # Scrive su Google Sheets
        conn.update(worksheet="DB_TRANSAZIONI", data=df_final)
        
        # Pulisce la memoria
        st.session_state["df_preview"] = pd.DataFrame()
        st.balloons()
        st.success("✅ Salvataggio Completato!")
        st.rerun()

    if st.button("❌ Annulla / Pulisci"):
        st.session_state["df_preview"] = pd.DataFrame()
        st.rerun()

st.divider()
st.caption("Ultimi movimenti salvati nel DB:")
st.dataframe(df_cloud.head(5), use_container_width=True)
