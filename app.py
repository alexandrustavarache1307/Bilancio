import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from imap_tools import MailBox, AND
import re 

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Bilancio Cloud", layout="wide", page_icon="☁️")

# --- CONNESSIONE GOOGLE SHEETS ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("Errore connessione. Controlla i secrets!")
    st.stop()

# --- IL CERVELLO: LEGGE LE MAIL WIDIBA (TUTTE, ANCHE QUELLE LETTE) ---
def scarica_spese_da_gmail():
    nuove_transazioni = []
    
    user = st.secrets["email"]["user"]
    pwd = st.secrets["email"]["password"]
    server = st.secrets["email"]["imap_server"]
    
    try:
        with MailBox(server).login(user, pwd) as mailbox:
            # ORA CERCA LE ULTIME 30 MAIL (Lette e Non lette)
            for msg in mailbox.fetch(limit=30, reverse=True): 
                
                soggetto = msg.subject
                corpo = msg.text or msg.html
                corpo_clean = " ".join(corpo.split())

                importo = 0.0
                tipo = "Uscita"
                descrizione = "Spesa Generica"
                categoria = "DA VERIFICARE"
                trovato = False

                # --- FILTRO ANTICIPATO ---
                # Se l'oggetto o il testo non c'entrano nulla con la banca, saltiamo subito
                # (Opzionale, ma velocizza se hai tante mail)
                if "widiba" not in corpo_clean.lower() and "widiba" not in soggetto.lower():
                     continue

                # --- CASO 1: PAGAMENTO CARTA ---
                match_uscita = re.search(r'pagamento di\s+([\d.,]+)\s+euro.*?presso\s+(.*?)(?:\.|$)', corpo_clean, re.IGNORECASE)
                
                # --- CASO 2: ACCREDITO/BONIFICO ---
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
                    nuove_transazioni.append({
                        "Data": msg.date.strftime("%Y-%m-%d"),
                        "Descrizione": descrizione,
                        "Importo": importo,
                        "Tipo": tipo,
                        "Categoria": categoria,
                        "Mese": msg.date.strftime('%b-%y'),
                        "Firma": f"{msg.date}-{importo}-{descrizione[:5]}" 
                    })
                    
    except Exception as e:
        st.error(f"Errore lettura mail: {e}")
        
    return pd.DataFrame(nuove_transazioni)
# --- INTERFACCIA APP ---
st.title("☁️ Dashboard Bilancio")

# Lettura dati dal Cloud
df_cloud = conn.read(worksheet="DB_TRANSAZIONI", usecols=list(range(6)), ttl=0)
df_cloud["Data"] = pd.to_datetime(df_cloud["Data"], errors='coerce')

# --- ZONA SINCRONIZZAZIONE ---
with st.expander("📩 Sincronizza con Widiba", expanded=True):
    col1, col2 = st.columns([1, 3])
    if col1.button("Cerca nella Posta"):
        with st.spinner("Analizzo le mail della banca..."):
            df_mail = scarica_spese_da_gmail()
            
        if not df_mail.empty:
            # Filtro per non vedere cose già salvate
            df_mail["Duplicato"] = df_mail.apply(
                lambda x: ((df_cloud["Importo"] == x["Importo"]) & 
                           (df_cloud["Data"] == x["Data"])).any(), axis=1
            )
            df_nuove = df_mail[df_mail["Duplicato"] == False].copy()
            
            if not df_nuove.empty:
                st.success(f"Trovate {len(df_nuove)} nuove operazioni!")
                
                # Tabella Interattiva per modifiche veloci
                df_edit = st.data_editor(
                    df_nuove[["Data", "Descrizione", "Importo", "Tipo", "Categoria", "Mese"]],
                    num_rows="dynamic",
                    use_container_width=True
                )
                
                if st.button("💾 Salva nel Database"):
                    df_final = pd.concat([df_cloud, df_edit], ignore_index=True)
                    df_final = df_final.sort_values("Data", ascending=False)
                    conn.update(worksheet="DB_TRANSAZIONI", data=df_final)
                    st.toast("Salvato con successo!", icon="✅")
                    st.rerun()
            else:
                st.info("Transazioni trovate, ma erano già nel database.")
        else:
            st.warning("Nessuna mail 'Non Letta' trovata.")

st.divider()

# --- DATI RECENTI ---
st.subheader("Ultimi Movimenti")
st.dataframe(df_cloud.head(10), use_container_width=True)




