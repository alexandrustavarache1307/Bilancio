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

# --- FUNZIONE MAIL (WIDIBA) ---
def scarica_spese_da_gmail():
    nuove_transazioni = []
    user = st.secrets["email"]["user"]
    pwd = st.secrets["email"]["password"]
    server = st.secrets["email"]["imap_server"]
    
    try:
        with MailBox(server).login(user, pwd) as mailbox:
            # Cerca le ultime 30 mail (lette e non)
            for msg in mailbox.fetch(limit=30, reverse=True): 
                
                soggetto = msg.subject
                corpo = msg.text or msg.html
                corpo_clean = " ".join(corpo.split())

                importo = 0.0
                tipo = "Uscita"
                descrizione = "Spesa Generica"
                categoria = "DA VERIFICARE"
                trovato = False

                if "widiba" not in corpo_clean.lower() and "widiba" not in soggetto.lower():
                     continue

                # REGEX WIDIBA
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
                    # ID firma per evitare duplicati
                    firma = f"{msg.date.strftime('%Y%m%d')}-{importo}-{descrizione[:5]}"
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
st.title("☁️ Dashboard Bilancio")

# Carica dati Cloud
df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(7)), ttl=0) # Ora leggiamo anche la colonna Firma se c'è
df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')

# --- LOGICA DI STATO (MEMORIA) ---
if "df_preview" not in st.session_state:
    st.session_state["df_preview"] = pd.DataFrame()

with st.expander("📩 Gestione Transazioni", expanded=True):
    # 1. Bottone Cerca
    if st.button("🔎 Cerca Nuove Transazioni"):
        with st.spinner("Analisi mail in corso..."):
            df_mail = scarica_spese_da_gmail()
            
            if not df_mail.empty:
                # Filtro duplicati basato sulla 'Firma' o su Data+Importo
                # Se nel foglio non c'è la colonna Firma, usiamo logica semplice
                if "Firma" in df_cloud.columns:
                    firme_esistenti = df_cloud["Firma"].tolist()
                    df_nuove = df_mail[~df_mail["Firma"].isin(firme_esistenti)]
                else:
                    # Fallback vecchia maniera
                    df_nuove = df_mail
                
                if not df_nuove.empty:
                    st.session_state["df_preview"] = df_nuove
                    st.success(f"Trovate {len(df_nuove)} nuove operazioni!")
                else:
                    st.session_state["df_preview"] = pd.DataFrame()
                    st.info("Nessuna nuova operazione (tutte già presenti).")
            else:
                st.warning("Nessuna mail rilevante trovata.")

    # 2. Mostra Tabella e Bottoni se c'è qualcosa in memoria
    if not st.session_state["df_preview"].empty:
        st.divider()
        st.write("### 📝 Controlla e Modifica prima di Salvare")
        
        # Editor modificabile
        df_da_salvare = st.data_editor(
            st.session_state["df_preview"],
            num_rows="dynamic",
            use_container_width=True,
            key="editor_dati"
        )
        
        col_a, col_b = st.columns(2)
        
        # Tasto SALVA
        if col_a.button("💾 Conferma e Salva", type="primary"):
            # Aggiunge al vecchio dataframe
            df_final = pd.concat([df_cloud, df_da_salvare], ignore_index=True)
            # Rimuove eventuali colonne extra tecniche prima di salvare (tipo Firma se non la vuoi visibile, ma meglio tenerla)
            # Ordina per data
            df_final = df_final.sort_values("Data", ascending=False)
            
            # Salva
            conn.update(worksheet="DB_TRANSAZIONI", data=df_final)
            
            # Pulisce memoria
            st.session_state["df_preview"] = pd.DataFrame()
            st.toast("Transazioni Salvate!", icon="🎉")
            st.rerun()
            
        # Tasto ANNULLA
        if col_b.button("❌ Annulla"):
            st.session_state["df_preview"] = pd.DataFrame()
            st.rerun()

st.divider()
st.subheader("Ultimi Movimenti nel Database")
st.dataframe(df_cloud.head(10), use_container_width=True)
